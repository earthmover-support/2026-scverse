"""Generate xenium_from_arraylake.ipynb.

Run: pixi run xenium-al        (regenerate)
     pixi run xenium-al-run    (regenerate, then execute)

The shapes cell uses SpatialData's own reader only with the PR #1107 branch. Otherwise it uses
the geopandas fallback. To use the branch, execute the notebook as follows (see
../icechunk-SpatialData/README.md for the clone):

    PYTHONPATH=$PWD/vendor/spatialdata-1107/src pixi run -e spatial jupyter nbconvert --to notebook \
        --execute --inplace --ExecutePreprocessor.timeout=3600 \
        notebooks/xenium_from_arraylake.ipynb

This notebook is the read side of scripts/upload_xenium_arraylake.py. That script builds
earthmover-demos/xenium-virtual-bundle. This notebook opens the repo and works with it. This part
must feel ordinary, or the approach has no value.
"""

from _notebook import code, md, write


md("""
# A 10x Xenium bundle from Arraylake, without a copy of it

`earthmover-demos/xenium-virtual-bundle` is an Arraylake repo for a 10x Xenium breast cancer run.
The run has transcripts, a morphology image, cell and nucleus boundaries, and an expression
matrix. The repo contains almost none of these bytes. Every file stays where 10x published it, in
the public 10x bucket `10x.files`. The repo holds byte ranges into the files.

This notebook is the read side. The build side is
[`../scripts/upload_xenium_arraylake.py`](../scripts/upload_xenium_arraylake.py). The design and
its constraints are in
[`../icechunk-SpatialData/README.md`](../icechunk-SpatialData/README.md).

Most of this notebook looks like ordinary data access. Only the byte counters show that the repo
copied nothing.
""")

md("""
## Open the repo

Nothing here is specific to virtual data. `get_repo` returns an Icechunk repository. A read-only
session returns a store. Zarr opens that store. The repository config only adds retries to the
reads. `bounded_reads` only limits their connections.

The one thing to notice is `authorized_virtual_container_prefixes`. It shows that Arraylake vends
credentials for references under `s3://samples/`. Without it, this repo opens and then fails on
the first read. In fact, `get_repo` itself returns HTTP 400.
""")

code("""
import warnings

warnings.simplefilter("ignore")

import numpy as np
import zarr
from arraylake import Client
from arraylake import config as al_config

import icechunk_spatialdata as isd

# The published repo is on prod. A local config can point the client at dev.
al_config.set({"service.uri": "https://api.earthmover.io"})

REPO = "earthmover-demos/xenium-virtual-bundle"

# The config adds retries. bounded_reads limits connections. The data path does not change.
repo = Client().get_repo(REPO, config=isd.repository_config())
isd.bounded_reads()
session = repo.readonly_session("main")
root = zarr.open_group(session.store, mode="r")

print(f"{REPO}")
print(f"  authorized virtual prefixes: {sorted(repo.authorized_virtual_container_prefixes)}")
print(f"  top level: {sorted(root.keys())}")
""")

md("""
## What the repo actually stores

`files/` holds one `uint8` array per published file. Each array has the file's exact length. A
`uint8` Zarr array has no codec, so a chunk of it *is* a byte range. Thus Icechunk can reference
an arbitrary file, whatever its format.

`chunk_type` tells you, per chunk, where the bytes are. Below, every chunk is `Virtual` except the
last. The build copied the last chunk. A Zarr chunk has a fixed size, and a byte range cannot pad.
""")

