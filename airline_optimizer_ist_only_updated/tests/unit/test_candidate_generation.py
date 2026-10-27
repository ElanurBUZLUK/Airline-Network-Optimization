from datetime import date

import pytest

from airline_optimizer.candidates.boundary_generator import generate_connection_boundary_options
from airline_optimizer.candidates.grid_generator import generate_grid_options
from airline_optimizer.domain.flights import FlightInstance, TimeOption


def flight(fid="F1", origin="ADB", destination="IST", departure=1000, duration=90):
    return FlightInstance(fid, fid, date(2026, 1, 1), origin, destination, departure, duration)


def test_grid_includes_baseline_even_when_not_on_grid():
    f = flight(departure=1003)
    options = generate_grid_options(f, 1000, 1020, 10)
    assert [o.departure_abs_min for o in options] == [1000, 1003, 1010, 1020]


def test_grid_does_not_impose_fifteen_minute_window():
    f = flight(departure=1000)
    options = generate_grid_options(f, 700, 1400, 60, include_baseline=False)
    assert options[0].departure_abs_min == 700
    assert options[-1].departure_abs_min == 1360


def test_boundary_generation_as_outbound():
    f = flight("OUT", "IST", "LHR", departure=1200, duration=120)
    inbound_flight = flight("IN", "ADB", "IST", duration=135)
    inbound = [(inbound_flight, TimeOption("IN@900", "IN", 900, "test"))]
    options = generate_connection_boundary_options(f, inbound_options=inbound)
    assert {o.departure_abs_min for o in options} == {1080, 1335}


def test_boundary_generation_as_inbound():
    f = flight("IN", "ADB", "IST", duration=100)
    outbound_flight = flight("OUT", "IST", "LHR", duration=120)
    outbound = [(outbound_flight, TimeOption("OUT@1200", "OUT", 1200, "test"))]
    options = generate_connection_boundary_options(f, outbound_options=outbound)
    assert {o.departure_abs_min for o in options} == {800, 1055}


def test_boundary_filters_to_explicit_window():
    f = flight("OUT", "IST", "LHR", duration=120)
    inbound_flight = flight("IN", "ADB", "IST", duration=135)
    inbound = [(inbound_flight, TimeOption("IN@900", "IN", 900, "test"))]
    options = generate_connection_boundary_options(f, inbound_options=inbound, earliest_departure_abs_min=1100)
    assert [o.departure_abs_min for o in options] == [1335]


def test_boundary_generation_uses_exact_45_and_300_minute_endpoints():
    out = flight("OUT", "IST", "LHR", departure=1200, duration=120)
    inbound_flight = flight("IN", "ADB", "IST", departure=800, duration=100)
    inbound = [(inbound_flight, TimeOption("IN@800", "IN", 800, "baseline"))]
    options = generate_connection_boundary_options(
        out, inbound_options=inbound, min_gap_minutes=45, max_gap_minutes=300
    )
    # Departure times create gaps of exactly 45 and 300 minutes after inbound arrival.
    assert {o.departure_abs_min for o in options} == {945, 1200}


def test_boundary_generation_deduplicates_repeated_partner_times_without_losing_boundary():
    out = flight("OUT", "IST", "LHR", departure=1200, duration=120)
    inbound_flight = flight("IN", "ADB", "IST", departure=800, duration=100)
    repeated_options = [
        (inbound_flight, TimeOption("IN@800a", "IN", 800, "grid")),
        (inbound_flight, TimeOption("IN@800b", "IN", 800, "refinement")),
    ]
    options = generate_connection_boundary_options(
        out, inbound_options=repeated_options, min_gap_minutes=45, max_gap_minutes=300
    )
    assert [o.departure_abs_min for o in options] == [945, 1200]
    assert all(o.generation_method == "connection_boundary" for o in options)
