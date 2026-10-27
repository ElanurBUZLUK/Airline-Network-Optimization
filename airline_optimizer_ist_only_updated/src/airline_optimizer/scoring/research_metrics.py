"""Non-official structural metrics for search guidance and diagnostics."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from airline_optimizer.domain.solutions import ScheduleMetrics


@dataclass(frozen=True, slots=True)
class ResearchMetrics:
    total_valid_connections: int
    markets_with_connections: int
    od_connection_counts: Mapping[tuple[str, str], int]


def from_schedule_metrics(metrics: ScheduleMetrics) -> ResearchMetrics:
    """Convert schedule counts to explicit research metrics; never label as official score."""
    return ResearchMetrics(
        total_valid_connections=metrics.connection_count,
        markets_with_connections=sum(count > 0 for count in metrics.od_connection_counts.values()),
        od_connection_counts=dict(metrics.od_connection_counts),
    )
