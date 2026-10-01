# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x: (upgrade: fixes below)  |

## Reporting a Vulnerability

If you discover a security vulnerability in PRANIDHI, please report it
responsibly. **Do not open a public GitHub issue.**

Email: security@pranidhi-framework.org

We will acknowledge receipt within 48 hours and provide a detailed
response within 7 days.

## Security Design Principles

PRANIDHI is designed with security-first principles:

1. **The coaching pipeline never transmits sensitive data externally.**
   The Nudging Engine uses an internally-hosted model.

2. **All telemetry is stored locally** by default. Export requires
   explicit configuration.

3. **Policy configurations are validated** at startup to prevent
   misconfigurations that could weaken protections.

4. **Audit logs are immutable** once written.

## Threat Model of the Guardrail Itself (v0.2.0)

| ID | Threat | Control in v0.2.0 | Residual risk |
|----|--------|-------------------|---------------|
| E1 | Input obfuscation (zero-width, bidi, homoglyphs, fullwidth, percent/hex/Base64, spacing) | NFKC fold, strip Unicode category Cf, UTF-8 percent-decoding, Cyrillic/Greek fold, decoded views appended (original never mutated), vendor credential patterns | Reversal, ROT13, paraphrase and multi-line secrets under character spacing are not normalised |
| E2 | Policy tampering or misconfiguration | Department thresholds clamped to the enterprise floor; policy cannot remove `CREDENTIAL` from the absolute-block set; missing or malformed policy fails closed (no exemptions) | Policy file integrity must be protected by the deployer (sign and verify at deploy time) |
| E3 | Identity spoofing | None in the library: `role` and `department` are caller-supplied | Bind them to an authenticated identity provider; never accept them from the client |
| E4 | Feedback-loop poisoning | Adaptive thresholds are advisory and clamped to the floor (0.70) | Proposals still need human review |
| E5 | Telemetry leakage | No prompt text in telemetry or audit records; user ids pseudonymised with HMAC-SHA256 | Set `PRANIDHI_TELEMETRY_KEY` for stable pseudonyms; protect exports |
| E6 | Semantic evasion | Out of scope for deterministic detectors | Requires a semantic detector (future work) |

### Fixed in 0.2.0

- Department thresholds and adaptive thresholds could exceed the enterprise floor (widening, contrary to the documented design). Now clamped.
- `enterprise_floor.absolute_block_entities` in the policy file was ignored. Now honoured (union with the hard-coded floor).
- A missing explicit policy file silently enabled default role exemptions. Now fails closed.
- Base64 decoding inserted text inside tokens, corrupting JWTs. Decoded views are now appended after the original.
- Overlap check skipped only partial overlaps, not spans that fully contained an earlier match.
- The code-snippet detector matched bare English words, producing false positives (and inflating v0.1.0 recall). It is now structural.
- Raw user ids were stored in telemetry. They are now pseudonymised by default.