code("""
files = {name: array for name, array in root["files"].arrays()}

total = 0
copied = 0
file_references = 0
print(f"{'file':<32} {'size':>10}  {'chunks':>7}  {'virtual':>8}  {'copied':>8}")
for name, array in sorted(files.items(), key=lambda kv: -kv[1].shape[0]):
    n_chunks = -(-array.shape[0] // array.chunks[0])
    kinds = [str(session.chunk_type(f"/files/{name}", [i])) for i in range(n_chunks)]
    virtual = sum(k == "ChunkType.virtual" for k in kinds)
    tail = array.shape[0] - (n_chunks - 1) * array.chunks[0]
    total += array.shape[0]
    copied += tail
    file_references += virtual
    print(f"{name:<32} {array.shape[0] / 1e6:>7.1f} MB  {n_chunks:>7}  "
          f"{virtual:>8}  {tail / 1e6:>5.1f} MB")

everything = len(session.all_virtual_chunk_locations())
print(f"\\n{total / 1e9:.2f} GB addressed by {file_references:,} references, "
      f"{copied / 1e6:.1f} MB of it copied ({copied / total:.2%}) — the tails, nothing else")
print(f"the repo holds {everything:,} references in all; the other "
      f"{everything - file_references:,} address one of these files a second way, as the image "
      f"element further down")
""")

md("""
### Where the bytes come from

The locations are ordinary `s3://` URLs into `10x.files`, a bucket that 10x owns. The bucket is
public, and anonymous reads work. Arraylake authorizes a virtual container through a map from a
URL prefix to a *bucket config*. Here a real bucket exists for that config.
""")

code("""
import collections

locations = collections.Counter(session.all_virtual_chunk_locations())
for location, references in sorted(locations.items()):
    print(f"{references:>4} refs  {location}")

print("\\n... each of which is served, byte for byte, over HTTPS from:")
print(min(locations).replace("s3://10x.files/", "https://s3-us-west-2.amazonaws.com/10x.files/"))
""")

md("""
## 42.6 million transcripts, and the 0.01% needed to describe them

`files/transcripts.parquet` is 670 MB. Its schema and row-group layout need only the footer and a
little more. An fsspec filesystem reaches each file inside the store. Thus
`pyarrow.parquet.ParquetFile` does its usual work.

The byte counter on the handle is the only unusual line in this cell.
""")

code("""
import pyarrow.parquet as pq
from icechunk_spatialdata._filesystem import ZarrArrayFileSystem

filesystem = ZarrArrayFileSystem(root)
size = files["transcripts.parquet"].shape[0]

with filesystem.open("files/transcripts.parquet", "rb") as handle:
    parquet = pq.ParquetFile(handle)
    schema = parquet.schema_arrow
    metadata = parquet.metadata
    groups = [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)]

    # The footer also holds per-row-group min/max for every column.
    # Thus the same bytes give the position of each row group on the slide.
    columns = [metadata.schema.column(i).name for i in range(metadata.num_columns)]
    x_column, y_column = columns.index("x_location"), columns.index("y_location")
    extents = [
        (metadata.row_group(i).column(x_column).statistics,
         metadata.row_group(i).column(y_column).statistics)
        for i in range(metadata.num_row_groups)
    ]
    footer_cost = handle.raw.bytes_read

    print(f"columns: {schema.names}")
    print(f"{sum(groups):,} transcripts in {len(groups)} row groups "
          f"(first: {groups[0]:,} rows)")
    print(f"read {footer_cost / 1e6:.2f} MB of {size / 1e6:.0f} MB "
          f"({footer_cost / size:.2%}) to learn all of that")

    # One row group, four columns. Parquet's layout makes these a few contiguous ranges.
    # Thus the read is a few ranged GETs.
    before = handle.raw.bytes_read
    batch = parquet.read_row_group(
        0, columns=["x_location", "y_location", "feature_name", "qv"]
    )
    group_cost = handle.raw.bytes_read - before

transcripts = batch.to_pandas()
transcripts["feature_name"] = transcripts["feature_name"].str.decode("utf-8")
print(f"\\nrow group 0: {len(transcripts):,} rows x 4 columns for "
      f"{group_cost / 1e6:.1f} MB ({group_cost / size:.2%})")
print(transcripts.head(3).to_string())
""")

