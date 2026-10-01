"""
Adversarial-evasion benchmark for the PRANIDHI detection layer.

The main corpus (benchmarks/corpus.py) is cooperative: sensitive strings
appear in plain form. This module measures what happens when a user (or a
careless copy-paste path) transforms the same sensitive strings so that a
naive pattern matcher no longer sees them. Every secret is synthetic and
is assembled at run time from fragments, so no real-shaped credential is
ever stored in the repository source.

Usage:
    python -m benchmarks.adversarial            # writes adversarial_results.json

Transformations (T0 is the untransformed control):
    T0 plain                   T5 fullwidth Unicode forms
    T1 zero-width injection    T6 inter-character spacing
    T2 Cyrillic homoglyphs     T7 hexadecimal encoding
    T3 percent-encoding        T8 reversed string
    T4 Base64 wrapping         T9 ROT13

T8-T9 are deliberately outside the IDL's normalisation scope and are reported
as known limitations, not as failures to be hidden.
"""

from __future__ import annotations

import base64
import codecs
import json
import logging
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

logging.getLogger("pranidhi").setLevel(logging.ERROR)

from pranidhi.models import Disposition, UserContext
from pranidhi.pipeline import PranidhiPipeline

RESULTS_PATH = Path(__file__).parent / "adversarial_results.json"
CTX = UserContext(user_id="adv", role="manager", department="operations", target_platform="chatgpt")

_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_HOMOGLYPH = {"a": "\u0430", "e": "\u0435", "o": "\u043e", "p": "\u0440", "c": "\u0441", "x": "\u0445"}


def _rand(rng: random.Random, n: int, charset: str = _ALNUM) -> str:
    return "".join(rng.choice(charset) for _ in range(n))


