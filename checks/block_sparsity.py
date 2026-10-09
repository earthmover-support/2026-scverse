"""Absent Zarr chunks cost no storage, but they cannot encode single-cell sparsity.

Run: pixi run check-sparsity

A Zarr array stores only the chunks that a writer writes. The empty regions of a dense chunk
grid over a sparse matrix therefore cost no storage. The script tests this on ClassErythrocyte
and ClassFibroblast at four grids. It asserts that every block of every grid holds a stored
value. A dense layout then stores every block. A Zarr array over single-cell counts must
therefore carry an explicit sparse encoding.

Needs local data: the h5ads of ClassErythrocyte and ClassFibroblast in h5ads/. The script prints
the download URLs when they are missing.
"""

import warnings

warnings.simplefilter("ignore")

import anndata as ad
import numpy as np

from _shards import path_for, skip_message

GRIDS = [(512, 512), (1024, 1024), (4096, 4096), (8192, 512)]
CLASSES = ["ClassErythrocyte", "ClassFibroblast"]


def occupancy(coo, rows, cols, n_genes):
    """Fraction of blocks in a (rows x cols) grid holding at least one stored value."""
    n_col_blocks = -(-n_genes // cols)
    block_ids = (coo.row // rows).astype(np.int64) * n_col_blocks + (coo.col // cols)
    occupied = np.unique(block_ids).size
    total = -(-coo.shape[0] // rows) * n_col_blocks
    return occupied, total


def main():
    missing = [c for c in CLASSES if path_for(c) is None]
    if missing:
        print(skip_message(missing))
        return

    for name in CLASSES:
        X = ad.read_h5ad(path_for(name)).X.tocoo()
        n_cells, n_genes = X.shape
        density = X.nnz / (n_cells * n_genes)
        detected = np.unique(X.col).size

        print(f"\n{name}  {n_cells:,} x {n_genes:,}  nnz={X.nnz:,}  "
              f"density={density*100:.2f}%")
        print(f"  genes ever detected: {detected:,}/{n_genes:,} "
              f"({detected/n_genes*100:.0f}%)")

        for rows, cols in GRIDS:
            occ, total = occupancy(X, rows, cols, n_genes)
            dense_gb = occ * rows * cols * 4 / 1e9
            coo_gb = X.nnz * 8 / 1e9
            print(f"  grid {rows:>5}x{cols:<5} {occ:>6,}/{total:<6,} occupied "
                  f"({occ/total*100:5.1f}%)  dense {dense_gb:6.2f} GB vs COO {coo_gb:.2f} GB")
            assert occ == total, (
                f"{name}: only {occ}/{total} blocks occupied at {rows}x{cols}. "
                "chunk absence may now be exploitable, revisit the design"
            )

    print("\nEvery block is occupied at every tested grid, so chunk absence encodes no")
    print("sparsity here. A Zarr-backed sparse array must store coordinates explicitly.")


if __name__ == "__main__":
    main()
