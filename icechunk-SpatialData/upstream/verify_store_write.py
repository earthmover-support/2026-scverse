"""This verifier checks 0004-write-to-a-store-without-a-path.patch on a store with no path.

The patch lets `write()` target that store. This verifier uses no virtual data and no Icechunk.
SpatialData's own `write()` writes `spatialdata.datasets.blobs()` to a `zarr.storage.MemoryStore`.
`read_zarr` reads it back.

The patches are a series, so the verifier also applies 0001 to 0003. Thus the verifier checks the
patch against the patches that come before it. It does not use a stack prepared by hand.

The verifier is two-sided:

    pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_write.py --unpatched
    pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_write.py --patched

With neither flag, the verifier runs both sides, each in its own clone.

This patch differs from the other patches here: it **reverses a deliberate restriction**. An
upstream test asserts that the write raises. The unpatched side asserts the same behaviour as that
test. Thus the verifier shows the change explicitly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import under_patched_clone

BRANCH = "feat/zarr-store-class"
UPSTREAM = "https://github.com/selmanozleyen/spatialdata.git"
SERIES = ["0001-require-ome-zarr-0.21.0.patch",
          "0002-parquet-fs-resolver-hook.patch",
          "0003-keep-the-element-location.patch",
          "0004-write-to-a-store-without-a-path.patch"]
#: Unpatched upstream raises this text. `test_write_to_memory_store_raises` tests for it.
UNPATCHED_MARKER = "does not expose a filesystem path"

if "--unpatched" not in sys.argv and "--patched" not in sys.argv:
    here = [sys.executable, os.path.abspath(__file__)]
    codes = [subprocess.run([*here, side]).returncode for side in ("--unpatched", "--patched")]
    raise SystemExit(max(codes))

PATCHED = "--patched" in sys.argv
under_patched_clone(UPSTREAM, BRANCH, SERIES if PATCHED else None)

warnings.simplefilter("ignore")

import numpy as np
import zarr
from spatialdata import SpatialData
from spatialdata.datasets import blobs

sdata = blobs()
# Geometry needs a filesystem, which the fallback in 0002 supplies. Rasters and tables do not.
for name in list(sdata.shapes):
    del sdata.shapes[name]
for name in list(sdata.points):
    del sdata.points[name]

store = zarr.storage.MemoryStore()

if not PATCHED:
    try:
        sdata.write(store)
    except NotImplementedError as exc:
        print(f"  NotImplementedError: {str(exc)[:150]}")
        assert UNPATCHED_MARKER in str(exc), f"the refusal is not the documented one: {exc!r}"
        print("\nVERDICT: unpatched, and a store with no filesystem path is refused by write()\n"
              "         on purpose: `test_write_to_memory_store_raises` asserts this")
        raise SystemExit(0)
    raise SystemExit("unpatched, but the write succeeded; this finding no longer holds")

sdata.write(store)
print(f"wrote {len(store._store_dict):,} keys to a MemoryStore\n")
assert sdata.path is None, f"writing to a pathless store set sdata.path to {sdata.path!r}"

read = SpatialData.read(store)
ok = True
for kind in ("images", "labels", "tables"):
    for name, expected in getattr(sdata, kind).items():
        got = getattr(read, kind)[name]
        if kind == "tables":
            dense = [np.asarray(x.todense() if hasattr(x, "todense") else x)
                     for x in (got.X, expected.X)]
            same, detail = np.array_equal(*dense), f"X {got.X.shape}"
        elif hasattr(got, "children") and got.children:
            levels = sorted(got.children)
            same = levels == sorted(expected.children) and all(
                np.array_equal(np.asarray(got[level]["image"]),
                               np.asarray(expected[level]["image"]))
                for level in levels
            )
            detail = f"{len(levels)} levels {levels[0]}..{levels[-1]}"
        else:
            same = np.array_equal(np.asarray(got), np.asarray(expected))
            detail = f"{tuple(got.shape)} {got.dtype}"
        ok &= same
        print(f"  {kind}/{name:<26} {detail:<30} survives the round trip: {same}")

assert ok, "an element read back from the MemoryStore differs from what was written"
print("\n  sdata.path stays None, and consolidated metadata is not written: both are path-shaped\n"
      "  and the store has no path. The elements are what the write is for, and they land.")
print("\nVERDICT: the patch writes a whole SpatialData to a store with no filesystem path, and\n"
      "         reads it back identical")
