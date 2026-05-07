"""Abstraction Elevation — lifts instance-specific queries to pattern-level."""

from pranidhi.models import RiskAnnotation, UserContext, CoachingSuggestion, CoachingStrategy


class AbstractionElevator:

    def suggest(self, annotation: RiskAnnotation, original_prompt: str, user_context: UserContext) -> CoachingSuggestion:
        return CoachingSuggestion(
            strategy=CoachingStrategy.ABSTRACTION_ELEVATION,
            original_fragment=original_prompt[:200],
            suggested_replacement=(
                "Try rephrasing at a higher level of abstraction. Instead of referencing "
                "specific entities, ask about the general analytical pattern or framework."
            ),
            rationale=(
                "Your prompt references specific entities whose identity could be inferred "
                "even from anonymised data. Elevating to pattern-level analysis eliminates "
                "inferential leakage risk whilst yielding equally actionable insights."
            ),
            confidence=0.70,
        )
