"""Connection-window boundary candidates derived from related flight times."""
from __future__ import annotations

from collections.abc import Iterable

from airline_optimizer.candidates.time_options import make_option, merge_options
from airline_optimizer.domain.flights import FlightInstance, TimeOption


def generate_connection_boundary_options(
    flight: FlightInstance,
    *,
    inbound_options: Iterable[tuple[FlightInstance, TimeOption]] = (),
    outbound_options: Iterable[tuple[FlightInstance, TimeOption]] = (),
    min_gap_minutes: int = 45,
    max_gap_minutes: int = 300,
    earliest_departure_abs_min: int | None = None,
    latest_departure_abs_min: int | None = None,
) -> list[TimeOption]:
    """Generate exact departure times that place a connection on either boundary.

    ``inbound_options`` contains (inbound flight, its option), because its
    duration is required when this flight is the outbound leg.
    For this flight as inbound: D_in = D_out - T_this - gap.
    For this flight as outbound: D_out = D_in + T_inbound + gap.
    Options outside the optional explicit window are discarded.
    """
    if min_gap_minutes < 0 or max_gap_minutes < min_gap_minutes:
        raise ValueError("invalid connection gap bounds")
    gaps = (min_gap_minutes,) if min_gap_minutes == max_gap_minutes else (min_gap_minutes, max_gap_minutes)
    # Keep only unique departure minutes while traversing partner options. A busy
    # hub can produce many partner-option pairs that collapse to the same boundary;
    # storing all intermediate TimeOption objects wastes memory without adding
    # candidate diversity.
    candidate_minutes: set[int] = set()
    for inbound_flight, inbound in inbound_options:
        if inbound.flight_id == flight.flight_id or inbound_flight.flight_id != inbound.flight_id:
            continue
        if inbound_flight.destination.strip().upper() != flight.origin.strip().upper():
            continue
        for gap in gaps:
            candidate_minutes.add(inbound.departure_abs_min + inbound_flight.flight_duration_min + gap)
    for outbound_flight, outbound in outbound_options:
        if outbound.flight_id == flight.flight_id or outbound_flight.flight_id != outbound.flight_id:
            continue
        if flight.destination.strip().upper() != outbound_flight.origin.strip().upper():
            continue
        for gap in gaps:
            candidate_minutes.add(outbound.departure_abs_min - flight.flight_duration_min - gap)
    if earliest_departure_abs_min is not None:
        candidate_minutes = {t for t in candidate_minutes if t >= earliest_departure_abs_min}
    if latest_departure_abs_min is not None:
        candidate_minutes = {t for t in candidate_minutes if t <= latest_departure_abs_min}
    return merge_options(make_option(flight, t, "connection_boundary") for t in candidate_minutes)
