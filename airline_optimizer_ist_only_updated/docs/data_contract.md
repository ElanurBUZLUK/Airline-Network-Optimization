# Data Contract (Draft)

## Canonical flight instance
Required conceptual fields:
- `flight_id`: stable unique ID for one dated flight instance
- `flight_number`: source flight number
- `flight_date`: fixed operating date
- `origin`, `destination`: normalized airport codes
- `baseline_departure_abs_min`: baseline departure as absolute minutes on a documented timeline
- `flight_duration_min`: validated duration for this flight instance
- `baseline_arrival_abs_min`: optional source value used for reconciliation, not silently trusted over the duration rule
- `source_record_ids`: source lineage

## Canonical OD market
- `origin`
- `destination`
- `passenger_importance` when supported by an unambiguous source value

OD keys are directional: A→B and B→A are different markets.

## Data quality
- Required columns and types are validated explicitly.
- Duplicate rows are not silently dropped when values conflict.
- Conflicting OD importance values are surfaced as errors/issues; no last-row-wins behavior.
- All transformations and source fingerprints are recorded.
- Competitor itinerary elapsed times are not assumed to be individual flight block durations.

## Implemented ingestion behavior (initial)
- `load_baseline_flights` reads baseline CSV/XLSX and creates `FlightInstance` records.
- When no explicit duration column is supplied, duration may be inferred from departure/arrival clock times with one midnight rollover. Every such row receives a warning; inferred duration is not considered independently validated block time.
- `load_od_importance` normalizes directional OD keys. Conflicting values for the same OD are excluded from the canonical map and emitted as errors; identical duplicates are collapsed but reported.
- `load_ranking_weights` validates positive rank/count fields and detects duplicate/conflicting transition keys. The loader does not establish that the table is officially authoritative or complete for all competitor counts.
- `load_flight_pairs_metadata` retains `Pair` only as source metadata; it does not constrain alternate connection pairings.
- Every loaded table is fingerprinted with SHA-256 and source row/column metadata. `write_quality_report` serializes the manifest and issues as JSON.
- XLSX reading is optional and requires `pip install -e '.[data]'`.
