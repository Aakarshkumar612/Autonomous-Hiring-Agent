"""
models/dsa_problem.py
═══════════════════════════════════════════════════════
Data models for the DSA interview platform.

Covers:
  - ProgrammingLanguage — all Piston-supported DSA languages + SQL
  - DSAProblem         — problem definition with test cases
  - CodeSubmission     — candidate submission record
  - SubmissionResult   — execution output per test case
  - ProctorEvent       — cheat-detection event log
  - DSASession         — full DSA interview session
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────
#  Language catalogue (Piston language names)
# ─────────────────────────────────────────────────────

class ProgrammingLanguage(str, Enum):
    # DSA languages — executed via Piston API (connectors/code_executor.py)
    PYTHON3     = "python3"
    JAVA        = "java"
    CPP17       = "cpp17"
    JAVASCRIPT  = "javascript"
    TYPESCRIPT  = "typescript"
    GO          = "go"
    RUST        = "rust"
    CSHARP      = "csharp"
    KOTLIN      = "kotlin"
    SWIFT       = "swift"
    RUBY        = "ruby"
    SCALA       = "scala"
    PHP         = "php"
    C           = "c"
    BASH        = "bash"
    # SQL — handled by local SQLite sandbox, not Piston
    SQL         = "sql"


# Human-readable display names for the frontend dropdown
LANGUAGE_DISPLAY_NAMES: dict[ProgrammingLanguage, str] = {
    ProgrammingLanguage.PYTHON3:    "Python 3",
    ProgrammingLanguage.JAVA:       "Java",
    ProgrammingLanguage.CPP17:      "C++ 17",
    ProgrammingLanguage.JAVASCRIPT: "JavaScript (Node)",
    ProgrammingLanguage.TYPESCRIPT: "TypeScript",
    ProgrammingLanguage.GO:         "Go",
    ProgrammingLanguage.RUST:       "Rust",
    ProgrammingLanguage.CSHARP:     "C#",
    ProgrammingLanguage.KOTLIN:     "Kotlin",
    ProgrammingLanguage.SWIFT:      "Swift",
    ProgrammingLanguage.RUBY:       "Ruby",
    ProgrammingLanguage.SCALA:      "Scala",
    ProgrammingLanguage.PHP:        "PHP",
    ProgrammingLanguage.C:          "C",
    ProgrammingLanguage.BASH:       "Bash",
    ProgrammingLanguage.SQL:        "SQL",
}


# ─────────────────────────────────────────────────────
#  Problem classification
# ─────────────────────────────────────────────────────

class ProblemDifficulty(str, Enum):
    EASY   = "easy"
    MEDIUM = "medium"
    HARD   = "hard"


class ProblemType(str, Enum):
    DSA = "dsa"   # code execution via Piston
    SQL = "sql"   # SQL sandbox via SQLite


# ─────────────────────────────────────────────────────
#  Test case
# ─────────────────────────────────────────────────────

class TestCase(BaseModel):
    """One input → expected output pair."""
    input:          str                     # stdin for code / rows for SQL
    expected_output: str                    # expected stdout / result set
    is_sample:      bool = False            # True → shown to candidate in UI
    explanation:    str  = ""               # optional hint shown with sample


# ─────────────────────────────────────────────────────
#  Problem definition
# ─────────────────────────────────────────────────────

class DSAProblem(BaseModel):
    """One problem in the bank — stored in Supabase `dsa_problems` table."""
    id:             str
    title:          str
    slug:           str                     # URL-safe identifier
    problem_type:   ProblemType = ProblemType.DSA
    difficulty:     ProblemDifficulty
    description:    str                     # Markdown — shown on left panel
    constraints:    str  = ""              # e.g. "1 ≤ n ≤ 10⁵"
    examples:       list[TestCase] = []    # sample test cases shown in UI
    hidden_tests:   list[TestCase] = []    # used for scoring only
    # SQL-specific
    schema_sql:     str  = ""              # CREATE TABLE statements for SQL problems
    # Starter code templates per language
    starter_code:   dict[str, str] = {}    # lang.value → boilerplate string
    time_limit_ms:  int  = 5000            # per test case execution limit
    memory_limit_mb: int = 256
    tags:           list[str] = []         # ["array", "dp", "graph", ...]
    created_at:     datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────
#  Submission
# ─────────────────────────────────────────────────────

class SubmissionStatus(str, Enum):
    PENDING         = "pending"
    RUNNING         = "running"
    ACCEPTED        = "accepted"         # all tests pass
    WRONG_ANSWER    = "wrong_answer"
    TIME_LIMIT      = "time_limit"
    MEMORY_LIMIT    = "memory_limit"
    RUNTIME_ERROR   = "runtime_error"
    COMPILE_ERROR   = "compile_error"
    INTERNAL_ERROR  = "internal_error"


class TestCaseResult(BaseModel):
    """Execution result for a single test case."""
    test_index:      int
    passed:          bool
    actual_output:   str = ""
    expected_output: str = ""
    runtime_ms:      Optional[float] = None
    memory_kb:       Optional[int]   = None
    error:           str = ""


class CodeSubmission(BaseModel):
    """Candidate's code submission — one row in `dsa_submissions`."""
    id:             str
    session_id:     str                    # DSASession.id
    problem_id:     str
    applicant_id:   str
    language:       ProgrammingLanguage
    source_code:    str
    submitted_at:   datetime = Field(default_factory=datetime.utcnow)
    status:         SubmissionStatus = SubmissionStatus.PENDING
    # Populated after execution
    test_results:   list[TestCaseResult] = []
    passed_count:   int  = 0
    total_count:    int  = 0
    score_pct:      float = 0.0            # passed / total * 100
    runtime_ms:     Optional[float] = None
    memory_kb:      Optional[int]   = None
    compile_error:  str  = ""
    runtime_error:  str  = ""


