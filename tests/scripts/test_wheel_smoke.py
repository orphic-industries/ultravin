from __future__ import annotations

import pytest

from scripts.wheel_smoke import main, unconditional_requirements


def test_an_extra_gated_requirement_is_not_unconditional() -> None:
    assert unconditional_requirements(['typer; extra == "cli"']) == []


def test_a_plain_requirement_is_unconditional() -> None:
    assert unconditional_requirements(["typer", 'rich; extra == "cli"']) == ["typer"]


@pytest.mark.parametrize("argv", [["--in-venv"], ["--in-venv", "all"], ["--in-venv", "cli", "extra"]])
def test_an_unknown_stage_is_a_usage_error(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "--in-venv {library,cli}" in capsys.readouterr().err
