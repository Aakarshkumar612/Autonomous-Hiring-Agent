"""
connectors/code_executor.py
═══════════════════════════════════════════════════════
Piston API wrapper for multi-language code execution.

Piston is open-source and provides a free public endpoint at
https://emkc.org/api/v2/piston — no API key required.

Set PISTON_URL in .env to point at a self-hosted instance.
Default: https://emkc.org/api/v2/piston (public endpoint).

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
import os
from typing import Optional

import httpx

from models.dsa_problem import (
    ProgrammingLanguage,
    SubmissionStatus,
    TestCase,
    TestCaseResult,
)
from utils.logger import logger

# ── Piston language names ─────────────────────────────
# Maps our internal ProgrammingLanguage enum → Piston language name + file name
_PISTON_LANGS: dict[ProgrammingLanguage, tuple[str, str]] = {
    ProgrammingLanguage.PYTHON3:    ("python",     "main.py"),
    ProgrammingLanguage.JAVA:       ("java",        "Main.java"),
    ProgrammingLanguage.CPP17:      ("c++",         "main.cpp"),
    ProgrammingLanguage.JAVASCRIPT: ("javascript",  "main.js"),
    ProgrammingLanguage.TYPESCRIPT: ("typescript",  "main.ts"),
    ProgrammingLanguage.GO:         ("go",           "main.go"),
    ProgrammingLanguage.RUST:       ("rust",         "main.rs"),
    ProgrammingLanguage.CSHARP:     ("csharp",       "Main.cs"),
    ProgrammingLanguage.KOTLIN:     ("kotlin",       "Main.kt"),
    ProgrammingLanguage.SWIFT:      ("swift",        "main.swift"),
    ProgrammingLanguage.RUBY:       ("ruby",         "main.rb"),
    ProgrammingLanguage.SCALA:      ("scala",        "Main.scala"),
    ProgrammingLanguage.PHP:        ("php",          "main.php"),
    ProgrammingLanguage.C:          ("c",            "main.c"),
    ProgrammingLanguage.BASH:       ("bash",         "main.sh"),
}


def _map_status(run: dict, compile_stage: Optional[dict]) -> tuple[SubmissionStatus, str]:
    """
    Derive SubmissionStatus from Piston's run/compile output.

    Returns (status, error_message).
    """
    # Compile-stage failure (e.g. Java, C++, Rust)
    if compile_stage and compile_stage.get("code", 0) != 0:
        err = (compile_stage.get("stderr") or compile_stage.get("output") or "").strip()
        return SubmissionStatus.COMPILE_ERROR, err

    exit_code = run.get("code", 0)
    signal    = run.get("signal")      # "SIGKILL" on TLE/OOM
    stderr    = (run.get("stderr") or "").strip()

    if signal == "SIGKILL":
        # Piston sends SIGKILL on run_timeout or memory exceeded
        return SubmissionStatus.TIME_LIMIT, "Time limit exceeded"

    if exit_code != 0:
        return SubmissionStatus.RUNTIME_ERROR, stderr or f"Exit code {exit_code}"

    return SubmissionStatus.ACCEPTED, ""


class CodeExecutor:
    """
    Async wrapper around the Piston code execution API.

    Piston is synchronous from the caller's perspective — one POST,
    one response. No polling required (unlike Judge0).

    Raises nothing — all errors are captured in SubmissionStatus.
    """

    def __init__(self) -> None:
        base = os.getenv("PISTON_URL", "https://emkc.org/api/v2/piston").rstrip("/")
        self._execute_url = f"{base}/execute"
        self._timeout     = int(os.getenv("PISTON_TIMEOUT_S", "30"))

    async def execute(
        self,
        source_code:    str,
        language:       ProgrammingLanguage,
        stdin:          str = "",
        time_limit_s:   float = 5.0,
        memory_limit_kb: int = 262144,   # kept for API compatibility; Piston ignores this
    ) -> tuple[SubmissionStatus, str, Optional[float], Optional[int], str]:
        """
        Execute code via Piston and return:
          (status, stdout, runtime_ms, memory_kb, error_msg)

        memory_kb is always None — Piston does not expose memory usage.
        Never raises.
        """
        lang_info = _PISTON_LANGS.get(language)
        if lang_info is None:
            return SubmissionStatus.INTERNAL_ERROR, "", None, None, f"Unsupported language: {language}"

        piston_lang, filename = lang_info

        payload = {
            "language": piston_lang,
            "version":  "*",          # always use latest available runtime
            "files":    [{"name": filename, "content": source_code}],
            "stdin":    stdin,
            "run_timeout":     int(time_limit_s * 1000),   # ms
            "compile_timeout": 10_000,                     # 10s compile ceiling
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                import time as _time
                t0   = _time.monotonic()
                resp = await client.post(self._execute_url, json=payload)
                runtime_ms = (_time.monotonic() - t0) * 1000
                resp.raise_for_status()

            data          = resp.json()
            run           = data.get("run", {})
            compile_stage = data.get("compile")   # None for interpreted languages
            stdout        = (run.get("stdout") or "").strip()

            status, error_msg = _map_status(run, compile_stage)

            # If process exited cleanly but stdout is empty and stderr has content,
            # surface stderr as the error message
            if not error_msg and not stdout and run.get("stderr"):
                error_msg = run["stderr"].strip()

            return status, stdout, round(runtime_ms, 1), None, error_msg

        except httpx.TimeoutException:
            logger.error(f"CODE_EXECUTOR | Piston request timed out ({self._timeout}s)")
            return SubmissionStatus.INTERNAL_ERROR, "", None, None, "Execution service timed out"
        except Exception as exc:
            logger.error(f"CODE_EXECUTOR | execute failed: {exc}")
            return SubmissionStatus.INTERNAL_ERROR, "", None, None, str(exc)

    async def run_test_cases(
        self,
        source_code:     str,
        language:        ProgrammingLanguage,
        test_cases:      list[TestCase],
        time_limit_ms:   int = 5000,
        memory_limit_mb: int = 256,
    ) -> tuple[list[TestCaseResult], SubmissionStatus]:
        """
        Run source_code against all test_cases concurrently.
        Returns (per-case results, aggregate status).

        Aggregate status:
          ACCEPTED      — all tests passed
          WRONG_ANSWER  — at least one test failed (no error)
          COMPILE_ERROR — first case returned compile error
          anything else — first terminal non-ACCEPTED status
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

        tasks   = [_run_one(i, tc) for i, tc in enumerate(test_cases)]
        results = list(await asyncio.gather(*tasks))

        all_passed = all(r.passed for r in results)
        if all_passed:
            return results, SubmissionStatus.ACCEPTED

        first_fail = next((r for r in results if not r.passed), None)
        if first_fail:
            err_lower = (first_fail.error or "").lower()
            if "compile" in err_lower:
                return results, SubmissionStatus.COMPILE_ERROR
            if "time limit" in err_lower:
                return results, SubmissionStatus.TIME_LIMIT
            if first_fail.error:
                return results, SubmissionStatus.RUNTIME_ERROR

        return results, SubmissionStatus.WRONG_ANSWER
