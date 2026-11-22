from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import wheel_smoke
from scripts.wheel_smoke import main, unconditional_requirements


def test_an_extra_gated_requirement_is_not_unconditional() -> None:
    assert unconditional_requirements(['typer; extra == "cli"']) == []


def test_a_plain_requirement_is_unconditional() -> None:
    assert unconditional_requirements(["typer", 'rich; extra == "cli"']) == ["typer"]


@pytest.mark.parametrize("argv", [["--in-venv"], ["--in-venv", "all"], ["--in-venv", "cli", "extra"]])
def test_an_unknown_stage_is_a_usage_error(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "--in-venv {library,cli}" in capsys.readouterr().err


def _record_runs(monkeypatch: pytest.MonkeyPatch, fail_on: str | None = None) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(cmd, 1 if fail_on is not None and fail_on in cmd else 0)

    monkeypatch.setattr(wheel_smoke.subprocess, "run", fake_run)
    monkeypatch.setattr(wheel_smoke.venv.EnvBuilder, "create", lambda self, env_dir: None)
    return calls


def test_the_bare_install_is_checked_before_the_cli_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _record_runs(monkeypatch)
    wheel = tmp_path / "ultravin-0.0.0-py3-none-any.whl"
    assert wheel_smoke.smoke_artifact(wheel) is True
    steps = [(c[-1], c[-2]) for c in calls]
    assert steps == [
        (str(wheel), "--no-input"),
        ("library", "--in-venv"),
        (f"{wheel}[cli]", "--no-input"),
        ("cli", "--in-venv"),
    ]


def test_a_failed_library_stage_skips_the_cli_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _record_runs(monkeypatch, fail_on="library")
    assert wheel_smoke.smoke_artifact(tmp_path / "ultravin.whl") is False
    assert [c[-1] for c in calls] == [str(tmp_path / "ultravin.whl"), "library"]
