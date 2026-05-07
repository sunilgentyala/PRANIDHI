"""
Core data models for the PRANIDHI pipeline.

These dataclasses define the contracts between layers, ensuring that each
component in the five-layer architecture communicates through well-typed,
immutable structures rather than ad hoc dictionaries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Disposition(str, Enum):
    """Traffic-light disposition assigned after risk scoring."""
    GREEN = "GREEN"    # Proceed without intervention
    AMBER = "AMBER"    # Proceed with coaching suggestions
    RED = "RED"        # Block with reformulation guidance


class SensitivityTier(str, Enum):
    """Five-tier data sensitivity classification (CRSE Dimension 1)."""
    UNRESTRICTED = "UNRESTRICTED"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    HIGHLY_CONFIDENTIAL = "HIGHLY_CONFIDENTIAL"
    LEGALLY_PRIVILEGED = "LEGALLY_PRIVILEGED"


class CoachingStrategy(str, Enum):
    """The four intervention modalities of the Nudging Engine."""
    SUBSTITUTIVE_REFORMULATION = "SUBSTITUTIVE_REFORMULATION"
    DECOMPOSITION = "DECOMPOSITION"
    ABSTRACTION_ELEVATION = "ABSTRACTION_ELEVATION"
    TOOL_REDIRECTION = "TOOL_REDIRECTION"


class ContentBlockType(str, Enum):
    """Categories of decomposed content blocks from the IDL."""
    FREE_TEXT = "FREE_TEXT"
    CODE_SNIPPET = "CODE_SNIPPET"
    TABULAR_DATA = "TABULAR_DATA"
    URL = "URL"
    CREDENTIAL = "CREDENTIAL"
    PII_FRAGMENT = "PII_FRAGMENT"
    DOCUMENT_EXCERPT = "DOCUMENT_EXCERPT"


@dataclass(frozen=True)
class UserContext:
    """Contextual metadata about the user and their interaction."""
    user_id: str
    role: str = "default"
    department: str = "unknown"
    target_platform: str = "unknown"
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ContentBlock:
    """A semantically discrete unit extracted by the IDL from raw input."""
    block_id: str
    block_type: ContentBlockType
    content: str
    start_offset: int
    end_offset: int
    language: str = "en"
    encoding_normalised: bool = False


@dataclass(frozen=True)
class RiskScore:
    """
    Three-dimensional risk assessment produced by the CRSE.

    Dimension 1 — Data Sensitivity: ordinal classification of data type.
    Dimension 2 — Contextual Exposure Risk: probability of actionable harm
                  given the target platform, user role, and data retention.
    Dimension 3 — Inferential Leakage Potential: risk that sanitised data
                  could be reconstituted through model inference.

    The composite score is a normalised [0, 1] value derived from all three.
    """
    sensitivity_tier: SensitivityTier
    exposure_risk: float        # [0, 1]
    inferential_leakage: float  # [0, 1]
    composite: float            # [0, 1] — weighted combination

    def __post_init__(self):
        for attr in ("exposure_risk", "inferential_leakage", "composite"):
            val = getattr(self, attr)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{attr} must be in [0, 1], got {val}")


@dataclass(frozen=True)
class RiskAnnotation:
    """Risk assessment attached to a specific content block."""
    block: ContentBlock
    risk_score: RiskScore
    disposition: Disposition
    flagged_entities: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass(frozen=True)
class CoachingSuggestion:
    """A single coaching intervention produced by the Nudging Engine."""
    strategy: CoachingStrategy
    original_fragment: str
    suggested_replacement: str
    rationale: str
    confidence: float = 0.0  # [0, 1]


@dataclass
class ScanResult:
    """
    The complete output of the PRANIDHI pipeline for a single prompt.

    Aggregates decomposition results, risk annotations, coaching suggestions,
    and the final enforcement disposition.
    """
    scan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_prompt: str = ""
    content_blocks: list[ContentBlock] = field(default_factory=list)
    risk_annotations: list[RiskAnnotation] = field(default_factory=list)
    suggestions: list[CoachingSuggestion] = field(default_factory=list)
    disposition: Disposition = Disposition.GREEN
    risk_score: float = 0.0
    user_context: Optional[UserContext] = None
    processing_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_safe(self) -> bool:
        return self.disposition == Disposition.GREEN

    @property
    def requires_coaching(self) -> bool:
        return self.disposition == Disposition.AMBER

    @property
    def is_blocked(self) -> bool:
        return self.disposition == Disposition.RED

    @property
    def highest_risk_block(self) -> Optional[RiskAnnotation]:
        if not self.risk_annotations:
            return None
        return max(self.risk_annotations, key=lambda a: a.risk_score.composite)
