import csv
import json
from datetime import date

from airline_optimizer.data import (
    DataBundle,
    load_baseline_flights,
    load_od_importance,
    load_ranking_weights,
    write_quality_report,
)


def write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def test_baseline_csv_becomes_canonical_flight_and_records_inferred_duration(tmp_path):
    source = tmp_path / "baseline.csv"
    write_csv(source,
        ["flight_no", "origin", "destination", "departure_date", "departure_time", "arrival_time"],
        [["1306", " agp ", "IST", "2026-01-07", "23:10", "01:40"]],
    )
    bundle = load_baseline_flights(source)
    assert len(bundle.flights) == 1
    flight = bundle.flights[0]
    assert flight.flight_date == date(2026, 1, 7)
    assert (flight.origin, flight.destination) == ("AGP", "IST")
    assert flight.flight_duration_min == 150
    assert any(i.code == "duration_inferred" and i.severity == "warning" for i in bundle.issues)
    assert source.resolve().as_posix() in bundle.source_manifest


def test_conflicting_od_importance_values_are_not_last_row_wins(tmp_path):
    source = tmp_path / "importance.csv"
    write_csv(source, ["Orig Airport Code", "Dest Airport Code", "OD importance factor"],
              [["IST", "LHR", 10], [" ist ", "lhr", 11]])
    bundle = load_od_importance(source)
    assert ("IST", "LHR") not in bundle.od_importance
    assert bundle.has_errors
    assert any(i.code == "conflicting_od_importance" for i in bundle.issues)


def test_identical_duplicate_od_importance_is_reported_and_collapsed(tmp_path):
    source = tmp_path / "importance.csv"
    write_csv(source, ["Orig Airport Code", "Dest Airport Code", "OD importance factor"],
              [["IST", "LHR", 10], ["IST", "LHR", 10]])
    bundle = load_od_importance(source)
    assert bundle.od_importance[("IST", "LHR")].passenger_importance == 10
    assert any(i.code == "duplicate_od_importance" for i in bundle.issues)


def test_ranking_weight_duplicate_conflict_is_reported(tmp_path):
    source = tmp_path / "weights.csv"
    write_csv(source, ["Rakip Sayısı", "İlk Rank", "Son Rank", "Weight"],
              [[4, 1, 2, 7], [4, 1, 2, 8]])
    bundle = load_ranking_weights(source)
    assert len(bundle.ranking_weights) == 1
    assert any(i.code == "conflicting_ranking_weight" for i in bundle.issues)


def test_quality_report_contains_fingerprints_and_issues(tmp_path):
    source = tmp_path / "baseline.csv"
    write_csv(source,
        ["flight_no", "origin", "destination", "departure_date", "departure_time", "arrival_time"],
        [["1306", "AGP", "IST", "2026-01-07", "08:00", "12:30"]],
    )
    bundle = load_baseline_flights(source)
    target = write_quality_report(bundle, tmp_path / "manifests" / "quality.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["flight_count"] == 1
    assert payload["source_manifest"]
    assert payload["status"] == "WARNINGS"
