"""
tests/test_scorer.py
═══════════════════════════════════════════════════════
Unit tests for ScorerAgent — specifically the JSON parsing
and grade calculation logic, which is pure Python and needs
no Groq API calls.

Run with:
    uv run pytest tests/test_scorer.py -v
"""

import json
import pytest

from models.score import (
    ApplicantScore,
    DimensionScore,
    ScoreGrade,
    ScoringDimension,
    ScoringStatus,
)
from agents.scorer import ScorerAgent


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def agent():
    """ScorerAgent with a dummy key — no API calls made in these tests."""
    return ScorerAgent(api_key="test-key-no-calls")


@pytest.fixture
def base_score():
    """Minimal ApplicantScore for use as parse target."""
    return ApplicantScore(
        applicant_id="APP-TEST001",
        applicant_name="Test Candidate",
        status=ScoringStatus.IN_PROGRESS,
    )


def _make_valid_response() -> str:
    """Return a well-formed JSON string matching the scorer prompt format."""
    return json.dumps({
        "dimensions": [
            {
                "dimension": "technical_skills",
                "score": 85.0,
                "weight": 0.35,
                "reasoning": "Strong Python and FastAPI skills.",
                "red_flags": [],
            },
            {
                "dimension": "experience",
                "score": 70.0,
                "weight": 0.25,
                "reasoning": "5 years matches the role requirement.",
                "red_flags": [],
            },
            {
                "dimension": "github_portfolio",
                "score": 60.0,
                "weight": 0.20,
                "reasoning": "Moderate GitHub activity.",
                "red_flags": ["Last commit 6 months ago"],
            },
            {
                "dimension": "cover_letter",
                "score": 80.0,
                "weight": 0.10,
                "reasoning": "Clear, targeted letter.",
                "red_flags": [],
            },
            {
                "dimension": "education",
                "score": 75.0,
                "weight": 0.10,
                "reasoning": "B.Tech in CS, relevant degree.",
                "red_flags": [],
            },
        ],
        "strengths": ["Strong Python", "Good communication"],
        "weaknesses": ["Limited open source contributions"],
        "overall_summary": "Solid mid-level candidate.",
        "recommendation": "Proceed to interview.",
    })


# ─── _parse_response tests ────────────────────────────────────────────────────

class TestParseResponse:

    def test_parses_all_five_dimensions(self, agent, base_score):
        """Parsing a valid 5-dimension response populates dimension_scores."""
        raw = _make_valid_response()
        result = agent._parse_response(raw, base_score)
        assert len(result.dimension_scores) == 5

    def test_dimension_types_are_correct(self, agent, base_score):
        """Each parsed dimension maps to the ScoringDimension enum."""
        raw = _make_valid_response()
        result = agent._parse_response(raw, base_score)
        dims = {ds.dimension for ds in result.dimension_scores}
        assert ScoringDimension.TECHNICAL_SKILLS in dims
        assert ScoringDimension.EXPERIENCE in dims

    def test_scores_are_floats(self, agent, base_score):
        """Score values are parsed as floats, not strings."""
        raw = _make_valid_response()
        result = agent._parse_response(raw, base_score)
        for ds in result.dimension_scores:
            assert isinstance(ds.score, float)

    def test_weights_preserved(self, agent, base_score):
        """Dimension weights from the JSON are stored correctly."""
        raw = _make_valid_response()
        result = agent._parse_response(raw, base_score)
        tech = next(d for d in result.dimension_scores if d.dimension == ScoringDimension.TECHNICAL_SKILLS)
        assert tech.weight == pytest.approx(0.35)

    def test_red_flags_parsed(self, agent, base_score):
        """Red flags list is populated from JSON."""
        raw = _make_valid_response()
        result = agent._parse_response(raw, base_score)
        github = next(d for d in result.dimension_scores if d.dimension == ScoringDimension.GITHUB_PORTFOLIO)
        assert "Last commit 6 months ago" in github.red_flags

    def test_strengths_and_weaknesses(self, agent, base_score):
        """Top-level strengths and weaknesses are stored on the score object."""
        raw = _make_valid_response()
        result = agent._parse_response(raw, base_score)
        assert "Strong Python" in result.strengths
        assert "Limited open source contributions" in result.weaknesses

    def test_missing_dimensions_raises(self, agent, base_score):
        """Response without 'dimensions' key raises ValueError."""
        raw = json.dumps({"overall_summary": "No dimensions here."})
        with pytest.raises(ValueError, match="dimensions"):
            agent._parse_response(raw, base_score)

    def test_invalid_json_raises(self, agent, base_score):
        """Non-JSON input raises json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            agent._parse_response("not json at all %%", base_score)

    def test_empty_dimensions_list_raises(self, agent, base_score):
        """Empty dimensions list is treated as missing and raises."""
        raw = json.dumps({"dimensions": []})
        with pytest.raises(ValueError):
            agent._parse_response(raw, base_score)


# ─── Grade calculation tests ──────────────────────────────────────────────────

class TestGradeCalculation:
    """
    Tests for ApplicantScore._assign_grade — the static method that converts
    a 0-100 float score into a letter grade.
    """

    @pytest.mark.parametrize("score,expected", [
        (97.0, ScoreGrade.A_PLUS),
        (90.0, ScoreGrade.A_PLUS),
        (85.0, ScoreGrade.A),
        (75.0, ScoreGrade.B),
        (70.0, ScoreGrade.B),
        (60.0, ScoreGrade.C),
        (55.0, ScoreGrade.C),
        (45.0, ScoreGrade.D),
        (40.0, ScoreGrade.D),
        (30.0, ScoreGrade.F),
        (0.0,  ScoreGrade.F),
    ])
    def test_grade_thresholds(self, score, expected):
        assert ApplicantScore._assign_grade(score) == expected

    def test_boundary_95(self):
        """95+ is A+."""
        assert ApplicantScore._assign_grade(95.0) == ScoreGrade.A_PLUS

    def test_boundary_exactly_85(self):
        """Exactly 85 is A (not A+)."""
        assert ApplicantScore._assign_grade(85.0) == ScoreGrade.A

    def test_boundary_exactly_70(self):
        """Exactly 70 is B."""
        assert ApplicantScore._assign_grade(70.0) == ScoreGrade.B


# ─── Weighted score calculation ───────────────────────────────────────────────

class TestWeightedScore:

    def test_weighted_score_formula(self):
        """DimensionScore.weighted_score() returns score * weight."""
        ds = DimensionScore(
            dimension=ScoringDimension.TECHNICAL_SKILLS,
            score=80.0,
            weight=0.35,
            reasoning="Good technical fundamentals demonstrated.",
        )
        assert ds.weighted_score() == pytest.approx(80.0 * 0.35)

    def test_compute_final_score_sums_weighted_dimensions(self):
        """ApplicantScore.compute_final_score() is the sum of weighted scores."""
        score = ApplicantScore(
            applicant_id="APP-X",
            applicant_name="X",
            dimension_scores=[
                DimensionScore(dimension=ScoringDimension.TECHNICAL_SKILLS, score=100.0, weight=0.5, reasoning="Strong technical skills shown."),
                DimensionScore(dimension=ScoringDimension.EXPERIENCE,       score=60.0,  weight=0.5, reasoning="Average experience level seen."),
            ],
        )
        final = score.compute_final_score()
        # (100*0.5) + (60*0.5) = 80
        assert final == pytest.approx(80.0)
