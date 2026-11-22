"""The release gate's comparison, on canned answers: no wheel and no oracle."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest

from scripts.parity import release_gate

VIN = "1HGCM82633A004352"

# The vPIC element ids of the canned decode, and their values.
_VALUES = {26: "HONDA", 28: "Accord", 29: "2003", 5: "Sedan/Saloon"}
_OUTSIDE = 143  # an error element, which the gate does not compare


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


def _crash_on(crash_vin: str) -> Any:
    def decode(vin: str) -> list[dict[str, Any]]:
        return _crash(vin) if vin == crash_vin else []

    return decode


def test_an_unregistered_oracle_crash_fails() -> None:
    report = release_gate.compare([_case(_VALUES)], _crash, frozenset())

    assert [(d.vin, d.element, d.field) for d in report.differences] == [(VIN, "oracle", "crash")]
    assert report.compared == 0


def test_a_registered_oracle_crash_is_skipped() -> None:
    report = release_gate.compare(
        [_case(_VALUES), release_gate.Case("1G1", "seeded", [])], _crash_on(VIN), frozenset({VIN})
    )

    assert report.differences == []
    assert report.excused_crashes == [VIN]
    assert report.compared == 1


def _stub_wheel(monkeypatch: pytest.MonkeyPatch, cases: list[release_gate.Case], oracle_values: dict[int, str]) -> None:
    def wheel_cases(wheel: Path, **_: Any) -> tuple[dict[str, Any], list[release_gate.Case]]:
        return {"module": "/env/site-packages/ultravin/__init__.py", "version": "0.0.0"}, cases

    monkeypatch.setattr(release_gate, "wheel_cases", wheel_cases)
    monkeypatch.setattr(release_gate.oracle, "connect", lambda batch: contextlib.nullcontext(object()))
    monkeypatch.setattr(release_gate, "check_unmodified", lambda conn: None)
    monkeypatch.setattr(release_gate, "_oracle_decoder", lambda conn: _oracle(oracle_values))


@pytest.fixture
def wheel(tmp_path: Path) -> str:
    path = tmp_path / "ultravin-0.0.0-cp310-abi3-any.whl"
    path.write_bytes(b"")
    return str(path)


def test_main_exits_0_with_no_difference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wheel: str
) -> None:
    _stub_wheel(monkeypatch, [_case(_VALUES)], _VALUES)

    assert release_gate.main([wheel]) == 0
    assert capsys.readouterr().out == ""


def test_main_exits_1_and_prints_the_difference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wheel: str
) -> None:
    _stub_wheel(monkeypatch, [_case(_VALUES)], {**_VALUES, 26: "ACURA"})

    assert release_gate.main([wheel]) == 1
    out = capsys.readouterr().out
    assert VIN in out
    assert "Make value: oracle='ACURA' wheel='HONDA'" in out


def test_main_exits_1_when_no_vin_is_compared(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wheel: str
) -> None:
    _stub_wheel(monkeypatch, [], _VALUES)

    assert release_gate.main([wheel]) == 1
    assert "no VIN was compared" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["", "target/wheels", "ultravin.tar.gz"])
def test_main_refuses_a_path_that_is_not_a_wheel(path: str) -> None:
    with pytest.raises(SystemExit, match="2"):
        release_gate.main([path])


def test_decodes_from_inside_the_repository_fail(tmp_path: Path) -> None:
    info = {"module": str(tmp_path / "python" / "ultravin" / "__init__.py")}

    with pytest.raises(release_gate.GateError, match="inside this repository"):
        release_gate.check_installed(info, repo=tmp_path)


def test_decodes_from_the_wheel_environment_pass(tmp_path: Path) -> None:
    release_gate.check_installed({"module": "/env/site-packages/ultravin/__init__.py"}, repo=tmp_path)


class _Cursor:
    def __init__(self, n: int) -> None:
        self.n = n

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        return None

    def fetchone(self) -> dict[str, int]:
        return {"n": self.n}


class _FakeConn:
    def __init__(self, n: int) -> None:
        self.n = n

    def cursor(self) -> _Cursor:
        return _Cursor(self.n)


def test_an_oracle_with_rewritten_procs_fails() -> None:
    with pytest.raises(release_gate.GateError, match="ULTRAVIN_ORACLE_FAST_PROCS unset"):
        release_gate.check_unmodified(_FakeConn(3))


def test_an_oracle_with_nhtsas_procs_passes() -> None:
    release_gate.check_unmodified(_FakeConn(0))


def test_a_failed_wheel_install_stops_the_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Failed:
        returncode = 2
        stdout = ""
        stderr = "no such wheel"

    monkeypatch.setattr(release_gate.subprocess, "run", lambda *a, **k: _Failed())

    with pytest.raises(release_gate.GateError, match="no such wheel"):
        release_gate.wheel_cases(tmp_path / "x.whl", cover=None, seeded=0, generate=0, seed=0)
