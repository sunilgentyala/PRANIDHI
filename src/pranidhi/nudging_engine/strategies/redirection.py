"""Tool Redirection — routes high-risk queries to safer execution paths."""

from pranidhi.models import RiskAnnotation, UserContext, CoachingSuggestion, CoachingStrategy


class ToolRedirector:

    ALTERNATIVES = {
        "CREDENTIAL": "Use your organisation's secrets manager or internal vault.",
        "CODE_SNIPPET": "Use the internally-hosted code assistant with data retention disabled.",
        "PII_FRAGMENT": "Use the privacy-preserving sandbox environment.",
    }
    DEFAULT = "Consider using your organisation's internally-hosted AI model for this query."

    def suggest(self, annotation: RiskAnnotation, original_prompt: str, user_context: UserContext) -> CoachingSuggestion:
        bt = annotation.block.block_type.value
        return CoachingSuggestion(
            strategy=CoachingStrategy.TOOL_REDIRECTION,
            original_fragment=annotation.block.content[:100],
            suggested_replacement=self.ALTERNATIVES.get(bt, self.DEFAULT),
            rationale=f"This {bt.lower()} content should not be transmitted to external AI services under any reformulation.",
            confidence=0.95,
        )
