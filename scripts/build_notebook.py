"""Generate virtualize_braun.ipynb.

Run: pixi run notebook       (regenerate, no outputs)
     pixi run notebook-run   (regenerate, then execute in place)

This script generates the notebook, so the narrative stays in one reviewable file.
Nobody edits the JSON by hand. Outputs exist only in the committed .ipynb. A regenerate
clears them. The next execution writes them again.
"""

from _notebook import BOOTSTRAP, code, md, write

md("""
> **This notebook needs an Arraylake account.** It writes an Icechunk repository and commits to it. The cells below hold the output of a completed run. That run wrote 1,052,916 virtual chunk references across 11 source objects, and stored zero expression bytes. To read the repository without running the notebook, read the printed values here.
""")

md("""
# A 12 GB cell atlas without a copy

The [Braun first-trimester human brain atlas](https://cellxgene.cziscience.com/collections/4d8fed08-2d6d-4692-b5ea-464f1d072077)
is on CZI's public S3 as 18 `.h5ad` files. This notebook builds an Icechunk repository over 11
of them: 1,654,197 cells, 11.95 GB. The repository stores **no expression data**.
Icechunk holds byte-range references into CZI's objects. The matrices stay where CZI put
them.

The notebook then edits metadata across six commits. Thus Icechunk versions the
annotation history separately from the data it describes.

**Braun, Emelie et al.** "Comprehensive cell atlas of the developing human brain."
*Science* (2023). [doi:10.1126/science.adf1226](https://doi.org/10.1126/science.adf1226)
""")

code(BOOTSTRAP + """
import os
import time
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

warnings.simplefilter("ignore")

import anndata as ad
import h5py
import pandas as pd
import scipy.sparse as sp
import zarr
from anndata.io import read_elem, write_elem
from arraylake import Client

import braun

REPO = "earthmover-demos/cellxgene-braun-atlas"
DATA_DIR = str(PROJECT_ROOT / "h5ads")
""")

md("""
## What VirtualiZarr can and cannot virtualize

An `.h5ad` is an HDF5 file. VirtualiZarr can point Zarr at HDF5 chunks if the compression
maps to a Zarr codec. The gzip in h5ad maps to a Zarr codec. The file has two clear parts:

| part of the file | virtualizable | why |
|---|---|---|
| `X/data`, `X/indices`, `X/indptr` | **yes** | numeric, chunked, gzip maps to `numcodecs.zlib` |
| dense `obsm`, `layers` | yes | same |
| `obs`, `var` | **no** | categorical `categories` and the dataframe index are HDF5 variable-length strings. They appear as numpy `object` dtype. Zarr v3 *deliberately rejects* `object` as ambiguous ([zarr-python#3077](https://github.com/zarr-developers/zarr-python/issues/3077), closed as resolved). Zarr v3 does store variable-length strings: `dtype="str"`, on disk `"string"`. The missing part is the automatic mapping, not the type system. |

This division suits the data. The expression matrix holds >99% of the bytes and never
changes. A reference is the correct storage for it. `obs` is small, and analysts rewrite
exactly this part. Native, versioned storage is correct for `obs`.

`checks/h5ad_virtualization.py` asserts both parts of that table.
""")

code("""
for c in braun.CLASSES:
    print(f"{c.cell_class:18s} {c.n_bytes/1e6:9.1f} MB  {c.n_cells:>9,} cells  -> {c.group}")
print(f"\\n{'total':18s} {sum(c.n_bytes for c in braun.CLASSES)/1e9:9.2f} GB  "
      f"{sum(c.n_cells for c in braun.CLASSES):>9,} cells")
""")

