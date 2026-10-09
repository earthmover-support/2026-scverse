"""This verifier checks that 0002-parquet-fs-resolver-hook.patch stores geometry in Icechunk.

The patch needs no monkeypatching. The verifier clones spatialdata at PR #1107's branch. It applies
the patch from this directory and re-runs itself against the result. Thus the test covers the patch
file, not a checkout that someone prepared by hand. `_bootstrap` explains why that difference
matters.
"""
import os, shutil, sys, tempfile, warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _bootstrap import under_patched_clone

BRANCH = "feat/zarr-store-class"
UPSTREAM = "https://github.com/selmanozleyen/spatialdata.git"

under_patched_clone(UPSTREAM, BRANCH, "0002-parquet-fs-resolver-hook.patch")
warnings.simplefilter("ignore")
import icechunk, numpy as np, zarr
import spatialdata._store
from spatialdata._io import io_points, io_shapes
from spatialdata._io.format import _parse_formats
from spatialdata.datasets import blobs
from icechunk_spatialdata import ZarrArrayFileSystem

# An extension only has to supply this resolver.
def icechunk_resolver(store, group, child):
    if not isinstance(store, icechunk.store.IcechunkStore):
        return None
    # Use the store's own read-only flag. A read session's store refuses mode="a".
    root = zarr.open_group(store, mode="r" if getattr(store, "read_only", False) else "a")
    path = f"{group.path}/{child}" if child else group.path
    return ZarrArrayFileSystem(root), path

spatialdata._store.parquet_fs_fallback = icechunk_resolver

w = tempfile.mkdtemp(); sdata = blobs(); parsed = _parse_formats(None)
repo = icechunk.Repository.create(icechunk.local_filesystem_storage(w+"/r"))
s = repo.writable_session("main")
root = zarr.create_group(store=s.store, zarr_format=3)

for name, el in sdata.shapes.items():
    io_shapes.write_shapes(shapes=el, group=root.require_group("shapes").require_group(name),
                           element_format=parsed["shapes"])
for name, el in sdata.points.items():
    io_points.write_points(points=el, group=root.require_group("points").require_group(name),
                           element_format=parsed["points"])
snap = s.commit("geometry, via the fallback only")
print("committed", snap, "\n")

rroot = zarr.open_group(repo.readonly_session("main").store, mode="r")
for p, n in sorted(rroot.members(max_depth=4)):
    if p.endswith(".parquet") and not isinstance(n, zarr.Group):
        print(f"  {p:<50} {n.shape[0]:>7,} bytes")

ok = True
for name, expected in sdata.shapes.items():
    got = io_shapes._read_shapes(rroot["shapes"][name])
    same = np.array_equal(got.geometry.to_wkb().to_numpy(),
                          expected.geometry.to_wkb().to_numpy())
    ok &= same
    print(f"  read shapes/{name:<24} identical={same}")
for name, expected in sdata.points.items():
    got = io_points._read_points(rroot["points"][name]).compute()
    same = list(got.columns) == list(expected.compute().columns)
    ok &= same
    print(f"  read points/{name:<24} columns match={same}")

outside = [f for f in os.listdir(w) if f != "r"]
print(f"\nnothing outside the repo: {not outside}   ({len(os.listdir(w))} entries in workdir)")
print("VERDICT:", "the hook alone is sufficient" if ok and not outside else "INCOMPLETE")
shutil.rmtree(w, ignore_errors=True)
