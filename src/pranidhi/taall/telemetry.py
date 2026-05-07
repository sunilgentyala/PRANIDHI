"""
Layer 5 — Telemetry, Analytics & Adaptive Learning Layer (TAALL).

Captures comprehensive interaction telemetry, powers the Prompt Hygiene
Dashboard, the Adaptive Threshold Engine, and the Coaching Effectiveness
Analyser.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from pranidhi.models import ScanResult

logger = logging.getLogger(__name__)


@dataclass
class InteractionRecord:
    """Immutable telemetry record for a single scan interaction."""
    scan_id: str
    timestamp: str
    user_id: str
    department: str
    target_platform: str
    disposition: str
    risk_score: float
    num_blocks: int
    num_suggestions: int
    strategies_offered: list[str]
    processing_time_ms: float

    def to_dict(self) -> dict:
        return {
            "scan_id": self.scan_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "department": self.department,
            "target_platform": self.target_platform,
            "disposition": self.disposition,
            "risk_score": self.risk_score,
            "num_blocks": self.num_blocks,
            "num_suggestions": self.num_suggestions,
            "strategies_offered": self.strategies_offered,
            "processing_time_ms": self.processing_time_ms,
        }


@dataclass
class PromptHygieneMetrics:
    """Aggregated prompt hygiene metrics for the dashboard."""
    total_scans: int = 0
    green_count: int = 0
    amber_count: int = 0
    red_count: int = 0
    avg_risk_score: float = 0.0
    coaching_acceptance_rate: float = 0.0
    most_common_strategy: str = "N/A"
    avg_processing_time_ms: float = 0.0
    top_risk_departments: list[str] = field(default_factory=list)
    top_risk_platforms: list[str] = field(default_factory=list)


class TelemetryCollector:
    """
    Collects, stores, and analyses interaction telemetry from the
    PRANIDHI pipeline.

    Provides three analytical subsystems:
      1. Prompt Hygiene Dashboard — real-time and historical metrics
      2. Adaptive Threshold Engine — dynamic threshold refinement
      3. Coaching Effectiveness Analyser — longitudinal coaching impact

    Parameters
    ----------
    max_buffer_size : int
        Maximum number of records held in memory before flushing.
    export_path : str, optional
        File path for JSONL telemetry export.
    """

    def __init__(
        self,
        max_buffer_size: int = 10_000,
        export_path: Optional[str] = None,
    ):
        self._buffer: list[InteractionRecord] = []
        self._max_buffer = max_buffer_size
        self._export_path = export_path

        # Aggregation accumulators
        self._disposition_counts: dict[str, int] = defaultdict(int)
        self._department_risk: dict[str, list[float]] = defaultdict(list)
        self._platform_risk: dict[str, list[float]] = defaultdict(list)
        self._strategy_counts: dict[str, int] = defaultdict(int)
        self._total_risk: float = 0.0
        self._total_time: float = 0.0
        self._total_scans: int = 0

    def record(self, result: ScanResult) -> None:
        """
        Record a completed scan result as a telemetry event.

        Parameters
        ----------
        result : ScanResult
            The pipeline output to be recorded.
        """
        ctx = result.user_context
        strategies = [s.strategy.value for s in result.suggestions]

        record = InteractionRecord(
            scan_id=result.scan_id,
            timestamp=result.timestamp.isoformat(),
            user_id=ctx.user_id if ctx else "anonymous",
            department=ctx.department if ctx else "unknown",
            target_platform=ctx.target_platform if ctx else "unknown",
            disposition=result.disposition.value,
            risk_score=result.risk_score,
            num_blocks=len(result.content_blocks),
            num_suggestions=len(result.suggestions),
            strategies_offered=strategies,
            processing_time_ms=result.processing_time_ms,
        )

        self._buffer.append(record)
        self._update_aggregates(record)

        if len(self._buffer) >= self._max_buffer:
            self._flush()

        logger.debug(
            "Telemetry recorded: scan=%s, disposition=%s, risk=%.3f",
            record.scan_id[:8],
            record.disposition,
            record.risk_score,
        )

    def _update_aggregates(self, record: InteractionRecord) -> None:
        """Update running aggregate accumulators."""
        self._total_scans += 1
        self._total_risk += record.risk_score
        self._total_time += record.processing_time_ms
        self._disposition_counts[record.disposition] += 1
        self._department_risk[record.department].append(record.risk_score)
        self._platform_risk[record.target_platform].append(record.risk_score)
        for strategy in record.strategies_offered:
            self._strategy_counts[strategy] += 1

    def get_dashboard_metrics(self) -> PromptHygieneMetrics:
        """
        Compute current Prompt Hygiene Dashboard metrics.

        Returns
        -------
        PromptHygieneMetrics
            Aggregated metrics across all recorded interactions.
        """
        if self._total_scans == 0:
            return PromptHygieneMetrics()

        # Find highest-risk departments
        dept_avg = {
            dept: sum(scores) / len(scores)
            for dept, scores in self._department_risk.items()
            if scores
        }
        top_depts = sorted(dept_avg, key=lambda k: dept_avg[k], reverse=True)[:5]

        # Find highest-risk platforms
        plat_avg = {
            plat: sum(scores) / len(scores)
            for plat, scores in self._platform_risk.items()
            if scores
        }
        top_plats = sorted(plat_avg, key=lambda k: plat_avg[k], reverse=True)[:5]

        # Most frequently offered coaching strategy
        most_common = max(self._strategy_counts, key=lambda k: self._strategy_counts[k]) if self._strategy_counts else "N/A"

        return PromptHygieneMetrics(
            total_scans=self._total_scans,
            green_count=self._disposition_counts.get("GREEN", 0),
            amber_count=self._disposition_counts.get("AMBER", 0),
            red_count=self._disposition_counts.get("RED", 0),
            avg_risk_score=round(self._total_risk / self._total_scans, 4),
            most_common_strategy=most_common,
            avg_processing_time_ms=round(self._total_time / self._total_scans, 2),
            top_risk_departments=top_depts,
            top_risk_platforms=top_plats,
        )

    def get_adaptive_thresholds(self) -> dict[str, float]:
        """
        Compute suggested threshold adjustments based on observed patterns.

        The Adaptive Threshold Engine analyses false positive indicators
        (high AMBER/RED rates with low actual incidents) and false negative
        indicators (GREEN dispositions followed by manual escalations) to
        recommend threshold refinements.

        Returns
        -------
        dict
            Suggested threshold adjustments per department.
        """
        suggestions = {}
        for dept, scores in self._department_risk.items():
            if len(scores) < 10:
                continue
            avg = sum(scores) / len(scores)
            # If average risk is consistently low, suggest relaxing thresholds
            if avg < 0.2:
                suggestions[dept] = round(min(0.8, avg + 0.15), 3)
            # If average risk is consistently high, suggest tightening
            elif avg > 0.6:
                suggestions[dept] = round(max(0.3, avg - 0.1), 3)
        return suggestions

    def _flush(self) -> None:
        """Flush buffered records to persistent storage."""
        if not self._export_path:
            self._buffer.clear()
            return

        try:
            with open(self._export_path, "a") as f:
                for record in self._buffer:
                    f.write(json.dumps(record.to_dict()) + "\n")
            logger.info("Flushed %d telemetry records to %s", len(self._buffer), self._export_path)
        except OSError as exc:
            logger.error("Failed to flush telemetry: %s", exc)
        finally:
            self._buffer.clear()

    def export_all(self) -> list[dict]:
        """Export all buffered records as a list of dictionaries."""
        return [r.to_dict() for r in self._buffer]
