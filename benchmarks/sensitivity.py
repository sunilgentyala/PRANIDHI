"""
Sensitivity analysis over the CRSE's fixed configuration.

The paper's evaluation uses one weighting (0.40, 0.35, 0.25) and one pair of
thresholds (0.30, 0.70). This script re-runs the same 400-item synthetic
corpus over a 5 x 5 grid of weightings and threshold pairs and reports how
detection quality and the disposition mix move.

Usage:
    python -m benchmarks.sensitivity     # writes sensitivity_results.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logging.getLogger("pranidhi").setLevel(logging.ERROR)

from pranidhi.crse.risk_scorer import RiskScorer
from pranidhi.models import Disposition, UserContext
from pranidhi.pipeline import PranidhiPipeline

from benchmarks.corpus import generate_corpus

RESULTS_PATH = Path(__file__).parent / "sensitivity_results.json"

WEIGHTS = [
    (0.40, 0.35, 0.25),  # reference default
    (0.50, 0.30, 0.20),
    (0.34, 0.33, 0.33),
    (0.60, 0.25, 0.15),
    (0.30, 0.30, 0.40),
]
THRESHOLDS = [
    (0.30, 0.70),  # reference default
    (0.25, 0.65),
    (0.35, 0.75),
    (0.20, 0.60),
    (0.40, 0.80),
]


def _evaluate(corpus, weights, thresholds) -> dict:
    pipe = PranidhiPipeline(policy_path="policies/default.yaml", enable_telemetry=False)
    pipe._risk_scorer = RiskScorer(weights=weights, green_threshold=thresholds[0], amber_threshold=thresholds[1])
    tp = fp = fn = 0
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for item in corpus:
        ctx = UserContext(user_id="s", role=item.role, department=item.department, target_platform=item.target_platform)
        res = pipe.scan(item.prompt, ctx)
        counts[res.disposition.value] += 1
        flagged = res.disposition != Disposition.GREEN
        risky = not item.is_benign
        tp += risky and flagged
        fp += (not risky) and flagged
        fn += risky and (not flagged)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    n = len(corpus)
    return {
        "weights": weights, "thresholds": thresholds,
        "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
        "green_pct": round(100 * counts["GREEN"] / n, 1),
        "amber_pct": round(100 * counts["AMBER"] / n, 1),
        "red_pct": round(100 * counts["RED"] / n, 1),
    }


def run(size: int = 400, seed: int = 20260721) -> dict:
    corpus = generate_corpus(size=size, seed=seed)
    grid = [_evaluate(corpus, w, t) for w in WEIGHTS for t in THRESHOLDS]
    f1s = [g["f1"] for g in grid]
    reds = [g["red_pct"] for g in grid]
    default = next(g for g in grid if g["weights"] == WEIGHTS[0] and g["thresholds"] == THRESHOLDS[0])
    return {
        "corpus_size": size, "corpus_seed": seed, "n_configurations": len(grid),
        "default": default,
        "f1_min": min(f1s), "f1_max": max(f1s),
        "red_pct_min": min(reds), "red_pct_max": max(reds),
        "grid": grid,
    }


if __name__ == "__main__":
    out = run()
    RESULTS_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"configurations: {out['n_configurations']}  F1 range: {out['f1_min']} - {out['f1_max']}  RED% range: {out['red_pct_min']} - {out['red_pct_max']}")
    print("default:", out["default"])
    for g in out["grid"]:
        print(g["weights"], g["thresholds"], "F1", g["f1"], "R", g["recall"], "P", g["precision"], "G/A/R", g["green_pct"], g["amber_pct"], g["red_pct"])
