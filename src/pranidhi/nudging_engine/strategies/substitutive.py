"""
Substitutive Reformulation — replaces sensitive data with synthetic equivalents.
"""

from pranidhi.models import (
    RiskAnnotation, UserContext, CoachingSuggestion, CoachingStrategy,
)


class SubstitutiveReformulator:

    PLACEHOLDERS = {
        "PII_FRAGMENT": "[REDACTED-PII]",
        "CREDENTIAL": "[REDACTED-CREDENTIAL]",
        "CODE_SNIPPET": "[code snippet describing the logic without proprietary details]",
        "URL": "[internal-url-redacted]",
        "TABULAR_DATA": "[sample data with synthetic values]",
    }

    def suggest(self, annotation: RiskAnnotation, original_prompt: str, user_context: UserContext) -> CoachingSuggestion:
        sensitive = annotation.block.content
        bt = annotation.block.block_type.value
        replacement = self.PLACEHOLDERS.get(bt, "[REDACTED]")
        safe_prompt = original_prompt.replace(sensitive, replacement)

        return CoachingSuggestion(
            strategy=CoachingStrategy.SUBSTITUTIVE_REFORMULATION,
            original_fragment=sensitive,
            suggested_replacement=safe_prompt,
            rationale=(
                f"The original prompt contains {bt.lower()} data. This reformulation "
                f"replaces specific data with a synthetic placeholder whilst "
                f"preserving the analytical intent of your query."
            ),
            confidence=0.85,
        )
