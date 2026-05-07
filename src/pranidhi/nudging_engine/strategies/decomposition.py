"""Decomposition — splits multi-entity prompts into safe sub-queries."""

from pranidhi.models import RiskAnnotation, UserContext, CoachingSuggestion, CoachingStrategy


class DecompositionPlanner:

    def suggest(self, annotation: RiskAnnotation, original_prompt: str, user_context: UserContext) -> CoachingSuggestion:
        entities = annotation.flagged_entities
        sub_queries = [
            f"Sub-query {i+1}: Ask about '{e.lower()}' aspects without cross-referencing other sensitive dimensions."
            for i, e in enumerate(entities)
        ]
        text = "Consider decomposing into separate queries:\n" + "\n".join(sub_queries) + "\nThen manually combine results."

        return CoachingSuggestion(
            strategy=CoachingStrategy.DECOMPOSITION,
            original_fragment=original_prompt[:200],
            suggested_replacement=text,
            rationale="Splitting into independent sub-queries prevents any single AI interaction from accessing the full risk surface.",
            confidence=0.75,
        )
