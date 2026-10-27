"""Independent full-schedule evaluator using airport/time range queries."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from airline_optimizer.connections.compatibility import evaluate_connection
from airline_optimizer.connections.dynamic_graph import ConnectionEdge
from airline_optimizer.domain.flights import FlightInstance

ODKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class FullScheduleEvaluation:
    edges: tuple[ConnectionEdge, ...]
    od_connection_counts: Mapping[ODKey, int]

    @property
    def connection_count(self) -> int:
        return len(self.edges)


def evaluate_schedule_fully(
    flights: Iterable[FlightInstance],
    departure_by_flight: Mapping[str, int],
    *,
    min_gap_minutes: int = 45,
    max_gap_minutes: int = 300,
) -> FullScheduleEvaluation:
    """Re-evaluate every feasible time-window pair from scratch.

    This remains independent of the incremental edge cache. Airport/time indexes
    avoid testing unrelated flight pairs on large hub schedules.
    """
    flight_list = list(flights)
    flight_map = {f.flight_id: f for f in flight_list}
    if len(flight_map) != len(flight_list):
        raise ValueError("flight_id values must be unique")
    if set(departure_by_flight) != set(flight_map):
        raise ValueError("departure_by_flight must contain exactly one time per flight")
    if min_gap_minutes < 0 or max_gap_minutes < min_gap_minutes:
        raise ValueError("invalid connection gap bounds")

    departures = {fid: int(value) for fid, value in departure_by_flight.items()}
    outbound_by_airport: dict[str, list[tuple[int, str]]] = {}
    for flight in flight_list:
        outbound_by_airport.setdefault(flight.origin.strip().upper(), []).append((departures[flight.flight_id], flight.flight_id))
    for values in outbound_by_airport.values():
        values.sort()

    edges: list[ConnectionEdge] = []
    counts: Counter[ODKey] = Counter()
    for inbound in flight_list:
        # Only inbound legs arriving at IST may start a counted connection.
        if inbound.destination.strip().upper() != "IST":
            continue
        inbound_id = inbound.flight_id
        arrival = departures[inbound_id] + inbound.flight_duration_min
        values = outbound_by_airport.get(inbound.destination.strip().upper(), [])
        lo = bisect_left(values, (arrival + min_gap_minutes, ""))
        hi = bisect_left(values, (arrival + max_gap_minutes + 1, ""))
        for _, outbound_id in values[lo:hi]:
            outbound = flight_map[outbound_id]
            if outbound.origin.strip().upper() != "IST":
                continue
            if inbound_id == outbound_id:
                continue
            if inbound.origin.strip().upper() == outbound.destination.strip().upper():
                continue
            result = evaluate_connection(
                inbound_id, departures[inbound_id], inbound.flight_duration_min,
                outbound_id, departures[outbound_id],
                min_gap_minutes=min_gap_minutes, max_gap_minutes=max_gap_minutes,
            )
            if result.feasible:
                edges.append(ConnectionEdge(inbound_id, outbound_id, result.gap_minutes))
                counts[(inbound.origin.strip().upper(), outbound.destination.strip().upper())] += 1
    return FullScheduleEvaluation(
        edges=tuple(sorted(edges, key=lambda e: (e.inbound_flight_id, e.outbound_flight_id))),
        od_connection_counts=dict(sorted(counts.items())),
    )
