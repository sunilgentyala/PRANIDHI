"""
Security-posture regression tests for PRANIDHI v0.2.0.

Each test pins a property that the paper (Section 11.8) claims about the
framework's own attack surface: normalisation resists common obfuscation,
policy tiers can only tighten, malformed policy fails closed, and telemetry
does not carry raw identities or prompt text. Secrets are assembled from
fragments so no real-shaped credential appears in source.
"""

import logging

import pytest

from pranidhi.idl.decomposer import Decomposer
from pranidhi.models import (
    ContentBlock,
    ContentBlockType,
    Disposition,
    RiskAnnotation,
    RiskScore,
    SensitivityTier,
    UserContext,
)
from pranidhi.peol.enforcer import PolicyEnforcer
from pranidhi.pipeline import PranidhiPipeline
from pranidhi.taall.telemetry import TelemetryCollector

CTX = UserContext(user_id="alice@example.com", role="manager", department="finance", target_platform="chatgpt")


def _types(prompt: str) -> set:
    return {b.block_type for b in Decomposer().decompose(prompt)}


def _ann(entities, composite, disposition=Disposition.AMBER):
    block = ContentBlock(
        block_id="t", block_type=ContentBlockType.PII_FRAGMENT, content="x",
        start_offset=0, end_offset=1,
    )
    score = RiskScore(
        sensitivity_tier=SensitivityTier.CONFIDENTIAL, exposure_risk=0.5,
        inferential_leakage=0.5, composite=composite,
    )
    return RiskAnnotation(
        block=block, risk_score=score, disposition=disposition,
        flagged_entities=list(entities), explanation="",
    )


# ── IDL: credential coverage and normalisation ──

VENDOR_SECRETS = [
    "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "xo" + "xb-" + "1234567890" + "-" + "abcdefghijklmnopqrstuvwx",
    "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghijklmnop",
    "-----BEGIN " + "RSA PRIVATE KEY-----",
]


@pytest.mark.parametrize("secret", VENDOR_SECRETS)
def test_vendor_shaped_credentials_are_detected(secret):
    assert ContentBlockType.CREDENTIAL in _types(f"here: {secret}")


def test_zero_width_and_bidi_controls_are_stripped():
    secret = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
    obfuscated = "\u202e".join(secret) + "\u2060"
    assert ContentBlockType.CREDENTIAL in _types(obfuscated)


def test_fullwidth_forms_are_folded_by_nfkc():
    secret = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
    fullwidth = "".join(chr(ord(c) + 0xFEE0) for c in secret)
    assert ContentBlockType.CREDENTIAL in _types(fullwidth)


def test_greek_and_cyrillic_confusables_are_folded():
    assert ContentBlockType.PII_FRAGMENT in _types("mail \u0430lice@\u0435xample.com now")


def test_percent_encoding_is_decoded_as_utf8():
    assert ContentBlockType.PII_FRAGMENT in _types("ssn %31%32%33-%34%35-%36%37%38%39")


def test_short_base64_ssn_is_decoded():
    import base64
    encoded = base64.b64encode(b"123-45-6789").decode()
    assert ContentBlockType.PII_FRAGMENT in _types(f"data {encoded}")


def test_spaced_characters_are_collapsed():
    assert ContentBlockType.PII_FRAGMENT in _types("ssn 1 2 3 - 4 5 - 6 7 8 9 please")


def test_jwt_segments_are_not_corrupted_by_base64_decoding():
    jwt = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghijklmnop"
    blocks = Decomposer().decompose("here: " + jwt)
    assert any(b.block_type == ContentBlockType.CREDENTIAL and b.content == jwt for b in blocks)


def test_ordinary_prose_is_not_altered_or_flagged_as_credential():
    prompt = "Summarise the key differences between symmetric and asymmetric encryption."
    blocks = Decomposer().decompose(prompt)
    assert all(b.block_type != ContentBlockType.CREDENTIAL for b in blocks)
    assert blocks[-1].content == prompt


def test_overlapping_spans_containing_an_earlier_match_are_skipped():
    blocks = Decomposer().decompose("call 555-12-3456 today")
    spans = [(b.start_offset, b.end_offset) for b in blocks if b.block_type != ContentBlockType.FREE_TEXT]
    for i, (s1, e1) in enumerate(spans):
        for s2, e2 in spans[i + 1:]:
            assert not (s1 < e2 and s2 < e1)


# ── PEOL: tier-narrowing, fail-closed, audit ──

def test_department_threshold_cannot_exceed_enterprise_floor(tmp_path, caplog):
    policy = tmp_path / "p.yaml"
    policy.write_text("departments:\n  finance:\n    block_threshold: 0.95\n", encoding="utf-8")
    enforcer = PolicyEnforcer(policy_path=policy)
    with caplog.at_level(logging.WARNING, logger="pranidhi"):
        result = enforcer.enforce([_ann(["PII"], 0.75)], [], CTX)
    assert result == Disposition.RED  # would be GREEN/AMBER if 0.95 were honoured
    assert "clamped" in caplog.text


