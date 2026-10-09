"""Generate spatialdata_versioning.ipynb.

Run: pixi run -e spatial versioning        (regenerate)
     pixi run -e spatial versioning-run    (regenerate, then execute)

The notebook needs the pinned SpatialData fork on PYTHONPATH. See docs/fork-pin.md.
"""

from _notebook import BOOTSTRAP_TERSE, code, md, write

md("""
# Versioning a SpatialData store

**Claim:** an Icechunk store keeps every committed version of a SpatialData dataset readable.
A later edit adds a snapshot. It does not overwrite the earlier state.

> **This notebook needs the pinned fork.** SpatialData on Icechunk depends on
> [pull request #1107](https://github.com/scverse/spatialdata/pull/1107) plus five commits.
> Released `spatialdata` 0.8.0 lacks them. Pixi cannot pin the fork. `docs/fork-pin.md` explains why
> and gives the steps. Fetch the fork, then run with the absolute path:
>
> ```shell
> pixi run -e spatial sdpr
> PYTHONPATH=<this repository>/vendor/spatialdata-1107/src pixi run -e spatial versioning-run
> ```
>
> The comparison link is
> [scverse/spatialdata...li-em:store-without-a-path](https://github.com/scverse/spatialdata/compare/main...li-em:spatialdata:li-em/store-without-a-path).

The data is `spatialdata.datasets.blobs()`, reduced to an image, a labels element and a table.
""")

code(BOOTSTRAP_TERSE + """
import os
import tempfile

import icechunk
import spatialdata
import zarr
from spatialdata import SpatialData, read_zarr
from spatialdata._io import write_shapes, write_table
from spatialdata.datasets import blobs

import icechunk_spatialdata as isd

if not isd.parquet_in_store_available():
    raise RuntimeError("this spatialdata lacks the fork; see docs/fork-pin.md")
print(f"spatialdata {spatialdata.__version__}   icechunk {icechunk.__version__}")
""")

md("""
## The subset

`blobs()` also holds shapes and points. The notebook builds the subset by hand, and it asserts
that the subset holds neither. Thus the first two commits write rasters and a table only.
""")

code("""
source = blobs()
sdata = SpatialData(
    images={"blobs_image": source.images["blobs_image"]},
    labels={"blobs_labels": source.labels["blobs_labels"]},
    tables={"table": source.tables["table"]},
)
assert not sdata.shapes, "this notebook writes rasters and a table only"
assert not sdata.points, "this notebook writes rasters and a table only"
print("elements:", sorted(sdata.images), sorted(sdata.labels), sorted(sdata.tables))
""")

md("""
## Commit 1: write the three elements

The table gets a `review` column with the value `pending`. The `transaction` commits when the
block ends without an error.
""")

code("""
repo = icechunk.Repository.create(
    icechunk.local_filesystem_storage(os.path.join(tempfile.mkdtemp(), "repo"))
)
sdata.tables["table"].obs["review"] = "pending"

with isd.transaction(repo, "main", "write image, labels and table") as first, \\
        isd.parquet_in_store():
    sdata.write(first.session.store)
print("first snapshot:", first.snapshot)
""")

md("""
## Commit 2: change the table's `obs`

`SpatialData.write_element` is the natural call here, and it fails even with the fork. It raises
`ValueError: ... appears not to be backed by a Zarr storage`, because `read_zarr` on a store sets
no `path` on the object. So the notebook does not use it. It reads the dataset from the open
session, edits the table, deletes the old table group, and calls SpatialData's `write_table`
on the session's root group. `icechunk-SpatialData/UPSTREAM.md` records this limit.
""")

code("""
with isd.transaction(repo, "main", "mark the table reviewed") as second, isd.parquet_in_store():
    edit = read_zarr(second.session.store)
    edit.tables["table"].obs["review"] = "reviewed"
    root = zarr.open_group(second.session.store, mode="a")
    del root["tables/table"]
    write_table(edit.tables["table"], root["tables"], "table")
print("second snapshot:", second.snapshot)
""")

code("""
# The object that `read_zarr` returned has no path, so `write_element` refuses it.
try:
    edit.write_element("table", overwrite=True)
except ValueError as exc:
    print(f"ValueError: {exc}")
""")

md("""
## The history

`ancestry` lists the snapshots from the newest to the oldest. The last entry is the empty
snapshot that Icechunk makes when it creates a repository.
""")

code("""
for entry in repo.ancestry(branch="main"):
    print(f"  {entry.id}  {entry.message}")
""")

md("""
## Both versions are readable

The first read uses the id of the first snapshot. The second read uses the tip of `main`.
""")

code("""
def review_values(**session_arguments):
    with isd.parquet_in_store():
        data = read_zarr(repo.readonly_session(**session_arguments).store)
    return list(data.tables["table"].obs["review"].unique())


before = review_values(snapshot_id=first.snapshot)
after = review_values(branch="main")
print("first snapshot, obs['review']:", before)
print("branch tip,     obs['review']:", after)
assert before == ["pending"] and after == ["reviewed"]
""")

md("""
## Commit 3: write shapes

SpatialData writes shapes as a Parquet file. That file needs a filesystem path. An Icechunk store
has no path. **Released packages cannot write shapes to Icechunk.** The same call fails with
`AttributeError: 'IcechunkStore' object has no attribute 'root'`. `pixi run check-store-path`
proves it: it writes shapes to a local store, then to an Icechunk store, and shows the failure.
With the fork, the write works.
""")

code("""
with isd.transaction(repo, "main", "add shapes") as third, isd.parquet_in_store():
    shapes_group = zarr.open_group(third.session.store, mode="a").require_group("shapes")
    write_shapes(source.shapes["blobs_circles"], shapes_group.create_group("blobs_circles"))
print("third snapshot:", third.snapshot)

with isd.parquet_in_store():
    final = read_zarr(repo.readonly_session(branch="main").store)
commits = [entry for entry in repo.ancestry(branch="main")
           if entry.id in (first.snapshot, second.snapshot, third.snapshot)]
elements = {kind: sorted(getattr(final, kind))
            for kind in ("images", "labels", "points", "shapes", "tables")}
print("commits written:", len(commits))
print("elements in the final snapshot:", elements)
""")

md("""
## Result

The repository holds **three commits** after the initial empty snapshot. The first snapshot still
reads `review = pending`. The branch tip reads `review = reviewed`. The final snapshot holds the
image `blobs_image`, the labels `blobs_labels`, the shapes `blobs_circles` and the table `table`.
""")

write("spatialdata_versioning.ipynb")
