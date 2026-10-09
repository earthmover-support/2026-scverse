"""This verifier checks 0003-keep-the-element-location.patch on a store with no path.

The patch makes `read_zarr` read that store. This verifier uses no virtual data and no Icechunk.
SpatialData's own `write()` writes `spatialdata.datasets.blobs()` to disk. The verifier copies each
key into a `zarr.storage.MemoryStore`. `read_zarr` then reads that store back. The docstring of
`read_zarr` lists this store type as supported.

The verifier is two-sided. It asserts the failure and the fix:

    pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_read.py --unpatched
    pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_read.py --patched

With neither flag, the verifier runs both sides, each in its own clone. `_bootstrap` explains why
the verifier patches the checkout itself. The verifier does not trust a checkout prepared by hand.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import under_patched_clone

BRANCH = "feat/zarr-store-class"
UPSTREAM = "https://github.com/selmanozleyen/spatialdata.git"
SERIES = ["0001-require-ome-zarr-0.21.0.patch",
          "0002-parquet-fs-resolver-hook.patch",
          "0003-keep-the-element-location.patch"]
#: The raster reader raises this text when `ome_zarr.io.ZarrLocation` reads the container root,
#: not the element, of a store that `store_from_group` cannot re-root.
UNPATCHED_MARKER = "len(nodes) = 0"

if "--unpatched" not in sys.argv and "--patched" not in sys.argv:
    here = [sys.executable, os.path.abspath(__file__)]
    codes = [subprocess.run([*here, side]).returncode for side in ("--unpatched", "--patched")]
    raise SystemExit(max(codes))

PATCHED = "--patched" in sys.argv
under_patched_clone(UPSTREAM, BRANCH, SERIES if PATCHED else None)

warnings.simplefilter("ignore")

import numpy as np
import zarr
from spatialdata import read_zarr
from spatialdata.datasets import blobs

#: All element types except geometry. Geometry needs the filesystem hook in the other patch.
SELECTION = ("images", "labels", "tables")


async def copy_into_memory(source: zarr.storage.LocalStore) -> zarr.storage.MemoryStore:
    """Return a MemoryStore with exactly the keys on disk. Thus the test covers only the *read*."""
    memory = zarr.storage.MemoryStore()
    prototype = zarr.core.buffer.default_buffer_prototype()
    async for key in source.list():
        await memory.set(key, await source.get(key, prototype=prototype))
    return memory


work = tempfile.mkdtemp()
sdata = blobs()
sdata.write(f"{work}/on_disk.zarr")
memory = asyncio.run(copy_into_memory(zarr.storage.LocalStore(f"{work}/on_disk.zarr",
                                                              read_only=True)))
print(f"blobs() written by SpatialData's own write(), copied into a MemoryStore: "
      f"{len(memory._store_dict):,} keys\n")

if not PATCHED:
    try:
        read_zarr(memory, selection=SELECTION)
    except Exception as exc:
        print(f"  {type(exc).__name__}: {str(exc)[:160]}")
        assert UNPATCHED_MARKER in str(exc), (
            f"unpatched, but the failure is not the documented one: {exc!r}. This verifier "
            "asserts the failure too, so a checkout that breaks differently is reported rather "
            "than passing as a reproduction."
        )
        print("\nVERDICT: unpatched, and the raster reader reads the container root of a store "
              "zarr\n         cannot re-root, on a store SpatialData itself wrote, which its "
              "docstring\n         says is supported")
        raise SystemExit(0)
    raise SystemExit("unpatched, but read_zarr succeeded; this finding no longer holds")

from_disk = read_zarr(f"{work}/on_disk.zarr", selection=SELECTION)
from_memory = read_zarr(memory, selection=SELECTION)

ok = True
for kind in SELECTION:
    for name, expected in getattr(from_disk, kind).items():
        got = getattr(from_memory, kind)[name]
        if kind == "tables":
            # `X` can be sparse. numpy does not compare a sparse matrix elementwise.
            dense = [np.asarray(x.todense() if hasattr(x, "todense") else x)
                     for x in (got.X, expected.X)]
            same = (np.array_equal(*dense)
                    and list(got.obs.columns) == list(expected.obs.columns))
            detail = f"X {got.X.shape}, obs {len(got.obs.columns)} columns"
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
        print(f"  {kind}/{name:<26} {detail:<34} identical to the on-disk read: {same}")

assert ok, "an element read from the MemoryStore differs from the same element read from disk"
print("\n  geometry is not read here: it needs a filesystem, which is the fallback in\n"
      "  0002-parquet-fs-resolver-hook.patch. With both, every element type reads from a\n"
      "  store that has no path.")
print("\nVERDICT: the patch reads every raster and table from a store with no path, and the\n"
      "         elements are identical to reading the same store from disk")
