"""Incrementally maintained active-schedule connection graph.

Only currently feasible edges are stored. Airport/time indexes avoid materializing
all route-compatible flight pairs, which can be millions for a large hub schedule.
"""
from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass
from collections.abc import Iterable, Mapping

from airline_optimizer.connections.compatibility import evaluate_connection
from airline_optimizer.domain.flights import FlightInstance

Pair = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ConnectionEdge:
    inbound_flight_id: str
    outbound_flight_id: str
    gap_minutes: int


class DynamicConnectionGraph:
    """Maintain feasible edges and update only route/time-affected pairs."""

    def __init__(
        self,
        flights: Iterable[FlightInstance],
        departure_by_flight: Mapping[str, int] | None = None,
        *,
        min_gap_minutes: int = 45,
        max_gap_minutes: int = 300,
    ) -> None:
        flight_list = list(flights)
        self.flights = {f.flight_id: f for f in flight_list}
        if len(self.flights) != len(flight_list):
            raise ValueError("flight_id values must be unique")
        self.departures = {f.flight_id: f.baseline_departure_abs_min for f in flight_list}
        if departure_by_flight:
            unknown = set(departure_by_flight) - set(self.flights)
            if unknown:
                raise ValueError(f"unknown flight IDs in departure map: {sorted(unknown)}")
            self.departures.update({k: int(v) for k, v in departure_by_flight.items()})
        self.min_gap_minutes = min_gap_minutes
        self.max_gap_minutes = max_gap_minutes
        if min_gap_minutes < 0 or max_gap_minutes < min_gap_minutes:
            raise ValueError("invalid connection gap bounds")

        self._inbound_by_airport: dict[str, list[tuple[int, str]]] = {}
        self._outbound_by_airport: dict[str, list[tuple[int, str]]] = {}
        for flight in flight_list:
            origin = flight.origin.strip().upper()
            destination = flight.destination.strip().upper()
            arrival = self.departures[flight.flight_id] + flight.flight_duration_min
            insort(self._inbound_by_airport.setdefault(destination, []), (arrival, flight.flight_id))
            insort(self._outbound_by_airport.setdefault(origin, []), (self.departures[flight.flight_id], flight.flight_id))

        self._edges: dict[Pair, ConnectionEdge] = {}
        self._edges_by_flight: dict[str, set[Pair]] = {fid: set() for fid in self.flights}
        self.recompute_all()

    @property
    def connection_count(self) -> int:
        """Number of active connections without materializing a sorted edge tuple."""
        return len(self._edges)

    @property
    def edges(self) -> tuple[ConnectionEdge, ...]:
        return tuple(self._edges[key] for key in sorted(self._edges))

    def incident_edges(self, flight_id: str) -> tuple[ConnectionEdge, ...]:
        """Return edges incident to one flight without scanning the whole graph."""
        if flight_id not in self.flights:
            raise KeyError(flight_id)
        return tuple(self._edges[pair] for pair in sorted(self._edges_by_flight[flight_id]))

    def neighbours(self, flight_id: str) -> set[str]:
        """Return flights connected to a given flight in either direction."""
        if flight_id not in self.flights:
            raise KeyError(flight_id)
        neighbours: set[str] = set()
        for inbound_id, outbound_id in self._edges_by_flight[flight_id]:
            neighbours.add(outbound_id if inbound_id == flight_id else inbound_id)
        return neighbours

    def degrees(self) -> dict[str, int]:
        """Return active connection degree per flight in O(number of flights)."""
        return {flight_id: len(pairs) for flight_id, pairs in self._edges_by_flight.items()}

    def preview_departure_change(
        self, flight_id: str, departure_abs_min: int
    ) -> tuple[tuple[ConnectionEdge, ...], tuple[ConnectionEdge, ...]]:
        """Return old and hypothetical incident edges without mutating graph state."""
        if flight_id not in self.flights:
            raise KeyError(flight_id)
        departure = int(departure_abs_min)
        if departure == self.departures[flight_id]:
            return (), ()
        flight = self.flights[flight_id]
        origin = flight.origin.strip().upper()
        destination = flight.destination.strip().upper()
        arrival = departure + flight.flight_duration_min
        proposed: dict[Pair, ConnectionEdge] = {}

        # Hypothetical flight as inbound.
        outbound_values = self._outbound_by_airport.get(destination, [])
        lo = bisect_left(outbound_values, (arrival + self.min_gap_minutes, ""))
        hi = bisect_left(outbound_values, (arrival + self.max_gap_minutes + 1, ""))
        for _, outbound_id in outbound_values[lo:hi]:
            if not self._route_allowed(flight_id, outbound_id):
                continue
            outbound_departure = self.departures[outbound_id]
            gap = outbound_departure - arrival
            proposed[(flight_id, outbound_id)] = ConnectionEdge(flight_id, outbound_id, gap)

        # Hypothetical flight as outbound.
        inbound_values = self._inbound_by_airport.get(origin, [])
        lo = bisect_left(inbound_values, (departure - self.max_gap_minutes, ""))
        hi = bisect_left(inbound_values, (departure - self.min_gap_minutes + 1, ""))
        for inbound_arrival, inbound_id in inbound_values[lo:hi]:
            if not self._route_allowed(inbound_id, flight_id):
                continue
            gap = departure - inbound_arrival
            proposed[(inbound_id, flight_id)] = ConnectionEdge(inbound_id, flight_id, gap)

        old = self.incident_edges(flight_id)
        return old, tuple(proposed[key] for key in sorted(proposed))

    def _route_allowed(self, inbound_id: str, outbound_id: str) -> bool:
        inbound = self.flights[inbound_id]
        outbound = self.flights[outbound_id]
        # This project optimizes transfers through Istanbul only. Matching routes at
        # outstations (including return-to-origin chains) are intentionally excluded.
        return (
            inbound_id != outbound_id
            and inbound.destination.strip().upper() == "IST"
            and outbound.origin.strip().upper() == "IST"
            and inbound.destination.strip().upper() == outbound.origin.strip().upper()
            and inbound.origin.strip().upper() != outbound.destination.strip().upper()
        )

    def _add_if_feasible(self, inbound_id: str, outbound_id: str) -> None:
        if not self._route_allowed(inbound_id, outbound_id):
            return
        result = evaluate_connection(
            inbound_id, self.departures[inbound_id], self.flights[inbound_id].flight_duration_min,
            outbound_id, self.departures[outbound_id],
            min_gap_minutes=self.min_gap_minutes, max_gap_minutes=self.max_gap_minutes,
        )
        if not result.feasible:
            return
        pair = (inbound_id, outbound_id)
        edge = ConnectionEdge(inbound_id, outbound_id, result.gap_minutes)
        self._edges[pair] = edge
        self._edges_by_flight[inbound_id].add(pair)
        self._edges_by_flight[outbound_id].add(pair)

    def _remove_pair(self, pair: Pair) -> None:
        if self._edges.pop(pair, None) is not None:
            self._edges_by_flight[pair[0]].discard(pair)
            self._edges_by_flight[pair[1]].discard(pair)

    def _remove_from_indexes(self, flight_id: str, departure: int) -> None:
        flight = self.flights[flight_id]
        arrival = departure + flight.flight_duration_min
        inbound_values = self._inbound_by_airport[flight.destination.strip().upper()]
        outbound_values = self._outbound_by_airport[flight.origin.strip().upper()]
        for values, item in ((inbound_values, (arrival, flight_id)), (outbound_values, (departure, flight_id))):
            index = bisect_left(values, item)
            if index >= len(values) or values[index] != item:
                raise AssertionError(f"time index entry missing for {flight_id}")
            values.pop(index)

    def _insert_into_indexes(self, flight_id: str, departure: int) -> None:
        flight = self.flights[flight_id]
        arrival = departure + flight.flight_duration_min
        insort(self._inbound_by_airport[flight.destination.strip().upper()], (arrival, flight_id))
        insort(self._outbound_by_airport[flight.origin.strip().upper()], (departure, flight_id))

    def _recompute_incident(self, flight_id: str) -> None:
        flight = self.flights[flight_id]
        origin = flight.origin.strip().upper()
        destination = flight.destination.strip().upper()
        departure = self.departures[flight_id]
        arrival = departure + flight.flight_duration_min

        # Changed flight as inbound: find outbound departures in the feasible window.
        outbound_values = self._outbound_by_airport.get(destination, [])
        lo = bisect_left(outbound_values, (arrival + self.min_gap_minutes, ""))
        hi = bisect_left(outbound_values, (arrival + self.max_gap_minutes + 1, ""))
        for _, outbound_id in outbound_values[lo:hi]:
            self._add_if_feasible(flight_id, outbound_id)

        # Changed flight as outbound: find inbound arrivals in the feasible window.
        inbound_values = self._inbound_by_airport.get(origin, [])
        lo = bisect_left(inbound_values, (departure - self.max_gap_minutes, ""))
        hi = bisect_left(inbound_values, (departure - self.min_gap_minutes + 1, ""))
        for _, inbound_id in inbound_values[lo:hi]:
            self._add_if_feasible(inbound_id, flight_id)

    def recompute_all(self) -> None:
        self._edges.clear()
        self._edges_by_flight = {fid: set() for fid in self.flights}
        # For each inbound flight, query only outbound flights in its time window.
        for inbound_id, inbound in self.flights.items():
            arrival = self.departures[inbound_id] + inbound.flight_duration_min
            outbound_values = self._outbound_by_airport.get(inbound.destination.strip().upper(), [])
            lo = bisect_left(outbound_values, (arrival + self.min_gap_minutes, ""))
            hi = bisect_left(outbound_values, (arrival + self.max_gap_minutes + 1, ""))
            for _, outbound_id in outbound_values[lo:hi]:
                self._add_if_feasible(inbound_id, outbound_id)

    def update_departures_with_delta(
        self, changes: Mapping[str, int]
    ) -> tuple[tuple[ConnectionEdge, ...], tuple[ConnectionEdge, ...]]:
        """Update changed flights and return only removed and added connection edges.

        Edges that remain feasible but have a different gap are not reported as
        added/removed because their OD contribution is unchanged.
        """
        unknown = set(changes) - set(self.flights)
        if unknown:
            raise ValueError(f"unknown flight IDs in changes: {sorted(unknown)}")
        changed = {fid: int(value) for fid, value in changes.items() if self.departures[fid] != int(value)}
        if not changed:
            return (), ()

        incident: set[Pair] = set()
        for fid in changed:
            incident.update(self._edges_by_flight[fid])
        old_incident_edges = {pair: self._edges[pair] for pair in incident if pair in self._edges}
        for pair in incident:
            self._remove_pair(pair)

        old_departures = {fid: self.departures[fid] for fid in changed}
        for fid, old_time in old_departures.items():
            self._remove_from_indexes(fid, old_time)
        self.departures.update(changed)
        for fid, new_time in changed.items():
            self._insert_into_indexes(fid, new_time)

        for fid in changed:
            self._recompute_incident(fid)

        affected_pairs = set(old_incident_edges)
        for fid in changed:
            affected_pairs.update(self._edges_by_flight[fid])
        removed = tuple(old_incident_edges[pair] for pair in sorted(affected_pairs)
                        if pair in old_incident_edges and pair not in self._edges)
        added = tuple(self._edges[pair] for pair in sorted(affected_pairs)
                      if pair in self._edges and pair not in old_incident_edges)
        return removed, added

    def update_departures(self, changes: Mapping[str, int]) -> tuple[ConnectionEdge, ...]:
        """Compatibility wrapper returning all currently active edges."""
        self.update_departures_with_delta(changes)
        return self.edges

    def assert_matches_full_recompute(self) -> None:
        incremental = dict(self._edges)
        self.recompute_all()
        if incremental != self._edges:
            raise AssertionError("incremental connection graph differs from full recomputation")
