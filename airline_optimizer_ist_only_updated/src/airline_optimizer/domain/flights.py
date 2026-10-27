"""Canonical flight and candidate time-option domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class FlightInstance:
    flight_id: str
    flight_number: str
    flight_date: date
    origin: str
    destination: str
    baseline_departure_abs_min: int
    flight_duration_min: int
    source_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.flight_id.strip():
            raise ValueError("flight_id must not be empty")
        if not self.flight_number.strip():
            raise ValueError("flight_number must not be empty")
        if not self.origin.strip() or not self.destination.strip():
            raise ValueError("origin and destination must not be empty")
        if self.origin.strip().upper() == self.destination.strip().upper():
            raise ValueError("origin and destination must differ")
        if self.flight_duration_min <= 0:
            raise ValueError("flight_duration_min must be positive")


@dataclass(frozen=True, slots=True)
class TimeOption:
    option_id: str
    flight_id: str
    departure_abs_min: int
    generation_method: str

    def __post_init__(self) -> None:
        if not self.option_id.strip() or not self.flight_id.strip():
            raise ValueError("option_id and flight_id must not be empty")
        if not self.generation_method.strip():
            raise ValueError("generation_method must not be empty")
