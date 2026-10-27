from __future__ import annotations

import argparse
from pathlib import Path

from airline_optimizer.data.observed_schedule import reconstruct_observed_timetable


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruct an observed TK weekly timetable proxy for source audit only."
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-csv", type=Path, default=Path("data/canonical/observed_tk_timetable_proxy.csv"))
    parser.add_argument("--report-json", type=Path, default=Path("data/manifests/observed_timetable_audit.json"))
    args = parser.parse_args()
    report = reconstruct_observed_timetable(
        args.data_dir / "competitor_od_connections_updated.xlsx",
        args.data_dir / "flight_pairs.xlsx",
        args.output_csv,
        args.report_json,
    )
    for key in (
        "status", "source_rows_read", "tk_leg_observation_rows",
        "distinct_tk_flight_route_combinations",
        "distinct_tk_flight_route_combinations_matching_flight_pairs",
        "matching_route_coverage_fraction", "unique_flight_route_weekday_groups",
        "exported_unambiguous_groups", "conflicting_groups_excluded",
    ):
        print(f"{key}: {report[key]}")
    print("WARNING: output is a diagnostic proxy, not an authoritative W26 schedule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