# ─────────────────────────────────────────────────────
#  Proctoring
# ─────────────────────────────────────────────────────

class CheatEventType(str, Enum):
    TAB_SWITCH      = "tab_switch"         # candidate switched browser tab
    COPY_PASTE      = "copy_paste"         # Ctrl+C / Ctrl+V detected
    RAPID_PASTE     = "rapid_paste"        # large code block pasted instantly
    WINDOW_BLUR     = "window_blur"        # browser window lost focus
    DEVTOOLS_OPEN   = "devtools_open"      # DevTools detected (heuristic)
    MULTIPLE_FACES  = "multiple_faces"     # not yet implemented — future CV hook


class CheatStrike(str, Enum):
    NONE       = "none"        # clean session
    WARNING_1  = "warning_1"  # first offence — avatar warns verbally
    WARNING_2  = "warning_2"  # second offence — avatar gives final warning
    KICKED     = "kicked"      # third offence — session terminated


class ProctorEvent(BaseModel):
    """One proctoring event emitted by the frontend and stored in Supabase."""
    id:           str
    session_id:   str
    applicant_id: str
    event_type:   CheatEventType
    detail:       str = ""                 # e.g. "tab: stackoverflow.com"
    strike_after: CheatStrike = CheatStrike.NONE
    timestamp:    datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────
#  DSA Interview Session
# ─────────────────────────────────────────────────────

class DSASessionStatus(str, Enum):
    ACTIVE     = "active"
    COMPLETED  = "completed"
    KICKED     = "kicked"       # terminated due to 3 strikes
    EXPIRED    = "expired"      # time limit exceeded


class DSASession(BaseModel):
    """One candidate's DSA interview session — stored in Supabase."""
    id:              str
    applicant_id:    str
    recruiter_id:    str
    problem_id:      str
    language:        ProgrammingLanguage = ProgrammingLanguage.PYTHON3
    status:          DSASessionStatus    = DSASessionStatus.ACTIVE
    strike_level:    CheatStrike         = CheatStrike.NONE
    strike_count:    int                 = 0
    started_at:      datetime            = Field(default_factory=datetime.utcnow)
    ended_at:        Optional[datetime]  = None
    submissions:     list[str]           = []    # submission IDs
    best_score_pct:  float               = 0.0
    duration_minutes: int               = 90    # session time limit
    # Avatar proctor integration
    avatar_session_id: Optional[str]    = None  # AvatarInterviewSession.id if running
