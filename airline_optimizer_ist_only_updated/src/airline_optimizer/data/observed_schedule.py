"""Reconstruct an observed weekly TK timetable proxy from itinerary legs.

This is a diagnostic adapter only. It does not claim to be an authoritative W26 schedule.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


def _duration_minutes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return int(value.total_seconds() // 60)
    if isinstance(value, (datetime, time)):
        return value.hour * 60 + value.minute
    match = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?$", str(value).strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _time_text(value: datetime) -> str:
    return value.strftime("%H:%M")


def _flight_number(value: Any) -> str:
    """Normalize Excel numeric flight numbers without changing alphanumeric IDs."""
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    if re.fullmatch(r"\d+", text):
        return text.lstrip("0") or "0"
    return text


def reconstruct_observed_timetable(
    connections_path: str | Path,
    flight_pairs_path: str | Path,
    output_csv: str | Path,
    report_json: str | Path,
) -> dict[str, Any]:
    connections_path = Path(connections_path)
    flight_pairs_path = Path(flight_pairs_path)
    output_csv = Path(output_csv)
    report_json = Path(report_json)

    pairs_wb = load_workbook(flight_pairs_path, read_only=True, data_only=True)
    pairs_ws = pairs_wb["W26 Flight Pair 20260227"]
    pair_rows = list(pairs_ws.iter_rows(values_only=True))
    pairs_wb.close()
    pair_headers = [str(x).strip() for x in pair_rows[0]]
    pair_idx = {name: pair_headers.index(name) for name in ("FlNo", "Orig", "Dest")}
    pair_keys = {
        (_flight_number(row[pair_idx["FlNo"]]), str(row[pair_idx["Orig"]]).strip().upper(), str(row[pair_idx["Dest"]]).strip().upper())
        for row in pair_rows[1:]
        if row[pair_idx["FlNo"]] is not None
    }

    wb = load_workbook(connections_path, read_only=True, data_only=True)
    ws = wb["Bağlantı Tablosu"]
    rows = ws.iter_rows(values_only=True)
    headers = [str(x).strip() for x in next(rows)]
    idx = {name: headers.index(name) for name in headers}
    # Key includes weekday because the same flight may operate on a subset of days.
    observations: dict[tuple[str, str, str, int], set[tuple[str, str, int]]] = defaultdict(set)
    source_rows = 0
    tk_leg_rows = 0
    unparseable_duration = 0
    unparseable_anchor = 0
    date_min: datetime | None = None
    date_max: datetime | None = None

    for row in rows:
        source_rows += 1
        day = row[idx["Gün"]]
        try:
            operating_day = int(day)
        except (TypeError, ValueError):
            continue
        if not 1 <= operating_day <= 7:
            continue
        for side in (1, 2):
            if str(row[idx[f"Cr{side}"]] or "").strip().upper() != "TK":
                continue
            tk_leg_rows += 1
            flight_no = _flight_number(row[idx[f"FlNo{side}"]])
            origin = str(row[idx[f"Dep{side}"]] or "").strip().upper()
            destination = str(row[idx[f"Arr{side}"]] or "").strip().upper()
            duration = _duration_minutes(row[idx[f"ElapsedTime{side}"]])
            if not flight_no or not origin or not destination or duration is None or duration <= 0:
                unparseable_duration += 1
                continue
            if side == 1:
                anchor = row[idx["Arr Time"]]
                if not isinstance(anchor, datetime):
                    unparseable_anchor += 1
                    continue
                arrival = anchor
                departure = arrival - timedelta(minutes=duration)
            else:
                anchor = row[idx["Dep Time"]]
                if not isinstance(anchor, datetime):
                    unparseable_anchor += 1
                    continue
                departure = anchor
                arrival = departure + timedelta(minutes=duration)
            date_min = min(date_min, anchor) if date_min else anchor
            date_max = max(date_max, anchor) if date_max else anchor
            observations[(flight_no, origin, destination, operating_day)].add(
                (_time_text(departure), _time_text(arrival), duration)
            )
    wb.close()

    rows_out: list[dict[str, Any]] = []
    conflicting_groups = []
    distinct_flight_routes = set()
    matched_flight_routes = set()
    observed_keys = set(observations)
    for key, values in sorted(observations.items()):
        flight_no, origin, destination, operating_day = key
        route_key = (flight_no, origin, destination)
        distinct_flight_routes.add(route_key)
        matched = route_key in pair_keys
        if matched:
            matched_flight_routes.add(route_key)
        if len(values) != 1:
            conflicting_groups.append({
                "flight_no": flight_no,
                "origin": origin,
                "destination": destination,
                "operating_day": operating_day,
                "distinct_observations": len(values),
                "observations": [list(v) for v in sorted(values)],
            })
            continue
        departure, arrival, duration = next(iter(values))
        rows_out.append({
            "flight_no": flight_no,
            "origin": origin,
            "destination": destination,
            "operating_day": operating_day,
            "departure_time_local_observed": departure,
            "arrival_time_local_observed": arrival,
            "duration_minutes_observed": duration,
            "pair_file_route_match": str(matched).lower(),
            "source_basis": "reconstructed_from_competitor_itinerary_leg",
            "authority_status": "PROXY_NOT_AUTHORITATIVE_W26_SCHEDULE",
        })

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0]) if rows_out else [
            "flight_no", "origin", "destination", "operating_day", "departure_time_local_observed",
            "arrival_time_local_observed", "duration_minutes_observed", "pair_file_route_match",
            "source_basis", "authority_status"
        ])
        writer.writeheader()
        writer.writerows(rows_out)

    def sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    report = {
        "schema_version": "observed-timetable-audit.v1",
        "status": "DIAGNOSTIC_PROXY_ONLY",
        "authoritative_schedule_claim": False,
        "source_period_observed_timestamps": {
            "minimum": date_min.isoformat(sep=" ") if date_min else None,
            "maximum": date_max.isoformat(sep=" ") if date_max else None,
        },
        "source_rows_read": source_rows,
        "tk_leg_observation_rows": tk_leg_rows,
        "distinct_tk_flight_route_combinations": len(distinct_flight_routes),
        "distinct_tk_flight_route_combinations_matching_flight_pairs": len(matched_flight_routes),
        "matching_route_coverage_fraction": round(len(matched_flight_routes) / len(distinct_flight_routes), 6) if distinct_flight_routes else None,
        "unique_flight_route_weekday_groups": len(observed_keys),
        "exported_unambiguous_groups": len(rows_out),
        "conflicting_groups_excluded": len(conflicting_groups),
        "unparseable_duration_rows": unparseable_duration,
        "unparseable_anchor_rows": unparseable_anchor,
        "source_sha256": {
            "competitor_connections_updated.xlsx": sha256(connections_path),
            "flight_pairs.xlsx": sha256(flight_pairs_path),
        },
        "critical_limitations": [
            "Connection observations are from August 2025, while the flight-pair workbook is labelled W26 2026.",
            "ElapsedTime fields are observed itinerary-leg durations and have not been independently validated as authoritative block times.",
            "Flight-pair matching does not prove schedule-time validity or completeness.",
            "Conflicting flight-route-weekday observations are excluded rather than silently resolved.",
            "This output must not be used as an official baseline without source-owner confirmation.",
        ],
        "conflict_examples": conflicting_groups[:100],
        "output_csv": str(output_csv),
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
