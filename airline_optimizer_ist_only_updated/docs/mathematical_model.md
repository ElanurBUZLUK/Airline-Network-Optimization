# Mathematical Model (Draft)

For each flight instance `i`, let `T_i` be its validated duration and `D_i` its selected departure time on an absolute-minute timeline.

`A_i = D_i + T_i`

For a potential connection from flight `i` to flight `j`:

`G_ij = D_j - A_i`

The connection is feasible iff:

`45 <= G_ij <= 300`

For a finite candidate set `C_i`, binary option variables may be used:

`x_ik ∈ {0,1}` and `sum(k in C_i) x_ik = 1`.

A connection's activation depends on the selected time options for both flights. Candidate generation will combine coarse exploration, connection-boundary-derived times, and adaptive refinement. Exact MILP subproblems and heuristic neighborhoods will be evaluated experimentally.

No objective coefficients are frozen until the official score contract is verified.
