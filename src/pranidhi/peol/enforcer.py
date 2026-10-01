"""
Layer 4: Policy Enforcement & Orchestration Layer (PEOL).

Implements federated governance hierarchy with three tiers:
  - Enterprise Floor Policies (immutable)
  - Business Unit Amplifications (department-specific, may only tighten)
  - Role-Based Exemptions (scoped, audited downgrades RED -> AMBER)

Security properties enforced here (see tests/test_security_posture.py):
  * A department threshold can never exceed the enterprise floor threshold.
  * Absolute-block entities from policy are added to, never subtracted from,
    the hard-coded floor set {CREDENTIAL}.
  * A missing, unreadable, or malformed policy file fails closed: no role
    exemptions, no department overrides.
  * Every Tier 1 block and Tier 3 exemption is written to an in-memory audit
    log (never containing prompt text) in addition to the logger.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from pranidhi.models import (
    CoachingSuggestion,
    Disposition,
    RiskAnnotation,
    UserContext,
)

logger = logging.getLogger(__name__)

# Policy-file aliases that map onto the canonical flagged-entity labels.
_ENTITY_ALIASES = {"API_KEY": "CREDENTIAL", "SECRET": "CREDENTIAL"}

_STRICT_DEFAULTS: dict[str, Any] = {"departments": {}, "exempt_roles": []}


class PolicyEnforcer:
    """
    Makes final disposition decisions based on risk assessments,
    coaching outcomes, and the federated policy hierarchy.
    """

    # Enterprise floor: content types that are ALWAYS blocked. Policy files
    # may add to this set but cannot remove from it.
    ABSOLUTE_BLOCKS: ClassVar[frozenset[str]] = frozenset({"CREDENTIAL"})

    # Enterprise floor threshold (tau_0). Departments may only lower it.
    FLOOR_THRESHOLD = 0.7

    def __init__(self, policy_path: Path | None = None):
        self._policy_path = policy_path
        self._policies = self._load_policies(policy_path)
        self.audit_log: list[dict[str, Any]] = []

        floor_cfg = self._policies.get("enterprise_floor") or {}
        extra = {
            _ENTITY_ALIASES.get(str(e).upper(), str(e).upper())
            for e in (floor_cfg.get("absolute_block_entities") or [])
        }
        self._absolute_blocks = set(self.ABSOLUTE_BLOCKS) | extra

        settings = self._policies.get("settings") or {}
        self._floor_threshold = self._valid_threshold(
            settings.get("default_block_threshold"), self.FLOOR_THRESHOLD
        )
        self._floor_threshold = min(self._floor_threshold, self.FLOOR_THRESHOLD)

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
          2. Business unit amplifications (cannot loosen the floor)
          3. Role-based exemptions
          4. Default to the highest risk annotation's disposition
        """
        # Tier 1: Enterprise floor: absolute blocks
        for ann in annotations:
            for entity in ann.flagged_entities:
                if entity in self._absolute_blocks:
                    self._audit("tier1_block", user_context, entity=entity)
                    return Disposition.RED

        # Tier 2: Business unit amplification, clamped to the floor
        dept_policy = (self._policies.get("departments") or {}).get(
            user_context.department, {}
        ) or {}
        requested = self._valid_threshold(
            dept_policy.get("block_threshold"), self._floor_threshold
        )
        dept_threshold = min(requested, self._floor_threshold)
        if requested > self._floor_threshold:
            logger.warning(
                "Department %r requested block_threshold=%.2f above the enterprise "
                "floor %.2f; clamped to the floor.",
                user_context.department, requested, self._floor_threshold,
            )

        # Tier 3: role exemptions (explicitly configured only)
        exempt_roles = self._policies.get("exempt_roles") or []
        is_exempt = user_context.role in exempt_roles

        for ann in annotations:
            if ann.risk_score.composite >= dept_threshold:
                if is_exempt:
                    self._audit(
                        "tier3_exemption", user_context,
                        composite=ann.risk_score.composite, threshold=dept_threshold,
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

    # ── helpers ──

    @staticmethod
    def _valid_threshold(value: Any, fallback: float) -> float:
        """Accept only a real number in (0, 1]; anything else falls back."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return fallback
        if not (0.0 < float(value) <= 1.0):
            return fallback
        return float(value)

    def _audit(self, event: str, ctx: UserContext, **fields: Any) -> None:
        """Record a reconstructable policy event. Never includes prompt text."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "user_id": ctx.user_id,
            "role": ctx.role,
            "department": ctx.department,
            **fields,
        }
        self.audit_log.append(record)
        logger.info("PEOL audit: %s", record)

    @staticmethod
    def _load_policies(path: Path | None) -> dict:
        """Load policy configuration from YAML; fail closed on any problem."""
        if path is None:
            return dict(_STRICT_DEFAULTS)
        if not path.exists():
            logger.error("Policy file %s not found; using strict defaults.", path)
            return dict(_STRICT_DEFAULTS)
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed; using strict default policies.")
            return dict(_STRICT_DEFAULTS)
        try:
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            logger.error("Failed to load policies from %s: %s", path, exc)
            return dict(_STRICT_DEFAULTS)
        if not isinstance(loaded, dict):
            logger.error("Policy file %s is not a mapping; using strict defaults.", path)
            return dict(_STRICT_DEFAULTS)
        return loaded
