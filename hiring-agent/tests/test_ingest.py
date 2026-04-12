"""
tests/test_ingest.py
═══════════════════════════════════════════════════════
Unit tests for CSVIngestor (pure Python parsing logic)
and IngestPipeline (bucketing, status assignment, result
dataclass). Zero Groq or Supabase calls are made.

Run with:
    uv run pytest tests/test_ingest.py -v
"""

import io
import pytest

from connectors.csv_ingestor import (
    CSVIngestor,
    IngestResult,
    _fix_url,
    _generate_id,
    _parse_experience_level,
    _parse_role,
    _parse_skills,
    _safe_str,
)
from models.applicant import (
    Applicant,
    ApplicationStatus,
    ExperienceLevel,
    TechRole,
)
from models.score import ApplicantScore, ScoringStatus
from pipelines.ingest import IngestPipeline, IngestPipelineResult


# ─── CSV helpers ──────────────────────────────────────────────────────────────

def _make_csv(*rows: str) -> bytes:
    """Build a minimal CSV file from header + data rows."""
    header = "name,email,role,experience,skills,github,location"
    lines  = [header] + list(rows)
    return "\n".join(lines).encode()


def _make_applicant(
    applicant_id: str = "APP-TEST001",
    score_val: float | None = None,
    status: ScoringStatus = ScoringStatus.COMPLETED,
) -> tuple[Applicant, ApplicantScore]:
    """Return a minimal (Applicant, ApplicantScore) pair for pipeline tests."""
    applicant = Applicant(
        id=applicant_id,
        full_name="Test User",
        email=f"{applicant_id.lower()}@test.com",
        role_applied=TechRole.SDE,
        status=ApplicationStatus.PENDING,
    )
    score = ApplicantScore(
        applicant_id=applicant_id,
        applicant_name="Test User",
        status=status,
        final_score=score_val,
    )
    return applicant, score


# ─── _parse_role ──────────────────────────────────────────────────────────────

class TestParseRole:

    def test_sde_exact(self):
        assert _parse_role("sde") == TechRole.SDE

    def test_software_engineer(self):
        assert _parse_role("Software Engineer") == TechRole.SDE

    def test_backend_engineer(self):
        assert _parse_role("Backend Engineer") == TechRole.BACKEND

    def test_frontend_developer(self):
        assert _parse_role("frontend developer") == TechRole.FRONTEND

    def test_fullstack(self):
        assert _parse_role("full stack") == TechRole.FULLSTACK

    def test_ml_engineer(self):
        assert _parse_role("ML Engineer") == TechRole.ML_ENGINEER

    def test_data_scientist(self):
        assert _parse_role("data scientist") == TechRole.DATA_SCIENTIST

    def test_devops(self):
        assert _parse_role("devops engineer") == TechRole.DEVOPS

    def test_unknown_defaults_to_sde(self):
        """Unrecognised role strings fall back to SDE."""
        assert _parse_role("quantum teleportation specialist") == TechRole.SDE


# ─── _parse_experience_level ──────────────────────────────────────────────────

class TestParseExperienceLevel:

    @pytest.mark.parametrize("years,expected", [
        (0,   ExperienceLevel.FRESHER),
        (0.5, ExperienceLevel.JUNIOR),
        (2,   ExperienceLevel.JUNIOR),
        (3,   ExperienceLevel.MID),
        (5,   ExperienceLevel.MID),
        (6,   ExperienceLevel.SENIOR),
        (8,   ExperienceLevel.SENIOR),
        (9,   ExperienceLevel.LEAD),
        (15,  ExperienceLevel.LEAD),
    ])
    def test_levels(self, years, expected):
        assert _parse_experience_level(years) == expected


# ─── _parse_skills ────────────────────────────────────────────────────────────

