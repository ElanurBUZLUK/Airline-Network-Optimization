"""Mutable schedule state used by search and incremental evaluation."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from airline_optimizer.connections.dynamic_graph import ConnectionEdge, DynamicConnectionGraph
from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.validation.full_recompute import evaluate_schedule_fully

ODKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ScheduleMetrics:
    connection_count: int
    od_connection_counts: Mapping[ODKey, int]


class ScheduleState:
    """Selected options, dynamic graph, and incrementally maintained OD counts.

    OD connection market is the inbound flight's origin to the outbound flight's
    destination through IST. This is a structural research metric, not an official score.
    """

    def __init__(
        self,
        flights: Iterable[FlightInstance],
        options_by_flight: Mapping[str, Iterable[TimeOption]],
        selected_option_by_flight: Mapping[str, str] | None = None,
        *,
        min_gap_minutes: int = 45,
        max_gap_minutes: int = 300,
    ) -> None:
        flight_list = list(flights)
        self.flights = {f.flight_id: f for f in flight_list}
        if len(self.flights) != len(flight_list):
            raise ValueError("flight_id values must be unique")
        if set(options_by_flight) != set(self.flights):
            raise ValueError("options_by_flight must contain exactly one key per flight")
        self.options: dict[str, dict[str, TimeOption]] = {}
        for flight_id, options in options_by_flight.items():
            option_map: dict[str, TimeOption] = {}
            for option in options:
                if option.flight_id != flight_id:
                    raise ValueError(f"option {option.option_id} belongs to another flight")
                if option.option_id in option_map:
                    raise ValueError(f"duplicate option_id: {option.option_id}")
                option_map[option.option_id] = option
            if not option_map:
                raise ValueError(f"flight {flight_id} has no time options")
            self.options[flight_id] = option_map

        requested = dict(selected_option_by_flight or {})
        if set(requested) - set(self.flights):
            raise ValueError("selected options contain unknown flight IDs")
        self.selected_option_by_flight: dict[str, str] = {}
        for flight_id, flight in self.flights.items():
            option_id = requested.get(flight_id)
            if option_id is None:
                matching = [o for o in self.options[flight_id].values()
                            if o.departure_abs_min == flight.baseline_departure_abs_min]
                option_id = matching[0].option_id if matching else next(iter(self.options[flight_id]))
            if option_id not in self.options[flight_id]:
                raise ValueError(f"unknown option {option_id!r} for flight {flight_id}")
            self.selected_option_by_flight[flight_id] = option_id

        departures = self._selected_departures()
        self.graph = DynamicConnectionGraph(
            flight_list, departures, min_gap_minutes=min_gap_minutes,
            max_gap_minutes=max_gap_minutes,
        )
        self.od_connection_counts: Counter[ODKey] = Counter()
        for edge in self.graph.edges:
            self.od_connection_counts[self._edge_od(edge)] += 1

    def _selected_departures(self) -> dict[str, int]:
        return {
            fid: self.options[fid][option_id].departure_abs_min
            for fid, option_id in self.selected_option_by_flight.items()
        }

    def _edge_od(self, edge: ConnectionEdge) -> ODKey:
        inbound = self.flights[edge.inbound_flight_id]
        outbound = self.flights[edge.outbound_flight_id]
        return inbound.origin.strip().upper(), outbound.destination.strip().upper()

    @property
    def metrics(self) -> ScheduleMetrics:
        return ScheduleMetrics(
            connection_count=self.graph.connection_count,
            od_connection_counts=dict(sorted(self.od_connection_counts.items())),
        )

    def preview_option_objective(self, flight_id: str, option_id: str) -> float:
        """Evaluate the research objective for one option without changing state."""
        if flight_id not in self.flights:
            raise ValueError(f"unknown flight ID: {flight_id}")
        if option_id not in self.options[flight_id]:
            raise ValueError(f"unknown option {option_id!r} for flight {flight_id}")
        departure = self.options[flight_id][option_id].departure_abs_min
        old_edges, proposed_edges = self.graph.preview_departure_change(flight_id, departure)
        if not old_edges and not proposed_edges:
            return float(self.graph.connection_count) + 0.001 * len(self.od_connection_counts)

        market_delta: Counter[ODKey] = Counter()
        for edge in old_edges:
            market_delta[self._edge_od(edge)] -= 1
        for edge in proposed_edges:
            market_delta[self._edge_od(edge)] += 1
        markets_changed = 0
        for market, delta in market_delta.items():
            before = self.od_connection_counts.get(market, 0)
            after = before + delta
            if after < 0:
                raise AssertionError(f"preview produced negative OD count for {market}")
            markets_changed += int(after > 0) - int(before > 0)
        connection_delta = len(proposed_edges) - len(old_edges)
        return (
            float(self.graph.connection_count + connection_delta)
            + 0.001 * (len(self.od_connection_counts) + markets_changed)
        )

    def apply_selection(self, changes: Mapping[str, str]) -> None:
        """Apply selections incrementally without materializing a full metrics report."""
        unknown = set(changes) - set(self.flights)
        if unknown:
            raise ValueError(f"unknown flight IDs: {sorted(unknown)}")
        # Validate the whole batch before mutating any state.
        for flight_id, option_id in changes.items():
            if option_id not in self.options[flight_id]:
                raise ValueError(f"unknown option {option_id!r} for flight {flight_id}")

        actual = {fid: oid for fid, oid in changes.items()
                  if self.selected_option_by_flight[fid] != oid}
        if not actual:
            return
        new_departures = {
            fid: self.options[fid][oid].departure_abs_min for fid, oid in actual.items()
        }
        removed_edges, added_edges = self.graph.update_departures_with_delta(new_departures)
        touched_markets: set[ODKey] = set()
        for edge in removed_edges:
            od_key = self._edge_od(edge)
            touched_markets.add(od_key)
            self.od_connection_counts[od_key] -= 1
        for edge in added_edges:
            od_key = self._edge_od(edge)
            touched_markets.add(od_key)
            self.od_connection_counts[od_key] += 1
        for od_key in touched_markets:
            count = self.od_connection_counts[od_key]
            if count < 0:
                raise AssertionError(f"negative incremental connection count for {od_key}: {count}")
            if count == 0:
                del self.od_connection_counts[od_key]
        self.selected_option_by_flight.update(actual)

    def update_selection(self, changes: Mapping[str, str]) -> ScheduleMetrics:
        """Apply changes and return a materialized metrics snapshot."""
        self.apply_selection(changes)
        return self.metrics

    def assert_matches_full_recompute(self) -> None:
        full = evaluate_schedule_fully(
            self.flights.values(), self.graph.departures,
            min_gap_minutes=self.graph.min_gap_minutes,
            max_gap_minutes=self.graph.max_gap_minutes,
        )
        if self.graph._edges != {
            (edge.inbound_flight_id, edge.outbound_flight_id): edge for edge in full.edges
        }:
            raise AssertionError("incremental edges differ from full recomputation")
        if dict(self.od_connection_counts) != dict(full.od_connection_counts):
            raise AssertionError("incremental OD counts differ from full recomputation")
