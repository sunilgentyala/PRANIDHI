"""
Prohibition-only baseline for comparative evaluation.

Reuses PRANIDHI's real IDL and CRSE (identical detection and risk-scoring
logic) but stops there: any non-GREEN disposition is a hard block, with
no coaching offered and no policy-tier nuance. This isolates the effect
of the Nudging Engine and PEOL rather than comparing against a
reimplemented or hypothetical competitor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pranidhi.idl.decomposer import Decomposer
from pranidhi.crse.risk_scorer import RiskScorer
from pranidhi.models import Disposition, UserContext


@dataclass
class BaselineResult:
    disposition: Disposition
    risk_score: float
    processing_time_ms: float
    num_blocks: int


class ProhibitionOnlyBaseline:
    """A DLP-style scan-and-block baseline with no coaching layer."""

    def __init__(self):
        self._decomposer = Decomposer()
        self._risk_scorer = RiskScorer()

    def scan(self, prompt: str, user_context: UserContext) -> BaselineResult:
        start = time.monotonic()

        blocks = self._decomposer.decompose(prompt)
        annotations = self._risk_scorer.score_blocks(blocks, user_context)

        dispositions = [a.disposition for a in annotations]
        if Disposition.RED in dispositions:
            disposition = Disposition.RED
        elif Disposition.AMBER in dispositions:
            # Prohibition-only baseline has no coaching path: escalate to a hard block.
            disposition = Disposition.RED
        else:
            disposition = Disposition.GREEN

        composite_scores = [a.risk_score.composite for a in annotations]
        risk_score = max(composite_scores) if composite_scores else 0.0

        elapsed_ms = (time.monotonic() - start) * 1000
        return BaselineResult(
            disposition=disposition,
            risk_score=risk_score,
            processing_time_ms=elapsed_ms,
            num_blocks=len(blocks),
        )
