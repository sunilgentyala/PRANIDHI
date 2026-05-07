"""
Test suite for the PRANIDHI pipeline.

Covers all five layers with unit tests for decomposition, risk scoring,
coaching strategy selection, policy enforcement, and telemetry collection.
"""

import pytest
from pranidhi.models import (
    ContentBlock, ContentBlockType, UserContext, RiskScore,
    RiskAnnotation, Disposition, SensitivityTier,
    CoachingSuggestion, CoachingStrategy, ScanResult,
)
from pranidhi.idl.decomposer import Decomposer
from pranidhi.crse.risk_scorer import RiskScorer
from pranidhi.nudging_engine.engine import NudgingEngine
from pranidhi.nudging_engine.strategies.substitutive import SubstitutiveReformulator
from pranidhi.nudging_engine.strategies.decomposition import DecompositionPlanner
from pranidhi.nudging_engine.strategies.abstraction import AbstractionElevator
from pranidhi.nudging_engine.strategies.redirection import ToolRedirector
from pranidhi.peol.enforcer import PolicyEnforcer
from pranidhi.taall.telemetry import TelemetryCollector


# ═══════════════════════════════════════════════════════════════════
# Layer 1: IDL — Decomposer Tests
# ═══════════════════════════════════════════════════════════════════

class TestDecomposer:

    def setup_method(self):
        self.decomposer = Decomposer()

    def test_empty_input_returns_empty(self):
        assert self.decomposer.decompose("") == []
        assert self.decomposer.decompose("   ") == []

    def test_clean_text_returns_free_text_only(self):
        blocks = self.decomposer.decompose("What is the capital of France?")
        types = [b.block_type for b in blocks]
        assert ContentBlockType.FREE_TEXT in types

    def test_detects_email_address(self):
        prompt = "Please contact john.smith@acmecorp.com for details"
        blocks = self.decomposer.decompose(prompt)
        pii_blocks = [b for b in blocks if b.block_type == ContentBlockType.PII_FRAGMENT]
        assert len(pii_blocks) >= 1
        assert "john.smith@acmecorp.com" in pii_blocks[0].content

    def test_detects_ssn_pattern(self):
        prompt = "Employee SSN is 123-45-6789 for the payroll system"
        blocks = self.decomposer.decompose(prompt)
        pii_blocks = [b for b in blocks if b.block_type == ContentBlockType.PII_FRAGMENT]
        assert len(pii_blocks) >= 1

    def test_detects_api_key_pattern(self):
        prompt = "Use this key: key_test_abc123def456ghi789jkl012mno345"
        blocks = self.decomposer.decompose(prompt)
        cred_blocks = [b for b in blocks if b.block_type == ContentBlockType.CREDENTIAL]
        assert len(cred_blocks) >= 1

    def test_detects_code_snippet(self):
        prompt = "def calculate_revenue(q3_data): return sum(q3_data['amounts'])"
        blocks = self.decomposer.decompose(prompt)
        code_blocks = [b for b in blocks if b.block_type == ContentBlockType.CODE_SNIPPET]
        assert len(code_blocks) >= 1

    def test_normalises_zero_width_characters(self):
        prompt = "john\u200b.\u200bsmith\u200b@\u200bacme\u200b.com"
        blocks = self.decomposer.decompose(prompt)
        pii_blocks = [b for b in blocks if b.block_type == ContentBlockType.PII_FRAGMENT]
        assert len(pii_blocks) >= 1

    def test_detects_url(self):
        prompt = "Check our internal dashboard at https://dashboard.internal.acme.com/reports"
        blocks = self.decomposer.decompose(prompt)
        url_blocks = [b for b in blocks if b.block_type == ContentBlockType.URL]
        assert len(url_blocks) >= 1

    def test_detects_credit_card_pattern(self):
        prompt = "The card number is 4532-1234-5678-9012"
        blocks = self.decomposer.decompose(prompt)
        pii_blocks = [b for b in blocks if b.block_type == ContentBlockType.PII_FRAGMENT]
        assert len(pii_blocks) >= 1

    def test_multiple_sensitive_elements(self):
        prompt = (
            "Send invoice to john@acme.com, account #ACCT-445566, "
            "API key: sk_test_abcdefghijklmnopqrstuvwxyz"
        )
        blocks = self.decomposer.decompose(prompt)
        sensitive = [
            b for b in blocks
            if b.block_type in (ContentBlockType.PII_FRAGMENT, ContentBlockType.CREDENTIAL)
        ]
        assert len(sensitive) >= 2


# ═══════════════════════════════════════════════════════════════════
# Layer 2: CRSE — Risk Scorer Tests
# ═══════════════════════════════════════════════════════════════════

