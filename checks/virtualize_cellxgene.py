"""A CELLxGENE h5ad matrix virtualizes into Icechunk, and reads back equal to anndata when h5ads/ has it.

Run: pixi run check-s3 [path/to/ground_truth.h5ad]

The script reads only chunk metadata over the network. The matrix bytes stay in CZI's public
bucket, and Icechunk stores byte-range references to them. It asserts that every chunk location
points into that bucket and that indptr is consistent with nnz. It asserts that data and indices
are not all zeros. VirtualiZarr #527 gives COMPACT-layout datasets an empty manifest, and such a
manifest reads as zeros with no error.

The equality check reads the same h5ad with anndata, which reads through h5py. It needs that
file on disk. The script finds it in h5ads/, or takes an explicit path, which wins. On the file
it finds itself, it first confirms that copy is the referenced bytes. Without a file it prints
the download URL and asserts the rest.

The script reads 1,522 byte ranges over the network, so it sets retries and a concurrency cap.
An icechunk.StorageError here is usually transient, and a re-run is safe.
"""

import os
import sys
import tempfile
import warnings
from datetime import datetime, timedelta, timezone

warnings.simplefilter("ignore")

import icechunk
import scipy.sparse as sp
import zarr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import braun

import _shards

# Braun et al. developing human brain, erythrocyte class: 8,959 cells, 12 dev stages.
DATASET_ID = "8775a6c6-b960-43ae-9f76-45c4acda3621"
SHARD = next(f for f in braun.CLASSES if f.dataset_id == DATASET_ID)

URL = braun.census_h5ad_url(DATASET_ID)
PREFIX = braun.PREFIX


def main():
    # An explicit path wins. Otherwise use the local shard the other checks download.
    ground_truth = sys.argv[1] if len(sys.argv) > 1 else None
    discovered = ground_truth is None
    if discovered:
        ground_truth = _shards.path_for(SHARD.cell_class)

    ds = braun.virtual_matrix(URL, braun.registry())
    n_cells = ds.sizes["indptr_dim"] - 1
    shape = dict(ds.attrs).get("shape")
    print(f"{URL}\n")
    print(f"  encoding-type : {ds.attrs.get('encoding-type')}  shape={shape}")
    for name, var in ds.variables.items():
        print(f"  {name:8s} {str(var.shape):12s} {str(var.dtype):8s} "
              f"chunks={var.data.metadata.chunks}")
    logical = sum(v.size * v.dtype.itemsize for v in ds.variables.values())
    print(f"\n  {ds.vz.nrefs()} virtual references covering {logical / 1e6:.1f} MB, "
          f"{ds.vz.nbytes} bytes resident in memory")

    with tempfile.TemporaryDirectory() as tmp:
        config = icechunk.RepositoryConfig.default()
        # The virtual read fetches 1,522 byte ranges. Retry each one, and cap the fan-out.
        config.storage = icechunk.StorageSettings(
            retries=icechunk.StorageRetriesSettings(
                max_tries=5, initial_backoff_ms=200, max_backoff_ms=4000),
            concurrency=icechunk.StorageConcurrencySettings(
                max_concurrent_requests_for_object=8),
        )
        config.set_virtual_chunk_container(
            icechunk.VirtualChunkContainer(
                PREFIX, icechunk.s3_store(region=braun.REGION, anonymous=True)
            )
        )
        repo = icechunk.Repository.create(
            icechunk.local_filesystem_storage(f"{tmp}/repo"),
            config=config,
            authorize_virtual_chunk_access=icechunk.containers_credentials(
                {PREFIX: icechunk.s3_anonymous_credentials()}
            ),
        )

        # Icechunk stores last_updated_at in whole seconds, so round up. A truncated value
        # before the real mtime of the object makes every read fail.
        checked_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).replace(
            microsecond=0
        )

        session = repo.writable_session("main")
        ds.vz.to_icechunk(session.store, group="X", last_updated_at=checked_at)
        snapshot = session.commit(
            f"virtualize {DATASET_ID} X from census {braun.CENSUS_RELEASE}"
        )
        print(f"\n  committed {snapshot}")

        rs = repo.readonly_session("main")
        locations = rs.all_virtual_chunk_locations()
        assert all(loc.startswith(PREFIX) for loc in locations), "unexpected chunk location"
        print(f"  every one of {len(locations)} chunks still lives in CZI's bucket")

        zg = zarr.open_group(rs.store, mode="r")["X"]
        data, indices, indptr = zg["data"][:], zg["indices"][:], zg["indptr"][:]

        # VirtualiZarr #527: an empty manifest reads back as zeros with no error.
        assert data.any(), "data read back all zeros (COMPACT layout?)"
        assert indices.any(), "indices read back all zeros (COMPACT layout?)"
        assert indptr[-1] == len(data), f"indptr tail {indptr[-1]} != nnz {len(data)}"
        assert len(indptr) == n_cells + 1

        matrix = sp.csr_matrix((data, indices, indptr), shape=tuple(shape))
        print(f"  rebuilt CSR {matrix.shape}, {matrix.nnz} stored values")

        if ground_truth:
            import anndata as ad

            if discovered:
                # Prove the local file is the object the references address, not the CDN copy.
                print(f"  local copy: {braun.check_local_copy(SHARD, _shards.DATA_DIR)}")
            want = ad.read_h5ad(ground_truth).X
            assert matrix.shape == want.shape, f"{matrix.shape} != {want.shape}"
            assert (matrix != want).nnz == 0, "virtual read does not match h5py"
            print(f"  every one of {matrix.nnz:,} values matches {ground_truth} exactly")
        else:
            print(f"  {_shards.skip_message([SHARD.cell_class])}")
            print("  (no h5py comparison; the rest of the check still asserted)")


if __name__ == "__main__":
    main()
