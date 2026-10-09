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
To use the fork, run:

```bash
pixi run -e spatial sdpr
export PYTHONPATH=$PWD/vendor/spatialdata-1107/src
```

`sdpr` clones `li-em/store-without-a-path` and checks out commit `391427b`. That commit holds #1107 and the five commits.
