"""Coarse-grid candidate generation."""
from __future__ import annotations

from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.candidates.time_options import make_option, merge_options


def generate_grid_options(
    flight: FlightInstance,
    earliest_departure_abs_min: int,
    latest_departure_abs_min: int,
    step_minutes: int,
    *,
    include_baseline: bool = True,
) -> list[TimeOption]:
    """Generate inclusive grid options and optionally retain the baseline time.

    Bounds are explicit inputs: this function does not impose a ±15-minute window.
    The final bound is included only when it lies on the grid; baseline is added
    separately if requested and inside the window.
    """
    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    if earliest_departure_abs_min > latest_departure_abs_min:
        raise ValueError("earliest departure must not exceed latest departure")
    times = range(earliest_departure_abs_min, latest_departure_abs_min + 1, step_minutes)
    options = [make_option(flight, t, "coarse_grid") for t in times]
    if include_baseline and earliest_departure_abs_min <= flight.baseline_departure_abs_min <= latest_departure_abs_min:
        options.append(make_option(flight, flight.baseline_departure_abs_min, "baseline"))
    return merge_options(options)