class TestParseSkills:

    def test_comma_separated(self):
        skills = _parse_skills("Python,FastAPI,Docker")
        names = [s.name for s in skills]
        assert names == ["Python", "FastAPI", "Docker"]

    def test_pipe_separated(self):
        skills = _parse_skills("Go|Rust|C++")
        assert len(skills) == 3
        assert skills[0].name == "Go"

    def test_semicolon_separated(self):
        skills = _parse_skills("Java;Spring;Kafka")
        assert len(skills) == 3

    def test_single_skill(self):
        skills = _parse_skills("Python")
        assert len(skills) == 1
        assert skills[0].name == "Python"

    def test_empty_string_returns_empty(self):
        assert _parse_skills("") == []

    def test_nan_float_returns_empty(self):
        """Pandas NaN cells come through as float('nan')."""
        assert _parse_skills(float("nan")) == []

    def test_strips_whitespace(self):
        skills = _parse_skills("  Python ,  FastAPI  ")
        assert skills[0].name == "Python"
        assert skills[1].name == "FastAPI"


# ─── _fix_url ─────────────────────────────────────────────────────────────────

class TestFixUrl:

    def test_adds_https_when_missing(self):
        assert _fix_url("github.com/user") == "https://github.com/user"

    def test_preserves_existing_https(self):
        assert _fix_url("https://github.com/user") == "https://github.com/user"

    def test_preserves_http(self):
        assert _fix_url("http://example.com") == "http://example.com"

    def test_none_returns_none(self):
        assert _fix_url(None) is None

    def test_empty_string_returns_none(self):
        assert _fix_url("") is None

    def test_whitespace_only_returns_none(self):
        assert _fix_url("   ") is None


# ─── _generate_id ─────────────────────────────────────────────────────────────

class TestGenerateId:

    def test_format(self):
        id_ = _generate_id("Alice", 0)
        assert id_.startswith("CSV-ALI")

    def test_index_padded(self):
        id_ = _generate_id("Bob", 5)
        assert "0005" in id_

    def test_empty_name_uses_fallback(self):
        id_ = _generate_id("", 1)
        assert id_.startswith("CSV-APP")


# ─── _safe_str ────────────────────────────────────────────────────────────────

class TestSafeStr:

    def test_normal_string(self):
        assert _safe_str("hello") == "hello"

    def test_nan_string_returns_none(self):
        assert _safe_str("nan") is None

    def test_empty_string_returns_none(self):
        assert _safe_str("") is None

    def test_whitespace_stripped(self):
        assert _safe_str("  hello  ") == "hello"


# ─── CSVIngestor: valid CSV ───────────────────────────────────────────────────

class TestCSVIngestorValid:

    def test_parses_single_valid_row(self):
        csv = _make_csv("Alice Smith,alice@example.com,sde,3,Python|FastAPI,github.com/alice,London")
        result = CSVIngestor().ingest(csv, "csv")
        assert result.success_count == 1
        assert result.applicants[0].full_name == "Alice Smith"
        assert result.applicants[0].email == "alice@example.com"

    def test_parses_multiple_rows(self):
        csv = _make_csv(
            "Alice,alice@test.com,sde,3,Python,,",
            "Bob,bob@test.com,backend,5,Go,,",
        )
        result = CSVIngestor().ingest(csv, "csv")
        assert result.success_count == 2

    def test_role_is_parsed(self):
        csv = _make_csv("Dev,dev@test.com,ml engineer,2,TensorFlow,,")
        result = CSVIngestor().ingest(csv, "csv")
        assert result.applicants[0].role_applied == TechRole.ML_ENGINEER

    def test_experience_converted_to_months(self):
        csv = _make_csv("Dev,dev@test.com,sde,2,Python,,")
        result = CSVIngestor().ingest(csv, "csv")
        # 2 years = 24 months
        assert result.applicants[0].total_experience_months == 24

    def test_github_url_fixed(self):
        csv = _make_csv("Dev,dev@test.com,sde,1,Python,github.com/dev,")
        result = CSVIngestor().ingest(csv, "csv")
        assert result.applicants[0].github_url == "https://github.com/dev"

    def test_source_label_stored(self):
        csv = _make_csv("Dev,dev@test.com,sde,0,,,")
        result = CSVIngestor().ingest(csv, "csv", source_label="test_source")
        assert result.applicants[0].source == "test_source"

    def test_skills_parsed_from_pipe(self):
        csv = _make_csv("Dev,dev@test.com,sde,1,Python|Django|PostgreSQL,,")
        result = CSVIngestor().ingest(csv, "csv")
        names = [s.name for s in result.applicants[0].skills]
        assert "Python" in names
        assert "Django" in names

    def test_status_defaults_to_pending(self):
        csv = _make_csv("Dev,dev@test.com,sde,1,,,")
        result = CSVIngestor().ingest(csv, "csv")
        assert result.applicants[0].status == ApplicationStatus.PENDING

    def test_total_rows_count(self):
        csv = _make_csv(
            "A,a@test.com,sde,1,,,",
            "B,b@test.com,sde,2,,,",
            "C,c@test.com,sde,3,,,",
        )
        result = CSVIngestor().ingest(csv, "csv")
        assert result.total_rows == 3