md("""
## Why we build the manifests from local copies

A chunk manifest holds one `(path, offset, length)` per chunk. To build one, VirtualiZarr
walks the HDF5 chunk B-tree. Over S3, each step goes through a Python file-object shim,
one round-trip at a time:

| manifest source | rate |
|---|---|
| over S3 | ~250 refs/s |
| local disk | ~150,000 refs/s |

This atlas needs approximately a million references. A remote build takes multiple
hours. A local build takes seconds. A manifest records only offsets. Thus we can build
locally and then rewrite the path with `rename_paths`. The result is identical, **if the
local copy is byte-identical to the referenced object.**

The procedure is: download once, build manifests, repoint at S3, discard the downloads.
The data materializes at *build* time only. The repository stores no expression data.
""")

code("""
os.makedirs(DATA_DIR, exist_ok=True)

def fetch(c):
    dest = os.path.join(DATA_DIR, c.local_name)
    if os.path.exists(dest) and os.path.getsize(dest) == c.n_bytes:
        return f"{c.cell_class:18s} already present"
    urllib.request.urlretrieve(c.https_url.decode(), dest)
    return f"{c.cell_class:18s} downloaded {os.path.getsize(dest)/1e6:.1f} MB"

t = time.time()
with ThreadPoolExecutor(max_workers=4) as pool:
    for line in pool.map(fetch, braun.CLASSES):
        print(line)
print(f"\\n{time.time()-t:.0f}s")
""")

md("""
### Check that each local copy has the same bytes as the referenced object

The whole approach depends on this assumption. Thus the notebook checks it.
Sizes must match. The four smallest Census objects are single-part uploads. Their ETag
*is* the md5, so the check compares the full content. The other objects are multipart
uploads, with up to 58 parts. Their ETag is a digest of the part digests, not of the
content. For those objects, the sampled byte ranges below are the real check.

This is also why the download route is important. CZI's Discover CDN serves the same
content *re-written*, with a size a few kB different. If you download from one route and
reference the other, the reads return corrupt data with no error.
""")

code("""
for c in braun.CLASSES:
    print(f"{c.cell_class:18s} {braun.check_local_copy(c, DATA_DIR)}")
""")

md("""
### One gene space

All 11 files share an identical 58,226-entry `var` index. Thus the per-class matrices
are column-aligned and directly comparable. Read the index once.
""")

code("""
smallest = min(braun.CLASSES, key=lambda c: c.n_bytes)
with h5py.File(os.path.join(DATA_DIR, smallest.local_name)) as h:
    var = read_elem(h["var"])
assert len(var) == braun.N_GENES
print(f"{len(var):,} genes: {list(var.index[:3])} ...")
var.head(3)
""")

md("""
## Commit 1: the matrices, by reference

Build each manifest from the local copy. Repoint every reference at the Census object.
Then verify that a sample of those references resolves to identical bytes on S3.

The `last_updated_at` stamp protects a reference against a change to the source object.
Icechunk turns the stamp into a conditional GET. If CZI rewrites an object, the read
fails with an error. It does not return different numbers without an error. Icechunk
truncates the stamp to whole seconds, so the code rounds it **up**. A value earlier than
the object's real mtime fails every read.
""")

code("""
repo = Client().get_repo(REPO)
checked_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).replace(microsecond=0)

session = repo.writable_session("main")
total_refs = 0
t = time.time()
for c in braun.CLASSES:
    ds = braun.virtual_matrix_from_local(c, DATA_DIR)
    assert list(ds.attrs["shape"]) == [c.n_cells, braun.N_GENES], c.cell_class
    braun.spot_check_refs(ds, c, DATA_DIR)
    # mode="w" lets the notebook re-run on a repository that holds an earlier run.
    # Without it, the write fails on the existing group.
    ds.vz.to_icechunk(session.store, group=f"{c.group}/X", mode="w",
                      last_updated_at=checked_at)
    total_refs += ds.vz.nrefs()
    print(f"{c.cell_class:18s} {ds.vz.nrefs():>8,} refs  nnz={ds.sizes['data_dim']:>12,}")

snap_matrices = session.commit(
    f"virtual refs: {len(braun.CLASSES)} cell classes from census {braun.CENSUS_RELEASE}"
)
print(f"\\n{total_refs:,} references built and spot-checked in {time.time()-t:.0f}s")
print(snap_matrices)
""")

