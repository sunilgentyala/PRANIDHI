"""
PranidhiPipeline — the primary entry point for scanning prompts.

Orchestrates the five-layer architecture:
  IDL → CRSE → NudgingEngine → PEOL → TAALL

Each layer operates on the output of its predecessor, building up a
comprehensive ScanResult that captures decomposition, risk scoring,
coaching suggestions, and enforcement decisions.
"""

from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Optional

from pranidhi.models import (
    ScanResult, UserContext, Disposition, RiskAnnotation
)
from pranidhi.idl.decomposer import Decomposer
from pranidhi.crse.risk_scorer import RiskScorer
from pranidhi.nudging_engine.engine import NudgingEngine
from pranidhi.peol.enforcer import PolicyEnforcer
from pranidhi.taall.telemetry import TelemetryCollector

logger = logging.getLogger(__name__)


class PranidhiPipeline:
    """
    The principal facade through which all prompt scanning is performed.

    Instantiate with a policy configuration path and optional platform
    connectors. Call :meth:`scan` to run the full five-layer pipeline
    on any user prompt.

    Parameters
    ----------
    policy_path : str or Path
        Path to the YAML policy configuration file.
    connectors : list, optional
        Platform adapter instances for cross-platform normalisation.
    enable_telemetry : bool
        Whether to collect interaction telemetry (Layer 5).
    coaching_model : str
        Identifier for the internally-hosted model used by the
        Nudging Engine for reformulation generation.
    """

    def __init__(
        self,
        policy_path: str | Path = "policies/default.yaml",
        connectors: Optional[list] = None,
        enable_telemetry: bool = True,
        coaching_model: str = "internal-coaching-v1",
    ):
        self.policy_path = Path(policy_path)
        self.connectors = connectors or []

        # Initialise each layer
        self._decomposer = Decomposer()
        self._risk_scorer = RiskScorer()
        self._nudging_engine = NudgingEngine(model_id=coaching_model)
        self._policy_enforcer = PolicyEnforcer(policy_path=self.policy_path)
        self._telemetry = TelemetryCollector() if enable_telemetry else None

        logger.info(
            "PRANIDHI pipeline initialised with %d connector(s), "
            "telemetry=%s",
            len(self.connectors),
            enable_telemetry,
        )

    def scan(
        self,
        prompt: str,
        user_context: Optional[dict | UserContext] = None,
    ) -> ScanResult:
        """
        Run the full PRANIDHI pipeline on a single prompt.

        Parameters
        ----------
        prompt : str
            The raw user input to be scanned.
        user_context : dict or UserContext, optional
            Contextual metadata (role, department, target platform).

        Returns
        -------
        ScanResult
            Complete analysis including risk scores, disposition,
            and coaching suggestions.
        """
        start_time = time.monotonic()

        # Normalise user context
        if isinstance(user_context, dict):
            ctx = UserContext(
                user_id=user_context.get("user_id", "anonymous"),
                role=user_context.get("role", "default"),
                department=user_context.get("department", "unknown"),
                target_platform=user_context.get("target_platform", "unknown"),
            )
        elif user_context is None:
            ctx = UserContext(user_id="anonymous")
        else:
            ctx = user_context

        # ── Layer 1: Ingestion & Decomposition ──
        content_blocks = self._decomposer.decompose(prompt)

        # ── Layer 2: Classification & Risk Scoring ──
        risk_annotations = self._risk_scorer.score_blocks(
            blocks=content_blocks,
            user_context=ctx,
        )

        # ── Layer 3: Nudging Engine ──
        suggestions = self._nudging_engine.generate_coaching(
            annotations=risk_annotations,
            original_prompt=prompt,
            user_context=ctx,
        )

        # ── Layer 4: Policy Enforcement ──
        disposition = self._policy_enforcer.enforce(
            annotations=risk_annotations,
            suggestions=suggestions,
            user_context=ctx,
        )

        # Compute aggregate risk score
        composite_scores = [a.risk_score.composite for a in risk_annotations]
        aggregate_risk = max(composite_scores) if composite_scores else 0.0

        elapsed_ms = (time.monotonic() - start_time) * 1000

        result = ScanResult(
            original_prompt=prompt,
            content_blocks=content_blocks,
            risk_annotations=risk_annotations,
            suggestions=suggestions,
            disposition=disposition,
            risk_score=aggregate_risk,
            user_context=ctx,
            processing_time_ms=elapsed_ms,
        )

        # ── Layer 5: Telemetry ──
        if self._telemetry is not None:
            self._telemetry.record(result)

        logger.info(
            "Scan complete: disposition=%s, risk=%.3f, blocks=%d, "
            "suggestions=%d, time=%.1fms",
            disposition.value,
            aggregate_risk,
            len(content_blocks),
            len(suggestions),
            elapsed_ms,
        )

        return result

    def scan_batch(
        self,
        prompts: list[str],
        user_context: Optional[dict | UserContext] = None,
    ) -> list[ScanResult]:
        """Scan multiple prompts sequentially."""
        return [self.scan(p, user_context) for p in prompts]