# ─── CSVIngestor: error handling ─────────────────────────────────────────────

class TestCSVIngestorErrors:

    def test_missing_email_skipped(self):
        csv = _make_csv("No Email,,sde,1,,,")
        result = CSVIngestor().ingest(csv, "csv")
        assert result.success_count == 0
        assert result.error_count == 1

    def test_invalid_email_skipped(self):
        csv = _make_csv("Bad Email,not-an-email,sde,1,,,")
        result = CSVIngestor().ingest(csv, "csv")
        assert result.success_count == 0
        assert result.error_count == 1

    def test_good_and_bad_rows_independent(self):
        """One bad row should not stop the other rows from being parsed."""
        csv = _make_csv(
            "Good,good@test.com,sde,2,,,",
            "Bad,,sde,1,,,",
            "Also Good,also@test.com,backend,3,,,",
        )
        result = CSVIngestor().ingest(csv, "csv")
        assert result.success_count == 2
        assert result.error_count == 1

    def test_unsupported_file_type(self):
        result = CSVIngestor().ingest(b"data", "pdf")
        assert result.success_count == 0
        assert result.error_count >= 1

    def test_corrupt_file_returns_error(self):
        result = CSVIngestor().ingest(b"\xff\xfe invalid bytes %%%", "csv")
        # May either error or return 0 rows — should not raise an exception
        assert isinstance(result, IngestResult)


# ─── IngestResult dataclass ───────────────────────────────────────────────────

class TestIngestResult:

    def test_success_count_property(self):
        result = IngestResult(source_label="test", file_type="csv")
        result.applicants = [object(), object()]   # type: ignore
        assert result.success_count == 2

    def test_error_count_property(self):
        result = IngestResult(source_label="test", file_type="csv")
        result.errors = [{"row": 2, "error": "bad email"}]
        assert result.error_count == 1

    def test_summary_contains_counts(self):
        result = IngestResult(source_label="mysrc", file_type="csv")
        result.total_rows = 10
        result.applicants = [object()] * 7   # type: ignore
        result.errors     = [{"row": i} for i in range(3)]
        s = result.summary()
        assert "10" in s
        assert "7" in s
        assert "3" in s


# ─── IngestPipelineResult dataclass ──────────────────────────────────────────

class TestIngestPipelineResult:

    def test_duration_seconds_none_before_completion(self):
        result = IngestPipelineResult()
        assert result.duration_seconds is None

    def test_duration_seconds_after_completion(self):
        import time
        result = IngestPipelineResult()
        time.sleep(0.05)
        from datetime import datetime
        result.completed_at = datetime.utcnow()
        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0.0

    def test_summary_contains_all_counts(self):
        result = IngestPipelineResult(total_applicants=5)
        _, s1 = _make_applicant("A")
        _, s2 = _make_applicant("B")
        result.shortlisted = [s1]
        result.rejected    = [s2]
        summary = result.summary()
        assert "5" in summary
        assert "Shortlisted" in summary
        assert "Rejected" in summary


# ─── IngestPipeline: _bucket_score ───────────────────────────────────────────

