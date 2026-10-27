# Architecture (Draft)

- `contracts`: typed input, scoring, and validation contracts
- `data`: loading, schema validation, canonicalization, provenance, quality reports
- `domain`: flights, time model, OD markets, solutions
- `candidates`: coarse time options, boundary-derived options, adaptive refinement
- `connections`: compatibility, indexes, dynamic graph, incremental updates
- `scoring`: connection score, ranking score, official scorer, research metrics
- `optimization`: mathematical formulation, subproblem, solver adapter, repair
- `search`: neighborhoods, destroy operators, ALNS policy, acceptance, engine
- `validation`: schedule validation, independent full recomputation, consistency checks
- `experiments`: controlled runs, metrics, comparisons
- `reporting`: schedule export, OD report, run summary

Dynamic graph updates should touch affected flights and edges, not rebuild the entire graph every iteration. Every incremental calculation must be checked against full recomputation during validation.
