"""
tests/test_api.py
═══════════════════════════════════════════════════════
Integration tests for the FastAPI portal endpoints.

Strategy:
  - Set fake env vars BEFORE any project module import
    so no real Groq/Supabase connections are attempted.
  - Patch connectors.portal_api.supabase_store in the
    client fixture so the lifespan startup succeeds with
    an empty cache (the patch must remain active while
    TestClient runs, not just during import).
  - Use FastAPI TestClient (synchronous, no running server
    needed) for all endpoint tests.
  - Zero real API calls are made.

Run with:
    uv run pytest tests/test_api.py -v
"""

from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest

# ── Fake credentials BEFORE any project module import ────────────────────────
os.environ.setdefault("GROQ_API_KEY",   "test-key-no-calls")
os.environ.setdefault("SUPABASE_URL",   "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY",   "fake-supabase-key")

# ── Now safe to import project modules ────────────────────────────────────────
from fastapi.testclient import TestClient
from connectors.portal_api import (
    _applicant_store,
    _email_index,
    _pipeline_config,
    app,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """
    Module-scoped TestClient.

    Patches connectors.portal_api.supabase_store so the lifespan warm-up
    succeeds with an empty list rather than hitting a real database.
    The patch stays active for the entire module.
    """
    mock_sup = MagicMock()
    mock_sup.get_all_applicants.return_value = []

    with patch("connectors.portal_api.supabase_store", mock_sup):
        with TestClient(app) as c:
            yield c


@pytest.fixture(autouse=True)
def _clear_stores():
    """
    Reset in-memory stores before every test so tests are fully independent.
    Applicants created in one test must not leak into another.
    """
    _applicant_store.clear()
    _email_index.clear()
    yield
    _applicant_store.clear()
    _email_index.clear()


# ─── /health ──────────────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_status_is_healthy(self, client):
        assert client.get("/health").json()["status"] == "healthy"

    def test_has_timestamp(self, client):
        assert "timestamp" in client.get("/health").json()

    def test_total_applicants_is_integer(self, client):
        assert isinstance(client.get("/health").json()["total_applicants"], int)

    def test_empty_store_reports_zero(self, client):
        assert client.get("/health").json()["total_applicants"] == 0


# ─── GET /settings/pipeline ───────────────────────────────────────────────────

class TestGetPipelineSettings:

    def test_returns_200(self, client):
        assert client.get("/settings/pipeline").status_code == 200

    def test_returns_all_five_keys(self, client):
        data = client.get("/settings/pipeline").json()
        required = {
            "shortlist_threshold",
            "auto_reject_threshold",
            "interview_rounds",
            "ai_detection_threshold",
            "max_applicants",
        }
        assert required.issubset(data.keys())

    def test_interview_rounds_in_valid_range(self, client):
        rounds = client.get("/settings/pipeline").json()["interview_rounds"]
        assert 1 <= rounds <= 5

    def test_thresholds_are_numbers(self, client):
        data = client.get("/settings/pipeline").json()
        assert isinstance(data["shortlist_threshold"],    (int, float))
        assert isinstance(data["auto_reject_threshold"],  (int, float))
        assert isinstance(data["ai_detection_threshold"], (int, float))

    def test_max_applicants_positive(self, client):
        assert client.get("/settings/pipeline").json()["max_applicants"] > 0


# ─── PATCH /settings/pipeline ─────────────────────────────────────────────────

class TestPatchPipelineSettings:

    def test_update_shortlist_threshold(self, client):
        resp = client.patch("/settings/pipeline", data={"shortlist_threshold": "55"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["config"]["shortlist_threshold"] == pytest.approx(55.0)

    def test_update_interview_rounds(self, client):
        resp = client.patch("/settings/pipeline", data={"interview_rounds": "2"})
        assert resp.status_code == 200
        assert resp.json()["config"]["interview_rounds"] == 2

    def test_update_ai_detection_threshold(self, client):
        resp = client.patch("/settings/pipeline", data={"ai_detection_threshold": "0.8"})
        assert resp.status_code == 200
        assert resp.json()["config"]["ai_detection_threshold"] == pytest.approx(0.8)

    def test_empty_patch_is_valid_no_op(self, client):
        """Sending no fields is a valid partial update (no-op)."""
        resp = client.patch("/settings/pipeline", data={})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_interview_rounds_above_max_rejected(self, client):
        """interview_rounds > 5 violates ge constraint → 422."""
        assert client.patch("/settings/pipeline", data={"interview_rounds": "99"}).status_code == 422

    def test_threshold_above_100_rejected(self, client):
        assert client.patch("/settings/pipeline", data={"shortlist_threshold": "150"}).status_code == 422

    def test_threshold_below_0_rejected(self, client):
        assert client.patch("/settings/pipeline", data={"auto_reject_threshold": "-5"}).status_code == 422

    def test_response_has_full_config(self, client):
        resp = client.patch("/settings/pipeline", data={"interview_rounds": "4"})
        config = resp.json()["config"]
        # All five keys must still be present after a partial update
        assert "shortlist_threshold" in config
        assert "max_applicants" in config


# ─── GET /applicants ──────────────────────────────────────────────────────────

class TestListApplicants:

    def test_returns_200_on_empty_store(self, client):
        assert client.get("/applicants").status_code == 200

    def test_empty_store_returns_zero_total(self, client):
        data = client.get("/applicants").json()
        assert data["total"] == 0
        assert data["applicants"] == []

    def test_response_has_pagination_fields(self, client):
        data = client.get("/applicants").json()
        assert "limit"  in data
        assert "offset" in data

    def test_valid_status_filter_accepted(self, client):
        assert client.get("/applicants?status_filter=pending").status_code == 200

    def test_limit_and_offset_query_params(self, client):
        assert client.get("/applicants?limit=5&offset=0").status_code == 200

    def test_limit_zero_returns_empty_page(self, client):
        """limit=0 is technically valid — returns 0 applicants from an empty store."""
        resp = client.get("/applicants?limit=0")
        assert resp.status_code == 200
        assert resp.json()["applicants"] == []


# ─── GET /applicants/{id} ─────────────────────────────────────────────────────

class TestGetApplicant:

    def test_nonexistent_id_returns_404(self, client):
        assert client.get("/applicants/DOES-NOT-EXIST").status_code == 404

    def test_404_has_detail_field(self, client):
        assert "detail" in client.get("/applicants/NONEXISTENT").json()


# ─── PATCH /applicants/{id}/status ───────────────────────────────────────────

class TestUpdateApplicantStatus:

    def test_nonexistent_id_returns_404(self, client):
        resp = client.patch("/applicants/FAKE-ID/status", data={"new_status": "shortlisted"})
        assert resp.status_code == 404

    def test_invalid_status_value_rejected(self, client):
        """Status outside the enum should return 422 (validation) or 404 (not found)."""
        resp = client.patch("/applicants/ANY/status", data={"new_status": "invented_status"})
        assert resp.status_code in (404, 422)


# ─── POST /apply — field validation ──────────────────────────────────────────

class TestSubmitApplicationValidation:
    """
    These tests check that FastAPI's Form validation rejects bad input
    before any business logic or external calls run.
    No resume is uploaded in any of these tests.
    """

    def test_completely_empty_form_returns_422(self, client):
        assert client.post("/apply", data={}).status_code == 422

    def test_missing_email_returns_422(self, client):
        resp = client.post("/apply", data={
            "full_name":        "Test User",
            "role_applied":     "sde",
            "experience_years": "2",
        })
        assert resp.status_code == 422

    def test_missing_name_returns_422(self, client):
        resp = client.post("/apply", data={
            "email":            "test@example.com",
            "role_applied":     "sde",
            "experience_years": "2",
        })
        assert resp.status_code == 422

    def test_negative_experience_returns_422(self, client):
        resp = client.post("/apply", data={
            "full_name":        "Test User",
            "email":            "test@example.com",
            "role_applied":     "sde",
            "experience_years": "-1",
        })
        assert resp.status_code == 422

    def test_duplicate_email_returns_409(self, client):
        """
        If the email is already in the _email_index the endpoint must
        return 409 Conflict before attempting any Groq call.
        """
        _email_index["existing@example.com"] = "EXISTING-ID"
        resp = client.post("/apply", data={
            "full_name":        "New User",
            "email":            "existing@example.com",
            "role_applied":     "sde",
            "experience_years": "2",
        })
        assert resp.status_code == 409


# ─── POST /apply — file validation ───────────────────────────────────────────

class TestSubmitApplicationFileValidation:
    """
    Tests for the two file gates (size limit + MIME type) that run
    before any LLM call. Both should return immediately without Groq.
    """

    _BASE_FORM = {
        "full_name":        "File Test User",
        "email":            "filetest@example.com",
        "role_applied":     "sde",
        "experience_years": "1",
    }

    def test_oversized_file_returns_413(self, client):
        """Files larger than 10 MB must be rejected with 413 Request Entity Too Large."""
        big_file = io.BytesIO(b"x" * (11 * 1024 * 1024))   # 11 MB
        resp = client.post(
            "/apply",
            data=self._BASE_FORM,
            files={"resume": ("big.pdf", big_file, "application/pdf")},
        )
        assert resp.status_code == 413

    def test_unsupported_mime_type_returns_415(self, client):
        """Uploading a binary file with an unsupported MIME type → 415."""
        resp = client.post(
            "/apply",
            data=self._BASE_FORM,
            files={"resume": ("malware.exe", io.BytesIO(b"MZ\x90"), "application/octet-stream")},
        )
        assert resp.status_code == 415


# ─── GET /stats ───────────────────────────────────────────────────────────────

class TestStatsEndpoint:

    def test_returns_200(self, client):
        assert client.get("/stats").status_code == 200

    def test_has_total_applicants(self, client):
        assert "total_applicants" in client.get("/stats").json()

    def test_by_status_is_dict(self, client):
        assert isinstance(client.get("/stats").json().get("by_status"), dict)

    def test_by_role_is_dict(self, client):
        assert isinstance(client.get("/stats").json().get("by_role"), dict)

    def test_empty_store_total_is_zero(self, client):
        assert client.get("/stats").json()["total_applicants"] == 0
