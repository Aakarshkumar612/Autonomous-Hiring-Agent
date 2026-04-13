"""
connectors/feature_gate.py
═══════════════════════════════════════════════════════
Subscription-aware feature gate.

Every DSA/interview action goes through FeatureGate.check()
before executing. Enforces:
  - Tier feature availability (is this feature in their plan?)
  - Daily usage limits (how many times today?)
  - Per-recruiter feature toggles (MAX/ENTERPRISE only)

Supabase tables used:
  subscriptions    — recruiter tier + expiry
  feature_toggles  — per-recruiter on/off overrides
  usage_records    — today's per-feature counts

Usage (FastAPI dependency):
    gate = FeatureGate()
    result = await gate.check(recruiter_id="rec_123", feature=Feature.DSA_TEST)
    if not result.allowed:
        raise HTTPException(403, result.reason)
    # ... do the thing ...
    await gate.increment_usage(recruiter_id="rec_123", feature=Feature.DSA_TEST)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from models.subscription import (
    DailyUsageRecord,
    Feature,
    FeatureToggle,
    RecruiterSubscription,
    SubscriptionStatus,
    TIER_CONFIGS,
    TierType,
)
from utils.logger import logger


@dataclass
class GateResult:
    allowed:    bool
    reason:     str = ""          # human-readable denial reason
    tier:       TierType = TierType.FREE
    usage_today: int = 0
    limit:      int = 0           # -1 = unlimited
    remaining:  int = 0           # -1 = unlimited


class FeatureGate:
    """
    Async feature gate. Backed by Supabase when available;
    falls back to a simple in-memory store for local dev.
    """

    def __init__(self) -> None:
        # In-memory fallback (dev mode when Supabase is not configured)
        self._dev_mode = not bool(os.getenv("SUPABASE_URL"))
        self._mem_usage:   dict[str, dict[str, int]]  = {}   # rec_id → feat → count
        self._mem_tiers:   dict[str, TierType]         = {}   # rec_id → tier
        self._mem_toggles: dict[str, dict[str, bool]]  = {}   # rec_id → feat → bool

        if self._dev_mode:
            logger.warning(
                "FEATURE_GATE | SUPABASE_URL not set — running in dev mode. "
                "All recruiters default to FREE tier. No persistence."
            )

    # ── Core gate check ───────────────────────────────

    async def check(
        self,
        recruiter_id: str,
        feature:      Feature,
    ) -> GateResult:
        """
        Check whether recruiter_id can use feature right now.
        Returns GateResult.allowed=True if all checks pass.
        """
        tier      = await self._get_tier(recruiter_id)
        config    = TIER_CONFIGS[tier]

        # 1. Is this feature available on their plan?
        if not config.features.has(feature):
            return GateResult(
                allowed=False,
                reason=(
                    f"Feature '{feature.value}' is not available on the {config.display_name} plan. "
                    f"Upgrade to access this feature."
                ),
                tier=tier,
            )

        # 2. Per-recruiter toggle override (MAX/ENTERPRISE only)
        toggle = await self._get_toggle(recruiter_id, feature)
        if toggle is False:
            return GateResult(
                allowed=False,
                reason=f"Feature '{feature.value}' has been disabled by your account settings.",
                tier=tier,
            )

        # 3. Daily usage limit
        limit       = config.limits.get(feature)
        usage_today = await self._get_usage_today(recruiter_id, feature)

        if limit != -1 and usage_today >= limit:
            return GateResult(
                allowed=False,
                reason=(
                    f"Daily limit reached for '{feature.value}'. "
                    f"Used {usage_today}/{limit} today. Resets at midnight UTC."
                ),
                tier=tier,
                usage_today=usage_today,
                limit=limit,
                remaining=0,
            )

        remaining = -1 if limit == -1 else max(0, limit - usage_today)
        return GateResult(
            allowed=True,
            tier=tier,
            usage_today=usage_today,
            limit=limit,
            remaining=remaining,
        )

    async def increment_usage(
        self,
        recruiter_id: str,
        feature:      Feature,
    ) -> None:
        """Increment today's usage count by 1. Call after successful feature use."""
        if self._dev_mode:
            today = date.today().isoformat()
            key   = f"{recruiter_id}:{today}"
            self._mem_usage.setdefault(key, {})
            self._mem_usage[key][feature.value] = (
                self._mem_usage[key].get(feature.value, 0) + 1
            )
            return

        # Supabase upsert
        try:
            from connectors.supabase_mcp import supabase_store
            await asyncio.to_thread(
                supabase_store.increment_feature_usage,
                recruiter_id,
                feature.value,
            )
        except Exception as exc:
            logger.error(f"FEATURE_GATE | increment_usage failed: {exc}")

    async def get_status(self, recruiter_id: str) -> SubscriptionStatus:
        """Return full subscription status (used by GET /subscription)."""
        tier   = await self._get_tier(recruiter_id)
        config = TIER_CONFIGS[tier]

        features:    dict[str, bool] = {}
        limits:      dict[str, int]  = {}
        usage_today: dict[str, int]  = {}
        remaining:   dict[str, int]  = {}
        toggles:     dict[str, bool] = {}

        for feat in Feature:
            feat_val  = feat.value
            enabled   = config.features.has(feat)
            lim       = config.limits.get(feat)
            used      = await self._get_usage_today(recruiter_id, feat)
            tog       = await self._get_toggle(recruiter_id, feat)

            # Override with per-recruiter toggle if set
            if tog is not None:
                enabled = tog

            rem = -1 if lim == -1 else max(0, lim - used)

            features[feat_val]    = enabled
            limits[feat_val]      = lim
            usage_today[feat_val] = used
            remaining[feat_val]   = rem
            if tog is not None:
                toggles[feat_val] = tog

        return SubscriptionStatus(
            recruiter_id=recruiter_id,
            tier=tier,
            display_name=config.display_name,
            price_monthly=config.price_monthly,
            is_active=True,
            features=features,
            limits=limits,
            usage_today=usage_today,
            remaining_today=remaining,
            toggles=toggles,
        )

    async def set_toggle(
        self,
        recruiter_id: str,
        feature:      Feature,
        enabled:      bool,
        note:         str = "",
    ) -> bool:
        """
        Set per-recruiter feature toggle. Only effective on MAX/ENTERPRISE.
        Returns False if tier doesn't support toggles.
        """
        tier = await self._get_tier(recruiter_id)
        if not TIER_CONFIGS[tier].features.has(Feature.FEATURE_TOGGLES):
            return False

        if self._dev_mode:
            self._mem_toggles.setdefault(recruiter_id, {})
            self._mem_toggles[recruiter_id][feature.value] = enabled
            return True

        try:
            from connectors.supabase_mcp import supabase_store
            await asyncio.to_thread(
                supabase_store.set_feature_toggle,
                recruiter_id,
                feature.value,
                enabled,
                note,
            )
            return True
        except Exception as exc:
            logger.error(f"FEATURE_GATE | set_toggle failed: {exc}")
            return False

    # ── Internal helpers ──────────────────────────────

    async def _get_tier(self, recruiter_id: str) -> TierType:
        if self._dev_mode:
            return self._mem_tiers.get(recruiter_id, TierType.FREE)
        try:
            from connectors.supabase_mcp import supabase_store
            row = await asyncio.to_thread(supabase_store.get_subscription, recruiter_id)
            if row:
                return TierType(row.get("tier", "free"))
        except Exception as exc:
            logger.warning(f"FEATURE_GATE | _get_tier failed: {exc}")
        return TierType.FREE

    async def _get_usage_today(self, recruiter_id: str, feature: Feature) -> int:
        if self._dev_mode:
            today = date.today().isoformat()
            key   = f"{recruiter_id}:{today}"
            return self._mem_usage.get(key, {}).get(feature.value, 0)
        try:
            from connectors.supabase_mcp import supabase_store
            count = await asyncio.to_thread(
                supabase_store.get_feature_usage_today,
                recruiter_id,
                feature.value,
            )
            return count or 0
        except Exception:
            return 0

    async def _get_toggle(self, recruiter_id: str, feature: Feature) -> Optional[bool]:
        """Returns None if no override is set."""
        if self._dev_mode:
            toggles = self._mem_toggles.get(recruiter_id, {})
            return toggles.get(feature.value)   # None if not set
        try:
            from connectors.supabase_mcp import supabase_store
            row = await asyncio.to_thread(
                supabase_store.get_feature_toggle,
                recruiter_id,
                feature.value,
            )
            if row is not None:
                return bool(row.get("enabled", True))
        except Exception:
            pass
        return None


# Singleton for FastAPI dependency injection
_gate_instance: Optional[FeatureGate] = None


def get_feature_gate() -> FeatureGate:
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = FeatureGate()
    return _gate_instance
