"""
tests/test_detector.py
═══════════════════════════════════════════════════════
Unit tests for DetectorAgent — specifically the JSON parsing
and verdict/confidence logic. No Groq API calls made.

Run with:
    uv run pytest tests/test_detector.py -v
"""

import json
import os
import pytest

from models.applicant import AIDetectionVerdict
from agents.detector import DetectorAgent, DetectionResult


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def agent():
    """DetectorAgent with a dummy key — no API calls in these tests."""
    return DetectorAgent(api_key="test-key-no-calls")


# ─── _parse_response tests ────────────────────────────────────────────────────

class TestParseResponse:

    def test_parses_clean_verdict(self, agent):
        raw = json.dumps({
            "verdict":    "clean",
            "confidence": 0.92,
            "signals":    ["Specific anecdotes", "Natural hesitation in phrasing"],
            "reasoning":  "Response contains personal details not found online.",
        })
        result = agent._parse_response(raw, question_id="Q1")
        assert result.verdict == AIDetectionVerdict.CLEAN
        assert result.confidence == pytest.approx(0.92)

    def test_parses_ai_generated_verdict(self, agent):
        raw = json.dumps({
            "verdict":    "ai_generated",
            "confidence": 0.88,
            "signals":    ["Overly structured bullet points", "Generic corporate-speak"],
            "reasoning":  "Response matches common ChatGPT patterns.",
        })
        result = agent._parse_response(raw, question_id="Q2")
        assert result.verdict == AIDetectionVerdict.AI_GENERATED
        assert result.confidence == pytest.approx(0.88)

    def test_parses_suspicious_verdict(self, agent):
        raw = json.dumps({
            "verdict":    "suspicious",
            "confidence": 0.62,
            "signals":    ["Unusually perfect grammar"],
            "reasoning":  "Unclear; borderline.",
        })
        result = agent._parse_response(raw, question_id="Q3")
        assert result.verdict == AIDetectionVerdict.SUSPICIOUS

    def test_signals_list_populated(self, agent):
        raw = json.dumps({
            "verdict":    "ai_generated",
            "confidence": 0.80,
            "signals":    ["Signal A", "Signal B", "Signal C"],
            "reasoning":  "Three signals detected.",
        })
        result = agent._parse_response(raw, question_id="Q4")
        assert len(result.signals) == 3
        assert "Signal A" in result.signals

    def test_empty_signals_defaults_to_empty_list(self, agent):
        raw = json.dumps({
            "verdict":    "clean",
            "confidence": 0.95,
            "signals":    [],
            "reasoning":  "Clearly human.",
        })
        result = agent._parse_response(raw, question_id="Q5")
        assert result.signals == []

    def test_question_id_stored(self, agent):
        raw = json.dumps({
            "verdict": "clean", "confidence": 0.9,
            "signals": [], "reasoning": ""
        })
        result = agent._parse_response(raw, question_id="my-question-id")
        assert result.question_id == "my-question-id"

    def test_missing_fields_use_defaults(self, agent):
        """Partial response: only verdict present — confidence defaults to 0.5."""
        raw = json.dumps({"verdict": "suspicious"})
        result = agent._parse_response(raw, question_id=None)
        assert result.confidence == pytest.approx(0.5)
        assert result.signals == []

    def test_invalid_json_raises(self, agent):
        with pytest.raises(json.JSONDecodeError):
            agent._parse_response("{bad json", question_id=None)


# ─── Flag threshold tests ─────────────────────────────────────────────────────

class TestFlagThreshold:
    """
    The DetectorAgent flags a response if confidence >= AI_DETECTION_THRESHOLD
    (default 0.75 from env). Test the flagging logic.
    """

    def test_flagged_when_confidence_above_threshold(self, agent):
        # Default threshold is 0.75
        raw = json.dumps({
            "verdict": "ai_generated", "confidence": 0.80,
            "signals": [], "reasoning": ""
        })
        result = agent._parse_response(raw, question_id=None)
        assert result.flagged is True

    def test_not_flagged_when_confidence_below_threshold(self, agent):
        raw = json.dumps({
            "verdict": "suspicious", "confidence": 0.50,
            "signals": [], "reasoning": ""
        })
        result = agent._parse_response(raw, question_id=None)
        assert result.flagged is False

    def test_not_flagged_for_clean_verdict_even_high_confidence(self, agent):
        """A 'clean' verdict with 0.95 confidence should resolve to CLEAN verdict."""
        raw = json.dumps({
            "verdict": "clean", "confidence": 0.95,
            "signals": [], "reasoning": ""
        })
        result = agent._parse_response(raw, question_id=None)
        assert result.verdict == AIDetectionVerdict.CLEAN


# ─── DetectionResult dataclass tests ─────────────────────────────────────────

class TestDetectionResult:

    def test_detection_result_fields(self):
        """DetectionResult stores all expected fields."""
        result = DetectionResult(
            question_id="q1",
            verdict=AIDetectionVerdict.AI_GENERATED,
            confidence=0.90,
            signals=["generic phrasing"],
            reasoning="Typical AI response.",
            flagged=True,
        )
        assert result.question_id == "q1"
        assert result.verdict == AIDetectionVerdict.AI_GENERATED
        assert result.confidence == 0.90
        assert result.flagged is True

    def test_signals_defaults_to_empty(self):
        """Signals has a default factory of empty list."""
        result = DetectionResult(
            question_id=None,
            verdict=AIDetectionVerdict.CLEAN,
            confidence=0.80,
            reasoning="Fine.",
            flagged=False,
        )
        assert result.signals == []