def test_invalid_department_threshold_falls_back_to_floor(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("departments:\n  finance:\n    block_threshold: 'high'\n", encoding="utf-8")
    enforcer = PolicyEnforcer(policy_path=policy)
    assert enforcer.enforce([_ann(["PII"], 0.75)], [], CTX) == Disposition.RED


def test_policy_cannot_remove_credential_from_absolute_blocks(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("enterprise_floor:\n  absolute_block_entities: []\n", encoding="utf-8")
    enforcer = PolicyEnforcer(policy_path=policy)
    assert enforcer.enforce([_ann(["CREDENTIAL"], 0.1, Disposition.GREEN)], [], CTX) == Disposition.RED


def test_policy_can_add_absolute_block_entities(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("enterprise_floor:\n  absolute_block_entities: [SOURCE_CODE]\n", encoding="utf-8")
    enforcer = PolicyEnforcer(policy_path=policy)
    assert enforcer.enforce([_ann(["SOURCE_CODE"], 0.1, Disposition.GREEN)], [], CTX) == Disposition.RED


@pytest.mark.parametrize("content", ["::: not: [valid yaml", "- just\n- a list\n"])
def test_malformed_policy_fails_closed(tmp_path, content):
    policy = tmp_path / "bad.yaml"
    policy.write_text(content, encoding="utf-8")
    enforcer = PolicyEnforcer(policy_path=policy)
    exempt = UserContext(user_id="u", role="security_researcher", department="x")
    assert enforcer.enforce([_ann(["PII"], 0.9, Disposition.RED)], [], exempt) == Disposition.RED


def test_missing_policy_file_fails_closed(tmp_path):
    enforcer = PolicyEnforcer(policy_path=tmp_path / "absent.yaml")
    exempt = UserContext(user_id="u", role="red_team", department="x")
    assert enforcer.enforce([_ann(["PII"], 0.9, Disposition.RED)], [], exempt) == Disposition.RED


def test_exemption_never_overrides_tier1_and_is_audited(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("exempt_roles: [red_team]\n", encoding="utf-8")
    enforcer = PolicyEnforcer(policy_path=policy)
    red = UserContext(user_id="u", role="red_team", department="x")
    assert enforcer.enforce([_ann(["CREDENTIAL"], 0.9, Disposition.RED)], [], red) == Disposition.RED
    assert enforcer.audit_log[-1]["event"] == "tier1_block"
    assert "prompt" not in enforcer.audit_log[-1]


# ── TAALL: privacy and feedback-loop safety ──

def _scan_many(collector, n, prompt="Explain TLS."):
    pipe = PranidhiPipeline(enable_telemetry=False)
    pipe._telemetry = collector
    for _ in range(n):
        pipe.scan(prompt, CTX)


def test_telemetry_pseudonymises_user_ids_and_stores_no_prompt_text():
    collector = TelemetryCollector(pseudonym_key=b"k" * 32)
    _scan_many(collector, 1, prompt="My SSN is 123-45-6789")
    exported = str(collector.export_all())
    assert "alice@example.com" not in exported
    assert "123-45-6789" not in exported
    assert collector.export_all()[0]["user_id"].startswith("u_")


def test_pseudonyms_are_stable_for_a_key_and_differ_across_keys():
    a1 = TelemetryCollector(pseudonym_key=b"a" * 32)._pseudonym("bob")
    a2 = TelemetryCollector(pseudonym_key=b"a" * 32)._pseudonym("bob")
    b1 = TelemetryCollector(pseudonym_key=b"b" * 32)._pseudonym("bob")
    assert a1 == a2 and a1 != b1


def test_pseudonymisation_can_be_disabled_explicitly():
    assert TelemetryCollector(pseudonymise_user_ids=False)._pseudonym("bob") == "bob"


def test_adaptive_thresholds_never_relax_above_the_floor():
    collector = TelemetryCollector(pseudonym_key=b"k" * 32)
    # A flood of benign prompts drives the department's average risk toward zero,
    # the poisoning scenario: the suggestion must still not exceed 0.70.
    _scan_many(collector, 30, prompt="Explain TLS.")
    for value in collector.get_adaptive_thresholds().values():
        assert value <= 0.70


PROSE_WITH_CODE_WORDS = [
    "Why did Acme Corp's Q3 revenue drop 14.7% after losing their largest client?",
    "Let me know which class action filings from last quarter we should import into the review.",
    "Select the best option from the list and explain why it is a function of cost.",
]


@pytest.mark.parametrize("prompt", PROSE_WITH_CODE_WORDS)
def test_prose_containing_code_keywords_is_not_a_code_snippet(prompt):
    assert ContentBlockType.CODE_SNIPPET not in _types(prompt)


@pytest.mark.parametrize("snippet", [
    "def total(rows):\n    return sum(rows)",
    "SELECT id, balance FROM accounts WHERE balance > 10",
    "class Model:\n    pass",
    "const apiUrl = 'x'",
    "items.map((x) => { return x; })",
])
def test_real_code_is_still_detected(snippet):
    assert ContentBlockType.CODE_SNIPPET in _types(snippet)
