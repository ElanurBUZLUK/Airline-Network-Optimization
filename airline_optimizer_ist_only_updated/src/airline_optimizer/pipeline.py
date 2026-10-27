"""End-to-end research pipeline for source loading, candidate generation and ALNS.

This pipeline deliberately reports research metrics only. It is not an official
competition scorer, and inferred flight durations must be independently validated.
"""
from __future__ import annotations

import csv
import hashlib
from bisect import bisect_left, bisect_right
import json
import time
from itertools import chain
from statistics import median
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from airline_optimizer.candidates.boundary_generator import generate_connection_boundary_options
from airline_optimizer.candidates.grid_generator import generate_grid_options
from airline_optimizer.candidates.time_options import merge_options
from airline_optimizer.data.loaders import (
    load_baseline_flights,
    load_flight_pairs_metadata,
    load_od_importance,
    load_ranking_weights,
    read_table,
    write_quality_report,
)
from airline_optimizer.data.schemas import DataBundle
from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.data.observed_schedule import reconstruct_observed_timetable
from airline_optimizer.domain.time_model import from_absolute_minutes, to_absolute_minutes
from airline_optimizer.validation.full_recompute import evaluate_schedule_fully
from airline_optimizer.search.engine import SearchConfig, run_search


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_pipeline(
    *,
    data_dir: str | Path,
    output_dir: str | Path,
    window_before_minutes: int,
    window_after_minutes: int,
    grid_step_minutes: int,
    iterations: int = 100,
    experiment_mode: str = "adaptive",
    seed: int = 42,
    max_flights: int | None = None,
    allow_inferred_durations: bool = True,
) -> dict[str, Any]:
    """Run a reproducible research pipeline on the explicitly supplied data.

    The candidate window is explicit; no hidden +/-15-minute restriction is used.
    """
    if window_before_minutes < 0 or window_after_minutes < 0:
        raise ValueError("candidate window sizes must be non-negative")
    if grid_step_minutes <= 0:
        raise ValueError("grid_step_minutes must be positive")
    started_at_utc = datetime.now(timezone.utc).isoformat()
    data_root, output_root = Path(data_dir), Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_dir = output_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    bundle = DataBundle()
    baseline_path = data_root / "baseline_sample.csv"
    if not baseline_path.exists():
        raise FileNotFoundError(
            f"{baseline_path} not found. Required source files include flight_pairs.xlsx "
            "and competitor_od_connections_updated.xlsx."
        )

    # A two-row sample is not a usable schedule. In that case, build an explicitly
    # labelled weekly IST-leg proxy from the supplied itinerary observations. This
    # makes the optimizer runnable while preserving the non-authoritative status.
    _, baseline_rows = read_table(baseline_path)
    using_observed_proxy = len(baseline_rows) <= 2
    schedule_source = "baseline_sample.csv"
    if using_observed_proxy:
        connections_path = data_root / "competitor_od_connections_updated.xlsx"
        pairs_path = data_root / "flight_pairs.xlsx"
        if not connections_path.exists() or not pairs_path.exists():
            raise FileNotFoundError(
                "baseline_sample.csv contains only a tiny sample; proxy fallback requires "
                "competitor_od_connections_updated.xlsx and flight_pairs.xlsx"
            )
        proxy_path = data_root.parent / "canonical" / "observed_tk_timetable_proxy.csv"
        audit_path = data_root.parent / "manifests" / "observed_timetable_audit.json"
        reconstruct_observed_timetable(connections_path, pairs_path, proxy_path, audit_path)
        import csv as _csv
        from datetime import datetime as _datetime
        with proxy_path.open("r", encoding="utf-8-sig", newline="") as stream:
            proxy_rows = list(_csv.DictReader(stream))
        # Weekday 1 is Sunday in the source workbook. Map source days to a synthetic
        # Monday-start week solely for time arithmetic; this is not a dated W26 baseline.
        synthetic_monday = date(2026, 1, 5)
        for index, row in enumerate(proxy_rows, start=2):
            origin = str(row.get("origin", "")).strip().upper()
            destination = str(row.get("destination", "")).strip().upper()
            if row.get("pair_file_route_match", "").lower() != "true":
                continue
            if origin != "IST" and destination != "IST":
                continue
            try:
                operating_day = int(row["operating_day"])
                flight_day = synthetic_monday + timedelta(days=(operating_day + 5) % 7)
                dep_clock = datetime.strptime(row["departure_time_local_observed"], "%H:%M").time()
                duration = int(row["duration_minutes_observed"])
                number = str(row["flight_no"]).strip()
                dep_abs = to_absolute_minutes(flight_day, dep_clock)
                if duration <= 0:
                    raise ValueError("non-positive observed duration")
                flight_id = f"{flight_day.isoformat()}:{number}:{origin}-{destination}"
                bundle.flights.append(FlightInstance(
                    flight_id, number, flight_day, origin, destination, dep_abs, duration,
                    (f"{proxy_path.name}:{index}",),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                from airline_optimizer.data.schemas import DataQualityIssue
                bundle.issues.append(DataQualityIssue(
                    "invalid_observed_proxy_row", "warning", proxy_path.name, str(exc), index
                ))
        schedule_source = "observed_tk_timetable_proxy.csv (non-authoritative; reconstructed from competitor observations)"
        from airline_optimizer.data.schemas import DataQualityIssue
        bundle.issues.append(DataQualityIssue(
            "non_authoritative_schedule_proxy", "warning", proxy_path.name,
            "Schedule is reconstructed from August 2025 competitor itinerary observations and mapped to a synthetic week; not an authoritative W26 baseline."
        ))
    else:
        load_baseline_flights(
            baseline_path, bundle, allow_duration_inference=allow_inferred_durations
        )

    optional_loaders = [
        ("passenger_od_importance.xlsx", load_od_importance),
        ("ranking_transition_weights.xlsx", load_ranking_weights),
        ("flight_pairs.xlsx", load_flight_pairs_metadata),
    ]
    for filename, loader in optional_loaders:
        path = data_root / filename
        if path.exists():
            loader(path, bundle)

    # Restrict the optimization variables to legs that touch IST; graph validation
    # additionally enforces that each counted connection is inbound-to-IST -> out of IST.
    bundle.flights = [f for f in bundle.flights if f.origin == "IST" or f.destination == "IST"]

    if max_flights is not None:
        if max_flights < 1:
            raise ValueError("max_flights must be positive when supplied")
        bundle.flights = sorted(bundle.flights, key=lambda f: (f.flight_date, f.baseline_departure_abs_min, f.flight_id))[:max_flights]

    if not bundle.flights:
        raise ValueError("no valid flights were loaded from baseline source")

    candidate_generation_started = time.perf_counter()
    options_by_flight: dict[str, list[TimeOption]] = {}
    grid_option_count = 0
    boundary_option_count = 0
    for flight in bundle.flights:
        earliest = flight.baseline_departure_abs_min - window_before_minutes
        latest = flight.baseline_departure_abs_min + window_after_minutes
        options = generate_grid_options(
            flight, earliest, latest, grid_step_minutes, include_baseline=True
        )
        options_by_flight[flight.flight_id] = options
        grid_option_count += len(options)

    # Build airport indexes once. The previous implementation scanned every
    # flight for every flight (quadratic in schedule size), despite only flights
    # sharing a connecting airport being relevant.
    # Index partner *options* by airport and absolute departure minute. The
    # time-sorted indexes let us binary-search the narrow interval that can
    # create a boundary, rather than visiting every option at a busy airport.
    by_origin: dict[str, list[tuple[int, Any, TimeOption]]] = {}
    by_destination: dict[str, list[tuple[int, Any, TimeOption]]] = {}
    max_inbound_duration_by_airport: dict[str, int] = {}
    for other in bundle.flights:
        origin = other.origin.strip().upper()
        destination = other.destination.strip().upper()
        for option in options_by_flight[other.flight_id]:
            if origin == "IST":
                by_origin.setdefault(origin, []).append((option.departure_abs_min, other, option))
            if destination == "IST":
                by_destination.setdefault(destination, []).append((option.departure_abs_min, other, option))
        if destination == "IST":
            max_inbound_duration_by_airport[destination] = max(
                max_inbound_duration_by_airport.get(destination, 0), other.flight_duration_min
            )
    by_origin_times: dict[str, list[int]] = {}
    by_destination_times: dict[str, list[int]] = {}
    for airport, index in by_origin.items():
        index.sort(key=lambda item: item[0])
        by_origin_times[airport] = [item[0] for item in index]
    for airport, index in by_destination.items():
        index.sort(key=lambda item: item[0])
        by_destination_times[airport] = [item[0] for item in index]

    # Add exact connection-window boundaries from every currently available coarse
    # option of each route-compatible flight, not just its baseline time. This lets
    # the candidate pool represent interactions between shifts on both legs. Airport
    # indexes keep this focused on plausible connection partners rather than all
    # flight pairs. These are candidate seeds, not an optimality claim.
    for flight in bundle.flights:
        # Lazy iterators avoid allocating two large intermediate lists per flight.
        # Boundary generation deduplicates resulting minutes as it goes.
        earliest = flight.baseline_departure_abs_min - window_before_minutes
        latest = flight.baseline_departure_abs_min + window_after_minutes
        # Only partner options whose boundary can land inside this flight's
        # allowed window can contribute. Filtering before boundary construction
        # avoids iterating over unrelated dates/times at the same airport.
        inbound_airport = flight.origin.strip().upper()
        inbound_index = by_destination.get("IST", ()) if inbound_airport == "IST" else ()
        inbound_times = by_destination_times.get("IST", ()) if inbound_airport == "IST" else ()
        inbound_lo = earliest - max_inbound_duration_by_airport.get(flight.origin.strip().upper(), 0) - 300
        inbound_hi = latest - 45
        inbound_start = bisect_left(inbound_times, inbound_lo)
        inbound_end = bisect_right(inbound_times, inbound_hi)
        inbound_options = (
            (other, option)
            for departure, other, option in inbound_index[inbound_start:inbound_end]
            if other.flight_id != flight.flight_id
            and earliest - other.flight_duration_min - 300 <= departure
            <= latest - other.flight_duration_min - 45
        )
        outbound_airport = flight.destination.strip().upper()
        outbound_index = by_origin.get("IST", ()) if outbound_airport == "IST" else ()
        outbound_times = by_origin_times.get("IST", ()) if outbound_airport == "IST" else ()
        outbound_lo = earliest + flight.flight_duration_min + 45
        outbound_hi = latest + flight.flight_duration_min + 300
        outbound_start = bisect_left(outbound_times, outbound_lo)
        outbound_end = bisect_right(outbound_times, outbound_hi)
        outbound_options = (
            (other, option)
            for departure, other, option in outbound_index[outbound_start:outbound_end]
            if other.flight_id != flight.flight_id
        )
        boundary = generate_connection_boundary_options(
            flight,
            inbound_options=inbound_options,
            outbound_options=outbound_options,
            min_gap_minutes=45,
            max_gap_minutes=300,
            earliest_departure_abs_min=flight.baseline_departure_abs_min - window_before_minutes,
            latest_departure_abs_min=flight.baseline_departure_abs_min + window_after_minutes,
        )
        boundary_option_count += len(boundary)
        options_by_flight[flight.flight_id] = merge_options(
            chain(options_by_flight[flight.flight_id], boundary)
        )

    candidate_generation_elapsed = time.perf_counter() - candidate_generation_started
    option_counts = [len(options) for options in options_by_flight.values()]
    config = SearchConfig(
        iterations=iterations,
        seed=seed,
        experiment_mode=experiment_mode,
    )
    start = time.perf_counter()
    result = run_search(
        bundle.flights, options_by_flight, config=config,
        min_gap_minutes=45, max_gap_minutes=300,
    )
    elapsed = time.perf_counter() - start

    # Reconstruct the selected departure table and write a human-readable CSV.
    selected_rows: list[dict[str, Any]] = []
    for flight in bundle.flights:
        option_id = result.best_selection[flight.flight_id]
        option = next(o for o in options_by_flight[flight.flight_id] if o.option_id == option_id)
        selected_rows.append({
            "flight_id": flight.flight_id,
            "flight_no": flight.flight_number,
            "flight_date": flight.flight_date.isoformat(),
            "origin": flight.origin,
            "destination": flight.destination,
            "baseline_departure_abs_min": flight.baseline_departure_abs_min,
            "selected_departure_abs_min": option.departure_abs_min,
            "departure_shift_minutes": option.departure_abs_min - flight.baseline_departure_abs_min,
            "flight_duration_minutes": flight.flight_duration_min,
            "duration_validation": (
                "OBSERVED_PROXY_DURATION_NOT_INDEPENDENTLY_VALIDATED" if using_observed_proxy else
                ("INFERRED_FROM_BASELINE_CLOCKS" if any(
                    issue.code == "duration_inferred" and issue.row_number is not None
                    for issue in bundle.issues
                ) else "SOURCE_DURATION")
            ),
            "selected_option_id": option_id,
            "generation_method": option.generation_method,
        })
    _write_csv(output_root / "best_schedule.csv", selected_rows, list(selected_rows[0].keys()))

    od_rows = [
        {"origin": origin, "destination": destination, "valid_connections": count}
        for (origin, destination), count in sorted(result.best_metrics.od_connection_counts.items())
    ]
    _write_csv(output_root / "best_od_metrics.csv", od_rows, ["origin", "destination", "valid_connections"])

    # Emit the actual best IST transfer pairs, independently recomputed from scratch.
    best_departures = {
        flight.flight_id: next(
            option.departure_abs_min for option in options_by_flight[flight.flight_id]
            if option.option_id == result.best_selection[flight.flight_id]
        )
        for flight in bundle.flights
    }
    full_best = evaluate_schedule_fully(
        bundle.flights, best_departures, min_gap_minutes=45, max_gap_minutes=300
    )
    flight_by_id = {flight.flight_id: flight for flight in bundle.flights}
    connection_rows = []
    for edge in full_best.edges:
        inbound = flight_by_id[edge.inbound_flight_id]
        outbound = flight_by_id[edge.outbound_flight_id]
        inbound_departure = from_absolute_minutes(best_departures[inbound.flight_id])
        inbound_arrival = from_absolute_minutes(best_departures[inbound.flight_id] + inbound.flight_duration_min)
        outbound_departure = from_absolute_minutes(best_departures[outbound.flight_id])
        connection_rows.append({
            "inbound_flight_no": inbound.flight_number,
            "inbound_origin": inbound.origin,
            "inbound_departure": inbound_departure.isoformat(sep=" ", timespec="minutes"),
            "ist_arrival": inbound_arrival.isoformat(sep=" ", timespec="minutes"),
            "outbound_flight_no": outbound.flight_number,
            "outbound_destination": outbound.destination,
            "outbound_departure": outbound_departure.isoformat(sep=" ", timespec="minutes"),
            "transfer_minutes": edge.gap_minutes,
            "od_origin": inbound.origin,
            "od_destination": outbound.destination,
        })
    connection_fields = [
        "inbound_flight_no", "inbound_origin", "inbound_departure", "ist_arrival",
        "outbound_flight_no", "outbound_destination", "outbound_departure",
        "transfer_minutes", "od_origin", "od_destination",
    ]
    _write_csv(output_root / "best_connections.csv", connection_rows, connection_fields)
    if full_best.connection_count != result.best_metrics.total_valid_connections:
        raise AssertionError("best-schedule IST transfer count differs from independent recomputation")

    write_quality_report(bundle, manifest_dir / "data_quality.json")
    input_fingerprints = {
        str(path.name): _sha256(path)
        for path in sorted(data_root.iterdir()) if path.is_file()
    }
    # Explicitly distinguish flight-pair metadata and competitor journey observations
    # from a dated, timed operating schedule. Neither can substitute for the latter.
    pair_rows = bundle.raw_tables.get("flight_pairs_metadata", [])
    baseline_keys = {
        (str(f.flight_number).strip().lstrip("0"), f.origin, f.destination)
        for f in bundle.flights
    }
    pair_keys = {
        (str(row.get("FlNo", "")).strip().lstrip("0"),
         str(row.get("Orig", "")).strip().upper(),
         str(row.get("Dest", "")).strip().upper())
        for row in pair_rows
    }
    matched_pair_keys = baseline_keys & pair_keys
    source_readiness = {
        "optimization_scope": "IST inbound-to-outbound transfers only",
        "baseline_schedule": {
            "file": schedule_source,
            "flight_rows_loaded": len(bundle.flights),
            "sufficient_for_full_schedule_optimization": len(bundle.flights) > 2 and not using_observed_proxy,
            "using_non_authoritative_proxy": using_observed_proxy,
            "note": "Observed itinerary legs mapped to a synthetic week; suitable for research smoke tests only, not official baseline scoring." if using_observed_proxy else "Baseline row count exceeds sample threshold; completeness still requires source-owner confirmation.",
        },
        "flight_pairs_metadata": {
            "file_present": (data_root / "flight_pairs.xlsx").exists(),
            "metadata_rows": len(pair_rows),
            "baseline_flight_keys_matched": len(matched_pair_keys),
            "note": "Pair metadata has no dated departure/arrival schedule and cannot be converted into schedule flights without a separate time source.",
        },
        "competitor_journey_observations": {
            "file_present": (data_root / "competitor_od_connections_updated.xlsx").exists(),
            "role": "source for an explicitly non-authoritative observed timetable proxy when no full dated schedule is supplied",
        },
        "full_schedule_ready": len(bundle.flights) > 2 and bool(matched_pair_keys) and not using_observed_proxy,
    }
    (manifest_dir / "source_readiness.json").write_text(
        json.dumps(source_readiness, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = {
        "run_status": "RESEARCH_ONLY",
        "official_score_computed": False,
        "started_at_utc": started_at_utc,
        "data_dir": str(data_root.resolve()),
        "output_dir": str(output_root.resolve()),
        "input_sha256": input_fingerprints,
        "configuration": {
            "window_before_minutes": window_before_minutes,
            "window_after_minutes": window_after_minutes,
            "grid_step_minutes": grid_step_minutes,
            "iterations": iterations,
            "seed": seed,
            "min_connection_minutes": 45,
            "max_connection_minutes": 300,
            "max_flights": max_flights,
            "hub_airport": "IST",
            "optimization_scope": "IST inbound-to-outbound transfers only",
            "schedule_source": schedule_source,
        },
        "loaded_flight_count": len(bundle.flights),
        "candidate_option_count": sum(option_counts),
        "candidate_generation": {
            "elapsed_seconds": round(candidate_generation_elapsed, 6),
            "grid_options_before_boundary_merge": grid_option_count,
            "boundary_options_before_deduplication": boundary_option_count,
            "unique_options_after_merge": sum(option_counts),
            "options_per_flight": {
                "minimum": min(option_counts),
                "median": median(option_counts),
                "maximum": max(option_counts),
            },
        },
        "initial_metrics": {
            "valid_connections": result.initial_metrics.total_valid_connections,
            "markets_with_connections": result.initial_metrics.markets_with_connections,
            "od_connection_counts": {f"{o}-{d}": c for (o, d), c in result.initial_metrics.od_connection_counts.items()},
        },
        "best_metrics": {
            "valid_connections": result.best_metrics.total_valid_connections,
            "markets_with_connections": result.best_metrics.markets_with_connections,
            "od_connection_counts": {f"{o}-{d}": c for (o, d), c in result.best_metrics.od_connection_counts.items()},
        },
        "search_iterations_completed": len(result.history),
        "elapsed_seconds": round(elapsed, 6),
        "operator_weights": dict(result.operator_weights),
        "source_readiness": source_readiness,
        "data_quality": {
            "error_count": sum(i.severity == "error" for i in bundle.issues),
            "warning_count": sum(i.severity == "warning" for i in bundle.issues),
            "duration_inferred": any(i.code == "duration_inferred" for i in bundle.issues),
        },
        "limitations": [
            "Only IST inbound-to-outbound transfers are counted; connections at other airports are excluded.",
            "Search objective is a research proxy: valid IST transfer count with OD market coverage as tie-breaker; official competition score is not calculated.",
            "Observed proxy durations and times are reconstructed from August 2025 competitor itinerary observations and have not been independently validated.",
            "The observed timetable proxy is mapped to a synthetic week and is not an authoritative W26 schedule.",
        ],
    }
    (manifest_dir / "run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report
