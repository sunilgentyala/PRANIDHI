# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x: (upgrade: fixes below)  |

## Reporting a Vulnerability

If you discover a security vulnerability in PRANIDHI, please report it
responsibly. **Do not open a public GitHub issue.**

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**
(https://github.com/sunilgentyala/PRANIDHI/security/advisories/new). If that option is unavailable, contact the maintainer
through the contact details on the maintainer's GitHub profile.

This is a research project maintained by volunteers: we aim to acknowledge reports within a few days and will
credit reporters unless they prefer otherwise.

## Security Design Principles

1. **No model call in the coaching path.** The four coaching strategies are
   deterministic templates, so the Nudging Engine introduces no new
   exfiltration channel. A future generative coaching model will need its own
   isolation and leakage evaluation before it ships.

2. **Telemetry holds no prompt text.** Records carry a keyed pseudonym
   (HMAC-SHA256) instead of the user identifier. Export to disk happens only
   when an export path is configured.

3. **Policies can only tighten.** Department thresholds are clamped to the
   enterprise floor, the policy file cannot remove `CREDENTIAL` from the
   absolute-block set, and a missing or malformed policy fails closed.

4. **Policy decisions are auditable.** Tier 1 blocks and Tier 3 exemptions are
   written to an audit log that never contains prompt text. The log is held in
   memory by the library; persisting it durably and tamper-evidently is the
   deployer's responsibility.

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
