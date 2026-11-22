# Monthly data refresh

NHTSA publishes a new standalone vPIC database roughly monthly
(`vPICList_lite_YYYY_MM.plain.zip`, observed day 9–18, kept online ~8 months,
occasionally re-touched after publication). No workflow in this fork detects,
integrates or merges a month. A person runs `scripts/refresh.py`, commits what
it writes, and opens a pull request that a person merges. CI checks that pull
request like any other.

## The mechanical path

`scripts/refresh.py` is the whole pipeline. It is stdlib-only, and everything
heavy is a subprocess of the existing tools:

```bash
make refresh-detect            # is there a newer dump than vpic/manifest.json?
make refresh MONTH=2026_08     # integrate it (wipes + reloads the docker oracle)
```

`run` downloads the dump, rebuilds `vpic/` + the embedded artifact
(`vpic-import`), rebuilds the Python extension, cycles the docker Postgres
oracle onto the new dump, re-freezes `tests/parity_corpus.json`, and gates:

- **corpus** — every diverging re-frozen VIN is registered in
  `scripts/known_problems.json` (kind `deviation`), the single source of truth
  for the defects ultravin deliberately does not reproduce; the evidence for
  each is in `docs/KNOWN_DEVIATIONS.md`. `freeze.py` happily snapshots *any*
  current diff as the new baseline, so this gate is what stops a regression from
  being laundered into a green test suite. The re-freeze re-freezes the
  *existing* corpus VIN set (`--vins`), so the diff always reads "same VINs, new
  expectations" rather than a fresh sample replacing the curated one — plus
  every registered `deviation` VIN, which belongs in the corpus so its expected
  difference is frozen too (the known-problems gate only asks whether it still
  diverges, not whether it still diverges the *same way*).
- **sweep** — 500 freshly generated VINs decoded live against the new oracle,
  zero undocumented divergence.
- **stale-cache** — `scripts/stale_cache_cells.json`, regenerated from this
  month's dump by the same `vpic-import` pass, is internally consistent, did not
  gain implausibly many cells, and still faces an empty
  `vpic.wmiyearvalidchars_cacheexceptions`. This is the one documented deviation
  class enumerated by machine rather than by VIN: every `(wmi, year)` cell whose
  `WMIYearValidChars` contents contradict the recompute from the dump's own
  pattern rows, with the VIN positions they disagree at. The list *changing*
  month to month is the point, not a failure — it self-documents in the PR diff.
  What fails is a list that contradicts its own summary, a jump past 500 newly
  stale cells in the charset-regression shape (recompute-only rows up by more
  than 500, or a nonzero stale count more than doubled and up by over 2,500;
  upstream churn moves tens, a decoder charset regression re-lists thousands,
  and schema-drop cache lag is reported, not failed), or a non-empty
  cacheexceptions table, which would mean the proc no longer reads the cache
  the way the scan assumes. Policy: `docs/ACCEPTANCE.md`;
  evidence: `docs/KNOWN_DEVIATIONS.md#stale-wmiyearvalidchars-cache`.
- **known-problems** — the converse of the three above: every registered VIN
  still *reproduces* its documented problem. See below.
- **coverage** — `make coverage`: the decode path still reaches 100% of the
  regions a VIN can reach, and no allowance in
  `scripts/coverage_allowances.json` went **stale**. A stale one is the
  interesting failure: it means this month's data reaches a branch the previous
  month's could not. The allowances rest on facts about the dump — 0 `tobeqced`
  schemas, 0 models with two makes, no reversed character classes — and a month
  that breaks one of those assumptions lights up exactly that entry instead of
  passing silently.

- **pytest / cargo** — the offline suites.

The behavioural cover baked into the artifact is recomputed from the *new* dump
by `vpic-import`, so it is never carried over. What does not update itself is the
code that decides *what to look for*: the token grammar, the sweep dimensions and
the constructed candidate families. The coverage gate is what notices when the
new data outgrows them.

Exit 0 = integrated and green; exit 2 = gates failed (report still written to
`target/refresh/report.{md,json}`); exit 1 = mechanical breakage. Paste
`target/refresh/report.md` into the pull request body. It carries the data-only vs schema-change classification (`git status` on
`vpic/schema` + `vpic/procs` — the importer strips volatile dump noise, so a
data-only month diffs clean there), manifest row/table/function deltas, lookup
value changes, gate results, and follow-ups (e.g. a new oracle-crash VIN freeze
had to skip).

## Documented problems must keep reproducing

Every other gate uses `scripts/known_problems.json` to *excuse* an observation,
so nothing ever made an
excuse prove it was still true. Upstream fixes things: 2026_08 healed the
stale-year-cache deviation and the refresh stayed green on that axis, because the
gates only ever ask "is this divergence forgiven?". Worse, the 63 crash VINs land
in neither freeze's sample nor the 500-VIN sweep, so most months they were never
decoded at all.

