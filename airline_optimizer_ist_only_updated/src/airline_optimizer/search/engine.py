"""Working LNS/ALNS search over candidate departure-time options.

The objective is explicitly a research proxy (valid connection count, with market
coverage as a small tie-breaker), not the official competition score.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from collections.abc import Iterable, Mapping

from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.domain.solutions import ScheduleState
from airline_optimizer.scoring.research_metrics import ResearchMetrics, from_schedule_metrics


@dataclass(frozen=True, slots=True)
class SearchConfig:
    iterations: int = 200
    destroy_fraction: float = 0.15
    min_destroy_flights: int = 1
    max_destroy_flights: int = 25
    initial_temperature: float = 1.0
    cooling_rate: float = 0.985
    seed: int = 42
    experiment_mode: str = "adaptive"
    adaptation_period: int = 10
    reward_best: float = 5.0
    reward_improve: float = 3.0
    reward_accept: float = 1.0

    def __post_init__(self) -> None:
        if self.experiment_mode not in {
            "adaptive", "random_only", "related_only", "market_focus_only"
        }:
            raise ValueError(
                f"Unknown experiment_mode: {self.experiment_mode}"
            )
        if self.iterations < 0:
            raise ValueError("iterations must be non-negative")
        if not 0 < self.destroy_fraction <= 1:
            raise ValueError("destroy_fraction must be in (0, 1]")
        if self.min_destroy_flights < 1:
            raise ValueError("min_destroy_flights must be positive")
        if self.max_destroy_flights < self.min_destroy_flights:
            raise ValueError("max_destroy_flights must be >= min_destroy_flights")
        if self.initial_temperature < 0 or not 0 < self.cooling_rate <= 1:
            raise ValueError("invalid simulated-annealing parameters")
        if self.adaptation_period < 1:
            raise ValueError("adaptation_period must be positive")


@dataclass(frozen=True, slots=True)
class SearchIteration:
    iteration: int
    operator: str
    current_connections: int
    candidate_connections: int
    best_connections: int
    accepted: bool
    best_improved: bool
    temperature: float


@dataclass(frozen=True, slots=True)
class SearchResult:
    initial_metrics: ResearchMetrics
    best_metrics: ResearchMetrics
    best_selection: Mapping[str, str]
    current_metrics: ResearchMetrics
    history: tuple[SearchIteration, ...]
    operator_weights: Mapping[str, float]
    seed: int


def _objective(metrics: ResearchMetrics) -> float:
    # Search guidance only: connection count dominates; market coverage breaks ties.
    return float(metrics.total_valid_connections) + 0.001 * metrics.markets_with_connections


def _objective_state(state: ScheduleState) -> float:
    # Avoid materializing/sorting the full OD report for every trial option.
    return float(state.graph.connection_count) + 0.001 * len(state.od_connection_counts)


def _state_from_selection(
    flights: list[FlightInstance],
    options: Mapping[str, list[TimeOption]],
    selection: Mapping[str, str],
    min_gap_minutes: int = 45,
    max_gap_minutes: int = 300,
) -> ScheduleState:
    return ScheduleState(
        flights, options, selection,
        min_gap_minutes=min_gap_minutes, max_gap_minutes=max_gap_minutes,
    )


def _choose_weighted(rng: random.Random, weights: Mapping[str, float]) -> str:
    total = sum(max(0.01, value) for value in weights.values())
    point = rng.random() * total
    for name, weight in weights.items():
        point -= max(0.01, weight)
        if point <= 0:
            return name
    return next(iter(weights))


def _destroy_random(state: ScheduleState, count: int, rng: random.Random) -> list[str]:
    return rng.sample(sorted(state.flights), min(count, len(state.flights)))


def _destroy_related(state: ScheduleState, count: int, rng: random.Random) -> list[str]:
    ids = sorted(state.flights)
    seed = rng.choice(ids)
    chosen = [seed]
    frontier = state.graph.neighbours(seed)
    while len(chosen) < min(count, len(ids)):
        candidates = sorted(frontier - set(chosen))
        if candidates:
            nxt = rng.choice(candidates)
        else:
            remaining = sorted(set(ids) - set(chosen))
            if not remaining:
                break
            nxt = rng.choice(remaining)
        chosen.append(nxt)
        frontier.update(state.graph.neighbours(nxt))
    return chosen


def _destroy_market_focus(state: ScheduleState, count: int, rng: random.Random) -> list[str]:
    # Bias toward flights that participate in few currently feasible connections.
    degree = state.graph.degrees()
    ordered = sorted(degree, key=lambda fid: (degree[fid], rng.random()))
    return ordered[:min(count, len(ordered))]


_OPERATORS = ("random", "related", "market_focus")


def run_search(
    flights: Iterable[FlightInstance],
    options_by_flight: Mapping[str, Iterable[TimeOption]],
    *,
    initial_selection: Mapping[str, str] | None = None,
    config: SearchConfig | None = None,
    min_gap_minutes: int = 45,
    max_gap_minutes: int = 300,
) -> SearchResult:
    """Run a reproducible ALNS-style destroy/greedy-repair search.

    The repair optimizes one destroyed flight at a time against the current full
    schedule. Candidate acceptance is separate from operator adaptation.
    """
    cfg = config or SearchConfig()
    rng = random.Random(cfg.seed)
    flight_list = list(flights)
    option_map = {fid: list(opts) for fid, opts in options_by_flight.items()}
    current = ScheduleState(
        flight_list, option_map, initial_selection,
        min_gap_minutes=min_gap_minutes, max_gap_minutes=max_gap_minutes,
    )
    initial_metrics = from_schedule_metrics(current.metrics)
    best_selection = dict(current.selected_option_by_flight)
    current_value = _objective_state(current)
    best_value = current_value
    best_connection_count = initial_metrics.total_valid_connections
    weights = {name: 1.0 for name in _OPERATORS}
    reward_sum = {name: 0.0 for name in _OPERATORS}
    use_count = {name: 0 for name in _OPERATORS}
    history: list[SearchIteration] = []
    temperature = cfg.initial_temperature

    destroyers = {
        "random": _destroy_random,
        "related": _destroy_related,
        "market_focus": _destroy_market_focus,
    }

    for iteration in range(1, cfg.iterations + 1):
        count = min(
            cfg.max_destroy_flights,
            max(cfg.min_destroy_flights, math.ceil(len(flight_list) * cfg.destroy_fraction)),
        )
        if cfg.experiment_mode == "random_only":
            operator = "random"
        elif cfg.experiment_mode == "related_only":
            operator = "related"
        elif cfg.experiment_mode == "market_focus_only":
            operator = "market_focus"
        else:
            operator = _choose_weighted(rng, weights)
        removed = destroyers[operator](current, count, rng)
        base_selection = dict(current.selected_option_by_flight)
        candidate_selection = dict(base_selection)

        # Incremental greedy repair: mutate the existing state for each trial,
        # then roll back to the current partial candidate. This avoids rebuilding
        # the entire graph and all OD counts for every option tested.
        for fid in removed:
            rollback_option = candidate_selection[fid]
            best_option = rollback_option
            best_local_value = float("-inf")
            option_candidates = list(option_map[fid])
            rng.shuffle(option_candidates)
            for option in option_candidates:
                value = current.preview_option_objective(fid, option.option_id)
                if value > best_local_value + 1e-12:
                    best_local_value = value
                    best_option = option.option_id
            candidate_selection[fid] = best_option
            if current.selected_option_by_flight[fid] != best_option:
                current.apply_selection({fid: best_option})

        candidate_metrics = from_schedule_metrics(current.metrics)
        candidate_value = _objective(candidate_metrics)
        old_value = current_value
        improved_best = candidate_value > best_value + 1e-12
        accepted = candidate_value >= current_value - 1e-12
        if not accepted and temperature > 0:
            probability = math.exp(max(-700.0, (candidate_value - current_value) / temperature))
            accepted = rng.random() < probability
        reward = 0.0
        if accepted:
            current_value = candidate_value
            reward = cfg.reward_accept
            if candidate_value > old_value + 1e-12:
                reward = cfg.reward_improve
        else:
            # Rejected candidate: restore the exact prior selected options.
            rollback = {
                fid: option_id for fid, option_id in base_selection.items()
                if current.selected_option_by_flight[fid] != option_id
            }
            if rollback:
                current.apply_selection(rollback)

        if improved_best:
            best_selection = dict(candidate_selection)
            best_value = candidate_value
            best_connection_count = candidate_metrics.total_valid_connections
            reward = cfg.reward_best
        reward_sum[operator] += reward
        use_count[operator] += 1
        history.append(SearchIteration(
            iteration=iteration,
            operator=operator,
            current_connections=current.metrics.connection_count,
            candidate_connections=candidate_metrics.total_valid_connections,
            best_connections=best_connection_count,
            accepted=accepted,
            best_improved=improved_best,
            temperature=temperature,
        ))
        temperature *= cfg.cooling_rate

        if (
            cfg.experiment_mode == "adaptive"
            and iteration % cfg.adaptation_period == 0
        ):
            for name in _OPERATORS:
                if use_count[name]:
                    average_reward = reward_sum[name] / use_count[name]
                    weights[name] = max(0.05, 0.8 * weights[name] + 0.2 * (1.0 + average_reward))
                reward_sum[name] = 0.0
                use_count[name] = 0

    # The reported best solution is always checked against a fresh full recomputation.
    best = _state_from_selection(flight_list, option_map, best_selection, min_gap_minutes, max_gap_minutes)
    best.assert_matches_full_recompute()
    current.assert_matches_full_recompute()
    return SearchResult(
        initial_metrics=initial_metrics,
        best_metrics=from_schedule_metrics(best.metrics),
        best_selection=dict(best_selection),
        current_metrics=from_schedule_metrics(current.metrics),
        history=tuple(history),
        operator_weights=dict(weights),
        seed=cfg.seed,
    )
