"""
connectors/sql_executor.py
═══════════════════════════════════════════════════════
Sandboxed SQL executor using Python's built-in sqlite3.

Each execution gets its own in-memory database — completely
isolated, no persistence between calls, no filesystem access.

Dangerous statements (DROP, DELETE without WHERE, ATTACH,
PRAGMA) are blocked before execution.

Usage:
    executor = SQLExecutor()
    result = executor.execute(
        sql="SELECT * FROM employees WHERE dept = 'Engineering'",
        schema_sql="CREATE TABLE employees (id INT, name TEXT, dept TEXT);
                    INSERT INTO employees VALUES (1, 'Ada', 'Engineering');",
        expected="1|Ada|Engineering",
    )
"""

from __future__ import annotations

import re
import sqlite3
import textwrap
from typing import Any

from models.dsa_problem import SubmissionStatus, TestCaseResult
from utils.logger import logger

# ── Blocked statement patterns ────────────────────────
_BLOCKED_PATTERNS = [
    re.compile(r"\bATTACH\b",              re.I),
    re.compile(r"\bDETACH\b",              re.I),
    re.compile(r"\bPRAGMA\b",             re.I),
    re.compile(r"\bLOAD_EXTENSION\b",     re.I),
    re.compile(r"\bDROP\s+TABLE\b",       re.I),
    re.compile(r"\bDROP\s+DATABASE\b",    re.I),
    re.compile(r"\bTRUNCATE\b",           re.I),
    # DELETE without WHERE is destructive in contest context
    re.compile(r"\bDELETE\s+FROM\s+\w+\s*;", re.I),
]


def _is_blocked(sql: str) -> tuple[bool, str]:
    for pat in _BLOCKED_PATTERNS:
        if pat.search(sql):
            return True, f"Blocked statement pattern: {pat.pattern}"
    return False, ""


def _rows_to_str(rows: list[tuple]) -> str:
    """Serialise result rows to pipe-separated lines, matching Judge0 stdout style."""
    return "\n".join("|".join(str(c) for c in row) for row in rows)


class SQLExecutor:
    """
    In-memory SQLite sandbox.
    Thread-safe: each call creates a fresh connection.
    """

    def execute(
        self,
        sql:          str,
        schema_sql:   str,
        expected:     str,
        test_index:   int = 0,
    ) -> TestCaseResult:
        """
        Execute `sql` inside a fresh in-memory SQLite populated by `schema_sql`.

        Returns a TestCaseResult with:
          - passed = True if output matches expected (whitespace-normalised)
          - actual_output = pipe-delimited rows
          - error = any exception message
        """
        # ── Security check ────────────────────────────
        blocked, reason = _is_blocked(sql)
        if blocked:
            return TestCaseResult(
                test_index=test_index,
                passed=False,
                actual_output="",
                expected_output=expected,
                error=f"SQL_EXECUTOR_BLOCKED: {reason}",
            )

        con = sqlite3.connect(":memory:")
        try:
            # Load schema + seed data
            if schema_sql.strip():
                con.executescript(textwrap.dedent(schema_sql))
                con.commit()

            # Execute candidate query
            cur = con.execute(sql)
            rows = cur.fetchall()
            actual = _rows_to_str(rows)

            # Normalise whitespace for comparison
            passed = actual.strip() == expected.strip()

            return TestCaseResult(
                test_index=test_index,
                passed=passed,
                actual_output=actual,
                expected_output=expected,
                error="",
            )

        except sqlite3.OperationalError as exc:
            return TestCaseResult(
                test_index=test_index,
                passed=False,
                actual_output="",
                expected_output=expected,
                error=f"OperationalError: {exc}",
            )
        except Exception as exc:
            logger.error(f"SQL_EXECUTOR | unexpected error: {exc}")
            return TestCaseResult(
                test_index=test_index,
                passed=False,
                actual_output="",
                expected_output=expected,
                error=str(exc),
            )
        finally:
            con.close()

    def run_test_cases(
        self,
        sql:        str,
        schema_sql: str,
        test_cases: list,            # list[TestCase]
    ) -> tuple[list[TestCaseResult], SubmissionStatus]:
        """
        Run sql against all test cases.
        Returns (results, aggregate_status).
        Synchronous — SQLite is not async.
        """
        results = [
            self.execute(sql, schema_sql, tc.expected_output, idx)
            for idx, tc in enumerate(test_cases)
        ]

        all_passed = all(r.passed for r in results)
        if all_passed:
            return results, SubmissionStatus.ACCEPTED

        first_fail = next((r for r in results if not r.passed), None)
        if first_fail and "BLOCKED" in first_fail.error:
            return results, SubmissionStatus.RUNTIME_ERROR
        if first_fail and first_fail.error:
            return results, SubmissionStatus.RUNTIME_ERROR
        return results, SubmissionStatus.WRONG_ANSWER
