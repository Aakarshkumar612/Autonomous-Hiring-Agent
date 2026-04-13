"""
connectors/code_executor.py
═══════════════════════════════════════════════════════
Judge0 API wrapper for multi-language code execution.

Supports self-hosted Judge0 (Docker) and the hosted
judge0.com API. Set JUDGE0_URL and optionally JUDGE0_API_KEY
in .env.

Default: uses the Community Edition endpoint at localhost:2358
when JUDGE0_URL is not set (assumes local Docker).

Usage:
    executor = CodeExecutor()
    result = await executor.execute(
        source_code="print('hello')",
        language=ProgrammingLanguage.PYTHON3,
        stdin="",
    )
"""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Optional

import httpx

from models.dsa_problem import (
    CodeSubmission,
    ProgrammingLanguage,
    SubmissionStatus,
    TestCase,
    TestCaseResult,
)
from utils.logger import logger

# ── Judge0 language IDs ───────────────────────────────
JUDGE0_LANGUAGE_IDS: dict[ProgrammingLanguage, int] = {
    ProgrammingLanguage.C:          50,
    ProgrammingLanguage.BASH:       46,
    ProgrammingLanguage.CSHARP:     51,
    ProgrammingLanguage.CPP17:      54,
    ProgrammingLanguage.GO:         60,
    ProgrammingLanguage.JAVA:       62,
    ProgrammingLanguage.JAVASCRIPT: 63,
    ProgrammingLanguage.PHP:        68,
    ProgrammingLanguage.PYTHON3:    71,
    ProgrammingLanguage.RUBY:       72,
    ProgrammingLanguage.RUST:       73,
    ProgrammingLanguage.TYPESCRIPT: 74,
    ProgrammingLanguage.KOTLIN:     78,
    ProgrammingLanguage.SCALA:      81,
    ProgrammingLanguage.SWIFT:      83,
}

# Judge0 status IDs → our SubmissionStatus
_J0_STATUS: dict[int, SubmissionStatus] = {
    1:  SubmissionStatus.PENDING,
    2:  SubmissionStatus.RUNNING,
    3:  SubmissionStatus.ACCEPTED,
    4:  SubmissionStatus.WRONG_ANSWER,
    5:  SubmissionStatus.TIME_LIMIT,
    6:  SubmissionStatus.COMPILE_ERROR,
    7:  SubmissionStatus.RUNTIME_ERROR,
    8:  SubmissionStatus.RUNTIME_ERROR,
    9:  SubmissionStatus.RUNTIME_ERROR,
    10: SubmissionStatus.RUNTIME_ERROR,
    11: SubmissionStatus.RUNTIME_ERROR,
    12: SubmissionStatus.MEMORY_LIMIT,
    13: SubmissionStatus.INTERNAL_ERROR,
    14: SubmissionStatus.INTERNAL_ERROR,
}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _from_b64(s: Optional[str]) -> str:
    if not s:
        return ""
    try:
        return base64.b64decode(s).decode(errors="replace")
    except Exception:
        return s