class TestRiskScorer:

    def setup_method(self):
        self.scorer = RiskScorer()
        self.default_ctx = UserContext(
            user_id="test-user",
            role="analyst",
            department="finance",
            target_platform="chatgpt",
        )

    def test_free_text_scores_low(self):
        block = ContentBlock(
            block_id="t1", block_type=ContentBlockType.FREE_TEXT,
            content="What is machine learning?", start_offset=0, end_offset=25,
        )
        annotations = self.scorer.score_blocks([block], self.default_ctx)
        assert len(annotations) == 1
        assert annotations[0].disposition == Disposition.GREEN

    def test_credential_scores_high(self):
        block = ContentBlock(
            block_id="t2", block_type=ContentBlockType.CREDENTIAL,
            content="key_test_abc123def456ghi789jkl012mno345",
            start_offset=0, end_offset=38,
        )
        annotations = self.scorer.score_blocks([block], self.default_ctx)
        assert annotations[0].risk_score.composite >= 0.6
        assert annotations[0].disposition in (Disposition.AMBER, Disposition.RED)

    def test_pii_scores_medium_to_high(self):
        block = ContentBlock(
            block_id="t3", block_type=ContentBlockType.PII_FRAGMENT,
            content="john.smith@acmecorp.com", start_offset=0, end_offset=23,
        )
        annotations = self.scorer.score_blocks([block], self.default_ctx)
        assert annotations[0].risk_score.composite >= 0.3

    def test_internal_platform_lowers_exposure(self):
        block = ContentBlock(
            block_id="t4", block_type=ContentBlockType.PII_FRAGMENT,
            content="test@example.com", start_offset=0, end_offset=16,
        )
        internal_ctx = UserContext(
            user_id="u1", role="analyst", department="hr",
            target_platform="internal",
        )
        external_ctx = UserContext(
            user_id="u1", role="analyst", department="hr",
            target_platform="chatgpt",
        )
        internal_ann = self.scorer.score_blocks([block], internal_ctx)
        external_ann = self.scorer.score_blocks([block], external_ctx)

        assert internal_ann[0].risk_score.exposure_risk < external_ann[0].risk_score.exposure_risk

    def test_trained_role_lowers_risk(self):
        block = ContentBlock(
            block_id="t5", block_type=ContentBlockType.CODE_SNIPPET,
            content="def process(): pass", start_offset=0, end_offset=20,
        )
        trained_ctx = UserContext(user_id="u1", role="security", target_platform="claude")
        untrained_ctx = UserContext(user_id="u2", role="marketing", target_platform="claude")

        trained_ann = self.scorer.score_blocks([block], trained_ctx)
        untrained_ann = self.scorer.score_blocks([block], untrained_ctx)

        assert trained_ann[0].risk_score.exposure_risk <= untrained_ann[0].risk_score.exposure_risk

    def test_risk_score_bounds(self):
        block = ContentBlock(
            block_id="t6", block_type=ContentBlockType.PII_FRAGMENT,
            content="555-12-3456", start_offset=0, end_offset=11,
        )
        annotations = self.scorer.score_blocks([block], self.default_ctx)
        score = annotations[0].risk_score
        assert 0.0 <= score.composite <= 1.0
        assert 0.0 <= score.exposure_risk <= 1.0
        assert 0.0 <= score.inferential_leakage <= 1.0


# ═══════════════════════════════════════════════════════════════════
# Layer 3: Nudging Engine Tests
# ═══════════════════════════════════════════════════════════════════

class TestNudgingEngine:

    def setup_method(self):
        self.engine = NudgingEngine()
        self.ctx = UserContext(
            user_id="u1", role="analyst", department="finance",
            target_platform="chatgpt",
        )

    def _make_annotation(self, disposition, entities=None, composite=0.5):
        block = ContentBlock(
            block_id="b1", block_type=ContentBlockType.PII_FRAGMENT,
            content="test@example.com", start_offset=0, end_offset=16,
        )
        return RiskAnnotation(
            block=block,
            risk_score=RiskScore(
                sensitivity_tier=SensitivityTier.CONFIDENTIAL,
                exposure_risk=0.5, inferential_leakage=0.5,
                composite=composite,
            ),
            disposition=disposition,
            flagged_entities=entities or ["PII"],
        )

    def test_green_produces_no_suggestions(self):
        ann = self._make_annotation(Disposition.GREEN, composite=0.1)
        suggestions = self.engine.generate_coaching([ann], "safe prompt", self.ctx)
        assert suggestions == []

    def test_amber_produces_suggestions(self):
        ann = self._make_annotation(Disposition.AMBER, composite=0.5)
        suggestions = self.engine.generate_coaching(
            [ann], "Analyse test@example.com account", self.ctx
        )
        assert len(suggestions) >= 1

    def test_credential_triggers_redirection(self):
        block = ContentBlock(
            block_id="b2", block_type=ContentBlockType.CREDENTIAL,
            content="sk_live_abc123xyz", start_offset=0, end_offset=17,
        )
        ann = RiskAnnotation(
            block=block,
            risk_score=RiskScore(
                sensitivity_tier=SensitivityTier.LEGALLY_PRIVILEGED,
                exposure_risk=0.9, inferential_leakage=0.3, composite=0.85,
            ),
            disposition=Disposition.RED,
            flagged_entities=["CREDENTIAL"],
        )
        suggestions = self.engine.generate_coaching(
            [ann], "Use key sk_live_abc123xyz", self.ctx
        )
        strategies = [s.strategy for s in suggestions]
        assert CoachingStrategy.TOOL_REDIRECTION in strategies

    def test_max_suggestions_cap(self):
        engine = NudgingEngine(max_suggestions=2)
        ann = self._make_annotation(Disposition.AMBER, ["PII", "SOURCE_CODE"], 0.6)
        suggestions = engine.generate_coaching(
            [ann], "A very long prompt " * 30, self.ctx
        )
        assert len(suggestions) <= 2


