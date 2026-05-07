"""
Layer 4 — Policy Enforcement & Orchestration Layer (PEOL).

Implements federated governance hierarchy with three tiers:
  - Enterprise Floor Policies (immutable)
  - Business Unit Amplifications (department-specific)
  - Role-Based Exemptions (scoped permissions)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pranidhi.models import (
    RiskAnnotation, CoachingSuggestion, UserContext, Disposition,
)

logger = logging.getLogger(__name__)


class PolicyEnforcer:
    """
    Makes final disposition decisions based on risk assessments,
    coaching outcomes, and the federated policy hierarchy.
    """

    # Enterprise floor: content types that are ALWAYS blocked
    ABSOLUTE_BLOCKS = {"CREDENTIAL"}

    def __init__(self, policy_path: Optional[Path] = None):
        self._policy_path = policy_path
        self._policies = self._load_policies(policy_path)

    def enforce(
        self,
        annotations: list[RiskAnnotation],
        suggestions: list[CoachingSuggestion],
        user_context: UserContext,
    ) -> Disposition:
        """
        Determine final disposition by applying the policy hierarchy.

        Priority order:
          1. Enterprise floor policies (cannot be overridden)
          2. Business unit amplifications
          3. Role-based exemptions
          4. Default to the highest risk annotation's disposition
        """
        # Tier 1: Enterprise floor — absolute blocks
        for ann in annotations:
            for entity in ann.flagged_entities:
                if entity in self.ABSOLUTE_BLOCKS:
                    logger.warning(
                        "Enterprise floor policy: BLOCKED (entity=%s, user=%s)",
                        entity, user_context.user_id,
                    )
                    return Disposition.RED

        # Tier 2: Business unit amplifications
        dept_policy = self._policies.get("departments", {}).get(
            user_context.department, {}
        )
        dept_threshold = dept_policy.get("block_threshold", 0.7)

        # Tier 2 + Tier 3 combined: department thresholds with role exemptions
        exempt_roles = self._policies.get("exempt_roles", [])
        is_exempt = user_context.role in exempt_roles

        for ann in annotations:
            if ann.risk_score.composite >= dept_threshold:
                if is_exempt:
                    logger.info(
                        "Role exemption applied: %s (dept=%s), downgrading RED→AMBER",
                        user_context.role, user_context.department,
                    )
                    return Disposition.AMBER
                if not suggestions:
                    return Disposition.RED
                return Disposition.AMBER  # Coach rather than block if suggestions exist

        # Default: use the highest annotation disposition
        dispositions = [a.disposition for a in annotations]
        if Disposition.RED in dispositions:
            return Disposition.RED if not suggestions else Disposition.AMBER
        if Disposition.AMBER in dispositions:
            return Disposition.AMBER
        return Disposition.GREEN

    @staticmethod
    def _load_policies(path: Optional[Path]) -> dict:
        """Load policy configuration from YAML file."""
        if path is None or not path.exists():
            return {
                "departments": {},
                "exempt_roles": ["security_researcher", "red_team"],
            }
        try:
            import yaml
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("PyYAML not installed; using default policies.")
            return {"departments": {}, "exempt_roles": []}
        except Exception as exc:
            logger.error("Failed to load policies from %s: %s", path, exc)
            return {"departments": {}, "exempt_roles": []}