`scripts/parity/known_problems.py` therefore decodes every listed VIN against the
new oracle and writes `target/refresh/known_problems.json`
(`{vin: {"outcome": "crash"|"diverged"|"exact"|"infra-error"}}`); the
**known-problems** gate requires each `oracle-crash` VIN to still crash and each
`deviation` VIN to still diverge. A stale excuse fails the run and the gate
detail names the VIN, what it does now, and its registry kind — retire the entry
from `scripts/known_problems.json`, the same house rule as the coverage gate
failing on a stale allowance.

A connection error is *not* evidence in either direction: it is reported as
`infra-error` and fails the gate as **unverifiable** rather than quietly
re-certifying the whole list, so an oracle outage can never be mistaken for
confirmation. A VIN with no record at all is treated the same way — the probe
writes its report in one go at the end, so a probe that dies (or an oracle it
could not connect to) leaves no file, the gate is handed nothing, and all of
them come back unverifiable rather than silently passing.

Row counts can't show an in-place label edit (2026_07 silently renamed
`bodystyle` 7 from `...(SUV)...` to `...[SUV]...` — 71 rows before and after),
so `run` also freezes every vpic table with ≤ 512 rows into `vpic/lookups.json`:
the rename becomes a one-line PR diff, and the report names each changed value
against the committed freeze.

## Failure playbook

- **build-data sha256 mismatch on an old PR/branch** — NHTSA re-touched the
  pinned month's file. `make refresh-detect` also catches this
  (`reason=reissue`, via the URL's `Content-Length` vs the manifest's
  `dump_bytes`). Refresh the *same* month to pin the new hash.
- **corpus/sweep gate names an unknown VIN** — either the decoder no longer
  matches the new data (fix Rust) or the dump itself is defective (oracle
  crash, stale cache table — precedent in `docs/KNOWN_DEVIATIONS.md`). The
  gates accept a diverging VIN from exactly two sources:
  registration in `scripts/known_problems.json`, which needs a named defective
  upstream artifact and not just the diff; or adjudication into the
  machine-enumerated stale-cache class, which needs the diff to touch only
  elements 142/143/144/156/191, land on a cell `scripts/stale_cache_cells.json`
  lists, and point at a position that cell is stale at. A VIN the gate names is
  one *neither* source covered — never widen either to make it go away.
- **stale-cache gate fails** — read the detail. `INCONSISTENT` means the
  committed list disagrees with the summary printed beside it: it was
  hand-edited or its halves came from different scans, so regenerate it rather
  than patch it. `REJECTED` names either a jump past 500 newly stale cells *in
  the charset-regression shape* (recompute-only rows leapt, or the stale-cell
  count doubled — confirm `make answerkey-verify` is green and read
  `target/refresh/stale_cache.json`) or a non-empty
  `vpic.wmiyearvalidchars_cacheexceptions`, which is upstream changing how the
  proc reads the cache and needs a human to re-derive the scan's assumptions
  against `vpic/procs/spvindecode_errorcode.sql`. A large newly-stale count that
  is cache-lag after schemas dropped (`rows_only_in_recompute` flat or down) is
  reported, not rejected.
- **known-problems gate names a healed VIN** — upstream fixed the defect (or the
  dump stopped carrying it). Confirm against §-evidence in
  `docs/KNOWN_DEVIATIONS.md`, retire the entry from
  `scripts/known_problems.json`, and retire the section if its last VIN went.
  Never re-green it by widening the registry.
  If instead the detail says **UNVERIFIABLE**, the oracle was unreachable and
  nothing was proven either way — fix the oracle and re-run.
- **known-problems gate says a deviation "changed shape"** — the VIN still
  diverges, but not the way `HEAD`'s corpus froze it, so the evidence in
  `docs/KNOWN_DEVIATIONS.md` now describes something other than what happens.
  Re-investigate it as a fresh divergence: if the upstream defect moved, update
  the entry *and* its evidence section deliberately; if ultravin's side moved,
  that is a decoder regression wearing an old excuse. Never re-freeze it away —
  the re-freeze is what proposes the new shape, not what justifies it.
- **freeze skips oracle-crash VINs** — reported as a follow-up, not a failure:
  those are upstream defects (malformed `Pattern.keys` regexes) and a crash has
  no answer to snapshot. `freeze.py` catches the `psycopg.Error`, records the
  skip and carries on, wherever the VIN came from — including the `--vins` list,
  which in the refresh path is the committed corpus plus every registered
  deviation (that path no longer samples a fresh corpus at all). A crash the
  *sweep* hits is the one that bites: it lands in `oracle_errors` and **fails**
  the sweep gate unless the VIN is registered as `oracle-crash`. Neither path
  produces a mechanical traceback. Either way, document the VIN per
  `KNOWN_DEVIATIONS.md` before the run can go green.
- **re-issued pin detection** — `detect` compares the pinned URL's
  `Content-Length` against `dump_bytes` in the manifest (recorded since
  2026_07); a same-size re-issue is invisible to HEAD probes and surfaces as a
  build-data sha mismatch instead.
- **nothing detected for 2+ months** — `detect` warns (`stale=true`); NHTSA
  prunes files after ~8 months, so investigate before the window closes.
- **January runs** — the corpus records `oracle_current_year`; a fresh freeze
  always matches the current year, so the year-skip guard in
  `tests/test_parity_corpus.py` only bites stale corpora, not refreshed ones.
