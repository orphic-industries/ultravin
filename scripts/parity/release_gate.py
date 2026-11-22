"""Release gate: a built wheel must decode like NHTSA's unmodified procedure.

Installs the wheel into a throwaway environment, asks it for VINs from its own
data (`cover_vins()`, `seeded()` and `generate()`), and decodes each one twice:
with the installed wheel, and with `vpic.spvindecode` in the parity oracle
(`make oracle-up`, then `make oracle-load DUMP=...` with
`ULTRAVIN_ORACLE_FAST_PROCS` unset, so the procedure is NHTSA's own text).

Only the vehicle elements in `GATED` are compared: make, model, series, trim,
body, drive, both fuel types, electrification, the GVWR band and model year.
Each is compared with `normalize.diff_rows`, the same comparison the sweep and
the answer key use, so a gated element's value and its provenance columns must
both match. The gate does not compare the error and correction elements.

Every difference prints its VIN, element, field and both answers, and the gate
exits 1. A VIN the oracle crashes on has no answer to compare: it is skipped
when `scripts/known_problems.json` registers it as an oracle crash, and fails
the gate otherwise. The gate also exits 1 when it compares no VIN, when the
decodes do not come from the installed wheel, and when the oracle holds the
fast-procs rewrite. Otherwise it exits 0.

    uv run -- python -m scripts.parity.release_gate target/wheels/<the wheel>.whl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.parity import normalize, oracle
from scripts.refresh import ORACLE_CRASH_VINS

REPO = Path(__file__).resolve().parents[2]

# The vehicle elements the gate compares, by vPIC element id.
GATED: dict[int, str] = {
    5: "Body Class",
    15: "Drive Type",
    24: "Fuel Type - Primary",
    25: "Gross Vehicle Weight Rating From",
    26: "Make",
    28: "Model",
    29: "Model Year",
    34: "Series",
    38: "Trim",
    66: "Fuel Type - Secondary",
    126: "Electrification Level",
    190: "Gross Vehicle Weight Rating To",
}

# Runs inside the wheel's environment with `python -I`, so neither the working
# directory nor PYTHONPATH can put this repository's `ultravin` on the path. A
# `.pth` file still could, so `check_installed` tests where `ultravin` came from.
# The first line names the module. Each line after it holds one VIN and the
# gated elements of its `full=True` decode.
_WHEEL_SIDE = """
import json, sys
import ultravin as uv

args = json.loads(sys.argv[1])
gated = set(args["gated"])
kinds = [
    ("cover", uv.cover_vins() if args["cover"] is None else uv.cover_vins()[: args["cover"]]),
    ("seeded", uv.seeded(limit=args["seeded"]) if args["seeded"] else []),
    ("generate", uv.generate(args["generate"], seed=args["seed"]) if args["generate"] else []),
]
print(json.dumps({"module": uv.__file__, "version": uv.__version__}), flush=True)
seen = set()
for kind, vins in kinds:
    for vin in vins:
        if vin in seen:
            continue
        seen.add(vin)
        elements = [e for e in uv.decode(vin, full=True)["elements"] if e["element_id"] in gated]
        print(json.dumps({"vin": vin, "kind": kind, "elements": elements}, default=str))
"""


class OracleCrashError(Exception):
    """The oracle raised on a VIN, so it has no answer to compare."""


class GateError(Exception):
    """The gate cannot run a valid comparison."""


@dataclass(frozen=True)
class Case:
    vin: str
    kind: str
    elements: list[dict[str, Any]]


@dataclass(frozen=True)
class Difference:
    vin: str
    kind: str
    element: str
    field: str
    oracle: Any
    wheel: Any

    def line(self) -> str:
        return f"{self.vin} ({self.kind}) {self.element} {self.field}: oracle={self.oracle!r} wheel={self.wheel!r}"


@dataclass(frozen=True)
class Report:
    compared: int
    differences: list[Difference]
    excused_crashes: list[str]

    @property
    def ok(self) -> bool:
        return self.compared > 0 and not self.differences


def _element_name(element_id: Any) -> str:
    return GATED.get(element_id, f"element {element_id}")


def differences(case: Case, oracle_rows: list[dict[str, Any]]) -> list[Difference]:
    """The gated elements' differences between the oracle's rows and the wheel's."""
    theirs = [normalize.from_oracle(r) for r in oracle_rows if r["itemelementid"] in GATED]
    mine = [normalize.from_ultravin(e) for e in case.elements if e.get("element_id") in GATED]
    d = normalize.diff_rows(theirs, mine)
    out = [
        Difference(case.vin, case.kind, _element_name(fd["element_id"]), fd["field"], fd["oracle"], fd["ultravin"])
        for fd in d["field_diffs"]
    ]
    out += [
        Difference(case.vin, case.kind, _element_name(r["element_id"]), "row", r["value"], None) for r in d["missing"]
    ]
    out += [
        Difference(case.vin, case.kind, _element_name(r["element_id"]), "row", None, r["value"]) for r in d["extra"]
    ]
    # A missing or extra row already changes the group sequence; the order is a
    # difference of its own only when both sides hold the same rows.
    if not d["order_ok"] and not d["missing"] and not d["extra"]:
        group_order = [r["group_name"] for r in theirs], [r["group_name"] for r in mine]
        out.append(Difference(case.vin, case.kind, "group order", "group_name", *group_order))
    return out


