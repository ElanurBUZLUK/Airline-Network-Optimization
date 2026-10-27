"""Typed records used at the canonical data boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from airline_optimizer.domain.flights import FlightInstance


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    code: str
    severity: str
    source_file: str
    message: str
    row_number: int | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ODImportance:
    origin: str
    destination: str
    passenger_importance: float
    source_record_ids: tuple[str, ...] = ()

    @property
    def od_key(self) -> tuple[str, str]:
        return self.origin, self.destination


@dataclass(frozen=True, slots=True)
class RankingTransitionWeight:
    competitor_count: int
    initial_rank: int
    final_rank: int
    weight: float
    source_record_id: str


@dataclass(slots=True)
class DataBundle:
    flights: list[FlightInstance] = field(default_factory=list)
    od_importance: dict[tuple[str, str], ODImportance] = field(default_factory=dict)
    ranking_weights: list[RankingTransitionWeight] = field(default_factory=list)
    raw_tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    issues: list[DataQualityIssue] = field(default_factory=list)
    source_manifest: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)
