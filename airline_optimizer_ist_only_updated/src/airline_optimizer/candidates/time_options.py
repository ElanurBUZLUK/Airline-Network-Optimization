"""Candidate departure-time option generation and deterministic merging."""
from __future__ import annotations

from collections.abc import Iterable

from airline_optimizer.domain.flights import FlightInstance, TimeOption


def make_option(flight: FlightInstance, departure_abs_min: int, method: str) -> TimeOption:
    """Create a stable option ID for a flight and absolute departure minute."""
    return TimeOption(
        option_id=f"{flight.flight_id}@{departure_abs_min}",
        flight_id=flight.flight_id,
        departure_abs_min=int(departure_abs_min),
        generation_method=method,
    )


def merge_options(options: Iterable[TimeOption]) -> list[TimeOption]:
    """Deduplicate by flight and time; preserve provenance of all generation methods."""
    merged: dict[tuple[str, int], TimeOption] = {}
    methods: dict[tuple[str, int], set[str]] = {}
    for option in options:
        key = (option.flight_id, option.departure_abs_min)
        methods.setdefault(key, set()).add(option.generation_method)
        merged[key] = option
    result = []
    for key in sorted(merged):
        original = merged[key]
        result.append(TimeOption(
            option_id=original.option_id,
            flight_id=original.flight_id,
            departure_abs_min=original.departure_abs_min,
            generation_method="+".join(sorted(methods[key])),
        ))
    return result
