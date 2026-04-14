"""
pipelines/harness_pipeline.py
═══════════════════════════════════════════════════════
Platform harness pipeline — runs HarnessAgent checks on a
configurable interval as a FastAPI background asyncio task.

Integration:
  Wire into main.py lifespan:

    from pipelines.harness_pipeline import HarnessPipeline
    harness = HarnessPipeline(...)
    harness_task = asyncio.create_task(harness.run())
    yield
    harness_task.cancel()

Cycle interval: HARNESS_INTERVAL_SECS env var (default 60s).

History: last N snapshots are kept in memory for the dashboard.
         N = HARNESS_HISTORY env var (default 20).

Circuit breakers per service are owned by this pipeline, not the agent,
so they persist across cycles without global state in the agent itself.
"""

from __future__ import annotations

import asyncio
import os
from collections import deque
from datetime import datetime
from typing import Any, Optional

from agents.harness_agent import (
    CBState,
    CircuitBreaker,
    HarnessAgent,
    HarnessSnapshot,
    PlatformMetrics,
    ServiceHealth,
)
from utils.logger import logger


_INTERVAL  = int(os.getenv("HARNESS_INTERVAL_SECS", "60"))
_HISTORY   = int(os.getenv("HARNESS_HISTORY", "20"))


class HarnessPipeline:
    """
    Owns the circuit breakers and runs check cycles indefinitely.

    All external references (dsa_sessions, session_store, page_index)
    are passed at construction so the harness always operates on the
    live in-memory objects — no copying, no staleness.
    """

    def __init__(
        self,
        dsa_sessions:  dict,       # portal_api._dsa_sessions (live ref)
        dsa_pipeline:  Any,        # DSAInterviewPipeline instance
        session_store: Any,        # SessionStore instance
        page_index:    Any,        # PageIndexStore instance
    ) -> None:
        self._agent        = HarnessAgent()
        self._dsa_sessions = dsa_sessions
        self._dsa_pipeline = dsa_pipeline
        self._session_store = session_store
        self._page_index   = page_index

        # One circuit breaker per external service
        self._cb: dict[str, CircuitBreaker] = {
            "groq":     CircuitBreaker(name="groq"),
            "supabase": CircuitBreaker(name="supabase"),
            "piston":   CircuitBreaker(name="piston"),
        }

        self._cycle       = 0
        self._history:    deque[HarnessSnapshot] = deque(maxlen=_HISTORY)
        self._latest:     Optional[HarnessSnapshot] = None
        self._started_at: Optional[datetime] = None
        self._running     = False

    # ── Background task entry point ───────────────────

    async def run(self) -> None:
        """
        Infinite loop: run one cycle, sleep, repeat.
        Designed to be run as asyncio.create_task().
        """
        self._running    = True
        self._started_at = datetime.utcnow()
        logger.info(
            f"HARNESS | Pipeline started | interval={_INTERVAL}s | history={_HISTORY}"
        )

        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The harness must NEVER crash the server
                logger.error(f"HARNESS | Unhandled cycle error (continuing): {exc}")

            await asyncio.sleep(_INTERVAL)

    # ── Single cycle ──────────────────────────────────

    async def _run_cycle(self) -> None:
        self._cycle += 1
        cycle_no = self._cycle
        t_start  = datetime.utcnow()
        services: dict[str, ServiceHealth] = {}

        logger.info(f"HARNESS | Cycle #{cycle_no} starting")

        # ── 1. External service checks (run in parallel) ──────────────
        tasks = {}

        if self._cb["groq"].is_callable():
            tasks["groq"] = asyncio.create_task(self._agent.check_groq())
        else:
            services["groq"] = ServiceHealth(
                name="groq", status="skipped",
                detail=f"Circuit OPEN — {self._cb['groq'].failures} failures",
            )

        if self._cb["supabase"].is_callable():
            tasks["supabase"] = asyncio.create_task(self._agent.check_supabase())
        else:
            services["supabase"] = ServiceHealth(
                name="supabase", status="skipped",
                detail=f"Circuit OPEN — {self._cb['supabase'].failures} failures",
            )

        if self._cb["piston"].is_callable():
            tasks["piston"] = asyncio.create_task(self._agent.check_piston())
        else:
            services["piston"] = ServiceHealth(
                name="piston", status="skipped",
                detail=f"Circuit OPEN — {self._cb['piston'].failures} failures",
            )

        # Gather all running tasks
        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    services[key] = ServiceHealth(
                        name=key, status="down", detail=str(result)[:100]
                    )
                    self._cb[key].record_failure()
                else:
                    services[key] = result
                    if result.status == "ok":
                        self._cb[key].record_success()
                    elif result.status == "down":
                        self._cb[key].record_failure()

        # ── 2. Internal consistency checks (sequential, fast) ─────────
        dsa_health, reaped = await self._agent.check_dsa_sessions(
            self._dsa_sessions, self._dsa_pipeline
        )
        services["dsa_sessions"] = dsa_health

        iv_health = await self._agent.check_interview_sessions(self._session_store)
        services["interview_sessions"] = iv_health

        pi_health = await self._agent.check_page_index(self._page_index)
        services["page_index"] = pi_health

        # ── 3. Metrics collection ─────────────────────────────────────
        groq_latency = services.get("groq", ServiceHealth(name="groq", status="skipped")).latency_ms
        metrics = await self._agent.collect_metrics(
            dsa_sessions=self._dsa_sessions,
            session_store=self._session_store,
            page_index=self._page_index,
            cycle_number=cycle_no,
            groq_latency_ms=groq_latency,
        )

        # ── 4. Build + store snapshot ─────────────────────────────────
        snapshot = self._agent.build_snapshot(cycle_no, services, metrics)
        self._latest = snapshot
        self._history.append(snapshot)

        # ── 5. Log summary ────────────────────────────────────────────
        elapsed_ms = (datetime.utcnow() - t_start).total_seconds() * 1000
        logger.info(
            f"HARNESS | Cycle #{cycle_no} done | "
            f"status={snapshot.status} | "
            f"alerts={len(snapshot.alerts)} | "
            f"reaped_dsa={len(reaped)} | "
            f"elapsed={elapsed_ms:.0f}ms"
        )

        if snapshot.alerts:
            for alert in snapshot.alerts:
                logger.warning(f"HARNESS | ALERT: {alert}")

    # ── Public API (called by health endpoint) ────────

    def get_status(self) -> dict:
        """Return a JSON-serialisable health status dict."""
        if not self._latest:
            return {
                "status":    "initializing",
                "cycle":     0,
                "message":   "First cycle not yet complete",
                "started_at": self._started_at.isoformat() if self._started_at else None,
            }

        snap = self._latest
        return {
            "status":      snap.status,
            "cycle":       snap.cycle,
            "timestamp":   snap.timestamp.isoformat(),
            "started_at":  self._started_at.isoformat() if self._started_at else None,
            "interval_s":  _INTERVAL,
            "alerts":      snap.alerts,
            "services": {
                name: {
                    "status":     svc.status,
                    "latency_ms": svc.latency_ms,
                    "detail":     svc.detail,
                    "checked_at": svc.checked_at.isoformat(),
                }
                for name, svc in snap.services.items()
            },
            "metrics": {
                "active_dsa_sessions":       snap.metrics.active_dsa_sessions,
                "active_interview_sessions": snap.metrics.active_interview_sessions,
                "page_index_size":           snap.metrics.page_index_size,
                "page_index_cap_pct":        snap.metrics.page_index_cap_pct,
                "groq_latency_ms":           snap.metrics.groq_latency_ms,
            },
            "circuit_breakers": {
                name: {
                    "state":    cb.state.value,
                    "failures": cb.failures,
                }
                for name, cb in self._cb.items()
            },
        }

    def get_history(self) -> list[dict]:
        """Return the last N cycle summaries for the dashboard chart."""
        out = []
        for snap in self._history:
            out.append({
                "cycle":     snap.cycle,
                "timestamp": snap.timestamp.isoformat(),
                "status":    snap.status,
                "alerts":    len(snap.alerts),
                "groq_ms":   snap.metrics.groq_latency_ms,
                "dsa_active": snap.metrics.active_dsa_sessions,
            })
        return out
