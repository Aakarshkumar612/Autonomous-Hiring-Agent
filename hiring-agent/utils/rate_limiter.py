"""
utils/rate_limiter.py
═══════════════════════════════════════════════════════
Rate limiting and retry logic for Groq API calls.
Handles free tier limits gracefully without crashing.

Groq Free Tier Limits (per model):
  llama-3.3-70b-versatile  → 30 RPM, 14,400 RPD
  llama-4-maverick         → 30 RPM, 14,400 RPD
  llama-3.1-8b-instant     → 30 RPM, 14,400 RPD
  deepseek-r1-distill      → 30 RPM, 14,400 RPD
  compound-beta            → 30 RPM, 14,400 RPD

Strategy:
  - Token bucket per model (tracks RPM)
  - Daily counter per model (tracks RPD)
  - Exponential backoff on 429 errors
  - Batch spacing to stay under limits
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import logger


# ─────────────────────────────────────────────────────
#  Groq Model Rate Limit Config
# ─────────────────────────────────────────────────────

@dataclass
class ModelLimits:
    """Rate limits for a single Groq model."""
    requests_per_minute: int   = 30
    requests_per_day:    int   = 14_400
    tokens_per_minute:   int   = 6_000
    min_delay_seconds:   float = 2.1    # 60s / 30 RPM + 0.1s buffer


GROQ_MODEL_LIMITS: dict[str, ModelLimits] = {
    "llama-3.3-70b-versatile":                       ModelLimits(),
    "meta-llama/llama-4-maverick-17b-128e-instruct": ModelLimits(),
    "llama-3.1-8b-instant":                          ModelLimits(),
    "deepseek-r1-distill-qwen-32b":                  ModelLimits(),
    "compound-beta":                                 ModelLimits(),
}


# ─────────────────────────────────────────────────────
#  Per-Model Usage Tracker
# ─────────────────────────────────────────────────────

@dataclass
class ModelUsage:
    """Tracks actual usage per model."""
    request_count_minute: int   = 0
    request_count_day:    int   = 0
    last_request_time:    float = 0.0
    minute_window_start:  float = field(default_factory=time.time)
    day_window_start:     float = field(default_factory=time.time)

    def reset_minute_if_needed(self) -> None:
        now = time.time()
        if now - self.minute_window_start >= 60:
            self.request_count_minute = 0
            self.minute_window_start = now

    def reset_day_if_needed(self) -> None:
        now = time.time()
        if now - self.day_window_start >= 86_400:
            self.request_count_day = 0
            self.day_window_start = now

    def record_request(self) -> None:
        self.request_count_minute += 1
        self.request_count_day += 1
        self.last_request_time = time.time()


# ─────────────────────────────────────────────────────
#  Core Rate Limiter
# ─────────────────────────────────────────────────────

class GroqRateLimiter:
    """
    Thread-safe rate limiter for Groq API calls.
    Tracks RPM and RPD per model independently.
    """

    def __init__(self) -> None:
        self._usage: dict[str, ModelUsage] = defaultdict(ModelUsage)
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, model: str) -> asyncio.Lock:
        if model not in self._locks:
            self._locks[model] = asyncio.Lock()
        return self._locks[model]

    def _get_limits(self, model: str) -> ModelLimits:
        return GROQ_MODEL_LIMITS.get(model, ModelLimits())

    async def acquire(self, model: str) -> None:
        """
        Wait until it's safe to make an API call for this model.
        Enforces both RPM and RPD limits.
        """
        async with self._get_lock(model):
            limits = self._get_limits(model)
            usage  = self._usage[model]

            usage.reset_minute_if_needed()
            usage.reset_day_if_needed()

            # Check daily limit
            if usage.request_count_day >= limits.requests_per_day:
                wait_time = 86_400 - (time.time() - usage.day_window_start)
                logger.warning(
                    f"Daily limit reached for {model}. "
                    f"Resets in {wait_time/3600:.1f} hours."
                )
                raise DailyLimitExceededError(model, wait_time)

            # Check per-minute limit
            if usage.request_count_minute >= limits.requests_per_minute:
                wait_time = 60 - (time.time() - usage.minute_window_start)
                if wait_time > 0:
                    logger.debug(
                        f"RPM limit hit for {model}. "
                        f"Waiting {wait_time:.1f}s..."
                    )
                    await asyncio.sleep(wait_time + 0.1)
                    usage.reset_minute_if_needed()

            # Enforce minimum delay between calls
            elapsed = time.time() - usage.last_request_time
            if elapsed < limits.min_delay_seconds:
                sleep_time = limits.min_delay_seconds - elapsed
                await asyncio.sleep(sleep_time)

            usage.record_request()
            logger.debug(
                f"Groq call | Model: {model} | "
                f"RPM: {usage.request_count_minute}/{limits.requests_per_minute} | "
                f"RPD: {usage.request_count_day}/{limits.requests_per_day}"
            )

    def get_usage_stats(self, model: str) -> dict:
        """Return current usage stats for a model."""
        usage  = self._usage[model]
        limits = self._get_limits(model)
        usage.reset_minute_if_needed()
        usage.reset_day_if_needed()
        return {
            "model":         model,
            "rpm_used":      usage.request_count_minute,
            "rpm_limit":     limits.requests_per_minute,
            "rpd_used":      usage.request_count_day,
            "rpd_limit":     limits.requests_per_day,
            "rpm_remaining": limits.requests_per_minute - usage.request_count_minute,
            "rpd_remaining": limits.requests_per_day - usage.request_count_day,
        }

    def print_all_stats(self) -> None:
        """Print usage stats for all tracked models."""
        for model in self._usage:
            stats = self.get_usage_stats(model)
            logger.info(
                f"Usage | {stats['model']} | "
                f"RPM: {stats['rpm_used']}/{stats['rpm_limit']} | "
                f"RPD: {stats['rpd_used']}/{stats['rpd_limit']}"
            )


# ─────────────────────────────────────────────────────
#  Retry Logic
# ─────────────────────────────────────────────────────

async def with_retry(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    model: str = "unknown",
    **kwargs: Any,
) -> Any:
    """
    Call an async function with exponential backoff retry.
    Delays: 2s -> 4s -> 8s
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            error_str  = str(e).lower()

            if "429" in error_str or "rate limit" in error_str:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Rate limited on {model} | "
                        f"Attempt {attempt + 1}/{max_retries} | "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Rate limit persists after {max_retries} retries on {model}")
                    raise
            elif "timeout" in error_str or "timed out" in error_str:
                if attempt < max_retries:
                    delay = base_delay * (attempt + 1)
                    logger.warning(
                        f"Timeout on {model} | "
                        f"Attempt {attempt + 1}/{max_retries} | "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise
            else:
                logger.error(f"Non-retryable error on {model}: {e}")
                raise

    raise last_error


def sync_retry(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    model: str = "unknown",
    **kwargs: Any,
) -> Any:
    """Synchronous version of with_retry."""
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            error_str  = str(e).lower()

            if "429" in error_str or "rate limit" in error_str:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Rate limited on {model} | "
                        f"Attempt {attempt + 1}/{max_retries} | "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    raise
            else:
                logger.error(f"Non-retryable error on {model}: {e}")
                raise

    raise last_error


# ─────────────────────────────────────────────────────
#  Batch Spacing Helper
# ─────────────────────────────────────────────────────

async def batch_delay(
    batch_index: int,
    delay_between_batches: float = 5.0,
) -> None:
    """Add a delay between batches to respect daily limits."""
    if batch_index > 0:
        logger.debug(
            f"Batch {batch_index} complete. "
            f"Waiting {delay_between_batches}s before next batch..."
        )
        await asyncio.sleep(delay_between_batches)


# ─────────────────────────────────────────────────────
#  Custom Exceptions
# ─────────────────────────────────────────────────────

class RateLimitError(Exception):
    """Raised when rate limit is exceeded after all retries."""
    def __init__(self, model: str, message: str = "") -> None:
        self.model = model
        super().__init__(f"Rate limit exceeded for {model}. {message}")


class DailyLimitExceededError(Exception):
    """Raised when daily request quota is exhausted."""
    def __init__(self, model: str, resets_in_seconds: float) -> None:
        self.model = model
        self.resets_in_seconds = resets_in_seconds
        hours = resets_in_seconds / 3600
        super().__init__(
            f"Daily limit exceeded for {model}. "
            f"Resets in {hours:.1f} hours."
        )


# ─────────────────────────────────────────────────────
#  Global Instance (import this everywhere)
# ─────────────────────────────────────────────────────

rate_limiter = GroqRateLimiter()