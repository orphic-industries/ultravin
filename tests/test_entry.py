from __future__ import annotations

import importlib.metadata
import subprocess
import sys

import pytest
import ultravin
from ultravin import _entry

from scripts.wheel_smoke import unconditional_requirements


def test_without_typer_the_command_names_the_cli_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "typer", None)
    monkeypatch.delitem(sys.modules, "ultravin.cli", raising=False)
    monkeypatch.delitem(sys.modules, "ultravin._batch_cli", raising=False)
    monkeypatch.delattr(ultravin, "cli", raising=False)
    monkeypatch.delattr(ultravin, "_batch_cli", raising=False)
    with pytest.raises(SystemExit, match="1"):
        _entry.main()
    assert "pip install 'ultravin[cli]'" in capsys.readouterr().err


def test_another_missing_module_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ultravin.cli", None)
    monkeypatch.delattr(ultravin, "cli", raising=False)
    with pytest.raises(ModuleNotFoundError, match=r"ultravin\.cli"):
        _entry.main()


def test_with_typer_the_command_runs_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from ultravin import cli  # noqa: PLC0415

    calls: list[str] = []
    monkeypatch.setattr(cli, "main", lambda: calls.append("main"))
    _entry.main()
    assert calls == ["main"]


def test_a_bare_install_requires_nothing() -> None:
    # The dev environment always has typer (the dev group pulls in [cli]), so
    # check the package's own metadata rather than what happens to be installed.
    assert unconditional_requirements(importlib.metadata.requires("ultravin") or []) == []


def test_importing_ultravin_loads_no_cli_code() -> None:
    code = "import sys, ultravin; ultravin.decode('1HGCM82633A004352'); print(sorted(m for m in sys.modules if m.split('.')[0] in {'typer', 'click', 'rich'} or m in {'ultravin.cli', 'ultravin._batch_cli'}))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