md("""
Every chunk stays in CZI's bucket. The build copied nothing into the repository.
""")

code("""
locations = repo.readonly_session("main").all_virtual_chunk_locations()
objects = {loc.rsplit("/", 1)[1] for loc in locations}
print(f"{len(locations):,} virtual chunks across {len(objects)} source objects, all under")
print(" ", sorted({loc.rsplit('/', 1)[0] for loc in locations})[0])
assert all(loc.startswith(braun.PREFIX) for loc in locations)
assert len(objects) == len(braun.CLASSES)
""")

md("""
## Commit 2: provenance

A reference is only as reliable as the record of its target. That record gets its own
commit, so you can audit it separately from the data.
""")

code("""
session = repo.writable_session("main")
root = zarr.open_group(session.store, mode="a")
root.attrs.update({
    "collection_id": braun.COLLECTION_ID,
    "citation": braun.CITATION,
    "census_release": braun.CENSUS_RELEASE,
    "retrieved_at": checked_at.isoformat(),
})
for c in braun.CLASSES:
    root[c.group].attrs.update({
        "cell_class": c.cell_class,
        "dataset_id": c.dataset_id,
        "source": c.census_url,
        "permalink": c.permalink,
        "n_cells": c.n_cells,
    })
snap_provenance = session.commit("provenance: source URLs, dataset ids, citation")
print(snap_provenance)
""")

md("""
## Commit 3: `obs` and `var`, written natively

VirtualiZarr cannot virtualize this half. This half is also the part to version. Every
future annotation pass appends here. The expression matrix under it never changes.

`anndata.io.write_elem` writes the correct spec attributes: `encoding-type`, `_index`,
`column-order`, categorical `codes`/`categories`. These attributes let `anndata` load
each group as a genuine `AnnData`.
""")

code("""
session = repo.writable_session("main")
root = zarr.open_group(session.store, mode="a")
obs_by_class = {}
for c in braun.CLASSES:
    obs = pd.DataFrame(braun.read_obs(c, DATA_DIR),
                       index=pd.RangeIndex(c.n_cells).astype(str))
    obs_by_class[c.cell_class] = obs
    g = root[c.group]
    write_elem(g, "obs", obs)
    write_elem(g, "var", var)
    g.attrs.update({"encoding-type": "anndata", "encoding-version": "0.1.0"})
    print(f"{c.cell_class:18s} obs{obs.shape}  stages={obs.development_stage.nunique():>2}")
snap_obs = session.commit("obs and var written natively alongside the virtual matrices")
print(f"\\n{snap_obs}")
""")

md("""
### The result is a real AnnData

Virtual `X` and native `obs`/`var` form one object. `anndata` does not know that the
matrix is a set of pointers into the bucket of a different owner.
""")

code("""
store = repo.readonly_session("main").store
adata = ad.read_zarr(zarr.open(store, mode="r")["classes/erythrocyte"])
print(adata)
print(f"\\nX is {type(adata.X).__name__} with {adata.X.nnz:,} stored values")
adata.obs.development_stage.value_counts().reindex(braun.DEVELOPMENT_STAGES)
""")

md("""
## Commit 4: a derived summary

This commit stores the cells per developmental stage per cell class. It puts an analysis
result next to unchanged source data. This is the purpose of version control for array
data. The derived table and its source matrix share one history.
""")

code("""
counts = pd.DataFrame(
    {cls: obs.development_stage.value_counts() for cls, obs in obs_by_class.items()}
).reindex(braun.DEVELOPMENT_STAGES).fillna(0).astype(int)

session = repo.writable_session("main")
summary = zarr.open_group(session.store, mode="a").require_group("summaries")
summary.create_array("cells_per_stage", shape=counts.shape, dtype="int64",
                     chunks=counts.shape, overwrite=True)
summary["cells_per_stage"][:] = counts.to_numpy()
summary.attrs.update({"stages": list(counts.index), "cell_classes": list(counts.columns)})
snap_summary = session.commit("summary: cells per development stage per cell class")
print(snap_summary)
counts
""")

