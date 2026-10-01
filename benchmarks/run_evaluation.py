"""
Run the PPHB-lite synthetic corpus through PRANIDHI and the
prohibition-only baseline, and write real, reproducible results.

Usage:
    python -m benchmarks.run_evaluation

Writes benchmarks/results.json and prints a Markdown summary table.
Every number here comes from actually executing src/pranidhi against
benchmarks/corpus.py: nothing is hand-entered or assumed.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from pathlib import Path

logging.getLogger("pranidhi").setLevel(logging.ERROR)

from pranidhi.pipeline import PranidhiPipeline
from pranidhi.models import UserContext, Disposition

from benchmarks.corpus import generate_corpus
from benchmarks.baseline import ProhibitionOnlyBaseline

RESULTS_PATH = Path(__file__).parent / "results.json"


def _precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def run(corpus_size: int = 400, seed: int = 20260721) -> dict:
    corpus = generate_corpus(size=corpus_size, seed=seed)
    pipeline = PranidhiPipeline(policy_path="policies/default.yaml", enable_telemetry=False)
    baseline = ProhibitionOnlyBaseline()

    pranidhi_dispositions: Counter = Counter()
    baseline_dispositions: Counter = Counter()
    strategy_counts: Counter = Counter()
    pranidhi_latencies: list[float] = []
    baseline_latencies: list[float] = []
    composite_scores: list[float] = []
    inferential_scores: list[float] = []

    # Ground-truth detection: "risky" = has_pii or has_credential or has_code or financial_leak
    tp_flag = fp_flag = fn_flag = 0  # non-GREEN vs ground-truth risky
    coached_non_green = 0
    total_non_green = 0

    for item in corpus:
        ctx = UserContext(
            user_id="synthetic",
            role=item.role,
            department=item.department,
            target_platform=item.target_platform,
        )

        result = pipeline.scan(item.prompt, ctx)
        pranidhi_dispositions[result.disposition.value] += 1
        pranidhi_latencies.append(result.processing_time_ms)

        for ann in result.risk_annotations:
            composite_scores.append(ann.risk_score.composite)
            inferential_scores.append(ann.risk_score.inferential_leakage)

        for s in result.suggestions:
            strategy_counts[s.strategy.value] += 1

        if result.disposition != Disposition.GREEN:
            total_non_green += 1
            if result.suggestions:
                coached_non_green += 1

        is_risky = not item.is_benign
        is_flagged = result.disposition != Disposition.GREEN
        if is_risky and is_flagged:
            tp_flag += 1
        elif (not is_risky) and is_flagged:
            fp_flag += 1
        elif is_risky and (not is_flagged):
            fn_flag += 1

        b_result = baseline.scan(item.prompt, ctx)
        baseline_dispositions[b_result.disposition.value] += 1
        baseline_latencies.append(b_result.processing_time_ms)

    precision, recall, f1 = _precision_recall_f1(tp_flag, fp_flag, fn_flag)

    def pct(counter: Counter, key: str, total: int) -> float:
        return round(100.0 * counter.get(key, 0) / total, 2) if total else 0.0

    total = len(corpus)
    summary = {
        "corpus_size": total,
        "corpus_seed": seed,
        "category_distribution": dict(Counter(i.category for i in corpus)),
        "pranidhi": {
            "disposition_distribution_pct": {
                k: pct(pranidhi_dispositions, k, total) for k in ("GREEN", "AMBER", "RED")
            },
            "mean_latency_ms": round(statistics.mean(pranidhi_latencies), 4),
            "p95_latency_ms": round(sorted(pranidhi_latencies)[int(0.95 * len(pranidhi_latencies)) - 1], 4),
            "coaching_coverage_pct": round(100.0 * coached_non_green / total_non_green, 2) if total_non_green else 0.0,
            "strategy_selection_distribution": dict(strategy_counts),
        },
        "prohibition_only_baseline": {
            "disposition_distribution_pct": {
                k: pct(baseline_dispositions, k, total) for k in ("GREEN", "RED")
            },
            "mean_latency_ms": round(statistics.mean(baseline_latencies), 4),
            "coaching_coverage_pct": 0.0,
        },
        "detection_quality_vs_ground_truth": {
            "note": "Ground truth is the corpus's own injected labels (has_pii/has_credential/"
                     "has_code/financial_leak vs benign), independent of the pipeline's own scoring. "
                     "Both arms share the same IDL/CRSE, so this figure is identical for PRANIDHI and "
                     "the baseline; it isolates detection quality from the coaching-vs-block decision.",
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "true_positives": tp_flag,
            "false_positives": fp_flag,
            "false_negatives": fn_flag,
        },
        "risk_score_stats": {
            "mean_composite": round(statistics.mean(composite_scores), 4) if composite_scores else 0.0,
            "mean_inferential_leakage": round(statistics.mean(inferential_scores), 4) if inferential_scores else 0.0,
        },
        "methodology": {
            "corpus": "Fully synthetic, templated, seeded (benchmarks/corpus.py). No real "
                      "enterprise data. This is a reproducibility artifact, not a live "
                      "deployment or human-subjects study.",
            "baseline": "Shares PRANIDHI's real IDL/CRSE; AMBER-equivalent risk is escalated "
                        "to a hard block since the baseline has no coaching path.",
        },
    }
    return summary


def render_markdown_table(summary: dict) -> str:
    p = summary["pranidhi"]
    b = summary["prohibition_only_baseline"]
    dq = summary["detection_quality_vs_ground_truth"]
    lines = [
        "| Metric | Prohibition-Only Baseline | PRANIDHI |",
        "|---|---|---|",
        f"| GREEN (proceed) | {b['disposition_distribution_pct'].get('GREEN', 0)}% | {p['disposition_distribution_pct'].get('GREEN', 0)}% |",
        f"| AMBER (coach) | n/a (no coaching path) | {p['disposition_distribution_pct'].get('AMBER', 0)}% |",
        f"| RED (block) | {b['disposition_distribution_pct'].get('RED', 0)}% | {p['disposition_distribution_pct'].get('RED', 0)}% |",
        f"| Coaching coverage of non-GREEN scans | 0% | {p['coaching_coverage_pct']}% |",
        f"| Mean latency (ms) | {b['mean_latency_ms']} | {p['mean_latency_ms']} |",
        f"| Detection precision (shared IDL/CRSE) | {dq['precision']} | {dq['precision']} |",
        f"| Detection recall (shared IDL/CRSE) | {dq['recall']} | {dq['recall']} |",
        f"| Detection F1 (shared IDL/CRSE) | {dq['f1']} | {dq['f1']} |",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    summary = run()
    RESULTS_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {RESULTS_PATH}")
    print()
    print(render_markdown_table(summary))