class TestBucketScore:
    """
    _bucket_score routes an ApplicantScore to the correct list in the
    IngestPipelineResult based on score value and status.
    No external calls — pure Python logic.
    """

    def _pipeline(self) -> IngestPipeline:
        """Pipeline with no-op scorer and page_index to avoid GROQ_API_KEY reads."""
        from unittest.mock import MagicMock
        pipeline = IngestPipeline.__new__(IngestPipeline)
        pipeline.scorer     = MagicMock()
        pipeline.researcher = MagicMock()
        pipeline.page_index = MagicMock()
        return pipeline

    def test_failed_score_goes_to_failed(self):
        _, score = _make_applicant(status=ScoringStatus.FAILED)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.failed

    def test_skipped_score_goes_to_skipped(self):
        _, score = _make_applicant(status=ScoringStatus.SKIPPED)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.skipped

    def test_high_score_goes_to_shortlisted(self):
        _, score = _make_applicant(score_val=80.0)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.shortlisted

    def test_low_score_goes_to_rejected(self):
        _, score = _make_applicant(score_val=20.0)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.rejected

    def test_middle_score_goes_to_on_hold(self):
        _, score = _make_applicant(score_val=50.0)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.on_hold

    def test_boundary_at_shortlist_threshold(self):
        """Score exactly at threshold → shortlisted (>= check)."""
        _, score = _make_applicant(score_val=65.0)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.shortlisted

    def test_boundary_just_below_threshold(self):
        _, score = _make_applicant(score_val=64.9)
        result = IngestPipelineResult()
        self._pipeline()._bucket_score(score, result, shortlist_threshold=65, auto_reject_threshold=35)
        assert score in result.on_hold


# ─── IngestPipeline: _update_applicant_status ────────────────────────────────

class TestUpdateApplicantStatus:

    def _pipeline(self) -> IngestPipeline:
        from unittest.mock import MagicMock
        pipeline = IngestPipeline.__new__(IngestPipeline)
        pipeline.scorer     = MagicMock()
        pipeline.researcher = MagicMock()
        pipeline.page_index = MagicMock()
        return pipeline

    def test_high_score_sets_shortlisted(self):
        applicant, score = _make_applicant(score_val=80.0)
        self._pipeline()._update_applicant_status(applicant, score, 65, 35)
        assert applicant.status == ApplicationStatus.SHORTLISTED

    def test_low_score_sets_rejected(self):
        applicant, score = _make_applicant(score_val=20.0)
        self._pipeline()._update_applicant_status(applicant, score, 65, 35)
        assert applicant.status == ApplicationStatus.REJECTED

    def test_middle_score_sets_on_hold(self):
        applicant, score = _make_applicant(score_val=50.0)
        self._pipeline()._update_applicant_status(applicant, score, 65, 35)
        assert applicant.status == ApplicationStatus.ON_HOLD


# ─── IngestPipeline: MAX_APPLICANTS cap ──────────────────────────────────────

class TestMaxApplicantsCap:

    @pytest.mark.asyncio
    async def test_run_from_applicants_caps_at_env_limit(self, monkeypatch):
        """If more applicants are passed than MAX_APPLICANTS, the list is truncated."""
        from unittest.mock import AsyncMock, MagicMock, patch

        monkeypatch.setenv("MAX_APPLICANTS", "2")

        # Build 5 applicants
        applicants = []
        for i in range(5):
            a, _ = _make_applicant(f"APP-{i:03d}")
            applicants.append(a)

        # Mock out scorer.score_all and supabase_store so no network calls
        mock_scorer = AsyncMock()
        mock_scorer.score_all = AsyncMock(return_value=[])

        mock_researcher = AsyncMock()
        mock_researcher.research = AsyncMock()

        mock_page_index = MagicMock()
        mock_page_index.add_applicant = MagicMock()

        pipeline = IngestPipeline(
            page_index=mock_page_index,
            scorer=mock_scorer,
            researcher=mock_researcher,
        )

        with patch("pipelines.ingest.supabase_store") as mock_sup:
            mock_sup.save_applicant = MagicMock(return_value=True)
            mock_sup.save_score     = MagicMock(return_value=True)
            result = await pipeline.run_from_applicants(applicants)

        # Cap should have reduced to 2
        assert result.total_applicants == 2
