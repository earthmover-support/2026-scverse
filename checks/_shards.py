"""Local copies of the Braun cell-class shards that the checks measure against."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import braun

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "h5ads")


def path_for(name):
    """Return the local path of the h5ad for a cell class, or None if no local copy exists."""
    cf = next(f for f in braun.CLASSES if f.cell_class == name)
    path = os.path.join(DATA_DIR, cf.local_name)
    return path if os.path.exists(path) else None


def skip_message(names):
    """Say which h5ads a check needs and where it looks for them.

    tools/verify.sh greps the leading "skipping: no local copy" to build its SKIPPED summary.
    """
    files = [next(f for f in braun.CLASSES if f.cell_class == n) for n in names]
    listing = "; ".join(f"{f.local_name} ({f.cell_class}, {f.https_url.decode()})" for f in files)
    return f"skipping: no local copy in {DATA_DIR}. Download: {listing}"


def csr_for(name):
    """Return X for a cell class as CSR with sorted indices, or None if no local copy exists."""
    import anndata as ad

    path = path_for(name)
    if path is None:
        return None
    csr = ad.read_h5ad(path).X.tocsr()
    csr.sort_indices()
    return csr
