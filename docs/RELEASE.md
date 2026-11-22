# Builds and releases

No workflow in this fork builds a release or publishes one. Nothing pushes a
tag, uploads a wheel to a package index, publishes the Rust crate, or attaches
an asset to a GitHub release. CI (`.github/workflows/ci.yaml`) and the security
scans (`.github/workflows/security.yaml`) only check code.

## Versions come from tags

The workspace `Cargo.toml` permanently says `0.0.0`.
`.github/stamp-version.sh vX.Y.Z` writes a tag's version into
`Cargo.toml` and `Cargo.lock` before a build, so the wheel, the sdist, and
`ultravin.__version__` all carry it. There is no version-bump commit. A build
that skips the stamp reports `0.0.0`.

## The embedded data artifact

The decoder embeds `crates/ultravin/data/vpic.rkyv` (~83 MB) via
`include_bytes!`. That file is a gitignored build product: a pure, deterministic
function of the pinned NHTSA dump recorded in `vpic/manifest.json` (month, source
URL, dump `sha256`, and the artifact's `blake3`).

The `build-data` action (`.github/actions/build-data`) rebuilds it in CI. It
downloads the pinned dump, checks the `sha256`, runs `vpic-import`, and asserts
that the emitted artifact's `blake3` matches the manifest. The sdist embeds the
artifact too (`[tool.maturin] include`), so a source install works offline.

The Rust crate's default `download-data` feature fetches
`releases/download/v<crate version>/vpic.rkyv` on a crate user's first build.
This fork attaches no such asset, so build the crate with a supplied
`ULTRAVIN_DATA` file or with `external-data` and `Db::open` at runtime. Both are
described in `crates/ultravin/README.md`.

## Wheels

The wheel is abi3 (`pyo3/abi3-py310`): one wheel per platform serves Python
3.10+. The crate is pure Rust (blake3 uses its `pure` feature), so every cross
target builds with the default cross-gcc.

A bare install of the wheel brings no dependency. The `ultravin` command needs
the `cli` extra, which adds `typer`.

## Build and check a wheel locally

```bash
make build-wheel        # wheel lands in target/wheels/
make wheel-smoke        # installs it into throwaway venvs and decodes
pip install 'target/wheels/ultravin-0.0.0-<platform>.whl[cli]'
ultravin version
```

`make wheel-smoke` runs `scripts/wheel_smoke.py` in two stages. It first checks
that the bare install has no `typer` and decodes a VIN. It then installs the
`cli` extra and checks that the `ultravin` console script decodes a VIN.

To take a new NHTSA month, see [DATA_REFRESH.md](DATA_REFRESH.md).
