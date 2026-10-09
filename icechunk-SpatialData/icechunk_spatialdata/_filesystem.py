"""An fsspec filesystem that stores each file as a Zarr array.

With this filesystem, sidecar formats fit in a transaction. This module puts geometry into an
Icechunk repository. It needs no change to Icechunk. It needs no change to SpatialData's format.

The reasoning has three steps:

1. Icechunk refuses non-Zarr keys. So a repository cannot hold a Parquet *file*.
2. PR #1107 already does all geometry I/O through an **fsspec filesystem**. `io_shapes` and
   `io_points` call `parquet_fs_and_path(group, "shapes.parquet")` and then `fs.open(...)`. They
   never touch a real path.
3. Zarr accepts `shapes.parquet` as an array name, at exactly that path. We confirmed that a v3
   array can exist at `shapes/blobs_circles/shapes.parquet`.

So each file is a 1-D `uint8` Zarr array at the identical path. The mapping from the fsspec
namespace to the Zarr namespace is the identity. Parquet readers and writers work without change.
The bytes are ordinary chunks. Icechunk versions them like all other chunks.

The cost: a `.parquet` array is opaque to a generic Zarr consumer, as an opaque key is. The design
avoids an Icechunk spec change and a new node type. It also avoids new conflict and
garbage-collection semantics for a second kind of stored object.

The design has one more result: **the file's bytes can themselves be virtual chunk references**.
Then a repository can *reference* a published Parquet file and not copy it. See
`_reference.reference_file`. That function has its own module because only that part needs
Icechunk. A `uint8` array has no codec, so a chunk is exactly a byte range. That fact makes the
mapping trivial. A codec-bearing array, by contrast, needs the source's encoding to match. Each read
fetches only the requested slice. So a read of a Parquet footer fetches a fraction of the file, not
all of it.

The `file:` Zarr convention specifies the encoding. `earth-mover/filestore` holds the spec and a
test vector. The `zarr-files` package holds the store-agnostic pieces: the convention helpers and
`ZarrArrayFileSystem`. This module keeps the part that only SpatialData needs. It sets
`parquet_fs_fallback` while SpatialData's readers and writers run.
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager

import zarr
from zarr_files import CHUNK, FILE_CONVENTION, ZarrArrayFileSystem, declare_file

__all__ = [
    "CHUNK",
    "FILE_CONVENTION",
    "ZarrArrayFileSystem",
    "available",
    "declare_file",
    "parquet_in_store",
]


def _store_module():
    """Return `spatialdata._store` with `parquet_fs_fallback`.

    Raise a `RuntimeError` that names the missing part.
    """
    try:
        from spatialdata import _store as store_module
    except ImportError as exc:  # pragma: no cover. The installed version decides this branch.
        raise RuntimeError(
            "this needs spatialdata's `_store` module, added in PR #1107; on 0.8.0 the geometry "
            "writers derive a path from store.root and there is no filesystem to substitute"
        ) from exc
    if not hasattr(store_module, "parquet_fs_fallback"):
        raise RuntimeError(
            "this spatialdata has no `parquet_fs_fallback`; use the pinned PR #1107 checkout; ../upstream/ documents its commits "
            "(`pixi run -e spatial sdpr` fetches it)"
        )
    return store_module


@contextmanager
def parquet_in_store():
    """Store SpatialData's Parquet files as `uint8` arrays in the Zarr store while the block runs.

    Set `spatialdata._store.parquet_fs_fallback` on entry. Restore the previous value on exit.
    SpatialData calls the fallback only for a store that it cannot derive a filesystem for. So the
    fallback does not affect a local or S3-backed SpatialData. `SpatialData.write` and
    `SpatialData.read` then work on an Icechunk store:

    ```python
    with parquet_in_store():
        sdata.write(session.store)
    ```

    This function needs the fallback from the patch series in `../upstream/`. See `available`.
    """
    store_module = _store_module()

    def fallback(store, group: zarr.Group, child: str):
        # Open the root at call time.
        # `SpatialData.write` creates the root itself and refuses one that exists.
        root = zarr.open_group(store, mode="r" if getattr(store, "read_only", False) else "a")
        path = f"{group.path}/{child}" if child else group.path
        return ZarrArrayFileSystem(root), path

    previous = store_module.parquet_fs_fallback
    store_module.parquet_fs_fallback = fallback
    try:
        yield
    finally:
        store_module.parquet_fs_fallback = previous


def available() -> bool:
    """Check if the installed SpatialData has `parquet_fs_fallback` (PR #1107 plus ../upstream/)."""
    if importlib.util.find_spec("spatialdata._store") is None:
        return False
    from spatialdata import _store

    return hasattr(_store, "parquet_fs_fallback")
