# Contributing to PRANIDHI

Thank you for your interest in contributing to PRANIDHI. This document
provides guidelines for contributing to the project.

## Development Setup

```bash
git clone https://github.com/pranidhi-framework/pranidhi.git
cd pranidhi
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v --cov=pranidhi
```

## Code Quality

```bash
ruff check src/ tests/
mypy src/pranidhi/
```

## Areas Where Help Is Needed

1. **Nudging Engine Strategies** — Improving the quality of reformulation
   suggestions, particularly for domain-specific prompts.

2. **Benchmark Corpus (SPHB)** — Contributing annotated enterprise prompts
   with sensitivity labels, risk scores, and gold-standard reformulations.

3. **Platform Connectors** — Adding adapters for new AI platforms.

4. **Multilingual Support** — Extending PII detection and coaching beyond
   English.

5. **Evaluation** — Conducting and reporting user studies.

## Pull Request Guidelines

- Create a feature branch from `main`
- Include tests for new functionality
- Update documentation as needed
- Ensure all tests pass and linting is clean
- Write clear commit messages

## Reporting Security Issues

Please report security vulnerabilities to security@pranidhi-framework.org
rather than opening a public issue.
