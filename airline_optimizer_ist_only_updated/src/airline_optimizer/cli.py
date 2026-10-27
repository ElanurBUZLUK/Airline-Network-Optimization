"""Command-line entry point for the end-to-end research pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from airline_optimizer.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Airline Optimizer research pipeline")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/latest"))
    parser.add_argument("--window-before-minutes", type=int, required=True,
                        help="Allowed candidate window before each baseline departure")
    parser.add_argument("--window-after-minutes", type=int, required=True,
                        help="Allowed candidate window after each baseline departure")
    parser.add_argument("--grid-step-minutes", type=int, default=30)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--experiment-mode",
        choices=["adaptive", "random_only", "related_only", "market_focus_only"],
        default="adaptive",
        help="Search operator experiment mode",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-flights", type=int, default=None,
                        help="Optional diagnostic cap; do not use for final experiments")
    parser.add_argument("--disallow-inferred-durations", action="store_true",
                        help="Fail rows without an explicit validated duration column")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_pipeline(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        window_before_minutes=args.window_before_minutes,
        window_after_minutes=args.window_after_minutes,
        grid_step_minutes=args.grid_step_minutes,
        iterations=args.iterations,
        experiment_mode=args.experiment_mode,
        seed=args.seed,
        max_flights=args.max_flights,
        allow_inferred_durations=not args.disallow_inferred_durations,
    )
    print(json.dumps({
        "run_status": report["run_status"],
        "loaded_flight_count": report["loaded_flight_count"],
        "candidate_option_count": report["candidate_option_count"],
        "initial_metrics": {
            "valid_ist_transfers": report["initial_metrics"]["valid_connections"],
            "od_markets_with_transfers": report["initial_metrics"]["markets_with_connections"],
        },
        "best_metrics": {
            "valid_ist_transfers": report["best_metrics"]["valid_connections"],
            "od_markets_with_transfers": report["best_metrics"]["markets_with_connections"],
        },
        "schedule_source": report["configuration"]["schedule_source"],
        "optimization_scope": report["configuration"]["optimization_scope"],
        "elapsed_seconds": report["elapsed_seconds"],
        "report_path": str(args.output_dir / "manifests" / "run_report.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
