# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

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
