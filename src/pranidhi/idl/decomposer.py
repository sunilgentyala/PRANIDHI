"""
Layer 1 — Ingestion & Decomposition Layer (IDL).

Receives raw user input and performs structural decomposition into
semantically discrete ContentBlocks. Handles encoding normalisation,
language detection, and structural fingerprinting.
"""

from __future__ import annotations

import re
import uuid
import base64
import logging
from typing import Optional

from pranidhi.models import ContentBlock, ContentBlockType

logger = logging.getLogger(__name__)

# ── Detection Patterns ──

# Credit card numbers (basic Luhn-eligible formats)
_RE_CREDIT_CARD = re.compile(
    r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"
)

# Social Security Numbers
_RE_SSN = re.compile(
    r"\b\d{3}[\s\-]?\d{2}[\s\-]?\d{4}\b"
)

# Email addresses
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# API keys and tokens (high-entropy strings)
_RE_API_KEY = re.compile(
    r"(?:sk|pk|api|token|key|secret|bearer)[\-_]?(?:[A-Za-z0-9][\-_A-Za-z0-9]{18,}[A-Za-z0-9])",
    re.IGNORECASE,
)

# IPv4 addresses
_RE_IPV4 = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)

# URLs
_RE_URL = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"
)

# Phone numbers (international and US formats)
_RE_PHONE = re.compile(
    r"\b(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}\b"
)

# Code snippets (heuristic: lines with common programming patterns)
_RE_CODE_INDICATORS = re.compile(
    r"(?:def |class |import |from |function |const |let |var |"
    r"SELECT |INSERT |CREATE |DROP |ALTER |#!/|"
    r"\{[\s\S]*\}|=>|->|\(\) =>)",
    re.IGNORECASE,
)

# Account numbers (generic numeric sequences with separators)
_RE_ACCOUNT_NUMBER = re.compile(
    r"\b(?:account|acct|a/c)[\s#:]*[\d\-]{6,}\b",
    re.IGNORECASE,
)


class Decomposer:
    """
    Decomposes raw prompt input into typed ContentBlocks.

    The decomposition is non-destructive: the original input is preserved
    verbatim, whilst each identified fragment receives a type annotation
    and positional metadata for downstream risk scoring.
    """

    def __init__(self, normalise_encoding: bool = True):
        self._normalise_encoding = normalise_encoding
        self._detectors = [
            (_RE_API_KEY, ContentBlockType.CREDENTIAL),
            (_RE_CREDIT_CARD, ContentBlockType.PII_FRAGMENT),
            (_RE_SSN, ContentBlockType.PII_FRAGMENT),
            (_RE_ACCOUNT_NUMBER, ContentBlockType.PII_FRAGMENT),
            (_RE_EMAIL, ContentBlockType.PII_FRAGMENT),
            (_RE_PHONE, ContentBlockType.PII_FRAGMENT),
            (_RE_IPV4, ContentBlockType.URL),
            (_RE_URL, ContentBlockType.URL),
        ]

    def decompose(self, raw_input: str) -> list[ContentBlock]:
        """
        Decompose raw user input into semantically typed ContentBlocks.

        Parameters
        ----------
        raw_input : str
            The complete, unmodified user prompt.

        Returns
        -------
        list[ContentBlock]
            Ordered list of content blocks with type annotations.
        """
        if not raw_input or not raw_input.strip():
            return []

        # Step 1: Encoding normalisation
        normalised = self._normalise(raw_input) if self._normalise_encoding else raw_input

        # Step 2: Extract typed fragments
        blocks: list[ContentBlock] = []
        matched_spans: list[tuple[int, int]] = []

        for pattern, block_type in self._detectors:
            for match in pattern.finditer(normalised):
                start, end = match.start(), match.end()
                # Skip if this span overlaps with an already-matched region
                if any(s <= start < e or s < end <= e for s, e in matched_spans):
                    continue
                blocks.append(ContentBlock(
                    block_id=str(uuid.uuid4())[:8],
                    block_type=block_type,
                    content=match.group(),
                    start_offset=start,
                    end_offset=end,
                    encoding_normalised=self._normalise_encoding,
                ))
                matched_spans.append((start, end))

        # Step 3: Check for code snippets
        if _RE_CODE_INDICATORS.search(normalised):
            blocks.append(ContentBlock(
                block_id=str(uuid.uuid4())[:8],
                block_type=ContentBlockType.CODE_SNIPPET,
                content=normalised,
                start_offset=0,
                end_offset=len(normalised),
            ))

        # Step 4: The entire input as a free-text block (always included)
        blocks.append(ContentBlock(
            block_id=str(uuid.uuid4())[:8],
            block_type=ContentBlockType.FREE_TEXT,
            content=normalised,
            start_offset=0,
            end_offset=len(normalised),
        ))

        logger.debug(
            "Decomposed input into %d block(s): %s",
            len(blocks),
            [b.block_type.value for b in blocks],
        )

        return blocks

    def _normalise(self, text: str) -> str:
        """
        Apply encoding normalisation to defeat common obfuscation techniques.

        Handles Base64-encoded fragments, URL encoding, Unicode homoglyph
        substitution, and zero-width character injection.
        """
        # Remove zero-width characters
        text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)

        # Decode URL-encoded sequences
        text = self._decode_url_encoding(text)

        # Attempt Base64 decoding of suspicious fragments
        text = self._decode_base64_fragments(text)

        # Normalise Unicode confusables (basic Latin lookalikes)
        confusables = {
            "\u0410": "A", "\u0412": "B", "\u0421": "C", "\u0415": "E",
            "\u041d": "H", "\u041a": "K", "\u041c": "M", "\u041e": "O",
            "\u0420": "P", "\u0422": "T", "\u0425": "X",
            "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p",
            "\u0441": "c", "\u0443": "y", "\u0445": "x",
        }
        for cyrillic, latin in confusables.items():
            text = text.replace(cyrillic, latin)

        return text

    @staticmethod
    def _decode_url_encoding(text: str) -> str:
        """Decode %XX URL-encoded sequences."""
        def replacer(match):
            try:
                return chr(int(match.group(1), 16))
            except (ValueError, OverflowError):
                return match.group(0)
        return re.sub(r"%([0-9A-Fa-f]{2})", replacer, text)

    @staticmethod
    def _decode_base64_fragments(text: str) -> str:
        """Detect and inline-decode Base64-encoded fragments."""
        b64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
        for match in b64_pattern.finditer(text):
            fragment = match.group()
            try:
                decoded = base64.b64decode(fragment).decode("utf-8", errors="strict")
                if decoded.isprintable() and len(decoded) > 4:
                    text = text.replace(fragment, f"{fragment} [decoded: {decoded}]", 1)
            except Exception:
                continue
        return text
