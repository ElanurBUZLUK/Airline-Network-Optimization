"""Pure connection-feasibility calculations."""

from __future__ import annotations

from dataclasses import dataclass

from airline_optimizer.domain.time_model import add_duration

DEFAULT_MIN_CONNECTION_MINUTES = 45
DEFAULT_MAX_CONNECTION_MINUTES = 300


@dataclass(frozen=True, slots=True)
class ConnectionEvaluation:
    inbound_flight_id: str
    outbound_flight_id: str
    inbound_arrival_abs_min: int
    outbound_departure_abs_min: int
    gap_minutes: int
    feasible: bool


def evaluate_connection(
    inbound_flight_id: str,
    inbound_departure_abs_min: int,
    inbound_duration_min: int,
    outbound_flight_id: str,
    outbound_departure_abs_min: int,
    *,
    min_gap_minutes: int = DEFAULT_MIN_CONNECTION_MINUTES,
    max_gap_minutes: int = DEFAULT_MAX_CONNECTION_MINUTES,
) -> ConnectionEvaluation:
    """Evaluate a connection; gap bounds are inclusive."""
    if min_gap_minutes < 0 or max_gap_minutes < min_gap_minutes:
        raise ValueError("invalid connection gap bounds")
    if inbound_flight_id == outbound_flight_id:
        raise ValueError("a flight cannot connect to itself")
    arrival = add_duration(inbound_departure_abs_min, inbound_duration_min)
    gap = outbound_departure_abs_min - arrival
    return ConnectionEvaluation(
        inbound_flight_id=inbound_flight_id,
        outbound_flight_id=outbound_flight_id,
        inbound_arrival_abs_min=arrival,
        outbound_departure_abs_min=outbound_departure_abs_min,
        gap_minutes=gap,
        feasible=min_gap_minutes <= gap <= max_gap_minutes,
    )