class TestSubstitutiveReformulator:

    def test_replaces_pii(self):
        reformulator = SubstitutiveReformulator()
        block = ContentBlock(
            block_id="b1", block_type=ContentBlockType.PII_FRAGMENT,
            content="john@acme.com", start_offset=0, end_offset=13,
        )
        ann = RiskAnnotation(
            block=block,
            risk_score=RiskScore(SensitivityTier.CONFIDENTIAL, 0.5, 0.5, 0.5),
            disposition=Disposition.AMBER,
        )
        suggestion = reformulator.suggest(ann, "Email john@acme.com for details", UserContext(user_id="u1"))
        assert "john@acme.com" not in suggestion.suggested_replacement
        assert suggestion.strategy == CoachingStrategy.SUBSTITUTIVE_REFORMULATION


class TestToolRedirector:

    def test_credential_redirection(self):
        redirector = ToolRedirector()
        block = ContentBlock(
            block_id="b1", block_type=ContentBlockType.CREDENTIAL,
            content="sk_live_xyz", start_offset=0, end_offset=11,
        )
        ann = RiskAnnotation(
            block=block,
            risk_score=RiskScore(SensitivityTier.LEGALLY_PRIVILEGED, 0.9, 0.3, 0.85),
            disposition=Disposition.RED,
        )
        suggestion = redirector.suggest(ann, "Use key sk_live_xyz", UserContext(user_id="u1"))
        assert suggestion.confidence >= 0.9
        assert "secrets manager" in suggestion.suggested_replacement.lower() or "vault" in suggestion.suggested_replacement.lower()


# ═══════════════════════════════════════════════════════════════════
# Layer 4: PEOL — Policy Enforcer Tests
# ═══════════════════════════════════════════════════════════════════

class TestPolicyEnforcer:

    def setup_method(self):
        self.enforcer = PolicyEnforcer(policy_path=None)
        self.ctx = UserContext(user_id="u1", role="analyst", department="finance")

    def _make_annotation(self, disposition, entities=None, composite=0.5):
        block = ContentBlock(
            block_id="b1", block_type=ContentBlockType.FREE_TEXT,
            content="test", start_offset=0, end_offset=4,
        )
        return RiskAnnotation(
            block=block,
            risk_score=RiskScore(SensitivityTier.INTERNAL, 0.3, 0.3, composite),
            disposition=disposition,
            flagged_entities=entities or [],
        )

    def test_credential_always_blocked(self):
        ann = self._make_annotation(Disposition.AMBER, ["CREDENTIAL"], 0.5)
        result = self.enforcer.enforce([ann], [], self.ctx)
        assert result == Disposition.RED

    def test_green_annotations_pass(self):
        ann = self._make_annotation(Disposition.GREEN, [], 0.1)
        result = self.enforcer.enforce([ann], [], self.ctx)
        assert result == Disposition.GREEN

    def test_amber_with_suggestions_stays_amber(self):
        ann = self._make_annotation(Disposition.AMBER, ["PII"], 0.75)
        suggestion = CoachingSuggestion(
            strategy=CoachingStrategy.SUBSTITUTIVE_REFORMULATION,
            original_fragment="test", suggested_replacement="safe",
            rationale="test", confidence=0.8,
        )
        result = self.enforcer.enforce([ann], [suggestion], self.ctx)
        assert result == Disposition.AMBER

    def test_security_researcher_exemption(self):
        ann = self._make_annotation(Disposition.RED, ["PII"], 0.85)
        exempt_ctx = UserContext(user_id="u2", role="security_researcher", department="security")
        result = self.enforcer.enforce([ann], [], exempt_ctx)
        assert result == Disposition.AMBER


# ═══════════════════════════════════════════════════════════════════
# Layer 5: TAALL — Telemetry Tests
# ═══════════════════════════════════════════════════════════════════

