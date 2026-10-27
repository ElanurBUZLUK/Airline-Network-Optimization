from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_project_has_no_legacy_source_dependency():
    """The new package must remain independently structured."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "airline-net-opt-unbounded-solver" not in pyproject


def test_connection_window_is_explicit_in_problem_contract():
    text = (ROOT / "docs" / "problem_definition.md").read_text(encoding="utf-8")
    assert "45 <= gap_minutes <= 300" in text


def test_no_aircraft_duty_chain_in_scope():
    text = (ROOT / "docs" / "problem_definition.md").read_text(encoding="utf-8")
    assert "No aircraft duty-chain or aircraft-rotation model" in text