md("""
Those 65 KB gave more than a schema. Parquet footers hold per-row-group min/max for every
column. Thus the same read gives the position of each row group on the slide. That is a spatial
index at no extra cost.

The index is coarse. The figure below shows the limit. The 43 footprints form clean bands in
`y`. Each one spans almost the full width in `x`. Thus the footer prunes a `y`-range query. It
does nothing at all for an `x`-range query. The figure draws the transcripts of row group 0 on
top. They fall in two disjoint patches inside their band. The rows have enough order to form
bands, but no order within a band. Thus the pruning to a few ranged GETs works here along one
axis only.

After that, the cell uses ordinary pandas on the row group that it already read.
""")

code("""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

confident = transcripts[transcripts["qv"] >= 20]
counts = confident["feature_name"].value_counts()

figure, axes = plt.subplots(1, 2, figsize=(13, 5),
                            gridspec_kw={"width_ratios": [1.15, 1]})

# Draw the footprint of each row group from the footer statistics.
for index, (x_statistics, y_statistics) in enumerate(extents):
    axes[0].add_patch(Rectangle(
        (x_statistics.min, y_statistics.min),
        x_statistics.max - x_statistics.min, y_statistics.max - y_statistics.min,
        fill=False, linewidth=1.0 if index == 0 else 0.6,
        edgecolor="#ff3b30" if index == 0 else plt.cm.viridis(index / len(extents)),
    ))

hexbin = axes[0].hexbin(confident["x_location"], confident["y_location"],
                        gridsize=90, cmap="magma", bins="log", linewidths=0)
axes[0].set(xlabel="x (um)", ylabel="y (um)",
            title=f"{len(groups)} row-group footprints, from the footer alone")
axes[0].set_aspect("equal")
axes[0].set_xlim(0, 7526)
axes[0].set_ylim(5478, 0)
figure.colorbar(hexbin, ax=axes[0], label="transcripts per bin")

top = counts.head(15)[::-1]
axes[1].barh(top.index, top.values, color="#3b5b92")
axes[1].set(xlabel="transcripts", title="most abundant genes in row group 0")
axes[1].tick_params(axis="y", labelsize=8)

figure.tight_layout()
print(f"{confident['feature_name'].nunique()} genes, "
      f"{len(confident) / len(transcripts):.1%} of transcripts pass Q20")
""")

md("""
## The morphology image, one pyramid level at a time

`morphology_mip.ome.tif` is 628 MB of tiled JPEG 2000 in eight pyramid levels. `tifffile` opens
it through the same filesystem. It reads the OME-TIFF structure first, then the requested pyramid
level, and nothing else.

The repo holds this image **twice**. The first way is as file bytes. This way needs no extra
installation. Any OME-TIFF reader can read this, because it *is* the OME-TIFF. The second way
comes after the boundaries. Each way is good at different tasks.
""")

code("""
import tifffile

size = files["morphology_mip.ome.tif"].shape[0]

with filesystem.open("files/morphology_mip.ome.tif", "rb") as handle:
    with tifffile.TiffFile(handle) as tif:
        series = tif.series[0]
        structure_cost = handle.raw.bytes_read
        print(f"{len(series.levels)} pyramid levels, level 0 is {series.shape}, "
              f"tiles of {tif.pages[0].tilelength}x{tif.pages[0].tilewidth}, "
              f"{tif.pages[0].compression.name}")
        print(f"  structure read for {structure_cost / 1e6:.2f} MB ({structure_cost / size:.2%})")

        before = handle.raw.bytes_read
        overview = series.levels[5].asarray()
        overview_cost = handle.raw.bytes_read - before

        before = handle.raw.bytes_read
        detail = series.levels[2].asarray()
        detail_cost = handle.raw.bytes_read - before

# Read the run's experiment.xenium from the store attributes, not from a copy in this cell.
# 10x publishes that file beside the bundle. Its `pixel_size` is the unit of level 0.
experiment = dict(root.attrs)["experiment_xenium"]["contents"]
MICRONS_PER_PIXEL = experiment["pixel_size"]
print(f"  pixel_size {MICRONS_PER_PIXEL} um, from {experiment['analysis_sw_version']} "
      f"on {experiment['instrument_sn']}")
overview_scale = MICRONS_PER_PIXEL * series.shape[1] / overview.shape[1]
detail_scale = MICRONS_PER_PIXEL * series.shape[1] / detail.shape[1]

print(f"  level 5 {overview.shape} at {overview_scale:.2f} um/px "
      f"for {overview_cost / 1e6:.2f} MB ({overview_cost / size:.2%})")
print(f"  level 2 {detail.shape} at {detail_scale:.2f} um/px "
      f"for {detail_cost / 1e6:.1f} MB ({detail_cost / size:.1%})")
""")

