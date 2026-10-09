"""VirtualiZarr turns the X matrix of an h5ad into virtual chunk references that read back bit-identical.

Run: pixi run check

The script writes a synthetic h5ad. It virtualizes each group in it and reads every array back.
It asserts that X round-trips with identical values and its AnnData attributes. It shows that
string-typed metadata (obs and var categoricals and indexes) fails on read. It asserts that HDF5
variable-length strings cause this, and that fixed-length strings read back.
"""

import os
import tempfile
import traceback
import warnings

warnings.simplefilter("ignore")

import anndata as ad
import h5py
import numpy as np
import scipy.sparse as sp
import zarr
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import LocalStore
from virtualizarr.parsers import HDFParser

N_CELLS, N_GENES = 500, 200


def write_h5ad(path):
    rng = np.random.default_rng(0)
    adata = ad.AnnData(
        X=sp.random(N_CELLS, N_GENES, density=0.1, format="csr", dtype=np.float32,
                    random_state=0),
        obs={"development_stage": rng.choice(["cs13", "w8", "w11"], N_CELLS)},
        var={"gene_symbol": [f"GENE{i}" for i in range(N_GENES)]},
    )
    adata.obs["development_stage"] = adata.obs["development_stage"].astype("category")
    adata.obsm["X_umap"] = rng.random((N_CELLS, 2)).astype(np.float32)
    adata.write_h5ad(path, compression="gzip")
    return adata


def try_group(url, registry, group):
    try:
        store = HDFParser(group=group)(url, registry)
        # The parser accepts variable-length strings. Only a read shows that they fail.
        for _, member in zarr.open_group(store, mode="r").members(max_depth=None):
            if isinstance(member, zarr.Array):
                member[:]
        return store, None
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)[-1]
        return None, f"{type(e).__name__} at {os.path.basename(tb.filename)}:{tb.lineno}"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "synthetic.h5ad")
        adata = write_h5ad(path)
        registry = ObjectStoreRegistry({"file://": LocalStore()})
        url = "file://" + path

        print("group                     virtualizable")
        print("-" * 62)
        results = {}
        for group in [None, "X", "obsm", "obs", "obs/development_stage", "var", "uns"]:
            store, err = try_group(url, registry, group)
            results[group] = store
            print(f"  {group or '<root>':24s} {'yes' if store else 'NO   ' + err}")

        # This project depends on the expression matrix. Verify that its bytes are exact.
        zg = zarr.open_group(results["X"], mode="r")
        rt = sp.csr_matrix(
            (zg["data"][:], zg["indices"][:], zg["indptr"][:]), shape=(N_CELLS, N_GENES)
        )
        assert (rt != adata.X).nnz == 0, "virtualized X does not match source"
        assert dict(zg.attrs)["encoding-type"] == "csr_matrix", "AnnData attrs lost"
        print("\nX round-trips bit-identical through virtual refs, attrs preserved.")

        # HDF5 variable-length strings cause the failure. Groups and nesting do not.
        fixed, vlen = os.path.join(tmp, "fixed.h5"), os.path.join(tmp, "vlen.h5")
        with h5py.File(fixed, "w") as f:
            f.create_dataset("a", data=np.array([b"ab", b"cd"], dtype="S2"))
        with h5py.File(vlen, "w") as f:
            f.create_dataset("a", data=np.array(["ab", "cd"], dtype=object),
                             dtype=h5py.string_dtype())
        HDFParser()("file://" + vlen, registry)  # raises if the parser refuses vlen strings
        assert try_group("file://" + fixed, registry, None)[0], "fixed-length strings should work"
        assert not try_group("file://" + vlen, registry, None)[0], "vlen strings should fail"
        # The README quotes this message, so assert the text and not only the failure.
        message = None
        try:
            zarr.open_group(HDFParser()("file://" + vlen, registry), mode="r")["a"][:]
        except ValueError as e:
            message = str(e)
        assert message == "corrupt buffer, data seem truncated", message
        print(f'The vlen read fails with "{message}".')
        print("Cause is variable-length strings only; fixed-length strings virtualize fine.")


if __name__ == "__main__":
    main()