def compare(
    cases: Iterable[Case],
    decode: Callable[[str], list[dict[str, Any]]],
    registered_crashes: frozenset[str],
) -> Report:
    """Decode every case with `decode` (the oracle) and collect the differences.

    `decode` raises `OracleCrashError` when the oracle has no answer for a VIN.
    """
    compared = 0
    found: list[Difference] = []
    excused: list[str] = []
    for case in cases:
        try:
            rows = decode(case.vin)
        except OracleCrashError as e:
            if case.vin in registered_crashes:
                excused.append(case.vin)
            else:
                found.append(Difference(case.vin, case.kind, "oracle", "crash", str(e), None))
            continue
        compared += 1
        found += differences(case, rows)
    return Report(compared, found, excused)


def wheel_cases(
    wheel: Path,
    *,
    cover: int | None,
    seeded: int,
    generate: int,
    seed: int,
) -> tuple[dict[str, Any], list[Case]]:
    """Install `wheel` into a throwaway environment and read its VINs and decodes."""
    args = {"cover": cover, "seeded": seeded, "generate": generate, "seed": seed, "gated": sorted(GATED)}
    cmd = [
        "uv",
        "run",
        "--no-project",
        "--isolated",
        "--python",
        sys.executable,
        "--with",
        str(wheel.resolve()),
        "--",
        "python",
        "-I",
        "-c",
        _WHEEL_SIDE,
        json.dumps(args),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        msg = f"the wheel's decodes failed (exit {proc.returncode}):\n{proc.stderr}"
        raise GateError(msg)
    header, *lines = proc.stdout.splitlines()
    cases = [Case(**json.loads(ln)) for ln in lines if ln.strip()]
    return json.loads(header), cases


def check_installed(info: dict[str, Any], repo: Path = REPO) -> None:
    """Fail unless `ultravin` came from outside this repository, so from the wheel."""
    module = Path(info["module"]).resolve()
    if module.is_relative_to(repo):
        msg = f"the decodes came from {module}, inside this repository, not from the wheel"
        raise GateError(msg)


# `fast_procs()` in scripts/oracle.sh rewrites `on commit drop` to this text, and
# NHTSA's procedures never contain it. Aggregates have no function definition.
_FAST_PROCS_SQL = """
select count(*) as n from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
where ns.nspname = 'vpic' and p.prokind in ('f', 'p')
  and pg_get_functiondef(p.oid) like '%on commit delete rows%'
"""


def check_unmodified(conn: Any) -> None:
    """Fail when the oracle was loaded with ULTRAVIN_ORACLE_FAST_PROCS=1."""
    with conn.cursor() as cur:
        cur.execute(_FAST_PROCS_SQL)
        row = cur.fetchone()
    if row and row["n"]:
        msg = (
            f"the oracle holds {row['n']} rewritten procedure(s): reload it with "
            "ULTRAVIN_ORACLE_FAST_PROCS unset, so that it runs NHTSA's unmodified spvindecode"
        )
        raise GateError(msg)


def _oracle_decoder(conn: Any) -> Callable[[str], list[dict[str, Any]]]:
    # Lazy, like scripts.parity.oracle: importing this module must not need psycopg.
    import psycopg  # noqa: PLC0415

    def decode(vin: str) -> list[dict[str, Any]]:
        try:
            return oracle.decode(conn, vin)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            # A lost connection says nothing about the VIN, so it never reads as a
            # crash the registry could excuse: it stops the gate.
            raise
        except psycopg.Error as e:
            raise OracleCrashError(repr(e)[:200]) from e

    return decode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare a built wheel with NHTSA's unmodified spvindecode.")
    ap.add_argument("wheel", type=Path, help="the built wheel (.whl)")
    ap.add_argument("--cover", type=int, default=None, help="VINs from cover_vins() (default: all of them)")
    ap.add_argument("--seeded", type=int, default=1000, help="VINs from seeded() (default 1000)")
    ap.add_argument("--generate", type=int, default=1000, help="VINs from generate() (default 1000)")
    ap.add_argument("--seed", type=int, default=0, help="generate()'s seed (default 0)")
    args = ap.parse_args(argv)
    # An empty path resolves to the repository root, and `uv run --with` would
    # then build and test the source tree instead of the artifact.
    if not args.wheel.is_file() or args.wheel.suffix != ".whl":
        ap.error(f"not a wheel file: {str(args.wheel)!r}")

    started = time.monotonic()
    try:
        info, cases = wheel_cases(
            args.wheel, cover=args.cover, seeded=args.seeded, generate=args.generate, seed=args.seed
        )
        check_installed(info)
        kinds = {k: sum(c.kind == k for c in cases) for k in ("cover", "seeded", "generate")}
        print(f"release-gate: ultravin {info['version']} from {info['module']}", file=sys.stderr)
        print(f"release-gate: {len(cases)} VINs {kinds}", file=sys.stderr)

        # batch=1 keeps the connection in autocommit, so one oracle error cannot
        # abort a transaction that later decodes run in.
        with oracle.connect(batch=1) as conn:
            check_unmodified(conn)
            report = compare(cases, _oracle_decoder(conn), ORACLE_CRASH_VINS)
    except GateError as e:
        print(f"release-gate: {e}", file=sys.stderr)
        return 1

    for d in report.differences:
        print(d.line())
    print(
        f"release-gate: {len(report.differences)} difference(s) over {report.compared} VINs compared; "
        f"{len(report.excused_crashes)} registered oracle crash(es) skipped; "
        f"{time.monotonic() - started:.0f}s",
        file=sys.stderr,
    )
    if report.compared == 0:
        print("release-gate: no VIN was compared", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
