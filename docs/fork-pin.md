# Why the SpatialData fork is not a pixi pin

The `spatial` environment needs spatialdata pull request #1107 and five more commits. The
fork is `li-em/spatialdata`, commit `391427b274e046b7068348aa68987589e3773748`.

## What failed

The manifest declared the fork as a git dependency of the `spatial` feature. `pixi lock`
solved the conda side for both platforms. The PyPI side failed on `osx-arm64`:

```
Error:   × failed to solve the pypi requirements of environment 'spatial' for
  │ platform 'osx-arm64'
  ├─▶ failed to resolve pypi dependencies
  ╰─▶ Because only spatialdata<0.8 is available and icechunk-
      spatialdata==0.0.1 depends on spatialdata>=0.8, we can conclude that
      icechunk-spatialdata==0.0.1 cannot be used.
      And because only icechunk-spatialdata==0.0.1 is available and you
      require icechunk-spatialdata, we can conclude that your requirements
      are unsatisfiable.
```

## Cause

`spatialdata` takes its version from git tags (`hatch-vcs`). The fork carries stale tags,
so the build reports a version below 0.8 (inferred from the solver error). `icechunk-spatialdata` requires `>=0.8`.

## What the repository does

The manifest drops the git pin and the `ome-zarr` pin. The lock then holds released
`spatialdata` 0.8.0 from PyPI in the `spatial` environment. That release lacks #1107.
To use the fork, fetch it once:

```bash
pixi run -e spatial sdpr
```

`sdpr` clones `li-em/store-without-a-path` and checks out commit `391427b`. That commit holds
#1107 and the five commits. Then prefix every command with the absolute path `sdpr` prints:

```bash
PYTHONPATH=<absolute path to this repository>/vendor/spatialdata-1107/src pixi run -e spatial <command>
```

The path must be absolute, because `nbconvert` runs its kernel in the notebook directory.

## What changes without it

Without `PYTHONPATH`, `spike-test` skips 14 tests. With it, the same run gives 27 passed and
6 skipped.

Five notebooks need the fork. `spatialdata_on_icechunk` stops at an explicit check.
`atera_from_arraylake`, `squidpy_xenium_virtual` and `xenium_tutorial_virtual` call
`isd.parquet_in_store()`, which raises a `RuntimeError` without it.

`xenium_from_arraylake` calls `isd.parquet_in_store()` in two cells. The shapes cell guards the
call and falls back to `geopandas`. That fallback returns the raw GeoParquet geometry. It skips
the coordinate transformations, and it builds no SpatialData object. A later cell reads the image
element with `read_zarr` inside `isd.parquet_in_store()`. That cell has no guard. So the notebook
cannot run to the end without the fork.

`virtualize_braun` does not use the fork.

## What the fork fixes

SpatialData writes shapes and points through a filesystem path. `parquet_fs_and_path` accepts
only `LocalStore` and `FsspecStore`, so an Icechunk store has no path to give. The fork lifts
that limit.
