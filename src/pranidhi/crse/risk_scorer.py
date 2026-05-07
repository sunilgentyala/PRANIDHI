"""
Layer 2 — Classification & Risk Scoring Engine (CRSE).

Applies three-dimensional risk assessment to each ContentBlock:
  Dimension 1: Data Sensitivity (five-tier ordinal scale)
  Dimension 2: Contextual Exposure Risk (platform + role + retention)
  Dimension 3: Inferential Leakage Potential (reconstitution risk)
"""

from __future__ import annotations

import logging
import math

from pranidhi.models import (
    ContentBlock, ContentBlockType, UserContext,
    RiskScore, RiskAnnotation, Disposition,
    SensitivityTier,
)

logger = logging.getLogger(__name__)

# ── Platform risk profiles ──
# Higher values indicate greater data retention / exposure risk
PLATFORM_RISK = {
    "claude": 0.3,
    "chatgpt": 0.5,
    "perplexity": 0.4,
    "grok": 0.5,
    "gemini": 0.4,
    "internal": 0.1,
    "unknown": 0.6,
}

# ── Disposition thresholds ──
THRESHOLD_GREEN = 0.3
THRESHOLD_AMBER = 0.7


class RiskScorer:
    """
    Assigns multi-dimensional risk scores to decomposed ContentBlocks.

    The scorer evaluates each block across three orthogonal dimensions
    and computes a weighted composite score that determines the traffic-light
    disposition (GREEN / AMBER / RED).

    Parameters
    ----------
    weights : tuple of float
        Relative weights for (sensitivity, exposure, inferential) dimensions.
        Defaults to (0.4, 0.35, 0.25).
    green_threshold : float
        Composite score below which disposition is GREEN.
    amber_threshold : float
        Composite score below which disposition is AMBER (above is RED).
    """

    def __init__(
        self,
        weights: tuple[float, float, float] = (0.40, 0.35, 0.25),
        green_threshold: float = THRESHOLD_GREEN,
        amber_threshold: float = THRESHOLD_AMBER,
    ):
        self._weights = weights
        self._green = green_threshold
        self._amber = amber_threshold

    def score_blocks(
        self,
        blocks: list[ContentBlock],
        user_context: UserContext,
    ) -> list[RiskAnnotation]:
        """Score every ContentBlock and return annotated results."""
        annotations = []
        for block in blocks:
            score = self._score_single(block, user_context)
            disposition = self._classify(score.composite)
            annotations.append(RiskAnnotation(
                block=block,
                risk_score=score,
                disposition=disposition,
                flagged_entities=self._extract_entities(block),
                explanation=self._explain(block, score, disposition),
            ))
        return annotations

    def _score_single(
        self, block: ContentBlock, ctx: UserContext
    ) -> RiskScore:
        """Compute three-dimensional risk for one block."""

        # ── Dimension 1: Data Sensitivity ──
        tier = self._classify_sensitivity(block)
        sensitivity_score = {
            SensitivityTier.UNRESTRICTED: 0.0,
            SensitivityTier.INTERNAL: 0.25,
            SensitivityTier.CONFIDENTIAL: 0.55,
            SensitivityTier.HIGHLY_CONFIDENTIAL: 0.80,
            SensitivityTier.LEGALLY_PRIVILEGED: 1.0,
        }[tier]

        # ── Dimension 2: Contextual Exposure Risk ──
        platform_risk = PLATFORM_RISK.get(ctx.target_platform.lower(), 0.6)
        role_modifier = self._role_risk_modifier(ctx.role)
        exposure = min(1.0, platform_risk * role_modifier)

        # ── Dimension 3: Inferential Leakage Potential ──
        inferential = self._estimate_inferential_leakage(block, ctx)

        # ── Composite ──
        w1, w2, w3 = self._weights
        composite = min(1.0, (
            w1 * sensitivity_score
            + w2 * exposure
            + w3 * inferential
        ))

        return RiskScore(
            sensitivity_tier=tier,
            exposure_risk=round(exposure, 4),
            inferential_leakage=round(inferential, 4),
            composite=round(composite, 4),
        )

    def _classify_sensitivity(self, block: ContentBlock) -> SensitivityTier:
        """Map content block type to sensitivity tier."""
        mapping = {
            ContentBlockType.CREDENTIAL: SensitivityTier.LEGALLY_PRIVILEGED,
            ContentBlockType.PII_FRAGMENT: SensitivityTier.HIGHLY_CONFIDENTIAL,
            ContentBlockType.CODE_SNIPPET: SensitivityTier.CONFIDENTIAL,
            ContentBlockType.TABULAR_DATA: SensitivityTier.CONFIDENTIAL,
            ContentBlockType.DOCUMENT_EXCERPT: SensitivityTier.INTERNAL,
            ContentBlockType.URL: SensitivityTier.INTERNAL,
            ContentBlockType.FREE_TEXT: SensitivityTier.UNRESTRICTED,
        }
        return mapping.get(block.block_type, SensitivityTier.INTERNAL)

    @staticmethod
    def _role_risk_modifier(role: str) -> float:
        """Higher modifier for roles with less data-handling training."""
        trained_roles = {"analyst", "security", "compliance", "legal", "admin"}
        return 0.8 if role.lower() in trained_roles else 1.2

    @staticmethod
    def _estimate_inferential_leakage(
        block: ContentBlock, ctx: UserContext
    ) -> float:
        """
        Estimate the probability that even sanitised data from this block
        could be reconstituted through model inference or cross-correlation.

        Uses Shannon entropy as a proxy: high-entropy content (e.g. account
        numbers) is harder to infer, whilst low-entropy content (e.g. a
        CEO's name + company) is trivially reconstructable.
        """
        if not block.content:
            return 0.0

        # Character-level entropy
        freq: dict[str, int] = {}
        for ch in block.content:
            freq[ch] = freq.get(ch, 0) + 1
        length = len(block.content)
        entropy = -sum(
            (c / length) * math.log2(c / length) for c in freq.values()
        )

        # Low entropy → high inferential risk (easier to guess/correlate)
        # Normalise to [0, 1] assuming max practical entropy ~6.5 bits
        normalised_entropy = min(entropy / 6.5, 1.0)
        inferential_risk = 1.0 - normalised_entropy

        # Boost if the block contains PII-adjacent content
        if block.block_type in (
            ContentBlockType.PII_FRAGMENT,
            ContentBlockType.CREDENTIAL,
        ):
            inferential_risk = min(1.0, inferential_risk + 0.2)

        return round(inferential_risk, 4)

    def _classify(self, composite: float) -> Disposition:
        """Map composite score to traffic-light disposition."""
        if composite < self._green:
            return Disposition.GREEN
        elif composite < self._amber:
            return Disposition.AMBER
        else:
            return Disposition.RED

    @staticmethod
    def _extract_entities(block: ContentBlock) -> list[str]:
        """Extract flagged entity labels from a block."""
        entities = []
        if block.block_type == ContentBlockType.PII_FRAGMENT:
            entities.append("PII")
        if block.block_type == ContentBlockType.CREDENTIAL:
            entities.append("CREDENTIAL")
        if block.block_type == ContentBlockType.CODE_SNIPPET:
            entities.append("SOURCE_CODE")
        return entities

    @staticmethod
    def _explain(
        block: ContentBlock, score: RiskScore, disposition: Disposition
    ) -> str:
        """Generate a human-readable explanation of the risk assessment."""
        return (
            f"Block type '{block.block_type.value}' classified as "
            f"'{score.sensitivity_tier.value}' sensitivity. "
            f"Contextual exposure={score.exposure_risk:.2f}, "
            f"inferential leakage={score.inferential_leakage:.2f}, "
            f"composite={score.composite:.2f} → {disposition.value}."
        )
