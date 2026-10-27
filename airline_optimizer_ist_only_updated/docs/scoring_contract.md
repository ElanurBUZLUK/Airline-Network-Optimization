# Scoring Contract (Draft)

The official score is not yet implemented as an authoritative contract.

Planned separation:
1. Connection feasibility and OD connection counts
2. Connection reward calculation
3. Ranking calculation
4. Official score aggregation
5. Research-only search guidance metrics

Each official component must identify its authoritative source, source version, applicable scope, and tests. Unsupported competitor-count ranges or ranking cases must be reported explicitly; they must not silently remove otherwise valid connections from connection evaluation.

The independent full scorer is the reference implementation. Incremental scores and solver objective values must be reconciled against it.