md("""
## The one element that is not a reference

`shapes/cell_boundaries` is a real SpatialData shapes element: 167,780 polygons. It uses
SpatialData's own on-disk format, and SpatialData's own writer wrote it. It is derived data. The
build made the polygons from the *referenced* vertex table, in the same transaction. Thus the
repo materializes it: 13 MB, against 1.33 GB addressed.

SpatialData's own reader needs one upstream change to read it back: the fsspec change in
[spatialdata#1107](https://github.com/scverse/spatialdata/pull/1107). Without it, geometry I/O
requires a filesystem path. Without that branch, the cell below reads the GeoParquet bytes
directly. That fallback works, but it skips the coordinate transformations.
""")

code("""
import icechunk_spatialdata as isd

if isd.parquet_in_store_available():
    from spatialdata._io import io_shapes

    with isd.parquet_in_store():
        boundaries = io_shapes._read_shapes(root["shapes"]["cell_boundaries"])
    how = "SpatialData's own reader, through parquet_fs_fallback"
else:
    import geopandas as gpd

    with filesystem.open("shapes/cell_boundaries/shapes.parquet", "rb") as handle:
        boundaries = gpd.read_parquet(handle)
    how = "geopandas directly (no #1107: SpatialData's reader wants a path)"

print(f"read by {how}")
print(f"{len(boundaries):,} {boundaries.geometry.geom_type.iloc[0]}s")
print(f"  bounds (um): {np.round(boundaries.total_bounds, 1)}")
print(f"  image extent (um): "
      f"{np.round(np.array(series.shape[::-1]) * MICRONS_PER_PIXEL, 1)}")
print(f"  attrs: {sorted(boundaries.attrs)}")
""")

md("""
### Both halves together

The boundaries are in micrometres and the image is in pixels. One scale factor puts them in the
same frame. The bounds printed above agree to a pixel. This check shows that the two files really
do describe the same slide.

Left: the whole 7.5 x 5.5 mm section, from level 5. Right: 260 um of it from level 2, with cell
boundaries drawn on top. Both come from the same session. The repo copied neither file.
""")

code("""
from matplotlib.patches import Rectangle

WINDOW = 260.0  # um
centre = np.array([3600.0, 2100.0])  # um, a dense region of the section
corner = centre - WINDOW / 2

figure, axes = plt.subplots(1, 2, figsize=(13.5, 5.2))

axes[0].imshow(overview, cmap="gray", vmax=np.percentile(overview, 99.5),
               extent=(0, overview.shape[1] * overview_scale,
                       overview.shape[0] * overview_scale, 0))
axes[0].add_patch(Rectangle(corner, WINDOW, WINDOW, fill=False, edgecolor="#ff3b30", lw=1.5))
axes[0].set(xlabel="x (um)", ylabel="y (um)",
            title=f"level 5, {overview_cost / 1e6:.2f} MB ({overview_cost / size:.2%} of the file)")

low = (corner / detail_scale).astype(int)
high = ((corner + WINDOW) / detail_scale).astype(int)
crop = detail[low[1]:high[1], low[0]:high[0]]
axes[1].imshow(crop, cmap="gray", vmax=np.percentile(crop, 99.5),
               extent=(corner[0], corner[0] + WINDOW, corner[1] + WINDOW, corner[1]))

window = boundaries.cx[corner[0]:corner[0] + WINDOW, corner[1]:corner[1] + WINDOW]
window.boundary.plot(ax=axes[1], color="#ffd60a", linewidth=0.8)
axes[1].set(xlim=(corner[0], corner[0] + WINDOW),
            ylim=(corner[1] + WINDOW, corner[1]),
            xlabel="x (um)",
            title=f"level 2 + {len(window):,} cell boundaries")

figure.tight_layout()
print(f"{len(window):,} of {len(boundaries):,} cells fall in the window")
""")

