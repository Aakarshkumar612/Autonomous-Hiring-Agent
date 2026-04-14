"""
agents/harness_agent.py
═══════════════════════════════════════════════════════
Platform Harness Agent — the operational backbone of HireIQ.

Responsibilities:
  1. Health checks    — verify every external service on each cycle
  2. Circuit breakers — stop hammering a dead service; recover gracefully
  3. Session reaping  — expire timed-out DSA and interview sessions
  4. Pipeline sync    — detect orphaned state and self-heal
  5. Metrics          — maintain live platform counters
  6. Alerting         — structured log warnings when thresholds are breached

Design principles:
  - Every check is wrapped in try/except — harness NEVER crashes the server
  - Circuit breakers: 3 consecutive failures → OPEN (skip for 5 min)
  - All checks have hard timeouts (Groq 5s, Supabase 3s, Piston 3s)
  - Deterministic: no randomness, no sleeps inside checks
  - Observable: every cycle produces a structured health snapshot

Circuit breaker states:
  CLOSED    → normal, checks run every cycle
  OPEN      → service failed 3+ times; skip for RECOVERY_SECS (300s)
  HALF_OPEN → recovery window elapsed; run one probe; CLOSED if pass
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from utils.logger import logger


# ─────────────────────────────────────────────────────
#  Circuit breaker
# ─────────────────────────────────────────────────────

class CBState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


FAILURE_THRESHOLD = 3       # failures before OPEN
RECOVERY_SECS     = 300     # seconds before trying HALF_OPEN


@dataclass
class CircuitBreaker:
    name:          str
    state:         CBState = CBState.CLOSED
    failures:      int     = 0
    last_failure:  Optional[float] = None   # epoch seconds

    def record_success(self) -> None:
        self.failures     = 0
        self.state        = CBState.CLOSED
        self.last_failure = None

    def record_failure(self) -> None:
        self.failures    += 1
        self.last_failure = time.monotonic()
        if self.failures >= FAILURE_THRESHOLD:
            self.state = CBState.OPEN
            logger.warning(
                f"HARNESS | Circuit OPEN: {self.name} "
                f"({self.failures} consecutive failures)"
            )

    def is_callable(self) -> bool:
        """Return True if a check should run right now."""
        if self.state == CBState.CLOSED:
            return True
        if self.state == CBState.OPEN:
            elapsed = time.monotonic() - (self.last_failure or 0)
            if elapsed >= RECOVERY_SECS:
                self.state = CBState.HALF_OPEN
                logger.info(f"HARNESS | Circuit HALF_OPEN: {self.name} — probing")
                return True
            return False
        # HALF_OPEN — allow exactly one probe
        return True


# ─────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────

@dataclass
class ServiceHealth:
    name:        str
    status:      str        # "ok" | "degraded" | "down" | "skipped"
    latency_ms:  Optional[float] = None
    detail:      str        = ""
    checked_at:  datetime   = field(default_factory=datetime.utcnow)


@dataclass
class PlatformMetrics:
    active_dsa_sessions:       int   = 0
    active_interview_sessions: int   = 0
    total_applicants:          int   = 0
    shortlisted:               int   = 0
    page_index_size:           int   = 0
    page_index_cap_pct:        float = 0.0
    groq_latency_ms:           Optional[float] = None
    cycle_number:              int   = 0
    last_cycle_at:             Optional[datetime] = None


@dataclass
class HarnessSnapshot:
    """Complete health snapshot produced once per cycle."""
    cycle:      int
    timestamp:  datetime
    services:   dict[str, ServiceHealth]
    metrics:    PlatformMetrics
    alerts:     list[str]           # human-readable warnings
    status:     str                 # "healthy" | "degraded" | "critical"


# ─────────────────────────────────────────────────────
#  Harness Agent
# ─────────────────────────────────────────────────────

class HarnessAgent:
    """
    Stateless agent — all mutable state is in HarnessPipeline.

    Exposes individual async check methods so tests can call them in isolation.
    All checks return a ServiceHealth and never raise.
    """

    def __init__(self) -> None:
        self._groq_key     = os.getenv("GROQ_API_KEY", "")
        self._piston_url   = os.getenv("PISTON_URL", "https://emkc.org/api/v2/piston").rstrip("/")
        self._supabase_url = os.getenv("SUPABASE_URL", "")

    # ── External service checks ───────────────────────

    async def check_groq(self) -> ServiceHealth:
        """
        Send a minimal 1-token completion to Groq.
        Uses llama-3.1-8b-instant (cheapest) with a 5s timeout.
        """
        t0 = time.monotonic()
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=self._groq_key)
            model  = os.getenv("GROQ_SCORER", "llama-3.3-70b-versatile")

            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                ),
                timeout=5.0,
            )
            latency = (time.monotonic() - t0) * 1000
            model_used = resp.model or model

            logger.debug(f"HARNESS | Groq OK | {latency:.0f}ms | {model_used}")
            return ServiceHealth(
                name="groq",
                status="ok",
                latency_ms=round(latency, 1),
                detail=f"model={model_used}",
            )

        except asyncio.TimeoutError:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"HARNESS | Groq TIMEOUT | {latency:.0f}ms")
            return ServiceHealth(name="groq", status="down", latency_ms=round(latency, 1), detail="timeout >5s")

        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"HARNESS | Groq ERROR | {exc}")
            return ServiceHealth(name="groq", status="down", latency_ms=round(latency, 1), detail=str(exc)[:120])

    async def check_supabase(self) -> ServiceHealth:
        """
        Call supabase_store.count_applicants() in a thread (sync client).
        3s timeout via asyncio.wait_for.
        """
        if not self._supabase_url:
            return ServiceHealth(name="supabase", status="skipped", detail="SUPABASE_URL not set")

        t0 = time.monotonic()
        try:
            from connectors.supabase_mcp import supabase_store

            count = await asyncio.wait_for(
                asyncio.to_thread(supabase_store.count_applicants),
                timeout=3.0,
            )
            latency = (time.monotonic() - t0) * 1000
            logger.debug(f"HARNESS | Supabase OK | {latency:.0f}ms | {count} applicants")
            return ServiceHealth(
                name="supabase",
                status="ok",
                latency_ms=round(latency, 1),
                detail=f"{count} applicants in DB",
            )

        except asyncio.TimeoutError:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"HARNESS | Supabase TIMEOUT | {latency:.0f}ms")
            return ServiceHealth(name="supabase", status="down", latency_ms=round(latency, 1), detail="timeout >3s")

        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"HARNESS | Supabase ERROR | {exc}")
            return ServiceHealth(name="supabase", status="degraded", latency_ms=round(latency, 1), detail=str(exc)[:120])

    async def check_piston(self) -> ServiceHealth:
        """
        GET {PISTON_URL}/runtimes — lightweight Piston probe.
        3s timeout. Returns the number of available runtimes on success.
        """
        t0  = time.monotonic()
        url = f"{self._piston_url}/runtimes"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                latency = (time.monotonic() - t0) * 1000
                if resp.status_code == 200:
                    runtimes = resp.json()
                    count    = len(runtimes) if isinstance(runtimes, list) else "?"
                    logger.debug(f"HARNESS | Piston OK | {latency:.0f}ms | {count} runtimes")
                    return ServiceHealth(
                        name="piston",
                        status="ok",
                        latency_ms=round(latency, 1),
                        detail=f"{count} runtimes available",
                    )
                else:
                    logger.warning(f"HARNESS | Piston HTTP {resp.status_code}")
                    return ServiceHealth(
                        name="piston",
                        status="degraded",
                        latency_ms=round(latency, 1),
                        detail=f"HTTP {resp.status_code}",
                    )

        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"HARNESS | Piston ERROR | {exc}")
            return ServiceHealth(name="piston", status="down", latency_ms=round(latency, 1), detail=str(exc)[:120])

    # ── Internal consistency checks ───────────────────

    async def check_dsa_sessions(
        self,
        dsa_sessions: dict,         # _dsa_sessions from portal_api
        dsa_pipeline: Any,          # DSAInterviewPipeline instance
    ) -> tuple[ServiceHealth, list[str]]:
        """
        Find and reap DSA sessions that exceeded their duration_minutes.
        Returns (health, list_of_reaped_session_ids).
        """
        reaped = []
        now    = datetime.utcnow()

        try:
            from models.dsa_problem import DSASessionStatus

            for sid, session in list(dsa_sessions.items()):
                if session.status != DSASessionStatus.ACTIVE:
                    continue
                deadline = session.started_at + timedelta(minutes=session.duration_minutes)
                if now > deadline:
                    session.status  = DSASessionStatus.EXPIRED
                    session.ended_at = now
                    reaped.append(sid)
                    logger.info(f"HARNESS | Reaped expired DSA session: {sid}")

            detail = f"{len(dsa_sessions)} active, {len(reaped)} reaped"
            return (
                ServiceHealth(name="dsa_sessions", status="ok", detail=detail),
                reaped,
            )

        except Exception as exc:
            logger.warning(f"HARNESS | DSA session check failed: {exc}")
            return ServiceHealth(name="dsa_sessions", status="degraded", detail=str(exc)[:80]), []

    async def check_interview_sessions(
        self,
        session_store: Any,         # SessionStore instance
    ) -> ServiceHealth:
        """
        Verify interview session store is healthy and report active count.
        Expired sessions are purged by the existing purge loop; we just report.
        """
        try:
            active = len(session_store._sessions) if hasattr(session_store, '_sessions') else 0
            return ServiceHealth(
                name="interview_sessions",
                status="ok",
                detail=f"{active} active session(s)",
            )
        except Exception as exc:
            return ServiceHealth(name="interview_sessions", status="degraded", detail=str(exc)[:80])

    async def check_page_index(
        self,
        page_index: Any,            # PageIndexStore instance
    ) -> ServiceHealth:
        """
        Report PageIndex capacity utilisation. Alert if >90% full.
        """
        try:
            stats    = page_index.stats()
            cap_pct  = stats.get("cap_usage_pct", 0)
            is_near  = stats.get("is_near_cap", False)
            is_full  = stats.get("is_full", False)

            status = "ok"
            if is_full:
                status = "degraded"
                logger.warning(f"HARNESS | PageIndex FULL ({cap_pct:.1f}% used)")
            elif is_near:
                status = "degraded"
                logger.warning(f"HARNESS | PageIndex near cap ({cap_pct:.1f}% used)")

            return ServiceHealth(
                name="page_index",
                status=status,
                detail=f"{page_index.count()}/{page_index.cap} ({cap_pct:.1f}%)",
            )
        except Exception as exc:
            return ServiceHealth(name="page_index", status="degraded", detail=str(exc)[:80])

    # ── Metrics collection ────────────────────────────

    async def collect_metrics(
        self,
        dsa_sessions:     dict,
        session_store:    Any,
        page_index:       Any,
        cycle_number:     int,
        groq_latency_ms:  Optional[float],
    ) -> PlatformMetrics:
        """
        Aggregate platform-wide metrics from all in-memory stores.
        Pure reads — no mutations.
        """
        try:
            from models.dsa_problem import DSASessionStatus

            active_dsa = sum(
                1 for s in dsa_sessions.values()
                if s.status == DSASessionStatus.ACTIVE
            )
        except Exception:
            active_dsa = 0

        try:
            active_iv = len(session_store._sessions) if hasattr(session_store, '_sessions') else 0
        except Exception:
            active_iv = 0

        try:
            stats     = page_index.stats()
            pi_size   = page_index.count()
            pi_cap_pct = stats.get("cap_usage_pct", 0.0)
        except Exception:
            pi_size, pi_cap_pct = 0, 0.0

        return PlatformMetrics(
            active_dsa_sessions=active_dsa,
            active_interview_sessions=active_iv,
            page_index_size=pi_size,
            page_index_cap_pct=pi_cap_pct,
            groq_latency_ms=groq_latency_ms,
            cycle_number=cycle_number,
            last_cycle_at=datetime.utcnow(),
        )

    # ── Snapshot assembly ─────────────────────────────

    def build_snapshot(
        self,
        cycle:    int,
        services: dict[str, ServiceHealth],
        metrics:  PlatformMetrics,
    ) -> HarnessSnapshot:
        """Assemble the cycle snapshot and determine overall platform status."""
        alerts = []

        # Service-level alerts
        for svc in services.values():
            if svc.status == "down":
                alerts.append(f"{svc.name.upper()} is DOWN — {svc.detail}")
            elif svc.status == "degraded":
                alerts.append(f"{svc.name.upper()} degraded — {svc.detail}")

        # Metric-level alerts
        if metrics.page_index_cap_pct >= 90:
            alerts.append(f"PageIndex at {metrics.page_index_cap_pct:.1f}% capacity — add more space or raise MAX_APPLICANTS")
        if metrics.groq_latency_ms and metrics.groq_latency_ms > 3000:
            alerts.append(f"Groq latency elevated: {metrics.groq_latency_ms:.0f}ms")
        if metrics.active_dsa_sessions > 50:
            alerts.append(f"High DSA session load: {metrics.active_dsa_sessions} active sessions")

        # Overall status
        down_count = sum(1 for s in services.values() if s.status == "down")
        if down_count >= 2:
            status = "critical"
        elif down_count == 1 or any(s.status == "degraded" for s in services.values()):
            status = "degraded"
        else:
            status = "healthy"

        return HarnessSnapshot(
            cycle=cycle,
            timestamp=datetime.utcnow(),
            services=services,
            metrics=metrics,
            alerts=alerts,
            status=status,
        )
