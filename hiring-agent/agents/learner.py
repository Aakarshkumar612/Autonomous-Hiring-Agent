"""
agents/learner.py
═══════════════════════════════════════════════════════
Learner Agent for the Autonomous Hiring Agent.
Uses Groq deepseek-r1-distill-qwen-32b (deep reasoning)
to analyse historical hiring outcomes and suggest
improvements to scoring weights, thresholds, and
interview question quality.

This agent runs offline / periodically — not in the
hot path. Latency doesn't matter; depth of reasoning does.

Usage:
    agent = LearnerAgent()
    insight = await agent.analyse(
        total_hired=80,
        total_rejected=320,
        avg_score_hired=78.4,
        avg_score_rejected=42.1,
        false_positive_rate=0.12,
        false_negative_rate=0.08,
        top_red_flags=["no GitHub", "vague claims"],
        scoring_dimension_accuracy={
            "technical_skills": 0.82,
            "experience": 0.74,
            ...
        },
    )
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from groq import AsyncGroq

from utils.logger import logger
from utils.prompt_templates import LEARNER_SYSTEM, learner_analysis_prompt
from utils.rate_limiter import DailyLimitExceededError, rate_limiter, with_retry

LEARNER_MODEL = os.getenv("GROQ_LEARNER", "deepseek-r1-distill-qwen-32b")


# ─────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────

@dataclass
class LearnerInsight:
    """
    Output of the Learner Agent's analysis run.

    Attributes:
        insights                — key patterns observed in hiring data
        weight_adjustments      — recommended new weights per dimension (sum → 1.0)
        new_red_flags           — newly identified signals to watch
        interview_improvements  — suggested changes to interview questions
        threshold_recommendations — recommended shortlist / auto-reject thresholds
        summary                 — human-readable overall summary
        raw_response            — raw JSON string from the model (for auditing)
    """
    insights:                  list[str]       = field(default_factory=list)
    weight_adjustments:        dict[str, float] = field(default_factory=dict)
    new_red_flags:             list[str]       = field(default_factory=list)
    interview_improvements:    list[str]       = field(default_factory=list)
    threshold_recommendations: dict[str, float] = field(default_factory=dict)
    summary:                   str             = ""
    raw_response:              str             = ""
    error:                     str | None      = None


# ─────────────────────────────────────────────────────
#  Agent
# ─────────────────────────────────────────────────────

class LearnerAgent:
    """
    Analyses historical hiring outcomes and produces
    data-driven recommendations to improve scoring accuracy,
    interview quality, and detection thresholds.

    Uses deepseek-r1-distill-qwen-32b's chain-of-thought
    reasoning for deep pattern recognition.

    Stateless — safe to reuse across multiple analysis runs.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = LEARNER_MODEL

    # ─────────────────────────────────────────────────
    #  Groq API call
    # ─────────────────────────────────────────────────

    async def _call_groq(self, prompt: str) -> str:
        """Single reasoning call — no conversation history needed."""
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": LEARNER_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.0,      # deterministic — same data must produce same recommendations
            max_tokens=900,       # JSON with 3-5 recommendations fits well under this
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    # ─────────────────────────────────────────────────
    #  JSON → LearnerInsight
    # ─────────────────────────────────────────────────

    def _parse_response(self, raw: str) -> LearnerInsight:
        data = json.loads(raw)

        weight_adj = data.get("weight_adjustments", {})
        thresh     = data.get("threshold_recommendations", {})

        insight = LearnerInsight(
            insights=data.get("insights", []),
            weight_adjustments={
                str(k): float(v) for k, v in weight_adj.items()
            },
            new_red_flags=data.get("new_red_flags", []),
            interview_improvements=data.get("interview_improvements", []),
            threshold_recommendations={
                str(k): float(v) for k, v in thresh.items()
            },
            summary=data.get("summary", ""),
            raw_response=raw,
        )
        return insight

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def analyse(
        self,
        total_hired:                int,
        total_rejected:             int,
        avg_score_hired:            float,
        avg_score_rejected:         float,
        false_positive_rate:        float,
        false_negative_rate:        float,
        top_red_flags:              list[str],
        scoring_dimension_accuracy: dict[str, float],
    ) -> LearnerInsight:
        """
        Run a full analysis of hiring outcomes and return
        actionable improvement recommendations.

        Args:
            total_hired                  — number of accepted candidates
            total_rejected               — number of rejected candidates
            avg_score_hired              — average score of hired candidates
            avg_score_rejected           — average score of rejected candidates
            false_positive_rate          — hired but performed poorly (0.0–1.0)
            false_negative_rate          — rejected but would have performed well (0.0–1.0)
            top_red_flags                — red flags that most predicted poor performance
            scoring_dimension_accuracy   — {dimension_name: accuracy_0.0_to_1.0}

        Returns:
            LearnerInsight with weight adjustments, new red flags, and more.
            On error, returns a LearnerInsight with error set and empty recommendations.
        """
        logger.info(
            f"LEARNER | Starting analysis | "
            f"Hired: {total_hired} | Rejected: {total_rejected} | "
            f"FP rate: {false_positive_rate:.1%} | FN rate: {false_negative_rate:.1%}"
        )

        try:
            prompt = learner_analysis_prompt(
                total_hired=total_hired,
                total_rejected=total_rejected,
                avg_score_hired=avg_score_hired,
                avg_score_rejected=avg_score_rejected,
                false_positive_rate=false_positive_rate,
                false_negative_rate=false_negative_rate,
                top_red_flags=top_red_flags,
                scoring_dimension_accuracy=scoring_dimension_accuracy,
            )

            raw = await with_retry(
                self._call_groq,
                prompt,
                max_retries=3,
                base_delay=2.0,
                model=self.model,
            )

            result = self._parse_response(raw)

        except DailyLimitExceededError:
            raise

        except Exception as e:
            logger.error(f"LEARNER | Analysis failed: {e}")
            return LearnerInsight(
                summary=f"Analysis failed — manual review required: {e}",
                error=str(e),
            )

        # Log all weight adjustment recommendations
        if result.weight_adjustments:
            logger.info(
                f"LEARNER | Weight adjustments recommended: "
                + " | ".join(
                    f"{k}={v:.2f}" for k, v in result.weight_adjustments.items()
                )
            )

        if result.threshold_recommendations:
            logger.info(
                f"LEARNER | Threshold recommendations: "
                + " | ".join(
                    f"{k}={v}" for k, v in result.threshold_recommendations.items()
                )
            )

        if result.new_red_flags:
            logger.info(
                f"LEARNER | New red flags identified: {result.new_red_flags}"
            )

        logger.info(f"LEARNER | Analysis complete | Summary: {result.summary[:120]}")

        return result