md("""
### What this route cannot do

A request for a full-resolution *tile* is not cheap. `tifffile` can slice a pyramid level only
through its own Zarr view. zarr 3 cannot open a `ZarrTiffStore`, which is a v2-style mapping, not
a `Store`. Thus the only route is `asarray()`, which decodes the whole level. For level 0, that
is about 450 MB to see a 1024-pixel square.

The second representation exists for this case.
""")

md("""
The TIFF parser that wrote the tile references also supplies their JPEG 2000 codec. Thus this
cell needs no extra installation.
""")

code("""
import icechunk_spatialdata as isd


morphology = root["images"]["morphology_mip"]
levels = sorted(morphology.array_keys())

print(f"images/morphology_mip: {len(levels)} levels")
for level in levels:
    array = morphology[level]
    grid = tuple(-(-s // c) for s, c in zip(array.shape, array.chunks))
    print(f"  {level}  {str(array.shape):>22}  chunks {array.chunks}  "
          f"{int(np.prod(grid)):>4} tiles")

finest = morphology["s0"]
n_chunks = int(np.prod([-(-s // c) for s, c in zip(finest.shape, finest.chunks)]))
kinds = collections.Counter(
    str(session.chunk_type("/images/morphology_mip/s0", [0, row, column]))
    for row in range(-(-finest.shape[1] // finest.chunks[1]))
    for column in range(-(-finest.shape[2] // finest.chunks[2]))
)
print(f"\\nlevel 0 chunk types: {dict(kinds)} — of {n_chunks}, none copied")
print(f"codec pipeline: {[type(codec).__name__ for codec in finest.metadata.codecs]}")
""")

md("""
The next cell does what the file route cannot do. One full-resolution tile is one chunk, so it is
one ranged GET and one decode. `tifffile` read its own per-tile byte counts with the structure
above. These counts give the exact size of that GET.
""")

code("""
with filesystem.open("files/morphology_mip.ome.tif", "rb") as handle:
    with tifffile.TiffFile(handle) as tif:
        tile_bytes = tif.series[0].levels[0].pages[0].databytecounts

ROW, COLUMN = 4, 4          # a tile well inside the section
y0, x0 = ROW * 1024, COLUMN * 1024
tile = np.asarray(finest[0, y0:y0 + 1024, x0:x0 + 1024])
across = -(-finest.shape[2] // 1024)
cost = tile_bytes[ROW * across + COLUMN]

print(f"tile ({ROW}, {COLUMN}) at full resolution: {tile.shape} {tile.dtype}, "
      f"mean {tile.mean():.1f}")
print(f"  one chunk of {n_chunks}, {cost / 1e6:.2f} MB of the {size / 1e6:.0f} MB file "
      f"({cost / size:.3%})")
print(f"  the same pixels via tifffile's asarray: the whole of level 0, "
      f"{sum(tile_bytes) / 1e6:.0f} MB ({sum(tile_bytes) / size:.0%})")
""")

md("""
### At full resolution, with the boundaries

The next figure draws the window from the overview figure twice. The left panel uses level 2
through the file. The right panel uses level 0 through the element. The nuclei are texture on the
left and objects on the right. The right-hand panel read a few tiles out of 910.

The element is also a real SpatialData image. The last cell below uses the prototype's reader to
rebuild it as a multiscale `Image2DModel`. The model has every pyramid level of the file, each
with its coordinate system.
""")

