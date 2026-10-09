"""This verifier checks whether a SpatialData write is a unit of work on each store.

It also shows that the store type decides the answer. `_transaction.py` in this repo has 37 lines.
Its docstring makes a claim that it never checked:
"The discard is the necessary capability. A filesystem store cannot offer it." This verifier
checks that claim on both stores. It uses the same sequence and the same library code.

The sequence is the usual one. The job writes a dataset, then starts the next step of the work.
That step fails. The verifier induces nothing inside `write()`. It simulates no crash and
monkeypatches nothing. The verifier only checks which data remains after the failure.

The verifier needs the patch series, because 0004 adds the write to a session store:

    pixi run -e spatial python icechunk-SpatialData/upstream/verify_transaction_semantics.py

The verifier has no unpatched side. Without the patches, `sdata.write(session.store)` raises
`NotImplementedError` before the verifier can show anything. `verify_store_write.py` already
asserts that error.
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import under_patched_clone

BRANCH = "feat/zarr-store-class"
UPSTREAM = "https://github.com/selmanozleyen/spatialdata.git"
SERIES = ["0001-require-ome-zarr-0.21.0.patch",
          "0002-parquet-fs-resolver-hook.patch",
          "0003-keep-the-element-location.patch",
          "0004-write-to-a-store-without-a-path.patch"]

under_patched_clone(UPSTREAM, BRANCH, SERIES)

warnings.simplefilter("ignore")

import icechunk
import zarr
from spatialdata import SpatialData
from spatialdata.datasets import blobs


class AnalysisFailed(Exception):
    """The second step of the work raises this error after the write."""


def sample() -> SpatialData:
    """Return rasters and a table.

    Geometry needs the resolver from 0002 registered. This verifier does not examine geometry.
    """
    sdata = blobs()
    for name in list(sdata.shapes):
        del sdata.shapes[name]
    for name in list(sdata.points):
        del sdata.points[name]
    return sdata


work = Path(tempfile.mkdtemp())
print("the same two-step job, failing at step two, against each store\n")

# --- a filesystem path ----------------------------------------------------------------------
path = work / "on_disk.zarr"
try:
    sample().write(path)
    raise AnalysisFailed
except AnalysisFailed:
    pass

survived = sorted(p.name for p in path.iterdir()) if path.exists() else []
left_behind = [name for name in ("images", "labels", "tables") if (path / name).exists()]
print(f"  path        {path.name} exists: {path.exists()}, holding {left_behind}")
assert path.exists(), "the write did not happen at all, so this proves nothing about durability"
assert left_behind, "nothing was written, so there is no partial dataset to be left with"
print("              the elements from step one are on disk, and there is no way to unwind them:")
print("              a reader arriving now sees a dataset, not a failed job")

# --- an icechunk session --------------------------------------------------------------------
repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(work / "repo")))
# The verifier pre-creates nothing. `write()` calls `zarr.create_group(overwrite=False)`.
# That call refuses a store with a root group, exactly as it refuses an occupied path.
# The "unchanged" check compares against the repository's own initial snapshot.
before = [entry.id for entry in repo.ancestry(branch="main")]

session = repo.writable_session("main")
try:
    sample().write(session.store)
    raise AnalysisFailed          # The commit that makes the write durable does not run.
except AnalysisFailed:
    pass

after = [entry.id for entry in repo.ancestry(branch="main")]
try:
    holds = sorted(zarr.open_group(repo.readonly_session("main").store, mode="r"))
except zarr.errors.GroupNotFoundError:
    holds = []          # No root group exists. The abandoned session wrote nothing to the branch.
print(f"\n  icechunk    branch has {len(after)} snapshot(s), unchanged: {after == before}")
print(f"              the store holds {holds}")
assert after == before, f"the branch moved: {before} -> {after}"
assert not holds, f"the abandoned session is visible on the branch: {holds}"

# --- the successful case still commits ------------------------------------------------------
session = repo.writable_session("main")
sdata = sample()
sdata.write(session.store)
snapshot = session.commit("the same job, finishing")
read = SpatialData.read(repo.readonly_session("main").store)
print(f"\n  icechunk    committed {snapshot}")
print(f"              reads back {sorted(read.images)} {sorted(read.labels)} {sorted(read.tables)}")
assert set(read.images) == set(sdata.images), "images differ after the committed write"
assert set(read.labels) == set(sdata.labels), "labels differ after the committed write"
assert set(read.tables) == set(sdata.tables), "tables differ after the committed write"
assert len([e.id for e in repo.ancestry(branch="main")]) == len(before) + 1

print("\n  What makes the difference is not a wrapper. `write(session.store)` stages, and the\n"
      "  branch moves only at `commit`, so an exception between the two discards the work by\n"
      "  doing nothing. On a path each element is durable as it lands, so there is nothing to\n"
      "  discard with. That is a property of the store, and it is the whole of what a\n"
      "  `transaction` context manager would wrap: 37 lines around `session.commit`.")
print("\nVERDICT: with the series applied, a SpatialData write is a unit of work on an Icechunk\n"
      "         session and is not one on a path. No code from this project is involved")
