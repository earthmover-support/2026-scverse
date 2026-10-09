"""Generate scanpy_equivalence.ipynb.

Run: pixi run equivalence       (regenerate, no outputs)
     pixi run equivalence-run   (regenerate, then execute in place)

The notebook needs released packages only. It uses no account, no credentials and no fork.
"""

from _notebook import BOOTSTRAP, code, md, write

md("""
# Scanpy gets the same answers from a virtual AnnData

Claim: scanpy gives identical results on a virtual AnnData and on the `.h5ad` that it
references.

The dataset is the erythrocyte class of the
[Braun first-trimester human brain atlas](https://cellxgene.cziscience.com/collections/4d8fed08-2d6d-4692-b5ea-464f1d072077):
8,959 cells, 25.5 MB, in CZI's public Census bucket.

This run is anonymous. It needs no account and no credentials. It uses released packages
only. The repository it builds is local, in a temporary directory.
""")

code(BOOTSTRAP + """
import tempfile
import urllib.request
import warnings

warnings.simplefilter("ignore")

import anndata as ad
import icechunk
import numpy as np
import scanpy as sc
import zarr
from anndata.io import write_elem
from datetime import datetime, timedelta, timezone

import braun

SHARD = next(c for c in braun.CLASSES if c.cell_class == "ClassErythrocyte")
URL = braun.census_h5ad_url(SHARD.dataset_id, scheme="s3")
WORKDIR = tempfile.mkdtemp(prefix="scverse-equivalence-")

# Every read is anonymous. The notebook configures no credentials.
print(f"source   {URL}")
print("anonymous: yes")
""")

md("""
## Build a virtual AnnData

The Icechunk repository stores `X` as byte-range references into CZI's object. Its virtual
chunk container covers CZI's prefix, with anonymous credentials. The build reads chunk
metadata only. The matrix bytes stay in the bucket.
""")

code("""
ds = braun.virtual_matrix(URL, braun.registry())
print(f"{ds.vz.nrefs()} virtual references, {ds.vz.nbytes} bytes resident in memory")

config = icechunk.RepositoryConfig.default()
# The read fetches many byte ranges. Retry each one, and cap the fan-out.
config.storage = icechunk.StorageSettings(
    retries=icechunk.StorageRetriesSettings(
        max_tries=5, initial_backoff_ms=200, max_backoff_ms=4000),
    concurrency=icechunk.StorageConcurrencySettings(
        max_concurrent_requests_for_object=8),
)
config.set_virtual_chunk_container(
    icechunk.VirtualChunkContainer(
        braun.PREFIX, icechunk.s3_store(region=braun.REGION, anonymous=True)
    )
)
repo = icechunk.Repository.create(
    icechunk.local_filesystem_storage(f"{WORKDIR}/repo"),
    config=config,
    authorize_virtual_chunk_access=icechunk.containers_credentials(
        {braun.PREFIX: icechunk.s3_anonymous_credentials()}
    ),
)

# Icechunk stores last_updated_at in whole seconds, so round up.
checked_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).replace(microsecond=0)
session = repo.writable_session("main")
ds.vz.to_icechunk(session.store, group="X", last_updated_at=checked_at)
""")

md("""
## Write `obs` and `var` natively

HDF5 variable-length strings do not virtualize. Zarr v3 rejects the numpy `object` dtype
that they read as. The notebook thus reads `obs` and `var` from a local copy of the
`.h5ad`, and writes them as native Zarr chunks. Then it commits and reads the group back
with `ad.read_zarr`.
""")

code("""
local = f"{WORKDIR}/{SHARD.local_name}"
urllib.request.urlretrieve(SHARD.https_url.decode(), local)
print(braun.check_local_copy(SHARD, WORKDIR))

frames = braun.read_elements_at(SHARD.https_url, ["obs", "var"], local)

root = zarr.open_group(session.store, mode="a")
write_elem(root, "obs", frames["obs"])
write_elem(root, "var", frames["var"])
root.attrs.update({"encoding-type": "anndata", "encoding-version": "0.1.0"})
print(session.commit("virtual X, native obs and var"))

rs = repo.readonly_session("main")
assert all(loc.startswith(braun.PREFIX) for loc in rs.all_virtual_chunk_locations())
virtual = ad.read_zarr(zarr.open_group(rs.store, mode="r"))
print(virtual)
""")

md("""
## Read the same file directly

The direct run reads the local copy with `ad.read_h5ad`. This is the baseline.
""")

code("""
direct = ad.read_h5ad(local)
print(direct)
assert virtual.shape == direct.shape
assert (virtual.X != direct.X).nnz == 0, "X differs between the virtual and direct reads"
print("X identical:", virtual.X.nnz, "stored values")
""")

md("""
## Run the same pipeline on both

The pipeline normalizes each cell to 10,000 counts, applies `log1p`, and selects the top
2,000 highly variable genes.
""")

code("""
def pipeline(adata):
    a = adata.copy()
    sc.pp.normalize_total(a, target_sum=1e4)
    sc.pp.log1p(a)
    sc.pp.highly_variable_genes(a, n_top_genes=2000)
    return a

virtual_run, direct_run = pipeline(virtual), pipeline(direct)
""")

md("""
## Compare

The cell asserts equality. It does not print a similarity and continue.
""")

code("""
v = set(virtual_run.var_names[virtual_run.var["highly_variable"]])
d = set(direct_run.var_names[direct_run.var["highly_variable"]])
jaccard = len(v & d) / len(v | d)
# Genes with no counts have NaN dispersion. Both runs must agree on which genes those are.
vd = virtual_run.var["dispersions_norm"].values
dd = direct_run.var["dispersions_norm"].values
assert (np.isnan(vd) == np.isnan(dd)).all(), "the runs disagree on undefined dispersions"
finite = np.isfinite(vd)
corr = np.corrcoef(vd[finite], dd[finite])[0, 1]
print(f"{finite.sum()} genes have a defined dispersion, {(~finite).sum()} have none")
print(f"highly variable genes: {len(v)} virtual, {len(d)} direct")
print(f"Jaccard: {jaccard:.4f}")
print(f"dispersion correlation: {corr:.6f}")
assert v == d, f"{len(v ^ d)} genes differ between the two runs"
assert jaccard == 1.0
""")

md("""
## What the run shows

Scanpy selects the same 2,000 genes from both objects. The two dispersion vectors correlate
as printed above, over the genes with a defined dispersion. `X` is identical, so scanpy has no way to tell the two objects apart.

The run does not show that all of the AnnData is virtual. `obs` and `var` are native
Zarr chunks, not virtual references. Only `X` is virtual.
""")

write("scanpy_equivalence.ipynb")
