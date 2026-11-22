"""The release gate's comparison, on canned answers: no wheel and no oracle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typing_extensions import Self

from scripts.parity import release_gate

VIN = "1HGCM82633A004352"

# The vPIC element ids of the canned decode, and their values.
_VALUES = {26: "HONDA", 28: "Accord", 29: "2003", 5: "Sedan/Saloon"}
_OUTSIDE = 143  # an error element: the gate leaves it to the known-problems gate


def _wheel_element(element_id: int, value: str) -> dict[str, Any]:
    return {
        "group_name": "General",
        "variable": release_gate.GATED.get(element_id, "Error Code"),
        "value": value,
        "pattern_id": 7,
        "vin_schema_id": 3,
        "keys": "CM826",
        "element_id": element_id,
        "attribute_id": value,
        "created_on": 0,
        "wmi_id": 1,
        "code": "",
        "data_type": "lookup",
        "decode": "",
        "source": "Pattern",
        "to_be_qced": False,
    }


def _oracle_row(element_id: int, value: str) -> dict[str, Any]:
    e = _wheel_element(element_id, value)
    return {
        "groupname": e["group_name"],
        "variable": e["variable"],
        "value": value,
        "itempatternid": e["pattern_id"],
        "itemvinschemaid": e["vin_schema_id"],
        "itemkeys": e["keys"],
        "itemelementid": element_id,
        "itemattributeid": value,
        "itemcreatedon": e["created_on"],
        "itemwmiid": e["wmi_id"],
        "code": "",
        "datatype": e["data_type"],
        "decode": "",
        "itemsource": e["source"],
        "itemtobeqced": False,
    }


def _case(values: dict[int, str]) -> release_gate.Case:
    return release_gate.Case(VIN, "cover", [_wheel_element(k, v) for k, v in values.items()])


def _oracle(values: dict[int, str]) -> Any:
    rows = [_oracle_row(k, v) for k, v in values.items()]
    return lambda vin: rows


def test_matching_answers_pass() -> None:
    report = release_gate.compare([_case(_VALUES)], _oracle(_VALUES), frozenset())

    assert report.ok
    assert report.compared == 1


def test_one_altered_answer_fails_and_names_the_vin_and_field() -> None:
    altered = {**_VALUES, 28: "Civic"}

    report = release_gate.compare([_case(altered)], _oracle(_VALUES), frozenset())

    assert not report.ok
    assert {(d.vin, d.element, d.field) for d in report.differences} >= {(VIN, "Model", "value")}
    line = next(d.line() for d in report.differences if d.field == "value")
    assert VIN in line
    assert "Model" in line
    assert "'Accord'" in line
    assert "'Civic'" in line


def test_a_row_only_one_side_has_is_a_difference() -> None:
    with_trim = {**_VALUES, 38: "EX"}

    report = release_gate.compare([_case(_VALUES)], _oracle(with_trim), frozenset())

    assert [(d.element, d.field, d.oracle, d.wheel) for d in report.differences] == [("Trim", "row", "EX", None)]


def test_elements_outside_the_gate_are_not_compared() -> None:
    oracle_values = {**_VALUES, _OUTSIDE: "0"}
    wheel_values = {**_VALUES, _OUTSIDE: "1"}

    report = release_gate.compare([_case(wheel_values)], _oracle(oracle_values), frozenset())

    assert report.ok


def _crash(vin: str) -> list[dict[str, Any]]:
    msg = "invalid regular expression"
    raise release_gate.OracleCrashError(msg)


def test_an_unregistered_oracle_crash_fails() -> None:
    report = release_gate.compare([_case(_VALUES)], _crash, frozenset())

    assert [(d.vin, d.element, d.field) for d in report.differences] == [(VIN, "oracle", "crash")]
    assert report.compared == 0


def test_a_registered_oracle_crash_is_skipped() -> None:
    report = release_gate.compare([_case(_VALUES)], _crash, frozenset({VIN}))

    assert report.ok
    assert report.excused_crashes == [VIN]


def _stub_wheel(monkeypatch: pytest.MonkeyPatch, oracle_values: dict[int, str]) -> None:
    def wheel_cases(wheel: Path, **_: Any) -> tuple[dict[str, Any], list[release_gate.Case]]:
        return {"module": "site-packages/ultravin/__init__.py", "version": "0.0.0"}, [_case(_VALUES)]

    class _Conn:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(release_gate, "wheel_cases", wheel_cases)
    monkeypatch.setattr(release_gate.oracle, "connect", _Conn)
    monkeypatch.setattr(release_gate, "_oracle_decoder", lambda conn: _oracle(oracle_values))


def test_main_exits_0_with_no_difference(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _stub_wheel(monkeypatch, _VALUES)

    assert release_gate.main(["ultravin.whl"]) == 0
    assert capsys.readouterr().out == ""


def test_main_exits_1_and_prints_the_difference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_wheel(monkeypatch, {**_VALUES, 26: "ACURA"})

    assert release_gate.main(["ultravin.whl"]) == 1
    out = capsys.readouterr().out
    assert VIN in out
    assert "Make value: oracle='ACURA' wheel='HONDA'" in out


def test_a_failed_wheel_install_stops_the_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Failed:
        returncode = 2
        stdout = ""
        stderr = "no such wheel"

    monkeypatch.setattr(release_gate.subprocess, "run", lambda *a, **k: _Failed())

    with pytest.raises(RuntimeError, match="no such wheel"):
        release_gate.wheel_cases(tmp_path / "x.whl", cover=None, seeded=0, generate=0, seed=0)