class CodeExecutor:
    """
    Async wrapper around the Judge0 API.

    All requests are base64-encoded (Judge0 `base64_encoded=true`
    parameter) to safely handle binary/special characters.

    Raises nothing — errors are captured in SubmissionStatus.
    """

    def __init__(self) -> None:
        self._base_url = os.getenv("JUDGE0_URL", "http://localhost:2358").rstrip("/")
        self._api_key  = os.getenv("JUDGE0_API_KEY", "")
        self._timeout  = int(os.getenv("JUDGE0_TIMEOUT_S", "30"))

    def _headers(self) -> dict:
        h: dict = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-Auth-Token"] = self._api_key
        return h

    async def _submit(
        self,
        source_code: str,
        language:    ProgrammingLanguage,
        stdin:       str,
        time_limit_s:  float = 5.0,
        memory_limit_kb: int = 262144,
    ) -> str:
        """
        Submit a code run to Judge0. Returns the submission token.
        Raises httpx.HTTPError on network failure.
        """
        lang_id = JUDGE0_LANGUAGE_IDS.get(language)
        if lang_id is None:
            raise ValueError(f"No Judge0 language ID for {language}")

        payload = {
            "source_code":    _b64(source_code),
            "language_id":    lang_id,
            "stdin":          _b64(stdin),
            "cpu_time_limit": time_limit_s,
            "memory_limit":   memory_limit_kb,
            "base64_encoded": True,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/submissions",
                json=payload,
                headers=self._headers(),
                params={"base64_encoded": "true"},
            )
            resp.raise_for_status()
            return resp.json()["token"]

    async def _poll(self, token: str) -> dict:
        """
        Poll Judge0 for results. Waits up to self._timeout seconds.
        Returns the raw Judge0 result dict.
        """
        deadline = asyncio.get_event_loop().time() + self._timeout
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            while asyncio.get_event_loop().time() < deadline:
                resp = await client.get(
                    f"{self._base_url}/submissions/{token}",
                    headers=self._headers(),
                    params={"base64_encoded": "true"},
                )
                resp.raise_for_status()
                data = resp.json()
                status_id = data.get("status", {}).get("id", 1)
                if status_id >= 3:   # terminal state
                    return data
                await asyncio.sleep(1)
        raise TimeoutError(f"Judge0 did not finish within {self._timeout}s")

    async def execute(
        self,
        source_code: str,
        language:    ProgrammingLanguage,
        stdin:       str = "",
        time_limit_s:  float = 5.0,
        memory_limit_kb: int = 262144,
    ) -> tuple[SubmissionStatus, str, Optional[float], Optional[int], str]:
        """
        Execute code against a single stdin and return:
          (status, stdout, runtime_ms, memory_kb, error_msg)

        Never raises — returns INTERNAL_ERROR on unexpected exceptions.
        """
        try:
            token  = await self._submit(source_code, language, stdin, time_limit_s, memory_limit_kb)
            result = await self._poll(token)

            status_id  = result.get("status", {}).get("id", 13)
            status     = _J0_STATUS.get(status_id, SubmissionStatus.INTERNAL_ERROR)
            stdout     = _from_b64(result.get("stdout"))
            stderr     = _from_b64(result.get("stderr"))
            compile_out = _from_b64(result.get("compile_output"))
            runtime_ms  = None
            memory_kb   = None

            if result.get("time"):
                try:
                    runtime_ms = float(result["time"]) * 1000
                except ValueError:
                    pass
            if result.get("memory"):
                try:
                    memory_kb = int(result["memory"])
                except ValueError:
                    pass

            error_msg = stderr or compile_out or ""
            return status, stdout, runtime_ms, memory_kb, error_msg

        except Exception as exc:
            logger.error(f"CODE_EXECUTOR | execute failed: {exc}")
            return SubmissionStatus.INTERNAL_ERROR, "", None, None, str(exc)

    async def run_test_cases(
        self,
        source_code:  str,
        language:     ProgrammingLanguage,
        test_cases:   list[TestCase],
        time_limit_ms: int = 5000,
        memory_limit_mb: int = 256,
    ) -> tuple[list[TestCaseResult], SubmissionStatus]:
        """
        Run source_code against all test_cases concurrently.
        Returns (per-case results, aggregate status).

        Aggregate status:
          ACCEPTED       — all tests passed
          WRONG_ANSWER   — at least one test failed (no error)
          COMPILE_ERROR  — first case returned compile error
          anything else  — first terminal non-ACCEPTED status
        """
        time_limit_s    = time_limit_ms / 1000
        memory_limit_kb = memory_limit_mb * 1024

        async def _run_one(idx: int, tc: TestCase) -> TestCaseResult:
            status, stdout, runtime_ms, memory_kb, error = await self.execute(
                source_code, language, tc.input, time_limit_s, memory_limit_kb,
            )
            passed = (
                status == SubmissionStatus.ACCEPTED
                and stdout.strip() == tc.expected_output.strip()
            )
            return TestCaseResult(
                test_index=idx,
                passed=passed,
                actual_output=stdout,
                expected_output=tc.expected_output,
                runtime_ms=runtime_ms,
                memory_kb=memory_kb,
                error=error if not passed else "",
            )

        # Run all test cases concurrently
        tasks   = [_run_one(i, tc) for i, tc in enumerate(test_cases)]
        results = list(await asyncio.gather(*tasks))

        # Determine aggregate status
        all_passed = all(r.passed for r in results)
        if all_passed:
            aggregate = SubmissionStatus.ACCEPTED
        else:
            # Use status from first failed case
            first_fail = next((r for r in results if not r.passed), None)
            if first_fail and "compile" in first_fail.error.lower():
                aggregate = SubmissionStatus.COMPILE_ERROR
            elif any(r.error for r in results):
                aggregate = SubmissionStatus.RUNTIME_ERROR
            else:
                aggregate = SubmissionStatus.WRONG_ANSWER

        return results, aggregate
