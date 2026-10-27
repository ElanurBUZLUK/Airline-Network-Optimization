# Problem Definition (Draft)

## Decision
For each scheduled flight instance, select one departure-time option.

## Fixed attributes
- Flight identity
- Origin and destination airports
- Flight date

## Derived attributes
- Arrival time = selected departure time + validated flight duration
- Connection gap = outbound departure − inbound arrival

## Connection feasibility
A connection is feasible when `45 <= gap_minutes <= 300`, inclusive.
The time representation must include the date/day rollover; `HH:MM` alone is insufficient.

## Scope
- Istanbul (IST) is a primary connection hub.
- Other valid OD connections remain in scope.
- Departure time shifts are explored beyond a fixed ±15-minute window in the research model.
- Departure/arrival capacity constraints are not mandatory constraints in this model.
- No aircraft duty-chain or aircraft-rotation model is part of this project.

## Objective policy
The primary target is the verified official score. OD-level gains/losses are also reported. Official scoring rules must be supported by an authoritative source before being labeled official.
