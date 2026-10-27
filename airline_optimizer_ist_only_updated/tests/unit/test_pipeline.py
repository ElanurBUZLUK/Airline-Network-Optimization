from __future__ import annotations

import csv
import json
from pathlib import Path

from airline_optimizer.pipeline import run_pipeline


def _write_baseline(path: Path) -> None:
    rows = [
        {"flight_no": "A1", "origin": "AAA", "destination": "IST", "departure_date": "2026-01-07", "departure_time": "08:00", "arrival_time": "10:00"},
        {"flight_no": "B1", "origin": "IST", "destination": "BBB", "departure_date": "2026-01-07", "departure_time": "11:30", "arrival_time": "13:30"},
        {"flight_no": "C1", "origin": "IST", "destination": "CCC", "departure_date": "2026-01-07", "departure_time": "15:00", "arrival_time": "17:00"},
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_pipeline_writes_research_only_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "raw"
    output_dir = tmp_path / "out"
    data_dir.mkdir()
    _write_baseline(data_dir / "baseline_sample.csv")

    report = run_pipeline(
        data_dir=data_dir,
        output_dir=output_dir,
        window_before_minutes=60,
        window_after_minutes=60,
        grid_step_minutes=15,
        iterations=5,
        seed=17,
    )

    assert report["run_status"] == "RESEARCH_ONLY"
    assert report["official_score_computed"] is False
    assert report["loaded_flight_count"] == 3
    assert report["candidate_option_count"] >= 2
    generation = report["candidate_generation"]
    assert generation["elapsed_seconds"] >= 0
    assert generation["grid_options_before_boundary_merge"] >= 2
    assert generation["unique_options_after_merge"] == report["candidate_option_count"]
    assert generation["options_per_flight"]["minimum"] >= 1
    assert (output_dir / "best_schedule.csv").exists()
    assert (output_dir / "best_od_metrics.csv").exists()
    assert (output_dir / "best_connections.csv").exists()
    saved = json.loads((output_dir / "manifests" / "run_report.json").read_text())
    assert saved["configuration"]["seed"] == 17
    assert saved["best_metrics"]["valid_connections"] >= 1


def test_pipeline_requires_explicit_window(tmp_path: Path) -> None:
    data_dir = tmp_path / "raw"
    data_dir.mkdir()
    _write_baseline(data_dir / "baseline_sample.csv")
    try:
        run_pipeline(
            data_dir=data_dir,
            output_dir=tmp_path / "out",
            window_before_minutes=-1,
            window_after_minutes=10,
            grid_step_minutes=5,
        )
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative candidate window should fail")
