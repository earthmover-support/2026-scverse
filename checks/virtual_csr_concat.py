"""VirtualiZarr cannot concatenate virtual h5ad CSR matrices unless every part is a multiple of one shared chunk size.

Run: pixi run check-concat

A regular Zarr chunk grid breaks when a part ends in a partial chunk. Take file A (nnz=1750,
chunk=500) and file B. B starts at index 1750, inside the fourth chunk of A. That chunk needs
bytes from two source files, and one byte range cannot express this.

A CSR concatenation joins along nnz, which the data fixes and the writer does not control. The
nnz of a file is almost never a multiple of its chunk size. h5py also chunks each file
differently.

The Zarr data model is not the blocker. A rectilinear chunk grid describes this concatenation.
zarr-python ships it
behind `zarr.config.set({"array.rectilinear_chunks": True})`. The blocker is VirtualiZarr, which
requires uniform chunk shapes when it combines manifests.

The script asserts six concatenation cases, the differing h5py chunk shapes, and the rectilinear
round trip.
"""

import os
import tempfile
import warnings

warnings.simplefilter("ignore")

import h5py
import numpy as np
import xarray as xr
import zarr
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import LocalStore
from virtualizarr.parsers import HDFParser

registry = ObjectStoreRegistry({"file://": LocalStore()})


def make(tmp, name, n_elements, chunk):
    path = os.path.join(tmp, f"{name}.h5")
    with h5py.File(path, "w") as f:
        g = f.create_group("X")
        g.create_dataset("data", data=np.arange(n_elements, dtype="f4"),
                         chunks=(chunk,), compression="gzip")
    return "file://" + path


def as_virtual(url):
    arrays = HDFParser(group="X")(url, registry)._group.arrays
    return xr.Dataset({"data": xr.Variable(("nnz",), arrays["data"])})


def concat_works(specs):
    """specs: [(n_elements, chunk_size), ...] -> (succeeded, reason)."""
    with tempfile.TemporaryDirectory() as tmp:
        parts = [as_virtual(make(tmp, f"f{i}", n, c)) for i, (n, c) in enumerate(specs)]
        try:
            xr.concat(parts, dim="nnz")
            return True, None
        except ValueError as e:
            return False, str(e).split(".")[0]


CASES = [
    ("every part an exact multiple of chunk", [(2000, 500), (1500, 500)], True),
    ("three parts, all exact multiples", [(1000, 500), (1500, 500), (2000, 500)], True),
    ("first part has a partial final chunk", [(1750, 500), (1500, 500)], False),
    ("last part has a partial final chunk", [(2000, 500), (1750, 500)], False),
    ("parts chunked differently", [(2000, 500), (1500, 300)], False),
    ("one chunk each, unequal lengths", [(1000, 1000), (1500, 1500)], False),
]


def main():
    print(f"{'case':40s} {'expect':8s} result")
    print("-" * 72)
    for label, specs, expected in CASES:
        ok, reason = concat_works(specs)
        assert ok == expected, f"{label}: expected {expected}, got {ok} ({reason})"
        if not expected:
            assert "chunk" in reason, f"{label}: error does not name the chunk grid: {reason}"
        print(f"{label:40s} {'works' if expected else 'blocked':8s} as expected")

    # h5py auto-chunking gives different chunk shapes even to inputs of the same shape.
    with tempfile.TemporaryDirectory() as tmp:
        import anndata as ad
        import scipy.sparse as sp

        chunks = []
        for i, n_cells in enumerate([300, 450]):
            p = os.path.join(tmp, f"tp{i}.h5ad")
            ad.AnnData(X=sp.random(n_cells, 200, density=0.1, format="csr",
                                   dtype=np.float32, random_state=i)).write_h5ad(
                p, compression="gzip")
            arrays = HDFParser(group="X")("file://" + p, registry)._group.arrays
            chunks.append(arrays["data"].metadata.chunks[0])
        assert chunks[0] != chunks[1], "expected h5py to pick differing chunk shapes"
        print(f"\nh5py auto-chunks each file differently ({chunks[0]} vs {chunks[1]}),")
        print("so real h5ads fail the uniform-chunk requirement before nnz even matters.")

    # A rectilinear grid can hold a partial chunk in the middle of the array, where two parts
    # meet. A regular grid cannot.
    edges = (500, 500, 500, 250, 500, 500, 500)  # a 1750-entry part then a 1500-entry part
    with zarr.config.set({"array.rectilinear_chunks": True}):
        store = zarr.storage.MemoryStore()
        arr = zarr.create_group(store=store, zarr_format=3).create_array(
            "nnz", shape=(sum(edges),), dtype="f4", chunks=(edges,)
        )
        arr[:] = np.arange(sum(edges), dtype="f4")
        assert np.array_equal(arr[:], np.arange(sum(edges), dtype="f4"))
        assert arr.metadata.chunk_grid.chunk_shapes == (edges,)
    print(f"\nA rectilinear grid holds those same parts as {len(edges)} uneven chunks")
    print(f"  {edges}  with the partial chunk mid-array, and round-trips.")
    print("So the Zarr model now permits this; VirtualiZarr's uniform-chunk check does not.")


if __name__ == "__main__":
    main()
