# SpatialData on a store without a filesystem path

Five patches against the branch of [PR #1107](https://github.com/scverse/spatialdata/pull/1107).
The first four let SpatialData read and write a `zarr.Group` whose store has no filesystem
path. An Icechunk session store is one such store. `MemoryStore` is another, and `read_zarr`
documents it as supported. The fifth fixes the repr of an object read from any remote path.

We verified them against `selmanozleyen/spatialdata@5443b05` (`feat/zarr-store-class`), `zarr`
3.3.0, `ome-zarr` 0.21.0 and `icechunk` 2.3.0a1.

## What already works

`write_image`, `write_labels` and `write_table` take a `zarr.Group`. They work unmodified on a
group in an Icechunk session. Multiscale pyramids, the AnnData table and
`coordinateTransformations` round-trip byte-identical through a commit. The patches change nothing
at the element layer.

## The patches

The first four patches form a series and apply in order. The fifth stands alone. Each patch
except 0001 adds tests to the `tests/io` suite.

### 0001: require ome-zarr 0.21.0

[`0001-require-ome-zarr-0.21.0.patch`](upstream/0001-require-ome-zarr-0.21.0.patch), +1 −1, in
`pyproject.toml`.

ome-zarr 0.21.0 lets `ZarrLocation` take any zarr store or a `StorePath`. Earlier releases raise
`TypeError` for a store other than `LocalStore` and `FsspecStore`. 0003 needs this release.

### 0002: a fallback for the parquet filesystem

[`0002-parquet-fs-resolver-hook.patch`](upstream/0002-parquet-fs-resolver-hook.patch), +51,
in `_store.py`.

`parquet_fs_and_path` derives an fsspec filesystem for `LocalStore` and `FsspecStore`. It raises
for any other store. The patch adds one module attribute, `parquet_fs_fallback`, and calls it
before the raise. An extension sets it to supply a filesystem for its own store type. SpatialData
gains no dependency and no new store class.

`io_shapes` and `io_points` only call `fs.open(path, "rb"/"wb")` on the result. Our extension
supplies a filesystem that stores each file as a 1-D `uint8` array. The array sits at the same path
in the Zarr hierarchy. Geometry then enters the Icechunk transaction through SpatialData's own
writers:

```
shapes/blobs_circles/shapes.parquet                array (3210,) uint8
points/blobs_points/points.parquet/part.0.parquet  array (6854,) uint8
```

### 0003: keep the element's location in a store that cannot be re-rooted

[`0003-keep-the-element-location.patch`](upstream/0003-keep-the-element-location.patch),
+43 −2, in `_io/io_raster.py` and `_io/io_zarr.py`.

This is a bug fix. `read_zarr` fails on a `MemoryStore` that `SpatialData.write()` produced:

```
spatialdata/_io/io_raster.py:171  image_loc = ZarrLocation(resolved_store, fmt=reader_format)
spatialdata/_io/io_raster.py:188  raise OSError(
OSError: Image location / [zgroup] exists, but len(nodes) = 0, expected 1.
```

For a store it cannot re-root, `store_from_group` returns the parent store unchanged.
`_read_multiscale` gives that store to `ZarrLocation`. `ZarrLocation` then reads the container root
and finds no image. The patch passes `StorePath(group.store, group.path)` for such a store. Every store that
`store_from_group` re-roots keeps the existing path.

The patch also fixes a second site. For a store it cannot re-root, `store_from_group` returns the
parent store unchanged. `_read_zarr_group_spatialdata_element` re-opens that store and hands the
table reader the container root instead of the table group. The patch keeps the element group for
such a store.

### 0004: write to a store that has no path

[`0004-write-to-a-store-without-a-path.patch`](upstream/0004-write-to-a-store-without-a-path.patch),
+47 −23, in `_core/spatialdata.py`, `_io/io_zarr.py` and `_store.py`.

This patch reverses a restriction that `test_write_to_memory_store_raises` asserts, so it is a
proposal. The restriction exists because the per-element machinery re-opens stores from the path.
Patches 0002 and 0003 remove that need. The element writers then take the store as the target.
`write()` skips the three steps that need a path: the directory checks, the `sdata.path` record
and consolidation. `open_write_store` yields the caller's store unchanged,
because the caller owns it.

### 0005: count points rows through the frame's filesystem

[`0005-points-rows-through-the-frame-filesystem.patch`](upstream/0005-points-rows-through-the-frame-filesystem.patch)
is +36 −2, in `_core/spatialdata.py` and `_io/_utils.py`.

This is a bug fix, and it does not depend on the other four. `SpatialData.__repr__` counts the
rows of a points element from the parquet metadata of its backing files. It opens them as local
paths, so `repr()` of an object read from a `memory://` path raises `FileNotFoundError`.
`get_dask_backing_files` also resolves every parquet path against the working directory. A path
that another filesystem names is not a local path.

The patch resolves only the paths of a local read, which the read task's
`ParquetFunctionWrapper.fs` identifies. The repr reads the metadata through the frame's own
filesystem when it has one.

## The fix in ome-zarr-py

ome-zarr-py merged the `ZarrLocation` change as
[ome/ome-zarr-py#674](https://github.com/ome/ome-zarr-py/pull/674) and released it in
[0.21.0](https://github.com/ome/ome-zarr-py/releases/tag/v0.21.0). We deleted the patch and its
verifier. A location on a store is the store plus a prefix inside it. A `Store` is the root, and a
`StorePath` names the prefix.

0003 uses the `StorePath` only for a store that `store_from_group` cannot re-root.
`get_dask_backing_files` takes the store of the `original-from-zarr` layer and ignores the
component. With a `StorePath` on a `LocalStore`, every backing file is the container, not the
element.

conda-forge does not have 0.21.0. The `spatial` environment thus takes `spatialdata`,
`spatialdata-io` and `ome-zarr` from PyPI.

## Reproduction

Each script clones the branch, applies its patch, and runs itself against the result. The scripts
for 0003, 0004 and 0005 assert the failure before the patch as well as the fix after it.

```shell
pixi run -e spatial python icechunk-SpatialData/upstream/verify_geometry_hook.py
pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_read.py
pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_write.py
pixi run -e spatial python icechunk-SpatialData/upstream/verify_repr.py
```

[`README.md`](README.md) holds the longer notes and the options we ruled out.
