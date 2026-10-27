# Istanbul Transfer Optimizer

Research prototype for optimizing **connections through Istanbul Airport (IST) only**.
A counted connection must be an inbound leg ending at IST followed by an outbound leg
starting at IST, with a transfer gap between 45 and 300 minutes inclusive. Connections
at other airports are excluded from the objective and validation.

## Inputs

Place these files in `data/raw/`:

- `flight_pairs.xlsx` — flight number and route metadata.
- `competitor_od_connections_updated.xlsx` — observed itinerary legs and clock/duration data.
- `passenger_od_importance.xlsx` — OD importance factors.
- `ranking_transition_weights.xlsx` — ranking transition lookup weights.
- `baseline_sample.csv` — optional full dated baseline. The two-row sample shipped here is only a placeholder.

If `baseline_sample.csv` has two or fewer rows, the pipeline automatically reconstructs a **non-authoritative weekly proxy** from the observed itinerary workbook, matches leg route/flight number against `flight_pairs.xlsx`, and retains only legs touching IST. Source weekday 1 (Sunday) through 7 is mapped to a synthetic week for time arithmetic. This allows the search to run, but does not make the data an authoritative W26 schedule. Observed durations and times have not been independently validated.

If a complete dated baseline is provided, the pipeline uses that baseline instead. Only IST-touching legs are retained for optimization.

## Install and run

```bash
python -m pip install -e '.[data,dev]'
airline-optimizer \
  --data-dir data/raw \
  --output-dir runs/ist_research \
  --window-before-minutes 180 \
  --window-after-minutes 180 \
  --grid-step-minutes 30 \
  --iterations 100 \
  --seed 42
```

The candidate time window is explicit; there is no hidden +/-15-minute restriction.

## Outputs

- `best_schedule.csv` — selected departure times for IST-touching legs.
- `best_od_metrics.csv` — OD markets with valid IST transfers.
- `best_connections.csv` — each best-schedule transfer pair, IST arrival, outbound departure, and transfer gap; independently recomputed.
- `manifests/data_quality.json` — input provenance and data quality issues.
- `manifests/source_readiness.json` — schedule source and authority status.
- `manifests/run_report.json` — configuration, baseline/best research metrics and limitations.

## Interpretation and limitations

- The search objective is a **research proxy**: number of valid IST transfers, with OD market coverage as a small tie-breaker.
- The program does **not** compute the official competition score. The OD importance and ranking-weight workbooks are loaded and audited but are not yet wired into a verified official scoring formula.
- When the observed proxy fallback is used, its timestamps originate from August 2025 competitor itinerary observations and are mapped to a synthetic week. Treat results as exploratory only, not as official W26 schedule performance.
- No connections outside IST are counted.