class TestTelemetryCollector:

    def setup_method(self):
        self.collector = TelemetryCollector(max_buffer_size=100)

    def _make_result(self, disposition=Disposition.GREEN, risk=0.1, dept="engineering"):
        return ScanResult(
            original_prompt="test prompt",
            disposition=disposition,
            risk_score=risk,
            user_context=UserContext(
                user_id="u1", role="analyst",
                department=dept, target_platform="claude",
            ),
            processing_time_ms=15.0,
        )

    def test_records_scan(self):
        self.collector.record(self._make_result())
        metrics = self.collector.get_dashboard_metrics()
        assert metrics.total_scans == 1
        assert metrics.green_count == 1

    def test_tracks_dispositions(self):
        self.collector.record(self._make_result(Disposition.GREEN))
        self.collector.record(self._make_result(Disposition.AMBER, 0.5))
        self.collector.record(self._make_result(Disposition.RED, 0.9))
        metrics = self.collector.get_dashboard_metrics()
        assert metrics.green_count == 1
        assert metrics.amber_count == 1
        assert metrics.red_count == 1

    def test_department_risk_tracking(self):
        for _ in range(5):
            self.collector.record(self._make_result(Disposition.RED, 0.9, "finance"))
        for _ in range(5):
            self.collector.record(self._make_result(Disposition.GREEN, 0.1, "engineering"))
        metrics = self.collector.get_dashboard_metrics()
        assert "finance" in metrics.top_risk_departments

    def test_adaptive_thresholds(self):
        # Generate enough data for threshold calculation
        for _ in range(20):
            self.collector.record(self._make_result(Disposition.GREEN, 0.1, "safe_dept"))
        for _ in range(20):
            self.collector.record(self._make_result(Disposition.RED, 0.8, "risky_dept"))
        thresholds = self.collector.get_adaptive_thresholds()
        assert "safe_dept" in thresholds or "risky_dept" in thresholds

    def test_export_all(self):
        self.collector.record(self._make_result())
        exported = self.collector.export_all()
        assert len(exported) == 1
        assert "scan_id" in exported[0]


# ═══════════════════════════════════════════════════════════════════
# Integration: Full Pipeline Tests
# ═══════════════════════════════════════════════════════════════════

class TestIntegration:
    """End-to-end pipeline tests using realistic prompts."""

    def setup_method(self):
        self.decomposer = Decomposer()
        self.scorer = RiskScorer()
        self.engine = NudgingEngine()
        self.enforcer = PolicyEnforcer()
        self.telemetry = TelemetryCollector()

    def _run_pipeline(self, prompt, role="analyst", dept="engineering", platform="claude"):
        ctx = UserContext(user_id="test", role=role, department=dept, target_platform=platform)
        blocks = self.decomposer.decompose(prompt)
        annotations = self.scorer.score_blocks(blocks, ctx)
        suggestions = self.engine.generate_coaching(annotations, prompt, ctx)
        disposition = self.enforcer.enforce(annotations, suggestions, ctx)
        return disposition, suggestions, annotations

    def test_safe_prompt_passes(self):
        disp, suggestions, _ = self._run_pipeline(
            "What are best practices for quarterly financial reporting?"
        )
        assert disp == Disposition.GREEN
        assert len(suggestions) == 0

    def test_api_key_blocked_with_redirection(self):
        disp, suggestions, _ = self._run_pipeline(
            "Use API key key_test_abcdefghijklmnopqrstuvwxyz123 to authenticate"
        )
        assert disp == Disposition.RED
        strategies = [s.strategy for s in suggestions]
        assert CoachingStrategy.TOOL_REDIRECTION in strategies

    def test_email_triggers_coaching(self):
        disp, suggestions, _ = self._run_pipeline(
            "Please review the complaint from jane.doe@bigclient.com about our service"
        )
        assert len(suggestions) >= 1
        assert disp in (Disposition.AMBER, Disposition.RED)

    def test_code_with_secrets_flagged(self):
        disp, suggestions, annotations = self._run_pipeline(
            'import os; api_key_production = "sk_prod_realkey12345678901234567890"'
        )
        # Should detect both code and credential
        block_types = [a.block.block_type for a in annotations]
        assert ContentBlockType.CREDENTIAL in block_types or ContentBlockType.CODE_SNIPPET in block_types

    def test_internal_platform_more_permissive(self):
        prompt = "Review the performance data for employee ID EMP-44521"
        disp_ext, _, _ = self._run_pipeline(prompt, platform="chatgpt")
        disp_int, _, _ = self._run_pipeline(prompt, platform="internal")
        # Internal should be same or more permissive
        risk_order = {Disposition.GREEN: 0, Disposition.AMBER: 1, Disposition.RED: 2}
        assert risk_order[disp_int] <= risk_order[disp_ext]
