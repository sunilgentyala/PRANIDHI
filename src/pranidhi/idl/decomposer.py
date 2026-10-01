"""
Layer 1 — Ingestion & Decomposition Layer (IDL).

Receives raw user input and performs structural decomposition into
semantically discrete ContentBlocks. Handles encoding normalisation,
language detection, and structural fingerprinting.
"""

from __future__ import annotations

import base64
import logging
import re
import unicodedata
import uuid
from urllib.parse import unquote

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

# Vendor-shaped credentials. These are structural patterns for well-known
# secret formats; each is anchored on a fixed prefix or header so that the
# false-positive rate on ordinary prose stays low.
_RE_VENDOR_CREDENTIALS = [
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{16}\b"),                      # AWS access key id
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),                                      # Slack tokens
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                                           # Google API key
    re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}\b"),                              # Stripe keys
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),                               # PEM private key
]

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

# Code snippets. Detection is structural, not keyword-based: bare English
# words such as "drop", "from", "let", "class" or "import" occur constantly in
# ordinary prose, so each indicator requires surrounding syntax (a definition
# header, an assignment, a statement pair, an object literal).
_RE_CODE_INDICATORS = re.compile(
    r"(?m)(?:"
    r"^[ \t]*def[ \t]+\w+[ \t]*\("
    r"|^[ \t]*class[ \t]+\w+[ \t]*[:(]"
    r"|^[ \t]*import[ \t]+[\w.]+(?:[ \t]+as[ \t]+\w+)?[ \t]*$"
    r"|^[ \t]*from[ \t]+[\w.]+[ \t]+import[ \t]+"
    r"|\bfunction[ \t]+\w*[ \t]*\("
    r"|\b(?:const|let|var)[ \t]+\w+[ \t]*="
    r"|\bSELECT\b[^;]{1,200}?\bFROM\b"
    r"|\bINSERT[ \t]+INTO\b"
    r"|\bCREATE[ \t]+(?:TABLE|INDEX|VIEW)\b"
    r"|\bDROP[ \t]+(?:TABLE|DATABASE)\b"
    r"|\bALTER[ \t]+TABLE\b"
    r"|^#!/"
    r"|\)[ \t]*=>[ \t]*[{(]"
    r"|\{[ \t]*[\"\w]+[ \t]*:[^{}\n]+\}"
    r")"
)

# Account numbers (generic numeric sequences with separators)
_RE_ACCOUNT_NUMBER = re.compile(
    r"\b(?:account|acct|a/c)[\s#:]*[\d\-]{6,}\b",
    re.IGNORECASE,
)


# Cyrillic and Greek letters that are visually confusable with Latin ones.
# (NFKC does not fold these: they are distinct scripts, not compatibility forms.)
_CONFUSABLES = {
    "\u0410": "A", "\u0412": "B", "\u0421": "C", "\u0415": "E", "\u041d": "H",
    "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T",
    "\u0425": "X", "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p",
    "\u0441": "c", "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0455": "s",
    "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0396": "Z", "\u0397": "H",
    "\u0399": "I", "\u039a": "K", "\u039c": "M", "\u039d": "N", "\u039f": "O",
    "\u03a1": "P", "\u03a4": "T", "\u03a7": "X", "\u03bf": "o", "\u03b9": "i",
}


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
            *[(rx, ContentBlockType.CREDENTIAL) for rx in _RE_VENDOR_CREDENTIALS],
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
                if any(start < e and s < end for s, e in matched_spans):
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

        Order matters: compatibility folding (NFKC) first, so that fullwidth
        and other presentation forms collapse to ASCII; then removal of
        invisible format characters; then percent-decoding and confusable
        folding. Hexadecimal, Base64, and character-spaced fragments are NOT
        substituted into the text: their decoded forms are appended after the
        original as separate "[decoded: ...]" views, so a token that merely
        looks like Base64 (for example a JWT segment) is never corrupted.
        """
        text = unicodedata.normalize("NFKC", text)

        # Remove invisible format characters (Unicode category Cf: zero-width
        # space/joiners, bidi controls, soft hyphen, BOM, word joiner, ...)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")

        text = self._decode_url_encoding(text)

        for src, dst in _CONFUSABLES.items():
            text = text.replace(src, dst)

        views = (
            self._decode_hex_fragments(text)
            + self._decode_base64_fragments(text)
            + self._collapse_spaced_runs(text)
        )
        if views:
            text = text + "\n" + "\n".join(f"[decoded: {v}]" for v in views)
        return text

    @staticmethod
    def _decode_url_encoding(text: str) -> str:
        """Decode %XX sequences as UTF-8 (a lone %XX byte is not a code point)."""
        return unquote(text, encoding="utf-8", errors="replace")

    @staticmethod
    def _decode_hex_fragments(text: str) -> list[str]:
        """Decode long even-length hexadecimal runs that decode to printable text."""
        views = []
        for match in re.finditer(r"\b(?:[0-9A-Fa-f]{2}){10,}\b", text):
            try:
                decoded = bytes.fromhex(match.group()).decode("utf-8", errors="strict")
            except ValueError:
                continue
            if len(decoded) > 4 and all(c.isprintable() or c in "\n\r" for c in decoded):
                views.append(decoded)
        return views

    @staticmethod
    def _collapse_spaced_runs(text: str) -> list[str]:
        """
        Collapse runs of 8+ single characters separated by single spaces
        ("1 2 3 - 4 5 - 6 7 8 9"). Ordinary prose never forms such runs.
        """
        pattern = re.compile(r"(?<!\S)(?:\S {1,3}){7,}\S(?!\S)")
        return [m.group().replace(" ", "") for m in pattern.finditer(text)]

    @staticmethod
    def _decode_base64_fragments(text: str) -> list[str]:
        """Decode Base64-looking fragments that yield printable UTF-8 text."""
        views = []
        for match in re.finditer(r"[A-Za-z0-9+/]{12,}={0,2}", text):
            fragment = match.group()
            if len(fragment) % 4:
                continue
            try:
                decoded: str | None = base64.b64decode(fragment).decode("utf-8", errors="strict")
            except ValueError:  # binascii.Error and UnicodeDecodeError are both ValueErrors
                decoded = None
            if decoded is not None and len(decoded) > 4 and all(
                c.isprintable() or c in "\n\r" for c in decoded
            ):
                views.append(decoded)
        return views
