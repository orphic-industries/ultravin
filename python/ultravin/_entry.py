"""The `ultravin` console script. Says how to get the CLI when typer is missing."""

from __future__ import annotations

import sys

MISSING_CLI = "the ultravin command needs the cli extra: pip install 'ultravin[cli]'"


def main() -> None:
    try:
        from ultravin import cli  # noqa: PLC0415 - deferred: typer is optional
    except ModuleNotFoundError as exc:
        if exc.name != "typer":
            raise
        print(MISSING_CLI, file=sys.stderr)
        raise SystemExit(1) from None
    cli.main()