# Synthetic secrets. Vendor-shaped prefixes are assembled from fragments so
# that no literal real-shaped token appears in source control.
def make_credentials(rng: random.Random) -> list[tuple[str, str]]:
    return [
        ("generic", "secret_synthetic_" + _rand(rng, 32)),
        ("github_pat_shape", "gh" + "p_" + _rand(rng, 36)),
        ("aws_access_key_shape", "AK" + "IA" + _rand(rng, 16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")),
        ("slack_token_shape", "xo" + "xb-" + _rand(rng, 12, "0123456789") + "-" + _rand(rng, 24)),
        ("jwt_shape", "eyJ" + _rand(rng, 20) + "." + "eyJ" + _rand(rng, 30) + "." + _rand(rng, 30)),
        ("pem_header", "-----BEGIN " + "RSA PRIVATE KEY-----\n" + _rand(rng, 64) + "\n-----END " + "RSA PRIVATE KEY-----"),
    ]


def make_pii(rng: random.Random) -> list[tuple[str, str]]:
    return [
        ("ssn", f"{rng.randint(100, 899):03d}-{rng.randint(10, 99):02d}-{rng.randint(1000, 9999):04d}"),
        ("email", f"{_rand(rng, 6, 'abcdefghijklmnopqrstuvwxyz')}.{_rand(rng, 5, 'abcdefghijklmnopqrstuvwxyz')}@example.com"),
        ("account", f"account #{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"),
    ]


def _zw(s: str, rng: random.Random) -> str:
    return "\u200b".join(s)


def _homoglyph(s: str, rng: random.Random) -> str:
    return "".join(_HOMOGLYPH.get(c, c) for c in s)


def _pct(s: str, rng: random.Random) -> str:
    return "".join(f"%{ord(c):02X}" if c.isalnum() else c for c in s)


def _b64(s: str, rng: random.Random) -> str:
    return base64.b64encode(s.encode()).decode()


def _fullwidth(s: str, rng: random.Random) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)


def _spaced(s: str, rng: random.Random) -> str:
    return " ".join(s)


def _hex(s: str, rng: random.Random) -> str:
    return s.encode().hex()


def _rev(s: str, rng: random.Random) -> str:
    return s[::-1]


def _rot13(s: str, rng: random.Random) -> str:
    return codecs.encode(s, "rot13")


TRANSFORMS = {
    "T0_plain": lambda s, r: s,
    "T1_zero_width": _zw,
    "T2_homoglyph": _homoglyph,
    "T3_percent_encoding": _pct,
    "T4_base64": _b64,
    "T5_fullwidth": _fullwidth,
    "T6_spacing": _spaced,
    "T7_hex": _hex,
    "T8_reversed": _rev,
    "T9_rot13": _rot13,
}

WRAPPERS = [
    "Can you check this for me: {x}",
    "Here is the value we use in production: {x}",
    "Please debug the failing call that uses {x} as the credential.",
]

BENIGN = [
    "Summarise the differences between symmetric and asymmetric encryption.",
    "Draft a checklist for onboarding a new vendor with a security review.",
    "Explain how rate limiting protects an internal API from abuse.",
]


@dataclass
class Cell:
    kind: str
    label: str
    transform: str
    n: int
    caught: int  # non-GREEN
    blocked: int  # RED


def run(per_cell: int = 20, seed: int = 20260930) -> dict:
    rng = random.Random(seed)
    pipe = PranidhiPipeline(policy_path="policies/default.yaml", enable_telemetry=False)
    cells: dict[tuple[str, str], list[int]] = {}
    for tname, fn in TRANSFORMS.items():
        for kind, maker in (("credential", make_credentials), ("pii", make_pii)):
            for _ in range(per_cell):
                for label, secret in maker(rng):
                    prompt = rng.choice(WRAPPERS).format(x=fn(secret, rng))
                    res = pipe.scan(prompt, CTX)
                    key = (kind, tname)
                    c = cells.setdefault(key, [0, 0, 0])
                    c[0] += 1
                    c[1] += res.disposition != Disposition.GREEN
                    c[2] += res.disposition == Disposition.RED

    # benign controls with the same transformations applied to ordinary text
    fp: dict[str, list[int]] = {}
    for tname in ("T0_plain", "T1_zero_width", "T2_homoglyph", "T5_fullwidth"):
        fn = TRANSFORMS[tname]
        for _ in range(per_cell):
            for text in BENIGN:
                res = pipe.scan(fn(text, rng), CTX)
                c = fp.setdefault(tname, [0, 0])
                c[0] += 1
                c[1] += res.disposition == Disposition.RED

    def rate(a: int, n: int) -> float:
        return round(a / n, 4) if n else 0.0

    table = {}
    for (kind, tname), (n, caught, blocked) in sorted(cells.items()):
        table.setdefault(tname, {})[kind] = {
            "n": n,
            "flag_rate": rate(caught, n),
            "block_rate": rate(blocked, n),
        }
    in_scope = [t for t in TRANSFORMS if t not in ("T8_reversed", "T9_rot13")]
    cred_flag = [table[t]["credential"]["flag_rate"] for t in in_scope]
    cred_block = [table[t]["credential"]["block_rate"] for t in in_scope]
    return {
        "seed": seed,
        "credential_items_per_transformation": per_cell * 6,
        "pii_items_per_transformation": per_cell * 3,
        "by_transformation": table,
        "benign_false_block_rate": {t: rate(v[1], v[0]) for t, v in fp.items()},
        "summary_in_scope_T0_T7": {
            "mean_credential_flag_rate": round(statistics.mean(cred_flag), 4),
            "mean_credential_block_rate": round(statistics.mean(cred_block), 4),
            "mean_pii_flag_rate": round(statistics.mean(table[t]["pii"]["flag_rate"] for t in in_scope), 4),
        },
        "note": "Synthetic secrets assembled at run time; T8-T9 are outside IDL normalisation scope by design.",
    }


if __name__ == "__main__":
    out = run()
    RESULTS_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {RESULTS_PATH}")
    print(f"{'transform':24s} {'cred flag':>9s} {'cred RED':>9s} {'pii flag':>9s}")
    for t, v in out["by_transformation"].items():
        print(f"{t:24s} {v['credential']['flag_rate']:9.2f} {v['credential']['block_rate']:9.2f} {v['pii']['flag_rate']:9.2f}")
    print("benign false-block:", out["benign_false_block_rate"])
    print("summary:", out["summary_in_scope_T0_T7"])
