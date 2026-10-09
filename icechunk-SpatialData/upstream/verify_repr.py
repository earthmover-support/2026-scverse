"""This verifier checks 0005-points-rows-through-the-frame-filesystem.patch on a remote path.

The patch makes `repr()` work on an object read from a remote path. This verifier uses no
Icechunk. SpatialData's own `write()` writes `spatialdata.datasets.blobs()` to a `memory://` UPath.
The verifier reads the object back and prints it. The repr counts points rows from the parquet
metadata of the backing files. The repr opened those files as local paths.

The verifier is two-sided. It asserts the failure and the fix:

    pixi run -e spatial python icechunk-SpatialData/upstream/verify_repr.py --unpatched
    pixi run -e spatial python icechunk-SpatialData/upstream/verify_repr.py --patched

With neither flag, the verifier runs both sides, each in its own clone. The patch is independent:
it applies without the other three patches.
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
PATCH = "0005-points-rows-through-the-frame-filesystem.patch"
#: The unpatched repr raises this text. pyarrow opens the backing file as a local path.
UNPATCHED_MARKER = "Failed to open local file"

if "--unpatched" not in sys.argv and "--patched" not in sys.argv:
    here = [sys.executable, os.path.abspath(__file__)]
    codes = [subprocess.run([*here, side]).returncode for side in ("--unpatched", "--patched")]
    raise SystemExit(max(codes))

PATCHED = "--patched" in sys.argv
under_patched_clone(UPSTREAM, BRANCH, PATCH if PATCHED else None)

warnings.simplefilter("ignore")

from fsspec.implementations.memory import MemoryFileSystem
from spatialdata import SpatialData
from spatialdata._io._utils import get_dask_backing_files
from spatialdata.datasets import blobs
from upath import UPath

sdata = blobs()
target = UPath("memory://blobs.zarr", fs=MemoryFileSystem(skip_instance_cache=True))
sdata.write(target, overwrite=True)
back = SpatialData.read(target)
print(f"blobs() written to {target} by SpatialData's own write() and read back\n")

if not PATCHED:
    try:
        repr(back)
    except Exception as exc:
        print(f"  {type(exc).__name__}: {str(exc)[:160]}")
        assert UNPATCHED_MARKER in str(exc), (
            f"unpatched, but the failure is not the documented one: {exc!r}. This verifier "
            "asserts the failure too, so a checkout that breaks differently is reported rather "
            "than passing as a reproduction."
        )
        print("\nVERDICT: unpatched, and repr() of an object read from a memory:// path raises,\n"
              "         because it opens the parquet backing files as local paths")
        raise SystemExit(0)
    raise SystemExit("unpatched, but repr() succeeded; this finding no longer holds")

text = repr(back)
ok = True
for name, frame in sdata.points.items():
    expected = f"{name!r}: DataFrame with shape: ({len(frame)}, "
    found = expected in text
    ok &= found
    print(f"  points/{name:<20} row count in the repr: {found}")
    print(f"  backing files: {get_dask_backing_files(back.points[name])}")

assert ok, "the repr does not show the row count of every points element"
print("\nVERDICT: the patch reads the parquet metadata through the frame's own filesystem, and\n"
      "         the repr shows the row counts")