code("""
FULL_RES_PX = 1.0 / MICRONS_PER_PIXEL

figure, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))

low = (corner / detail_scale).astype(int)
high = ((corner + WINDOW) / detail_scale).astype(int)
coarse = detail[low[1]:high[1], low[0]:high[0]]
axes[0].imshow(coarse, cmap="gray", vmax=np.percentile(coarse, 99.5),
               extent=(corner[0], corner[0] + WINDOW, corner[1] + WINDOW, corner[1]))
axes[0].set(xlabel="x (um)", ylabel="y (um)",
            title=f"level 2 through the file, {coarse.shape[0]}x{coarse.shape[1]} px")

pixel_low = (corner * FULL_RES_PX).astype(int)
pixel_high = ((corner + WINDOW) * FULL_RES_PX).astype(int)
sharp = np.asarray(finest[0, pixel_low[1]:pixel_high[1], pixel_low[0]:pixel_high[0]])
touched = ((pixel_high[1] // 1024) - (pixel_low[1] // 1024) + 1) * (
    (pixel_high[0] // 1024) - (pixel_low[0] // 1024) + 1)
axes[1].imshow(sharp, cmap="gray", vmax=np.percentile(sharp, 99.5),
               extent=(corner[0], corner[0] + WINDOW, corner[1] + WINDOW, corner[1]))
window.boundary.plot(ax=axes[1], color="#ffd60a", linewidth=0.8)
axes[1].set(xlim=(corner[0], corner[0] + WINDOW),
            ylim=(corner[1] + WINDOW, corner[1]), xlabel="x (um)",
            title=f"level 0 through the element, {sharp.shape[0]}x{sharp.shape[1]} px "
                  f"({touched} chunks)")

figure.tight_layout()
print(f"{sharp.shape[0] / coarse.shape[0]:.0f}x the linear resolution, "
      f"{touched} of {n_chunks} level-0 chunks read")
""")

code("""
from spatialdata import read_zarr

with isd.parquet_in_store():
    element = read_zarr(session.store).images["morphology_mip"]
levels = {name: node.ds["image"] for name, node in element.children.items()}
print(f"{type(element).__name__}, {len(levels)} levels")
for name, level in levels.items():
    print(f"  {name}: {tuple(level.shape)}, dims {level.dims}")
print(f"  transformations: {levels['scale0'].attrs['transform']}")
""")

md("""
## It is a repo, so it has a history

The history shows the steps in order. The build referenced the published files. It derived the
boundaries from them. It added the image element. You can
attribute each step separately and read it on its own. Corrections stay in the history. No commit
changed an earlier snapshot.
""")

code("""
for snapshot in repo.ancestry(branch="main"):
    when = snapshot.written_at.strftime("%Y-%m-%d %H:%M")
    print(f"{snapshot.id}  {when}  {snapshot.message}")
""")

md("""
## What this shows

**The read side is ordinary. That is the result.** `pq.ParquetFile`, `tifffile.TiffFile` and
SpatialData's shapes reader all got their data from one repo. That repo holds 13 MB of a 1.33 GB
bundle. We reimplemented no format and patched no reader. The repo addresses the files and does
not move them.

**The cost follows the request, not the size of the data.** The description of 42.6 million
transcripts cost 0.01% of a 670 MB file. A whole-slide overview cost 0.25% of a 628 MB file. The
layouts of Parquet and OME-TIFF do this work. The contribution is only that a byte range into
published storage is as good a chunk as a local one.

**One image, two representations, each with a cost.** As file bytes, it needs no extra
installation, and any OME-TIFF reader can open it. But a full-resolution tile costs a whole
pyramid level. As an image element, a tile is a chunk. The element is a real `Image2DModel` with
its coordinate system. But any read of it requires a JPEG 2000 codec. For interoperability, that
is weaker than the rest of this repo.

**The remaining limits.** The build copies the tail of every file in `files/`, because a Zarr
chunk cannot pad. The image element has no tail, because there a chunk is a whole codestream. The
JPEG 2000 codec comes with `virtual-tiff`. Its fixes for these files are in review and not
released. Thus the environment pins the pull-request branches. SpatialData's own reader needs the
#1107 fsspec change to read geometry out of a store at all. That is one upstream change, on the
read path. With it, the whole approach works with nothing monkeypatched.
""")

write("xenium_from_arraylake.ipynb")
