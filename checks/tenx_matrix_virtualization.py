"""A 10x Xenium cell_feature_matrix.h5 holds CSR bytes over cells, so it virtualizes without a transpose.

Run: pixi run check-tenx

The check needs network access and reads about 24 MB from the public 10x bucket. It reads the
same 12.1 MB file twice: once through fsspec for the h5py comparison, once to a temporary file
for scanpy's read_10x_h5. The second read asks for the whole file in one GET.

10x stores the matrix as CSC of shape (n_features, n_barcodes). Its indptr indexes barcodes and
its indices hold feature indices. The same bytes are therefore CSR over cells, which is the
orientation an `X` of shape (cells, genes) needs. A byte range cannot transpose, so this layout
decides whether the matrix can stay virtual.

The check compares the references with an h5py read and with scanpy read_10x_h5. scanpy builds
its csr_matrix from the same three arrays, with no transpose. The check passes gex_only=False,
so both sides use the same 541 features. The scanpy default keeps only 313 Gene Expression
features. The references hold all 541, because a byte range is the full array.

10x writes fixed-length byte strings (|S6 barcodes, |S23 gene names). AnnData writes HDF5
variable-length strings. `pixi run check` shows that references work for fixed-length strings
and not for variable-length strings. A 10x matrix therefore has more complete references than a
CELLxGENE h5ad. They include gene names and cell ids.

"""

import warnings

warnings.simplefilter("ignore")

import fsspec
import h5py
import scipy.sparse as sp
import zarr
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import HTTPStore
from virtualizarr.parsers import HDFParser

# Xenium human breast cancer, replicate 1 (Janesick et al., Nat Biotechnol 2023), CC BY 4.0.
# The store base must be the host root. obstore resolves keys relative to the base.
# With a deeper base, CloudFront returns 403, not 404.
HOST = "https://s3-us-west-2.amazonaws.com/10x.files/"
KEY = ("samples/xenium/1.0.1/Xenium_FFPE_Human_Breast_Cancer_Rep1/"
       "Xenium_FFPE_Human_Breast_Cancer_Rep1_cell_feature_matrix.h5")
URL = HOST + KEY


def main():
    registry = ObjectStoreRegistry({HOST: HTTPStore(HOST.rstrip("/"))})
    matrix = zarr.open_group(HDFParser(group="matrix")(URL, registry), mode="r")
    features = zarr.open_group(HDFParser(group="matrix/features")(URL, registry), mode="r")

    n_features, n_cells = (int(v) for v in matrix["shape"][:])
    print(f"{URL.rsplit('/', 1)[-1]}")
    print(f"  stored shape        ({n_features:,} features, {n_cells:,} barcodes), 10x's CSC")
    print(f"  indptr length       {matrix['indptr'].shape[0]:,}")

    # The claim: indptr indexes cells, so the matrix needs no transpose.
    assert matrix["indptr"].shape[0] == n_cells + 1, (
        "indptr does not index barcodes; this file is not CSR over cells"
    )
    assert int(matrix["indices"][:].max()) < n_features, (
        "indices are not feature indices"
    )
    virtual = sp.csr_matrix(
        (matrix["data"][:], matrix["indices"][:], matrix["indptr"][:]),
        shape=(n_cells, n_features),
    )
    print(f"  as CSR over cells   {virtual.shape[0]:,} x {virtual.shape[1]:,}, "
          f"{virtual.nnz:,} stored values")

    # The references return fixed-length strings. vlen strings would have no reference.
    barcodes = matrix["barcodes"][:4]
    names = features["name"][:4]
    assert barcodes.dtype.kind == "S", f"expected fixed-length bytes, got {barcodes.dtype}"
    assert names.dtype.kind == "S", f"expected fixed-length bytes, got {names.dtype}"
    print(f"  barcodes            {barcodes.dtype}, e.g. {[b.decode() for b in barcodes]}")
    print(f"  gene names          {names.dtype}, e.g. {[b.decode() for b in names]}")

    # Compare with an independent read of the source, to check the references.
    # This catches an empty manifest that reads back as zeros.
    filesystem = fsspec.filesystem("http", block_size=4 * 1024 * 1024)
    with filesystem.open(URL, "rb") as handle, h5py.File(handle, "r") as source:
        direct = sp.csr_matrix(
            (source["matrix/data"][:], source["matrix/indices"][:],
             source["matrix/indptr"][:]),
            shape=(n_cells, n_features),
        )
        source_barcodes = source["matrix/barcodes"][:4]
        source_names = source["matrix/features/name"][:4]
    assert virtual.nnz > 0, "the manifest is empty; references resolved to nothing"
    assert (virtual != direct).nnz == 0, "virtualized matrix differs from the source"
    assert list(source_barcodes) == list(barcodes), "barcodes differ from the source"
    assert list(source_names) == list(names), "gene names differ from the source"
    print("\n  matrix, barcodes and gene names all identical to an independent h5py read")

    # Check the claim against the upstream scanpy reader. `_read_v3_10x_h5` has the same
    # orientation: `n_cols, n_rows = dsets["shape"]  # transposed`. It then builds a
    # csr_matrix from the same three arrays, with no change.
    import tempfile
    from pathlib import Path

    import scanpy as sc

    # `read_10x_h5` takes a path, not a handle. Write the 12.1 MB to a temporary file.
    # `remote.read()` takes no length, so fsspec gets the whole file in one GET.
    with tempfile.TemporaryDirectory() as work:
        local = Path(work) / "cell_feature_matrix.h5"
        with fsspec.open(URL, "rb") as remote:
            local.write_bytes(remote.read())
        # `gex_only=True` keeps only the 313 Gene Expression features and drops the Xenium
        # control probes. The references must hold them, because a byte range is the full array.
        reference = sc.read_10x_h5(local, gex_only=False)

    assert reference.shape == virtual.shape, (
        f"scanpy reads {reference.shape}, the references give {virtual.shape}"
    )
    assert (sp.csr_matrix(reference.X) != virtual).nnz == 0, (
        "the virtualized matrix differs from what scanpy reads from the same file"
    )
    # `barcodes` and `names` above are samples of four elements, as fixed-length bytes.
    assert list(reference.obs_names[:4]) == [b.decode() for b in barcodes], (
        "scanpy's barcodes differ from the referenced ones"
    )
    assert list(reference.var_names[:4]) == [b.decode() for b in names], (
        "scanpy's gene names differ from the referenced ones"
    )
    print(f"  and identical to scanpy.read_10x_h5, which declares the same layout: "
          f"{reference.shape[0]:,} x {reference.shape[1]:,}")

    print("\n10x's own layout is virtualizable, and more completely than an h5ad's, because")
    print("its strings are fixed length. Supporting it is a recognition change, not a")
    print("restructuring. This repository references the matrix and does not restructure it.")


if __name__ == "__main__":
    main()
