"""
Layer 3 — The Nudging Engine (NE).

The framework's cardinal innovation. Rather than merely blocking risky
prompts, the NE generates context-sensitive, actionable coaching
interventions through four distinct modalities.
"""

from __future__ import annotations

import logging
from typing import Optional

from pranidhi.models import (
    RiskAnnotation, UserContext, CoachingSuggestion,
    CoachingStrategy, Disposition,
)
from pranidhi.nudging_engine.strategies.substitutive import SubstitutiveReformulator
from pranidhi.nudging_engine.strategies.decomposition import DecompositionPlanner
from pranidhi.nudging_engine.strategies.abstraction import AbstractionElevator
from pranidhi.nudging_engine.strategies.redirection import ToolRedirector

logger = logging.getLogger(__name__)


class NudgingEngine:
    """
    Generates real-time coaching interventions for risky prompts.

    When the CRSE flags content as AMBER or RED, the NudgingEngine
    produces one or more CoachingSuggestion objects that guide the
    user toward safer, equally efficacious prompt formulations.

    Parameters
    ----------
    model_id : str
        Identifier for the internally-hosted coaching model.
    max_suggestions : int
        Maximum number of suggestions to generate per scan.
    """

    def __init__(self, model_id: str = "internal-coaching-v1", max_suggestions: int = 3):
        self._model_id = model_id
        self._max_suggestions = max_suggestions

        # Initialise strategy implementations
        self._substitutive = SubstitutiveReformulator()
        self._decomposition = DecompositionPlanner()
        self._abstraction = AbstractionElevator()
        self._redirection = ToolRedirector()

    def generate_coaching(
        self,
        annotations: list[RiskAnnotation],
        original_prompt: str,
        user_context: UserContext,
    ) -> list[CoachingSuggestion]:
        """
        Produce coaching suggestions for all non-GREEN annotations.

        The engine selects the most appropriate strategy (or combination
        of strategies) based on the risk profile, content type, and
        user context.

        Parameters
        ----------
        annotations : list[RiskAnnotation]
            Risk-scored content blocks from the CRSE.
        original_prompt : str
            The unmodified user input.
        user_context : UserContext
            Contextual metadata for personalised coaching.

        Returns
        -------
        list[CoachingSuggestion]
            Ordered list of coaching interventions, most relevant first.
        """
        risky = [a for a in annotations if a.disposition != Disposition.GREEN]

        if not risky:
            return []

        suggestions: list[CoachingSuggestion] = []

        for annotation in risky:
            # Select strategy based on risk profile
            strategy_suggestions = self._select_and_apply(
                annotation, original_prompt, user_context
            )
            suggestions.extend(strategy_suggestions)

        # Deduplicate and cap at max_suggestions
        seen = set()
        unique: list[CoachingSuggestion] = []
        for s in suggestions:
            key = (s.strategy, s.suggested_replacement)
            if key not in seen:
                seen.add(key)
                unique.append(s)

        # Sort by confidence descending
        unique.sort(key=lambda s: s.confidence, reverse=True)

        return unique[: self._max_suggestions]

    def _select_and_apply(
        self,
        annotation: RiskAnnotation,
        original_prompt: str,
        user_context: UserContext,
    ) -> list[CoachingSuggestion]:
        """
        Select the most appropriate coaching strategy for a given annotation
        and generate suggestions.

        Strategy selection heuristic:
        - RED + CREDENTIAL → Tool Redirection (never send externally)
        - RED + PII → Substitutive Reformulation
        - AMBER + multi-entity → Decomposition
        - AMBER + specific instances → Abstraction Elevation
        - Fallback → Substitutive Reformulation
        """
        results: list[CoachingSuggestion] = []
        block = annotation.block
        risk = annotation.risk_score

        # Credential-type content: always redirect
        if "CREDENTIAL" in annotation.flagged_entities:
            results.append(self._redirection.suggest(
                annotation, original_prompt, user_context
            ))
            return results

        # High-risk PII: substitutive reformulation
        if risk.composite >= 0.7 and "PII" in annotation.flagged_entities:
            results.append(self._substitutive.suggest(
                annotation, original_prompt, user_context
            ))

        # Multi-entity prompts: decomposition
        entity_count = len(annotation.flagged_entities)
        if entity_count >= 2 or len(original_prompt) > 500:
            results.append(self._decomposition.suggest(
                annotation, original_prompt, user_context
            ))

        # Instance-level specificity: abstraction elevation
        if risk.inferential_leakage > 0.5:
            results.append(self._abstraction.suggest(
                annotation, original_prompt, user_context
            ))

        # Fallback: always offer substitutive reformulation
        if not results:
            results.append(self._substitutive.suggest(
                annotation, original_prompt, user_context
            ))

        return results