md("""
## Commits 5 and 6: a mistake, then its fix

Metadata is sometimes wrong. That is the reason for version control over metadata. The
next cell makes a mistake and its correction as two commits. Both commits stay reachable.
""")

code("""
session = repo.writable_session("main")
zarr.open_group(session.store, mode="a").attrs["census_release"] = "2024-01-01"
snap_wrong = session.commit("record census release (wrong: transcribed the wrong tag)")

session = repo.writable_session("main")
zarr.open_group(session.store, mode="a").attrs["census_release"] = braun.CENSUS_RELEASE
snap_fixed = session.commit(f"correct census release to {braun.CENSUS_RELEASE}")

for label, snap in [("as committed wrong", snap_wrong), ("as corrected", snap_fixed)]:
    s = repo.readonly_session(snapshot_id=snap)
    got = zarr.open_group(s.store, mode="r").attrs["census_release"]
    print(f"{label:20s} {snap}  census_release={got!r}")
""")

md("""
## Validation against the source

We built the references from local copies. Thus the full chain needs an end-to-end
check, not trust. The next cell reads matrices back from the repository, which fetches
from S3. It then compares them to the original files.
""")

code("""
store = repo.readonly_session("main").store
for c in sorted(braun.CLASSES, key=lambda c: c.n_bytes)[:4]:
    zg = zarr.open(store, mode="r")[f"{c.group}/X"]
    got = sp.csr_matrix((zg["data"][:], zg["indices"][:], zg["indptr"][:]),
                        shape=tuple(zg.attrs["shape"]))
    want = ad.read_h5ad(os.path.join(DATA_DIR, c.local_name)).X
    assert got.shape == want.shape and (got != want).nnz == 0, c.cell_class
    print(f"{c.cell_class:18s} {got.shape} read from S3, identical to source")
""")

md("""
## The history

Each run makes six commits. In order, they hold: matrices by reference, provenance, native
`obs` and `var`, the derived summary, a mistake and its correction. A re-run appends six
more commits. It does not start over. Thus a repository with more than one build shows
all of them.
""")

code("""
for s in repo.ancestry(branch="main"):
    print(f"{s.id}  {s.written_at:%Y-%m-%d %H:%M}  {s.message}")
""")

code("""
print(f"source file bytes       : {sum(c.n_bytes for c in braun.CLASSES)/1e9:>8.2f} GB")
print(f"expression bytes stored : {0:>8.2f} GB")
print(f"cells addressable       : {sum(c.n_cells for c in braun.CLASSES):>11,}")
print(f"virtual references      : {len(locations):>11,}")
""")

md("""
## What this cannot do

The scripts in `checks/` establish three limits:

**You cannot combine the matrices into one.** A Zarr array has a regular chunk grid.
Consider parts with lengths that are not exact multiples of a shared chunk size. A
concatenation of them needs one chunk to span two source files. For CSR the concat axis
is `nnz`, and no dataset controls `nnz`. Also, h5py picks a different chunk shape for
each file. Thus the store has one group per cell class. It has no single atlas-wide
matrix. The fix for this limit needs ZEP003 variable-length chunks.

**The chunking comes from the source, not from us.** References point at chunks that CZI
wrote. Thus you cannot tune the chunk grid for a query pattern. A task that needs
different chunks, such as a sort of rows by cell type, must materialize the data.

**You must verify reads, because one failure mode gives no error.** HDF5 COMPACT-layout
datasets under ~64 kB have no resolvable offset. For them, VirtualiZarr emits an empty
manifest. That manifest reads back as zeros with no error
([VirtualiZarr#527](https://github.com/zarr-developers/VirtualiZarr/issues/527)). None of
Braun's arrays are COMPACT. That is chance, not a guarantee.

The tradeoff is explicit. You give up control of the chunk grid. In return, you pay
nothing to store or version 12 GB of matrix.
""")

write("virtualize_braun.ipynb")
