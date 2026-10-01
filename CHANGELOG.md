# Changelog

## 0.2.0 (2026-10-01)

### Security
- Normalisation: NFKC folding, removal of all Unicode format characters (category Cf), UTF-8 percent-decoding, extended Cyrillic and Greek confusable folding, hexadecimal and Base64 decoding as appended views, collapse of character-spaced runs.
- Vendor credential patterns: AWS, GitHub, Slack, Google, Stripe, JWT, PEM private-key headers.
- PEOL: department thresholds clamped to the enterprise floor; policy-defined absolute-block entities honoured; fail-closed policy loading; structured audit log without prompt text.
- TAALL: HMAC-SHA256 user pseudonyms; adaptive thresholds clamped to the floor.

### Fixes
- Code-snippet detection is structural rather than keyword-based (v0.1.0 over-flagged prose and inflated recall).
- Overlap handling in fragment extraction; Base64 inline-mutation bug.

### Evaluation
- New `benchmarks/adversarial.py` and `benchmarks/sensitivity.py`; results committed as JSON.
- Main corpus (seed 20260721): F1 0.8878 (v0.1.0 reported 0.9359; see README for the correction).

### Tests
- 77 tests (was 43), including `tests/test_security_posture.py`.
