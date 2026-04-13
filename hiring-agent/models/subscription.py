"""
models/subscription.py
═══════════════════════════════════════════════════════
Subscription tiers, feature flags, and usage limits.

Tiers:
  FREE       — interview section only, 5 uses/day
  PRO        — all features, 25–40 uses/day
  MAX        — all features, 100–200 uses/day, full feature toggles
  ENTERPRISE — unlimited, contact aakarshkumar241@gmail.com
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────
#  Tier definition
# ─────────────────────────────────────────────────────

class TierType(str, Enum):
    FREE       = "free"
    PRO        = "pro"
    MAX        = "max"
    ENTERPRISE = "enterprise"


# ─────────────────────────────────────────────────────
#  Feature names (used as keys everywhere)
# ─────────────────────────────────────────────────────

class Feature(str, Enum):
    # Interview features
    AI_INTERVIEW       = "ai_interview"        # avatar-led video interview
    TEXT_INTERVIEW     = "text_interview"       # basic text Q&A interview

    # DSA platform
    DSA_TEST           = "dsa_test"            # LeetCode-style coding round
    SQL_TEST           = "sql_test"            # SQL problem round
    AI_PROCTORING      = "ai_proctoring"       # avatar proctor with cheat detection
    MULTI_LANGUAGE     = "multi_language"      # all 15+ languages (not just Python)

    # Hiring pipeline
    RESUME_PARSING     = "resume_parsing"      # PDF/DOCX parsing
    AI_SCORING         = "ai_scoring"          # Groq-based applicant scoring
    BULK_INGEST        = "bulk_ingest"         # CSV/Excel bulk upload
    AI_DETECTION       = "ai_detection"        # AI-written response detection

    # Analytics
    ANALYTICS          = "analytics"           # activity logs, session replays
    EXPORT             = "export"              # export results to CSV/PDF

    # Settings
    FEATURE_TOGGLES    = "feature_toggles"     # enable/disable features per role


# ─────────────────────────────────────────────────────
#  Per-tier configuration
# ─────────────────────────────────────────────────────

@dataclass
class UsageLimits:
    """Daily usage caps per feature. -1 = unlimited."""
    ai_interview:   int = 0
    text_interview: int = 0
    dsa_test:       int = 0
    sql_test:       int = 0
    resume_parsing: int = 0
    ai_scoring:     int = 0
    bulk_ingest:    int = 0
    analytics:      int = 0
    export:         int = 0

    def get(self, feature: Feature) -> int:
        return getattr(self, feature.value, 0)


@dataclass
class FeatureSet:
    """Which features are available on this tier."""
    ai_interview:    bool = False
    text_interview:  bool = True
    dsa_test:        bool = False
    sql_test:        bool = False
    ai_proctoring:   bool = False
    multi_language:  bool = False
    resume_parsing:  bool = False
    ai_scoring:      bool = False
    bulk_ingest:     bool = False
    ai_detection:    bool = False
    analytics:       bool = False
    export:          bool = False
    feature_toggles: bool = False

    def has(self, feature: Feature) -> bool:
        return getattr(self, feature.value, False)


@dataclass
class TierConfig:
    tier:         TierType
    display_name: str
    price_monthly: str          # display string, e.g. "$0/mo"
    features:     FeatureSet
    limits:       UsageLimits
    description:  str


# ── Tier definitions ──────────────────────────────────────────────────────────

TIER_CONFIGS: dict[TierType, TierConfig] = {

    TierType.FREE: TierConfig(
        tier          = TierType.FREE,
        display_name  = "Free",
        price_monthly = "$0/mo",
        description   = "Get started with basic interview features. No credit card required.",
        features      = FeatureSet(
            text_interview  = True,
            ai_interview    = True,    # but capped to 5/day
            resume_parsing  = True,
        ),
        limits        = UsageLimits(
            ai_interview   = 5,
            text_interview = 5,
            resume_parsing = 5,
            ai_scoring     = 0,
            dsa_test       = 0,
            bulk_ingest    = 0,
        ),
    ),

    TierType.PRO: TierConfig(
        tier          = TierType.PRO,
        display_name  = "Pro",
        price_monthly = "$49/mo",
        description   = "Full feature access for growing teams. Up to 40 sessions per day.",
        features      = FeatureSet(
            ai_interview    = True,
            text_interview  = True,
            dsa_test        = True,
            sql_test        = True,
            ai_proctoring   = True,
            multi_language  = True,
            resume_parsing  = True,
            ai_scoring      = True,
            bulk_ingest     = True,
            ai_detection    = True,
            analytics       = True,
            export          = True,
            feature_toggles = False,   # cannot toggle features on/off
        ),
        limits        = UsageLimits(
            ai_interview   = 40,
            text_interview = 40,
            dsa_test       = 30,
            sql_test       = 30,
            resume_parsing = 200,
            ai_scoring     = 200,
            bulk_ingest    = 5,
            analytics      = -1,
            export         = 10,
        ),
    ),

    TierType.MAX: TierConfig(
        tier          = TierType.MAX,
        display_name  = "Max",
        price_monthly = "$149/mo",
        description   = "Maximum power with full feature toggles and 200 sessions/day.",
        features      = FeatureSet(
            ai_interview    = True,
            text_interview  = True,
            dsa_test        = True,
            sql_test        = True,
            ai_proctoring   = True,
            multi_language  = True,
            resume_parsing  = True,
            ai_scoring      = True,
            bulk_ingest     = True,
            ai_detection    = True,
            analytics       = True,
            export          = True,
            feature_toggles = True,   # ← can enable/disable per hiring role
        ),
        limits        = UsageLimits(
            ai_interview   = 200,
            text_interview = 200,
            dsa_test       = 150,
            sql_test       = 150,
            resume_parsing = -1,
            ai_scoring     = -1,
            bulk_ingest    = 20,
            analytics      = -1,
            export         = -1,
        ),
    ),

    TierType.ENTERPRISE: TierConfig(
        tier          = TierType.ENTERPRISE,
        display_name  = "Enterprise",
        price_monthly = "Custom — contact us",
        description   = (
            "Unlimited usage, dedicated infrastructure, SLA, custom integrations. "
            "Contact aakarshkumar241@gmail.com"
        ),
        features      = FeatureSet(
            ai_interview    = True,
            text_interview  = True,
            dsa_test        = True,
            sql_test        = True,
            ai_proctoring   = True,
            multi_language  = True,
            resume_parsing  = True,
            ai_scoring      = True,
            bulk_ingest     = True,
            ai_detection    = True,
            analytics       = True,
            export          = True,
            feature_toggles = True,
        ),
        limits        = UsageLimits(
            ai_interview   = -1,
            text_interview = -1,
            dsa_test       = -1,
            sql_test       = -1,
            resume_parsing = -1,
            ai_scoring     = -1,
            bulk_ingest    = -1,
            analytics      = -1,
            export         = -1,
        ),
    ),
}


# ─────────────────────────────────────────────────────
#  Pydantic models (stored in Supabase)
# ─────────────────────────────────────────────────────

class RecruiterSubscription(BaseModel):
    """One row per recruiter in the `subscriptions` table."""
    recruiter_id:    str
    tier:            TierType       = TierType.FREE
    started_at:      datetime       = Field(default_factory=datetime.utcnow)
    expires_at:      Optional[datetime] = None   # None = never (free/enterprise)
    is_active:       bool           = True
    contact_email:   str            = ""


class FeatureToggle(BaseModel):
    """
    Per-recruiter feature overrides (only meaningful on MAX / ENTERPRISE).
    A recruiter hiring for non-tech roles can disable dsa_test entirely.
    """
    recruiter_id:    str
    feature:         Feature
    enabled:         bool           = True
    updated_at:      datetime       = Field(default_factory=datetime.utcnow)
    note:            str            = ""    # e.g. "Disabled — non-tech hiring round"


class DailyUsageRecord(BaseModel):
    """Tracks how many times each feature was used today per recruiter."""
    recruiter_id:    str
    feature:         Feature
    date:            str            = Field(default_factory=lambda: date.today().isoformat())
    count:           int            = 0

    def is_exhausted(self, limit: int) -> bool:
        if limit == -1:
            return False   # unlimited
        return self.count >= limit


class SubscriptionStatus(BaseModel):
    """Returned by GET /subscription — full picture for the UI."""
    recruiter_id:    str
    tier:            TierType
    display_name:    str
    price_monthly:   str
    is_active:       bool
    features:        dict[str, bool]        # feature_name → enabled
    limits:          dict[str, int]         # feature_name → daily limit (-1=unlimited)
    usage_today:     dict[str, int]         # feature_name → used today
    remaining_today: dict[str, int]         # feature_name → remaining (-1=unlimited)
    toggles:        dict[str, bool]         # per-recruiter overrides (MAX/ENT only)
