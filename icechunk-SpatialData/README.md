# icechunk-SpatialData: a spike plan

**Status: the spikes are complete, and a prototype followed them.** The spikes concluded "don't
ship a package". The prototype exists anyway, because it makes the upstream conversation concrete.
The ask is [`UPSTREAM.md`](UPSTREAM.md). The prototype is
[`icechunk_spatialdata/`](icechunk_spatialdata), with `pixi run spike-test` (56 tests).

**S1, S3, S4 and S5 as measured, below.** This project re-checked all four against
[PR #1107](https://github.com/scverse/spatialdata/pull/1107)'s branch. That branch changes the
diagnostics substantially. It does not change the conclusions. See
[re-checked against #1107](#re-checked-against-pr-1107).
The commands are `pixi run spike-s1` / `spike-s3` / `spike-s4`. The sources are under
[`spikes/`](spikes). The results are in [S1](#s1-as-measured), [S3](#s3-as-measured),
[S4](#s4-as-measured) and [S5](#s5-as-measured). See [the conclusion](#conclusion).

The short version:

* **Versioning works** for rasters and tables. It is also SpatialData's own plan, and SpatialData
  scoped it in more detail than this spike reached.
* **Geometry** can join the transaction only as Zarr arrays. That costs no bytes, but it forfeits
  interoperability.
* **References work today for OME-Zarr sources.** They need nothing built, and nobody in this
  ecosystem claims them.
* **References to OME-TIFF** had exactly one missing piece: a Zarr v3 JPEG 2000 codec. The reason
  that this plan first gave was not the blocker. That piece exists. The images become references
  through `virtual-tiff`, which supplies the codec with thirteen other compressions.

This project established the facts below on 2026-08-04. The versions were `spatialdata` 0.8.0 /
`spatialdata-io` 0.7.0 and `virtualizarr` 2.7.1 / `icechunk` 2.1.2. Each fact says how.

## The question

SpatialData is already Zarr-based and already NGFF-aligned. It also has a richer coordinate
transformation set than SOMA. So the question is narrow:

> Does putting a SpatialData store on Icechunk add anything SpatialData does not already have, or
> is not already building?

Two candidate contributions:

1. **Transactional versioning.** ACID commits and time travel cover a whole spatial dataset. An
   annotation pass is then a snapshot and not a mutation.
2. **Virtual chunk references.** These present a spatial dataset over files that nobody can write
   to, and they copy nothing.

SpatialData already does everything else better. The spike exists to find out whether either of
those two contributions holds. If neither holds, the spike stops early.

## Why this is separate from `zarr-SOMA`

* **Different contract.** SOMA is an abstract specification. Its extension mechanism is
  structural typing against `runtime_checkable` Protocols, so a backend *conforms*. SpatialData is
  a Python library with an on-disk format, and it has no protocol surface to implement. The work
  here is not "implement the model in Zarr". It is "back an existing format with a different
  store". That work mostly belongs upstream.
* **Different consumer.** zarr-SOMA serves scanpy. SpatialData serves squidpy and napari.
* **Different dependency weight.** SpatialData needs geopandas, shapely, dask and xarray.
  `zarr-SOMA` deliberately depends on none of them, and it should not add them.
* **Different failure modes.** The plan below is about these.

## What is already established

| # | fact | how |
|---|---|---|
| 1 | Images and labels are Zarr arrays (OME-NGFF). Tables use AnnData's Zarr storage. Icechunk versions these natively. | SpatialData design doc |
| 2 | Transformations are JSON in Zarr attributes under `coordinateTransformations`. Icechunk versions attributes, so it also versions the coordinate model at no extra cost. | design doc |
| 3 | Points and shapes are **Parquet, outside the Zarr hierarchy**. SpatialData's own source says so: *"the parquet file is not recognized as part of the zarr hierarchy as it is not a valid component of a zarr store, e.g. group, array or metadata file."* | `_io/io_shapes.py:79` |
| 4 | **The blocker.** `_write_shapes_v02_v03` does `store_root = group.store_path.store.root`, then `shapes.to_parquet(store_root / group.path / "shapes.parquet")`. | `_io/io_shapes.py:171-177` |
| 5 | `.root` exists **only** on `LocalStore`. The measurement: `LocalStore` yes, `FsspecStore` no, `IcechunkStore` no. So shapes and points are local-filesystem-only today. SpatialData cannot write them to S3, and it cannot write them to Icechunk. | measured |
| 6 | An extension point does exist: `_resolve_zarr_store` accepts `str \| Path \| UPath \| zarr.storage.StoreLike \| zarr.Group`. | `_io/_utils.py:460` |
| 7 | `spatialdata/_io` does not mention `icechunk` anywhere. | grep |
| 8 | VirtualiZarr has no TIFF parser. Its parsers are DMRPP, FITS, HDF4, HDF5, Icechunk, KerchunkJSON, KerchunkParquet, NetCDF3 and Zarr. Xenium morphology images are OME-TIFF. **Two later findings correct this fact.** The missing parser is real, but it is not the obstacle. Format parsers are separate packages by design. TIFF's parser is `virtual-tiff`. It also publishes the Zarr v3 JPEG 2000 codec that S4 named as the real blocker. | measured |
| 9 | SpatialData has a prototype of "lazy file linking" from the 2nd SpatialData Hackathon, June 2026. **S5 resolves this.** The prototype makes soft links to whole files through a JSON-serialized `LazyContainer`. The container defers to the source format's own reader. It does not use chunk-level byte ranges. The same report also scopes an Icechunk integration in detail. | BioHackrXiv, full text |

Fact 5 shapes everything. It also connects to a finding in
[`../docs/zarr-soma/README.md`](../docs/zarr-soma/README.md). NGFF PR #64 tried to standardise
tables in Zarr. It failed because reviewers argued for Parquet instead: *"which is what SpatialData
does"*. That choice is exactly what stops a transactional Zarr store from holding a SpatialData
store. Parquet gave better tabular performance and cost versionability. Nobody appears to have
written that down.

## S1 as measured

The command is `pixi run spike-s1`. It uses `spatialdata.datasets.blobs()` and not a real Xenium
bundle, by design. S1 asks about the *store*. A synthetic dataset with one of every element type
answers that question in seconds, not in gigabytes. Ingest is a different question.

**S1a: the public API rejects a store, with an explicit check.**

```
ValueError: file_path must be a string or a Path object,
            type(file_path) = <class 'icechunk.store.IcechunkStore'>
```

`SpatialData.write()` validates `isinstance(file_path, Path)` *before* it calls
`_resolve_zarr_store`. So the public API cannot reach the extension point at fact 6. The check is
a type check, not an architectural one.

**S1b: the element writers work, and versioning works too.** The spike creates the root group on
an Icechunk session store. Then it calls SpatialData's own `write_image` / `write_labels` /
`write_table` against groups on that store. That succeeds for every raster and table element:

| element | result |
|---|---|
| `blobs_image` | `(3, 512, 512)` identical, scales `['s0']` |
| `blobs_multiscale_image` | `(3, 512, 512)` identical, scales `['s0', 's1', 's2']` |
| `blobs_labels` | `(512, 512)` identical, scales `['s0']` |
| `blobs_multiscale_labels` | `(512, 512)` identical, scales `['s0', 's1', 's2']` |
| `table` | AnnData-in-Zarr, `X` with 78 stored values, `obs`/`obsm`/`layers` all present |

The spike committed all of it and read it back from the snapshot. Each element matched the
in-memory source. A second commit adds an attribute and leaves the first snapshot unchanged. So
**S1 already answers S2's question: versioning works.** Transformations and metadata are Zarr
attributes (fact 2), and Icechunk versions those natively.

The writers are not uniform. The plan had these details wrong:

* Scales are `s0`, `s1`, `s2`, *not* `0`, `1`, `2`.
* `write_labels` takes the **root** group and creates `labels/<name>` itself. `write_image` takes
  the element group. `write_table` takes the element-*type* group.
* The AnnData table goes entirely inside the Zarr store, `StringDType` arrays included. It is not
  a file beside the store.

The spike also confirmed that SpatialData 0.8.0 writes `zarr_format=3` for every element format.
So Icechunk's v3-only constraint is not a blocker.

**S1c: geometry cannot enter the store, exactly as the plan predicted.**

```
shapes  AttributeError: 'IcechunkStore' object has no attribute 'root'
points  AttributeError: 'IcechunkStore' object has no attribute 'root'
```

### What S1 changes

S1 passed, so the first kill criterion does not fire. But the result is uneven.
**An Icechunk-backed SpatialData versions everything except the geometry.** Xenium and CosMx are
the imaging assays that motivated this work. For them, the geometry is the part that nobody else
versions. So the whole spike depends on S3.

This plan's own reasoning needs one correction. It claimed that the SpatialData stack "cannot be
assumed to co-resolve with this project's pinned `pandas` and `somacore`". It does co-resolve: the
`spatial` environment resolved to the same `pandas` 3.0.5 as the default one. The isolation is
still useful, but only for the dependency-weight reason. The resolver reason does not apply.

## S3 as measured

The command is `pixi run spike-s3`. It measures correctness on `blobs()`. It measures cost at scale
on 10x's published cell boundaries.

**(a) Route Parquet through `store.set()`: impossible on Icechunk.**

```
Icechunk   InvalidInputError: invalid zarr key format `shapes/blobs_circles/shapes.parquet`
LocalStore ACCEPTED the same key
```

Icechunk is a Zarr store, not a key-value store. It accepts only `zarr.json` and chunk keys. The
plan imagined an upstream change: buffer the Parquet, and hand the bytes to the store. That change
would make shapes writable to S3 for SpatialData in general. It is a real improvement, but it
still does not put geometry in Icechunk. So, for the purpose here, this result eliminates (a).

**(b) Geometry as Zarr arrays: works, and costs nothing in bytes.** Both encodings round-trip all
three `blobs()` shape elements, and the geometry stays byte-identical:

* **(b1) blob.** The GeoParquet bytes go into one 1-D `uint8` array. It is exact, trivial and
  opaque.
* **(b2) native.** WKB goes, concatenated, into a `uint8` values array plus an `int64` offsets
  array. The attribute columns are their own arrays. `zarr-SOMA` uses the same values-and-offsets
  shape for sparse data. It is legible with no Parquet reader, and each column chunks independently.

At real scale, 2,181,086 vertex rows become 167,780 polygons. The codec is the same for each
encoding:

| encoding | size | vs baseline |
|---|---|---|
| geoparquet, uncompressed | 38.8 MB | |
| geoparquet, snappy (geopandas default) | 16.8 MB | |
| **geoparquet, zstd** | **12.2 MB** | the fair baseline |
| icechunk, blob | 13.1 MB | 1.07× |
| icechunk, native | 11.4 MB | **0.94×** |
| 10x's published file, for context | 8.8 MB | |

Two corrections to expectations that this plan stated earlier:

* **The byte argument against (b) fails under measurement.** With the same codec on both sides, the
  values-and-offsets encoding is *marginally smaller* than GeoParquet. The uncompressed WKB figure
  makes it look expensive, and that number never reaches disk.
* **10x's own file is smaller than all of them, for a reason unrelated to encoding.** It stores
  vertex rows with float32 coordinates, and WKB polygons are always float64. The difference is
  content, not codec.

So the cost of (b) is interoperability alone. Only this code can read the resulting store, and that
forfeits the thing SpatialData exists to provide.

**(c) Leave the Parquet beside the repository: the cost, on a real bundle.** The 10x Xenium breast
cancer Rep1 bundle is 7.16 GB:

| file | size | where it goes |
|---|---|---|
| `morphology.ome.tif` | 5178.5 MB | image, needs conversion |
| `transcripts.parquet` | 669.8 MB | points, **outside** |
| `morphology_focus.ome.tif` | 654.8 MB | image, needs conversion |
| `morphology_mip.ome.tif` | 627.8 MB | image, needs conversion |
| `cell_feature_matrix.h5` | 12.1 MB | table, in Zarr |
| `cell_boundaries.parquet` | 8.8 MB | shapes, **outside** |
| `nucleus_boundaries.parquet` | 8.3 MB | shapes, **outside** |
| `cells.parquet` | 3.5 MB | merged into the table |

686.8 MB, or 9.6% of bytes, would stay outside the repository, unversioned and outside the
transaction. The byte share understates the problem. That 9.6% is every transcript position and
every cell and nucleus boundary. It is all of the geometry. It is also the only thing that Xenium
has and a Visium slide does not.

The same table also shows a fact for S4: **90.2% of the bundle is OME-TIFF**. Fact 8 says that
VirtualiZarr cannot make references to TIFF. So an Icechunk-backed SpatialData of this dataset
needs a conversion of 6.46 GB of images. That conversion is a copy, and the goal is no copy.

### What S3 decides

Ranked by the measurements:

1. **(b2) native arrays** is the only option that puts the whole dataset under one transaction. It
   is also free in bytes. Its cost: no existing reader understands the result. For a format whose
   value *is* interoperability, that cost alone nearly disqualifies it.
2. **(a) upstream** has merit on its own. It would make SpatialData's geometry writable to the
   cloud. SpatialData cannot write geometry to any remote store today. But (a) does not serve this
   spike.
3. **(c) split** is the only option that keeps the format intact. It gives up versioning for
   exactly the elements that motivated the exercise.

None of the three is good.

## S4 as measured

The command is `pixi run spike-s4`. S3 showed that 90% of a Xenium bundle is OME-TIFF. So
contribution 2 succeeds or fails here.

**An OME-Zarr source becomes references natively, with nothing to build.** VirtualiZarr's
`ZarrParser` turns an existing Zarr hierarchy into chunk references, one per chunk. The read-back
was identical. So an Icechunk repository can present a *published OME-Zarr pyramid* and copy no
bytes. This is the strongest case for contribution 2 in the spike. It needs no code from this
project.

**An OME-TIFF's tiles are valid virtual chunks.** 10x's `morphology_mip.ome.tif` already has
1024×1024 tiles across 8 pyramid levels, `uint16`. That layout is structurally a Zarr chunk grid.
`tifffile.aszarr().write_fsspec()` emits 1,255 kerchunk entries that cover all 8 levels. Of those,
1,237 are literal `(url, offset, length)` triples, and OME `multiscales` metadata comes with them.
Chunk `0/0.0` is 504,157 bytes at offset 11,344. A plain HTTP range request gets exactly those
bytes. `imagecodecs_jpeg2k` decodes them, and the tile is **identical to tifffile's own read**. So
the references are correct and the bytes are decodable.

**And the blocker was one layer below where this plan looked.** A later finding resolves it: see
[the codec, found](#the-codec-found). The tiles are JPEG 2000. When this spike measured them, Zarr
v3 shipped no JPEG 2000 codec. Numcodecs' v2 registry did not supply one to Zarr v3 either.
Icechunk is Zarr v3 only, so a process could write the references but never read them.

An install of `virtual-tiff` resolves the gap. The package that parses the file also publishes the
codec through zarr's entry points:

```
zarr v3 get_codec_class('imagecodecs_jpeg2k')            -> Jpeg2KCodec
zarr v3 get_codec_class('numcodecs.imagecodecs_jpeg2k')  -> KeyError
zarr v3 get_codec_class('jpeg2k')                        -> KeyError
numcodecs v2 registry has it                             -> True
```

`pixi run spike-s4` asserts that the first of those resolves. It once asserted the opposite. The
gap was never a capability, only a name.

### What S4 changes

Fact 8 blamed the missing VirtualiZarr TIFF parser. That diagnosis was wrong. The parser gap is
real, but another route exists. The actual blocker is a single missing codec wrapper. This changes
the size of the fix from "write a TIFF parser" to "wrap one codec for Zarr v3". That wrapper would
unblock every OME-TIFF with JPEG2000 tiles. That is most of digital pathology, and not only Xenium.

It also gives two clear answers to whether OME-Zarr helps:

* **For data already in OME-Zarr:** yes, decisively, and today.
* **For OME-TIFF:** no, because the conversion *is* the copy. But a reference to the TIFF in place
  needs only one small codec. That is a much better position than this plan assumed.

### The codec, found

That "one small codec" already existed, in two packages.

**First, `osml-imagery-io`** (AWS Labs, Apache 2.0). It ships JPEG 2000, JPEG, TIFF-tile, DTED and
NITF-block codecs as genuine Zarr v3 `BytesBytesCodec`s. It proved that the full read path works,
and it exposed a bug. A numcodecs shim shadowed the v3 batch `decode`: `Jpeg2000Codec.decode(buf,
out=None)` overrode `BaseCodec.decode(chunks_and_specs)`. So every v3 read raised `TypeError:
'tuple' object cannot be interpreted as an integer`. The error came before the read reached the
working `_decode_single`. The whole fix was one guard per codec, [merged as PR
#9](https://github.com/awslabs/osml-imagery-io/pull/9).

**Then `virtual-tiff`**, which reads the images. The package that parses the TIFF publishes the
codec, so decoding needs no separate install. osml is out of the environment entirely. The probe
and the runtime workaround that it carried are out too.

That route pinned facts that the first route did not:

* **The TIFF tiles are JP2 containers, not bare codestreams.** osml's codec rejected a container
  because the container has no SOC marker at its start. A reference could skip the container with
  a start 85 bytes in. A reference cannot transform bytes, but it can skip them. `virtual-tiff`'s
  codec reads the container, so the references point at the tile as the file stores it.
* **The decoder returns `(bands, y, x)`.** `Image2DModel` requires exactly that, and AnnData's own
  images do not have it. So the transposition objection in blocker 3 does not apply on this route.
* **A codec name is published data.** `virtual-tiff` wrote `ChunkyCodec` into array metadata, but
  its entry point published `virtual_tiff.ChunkyCodec`. So the H&E decoded only in a process that
  had already imported the parser. The name fix meant a rewrite of the element in an already
  published store, from the same byte ranges.

So `images/morphology_mip` in `earthmover-demos/xenium-virtual-bundle` reads back identical to
tifffile's own decode. It needs no codec installed by hand.

### And so the images become an element

`virtual_image` in [`_virtual.py`](icechunk_spatialdata/_virtual.py) builds the whole pyramid as a
SpatialData image element. The element has one array per level, with the names `s0`…`s7`. Its
chunks are references to the tiles. The code writes the OME `multiscales` metadata by hand, because
`write_image` writes pixels and there are none to write. `_read_raster` then rebuilds the element
as an `Image2DModel` with its coordinate system. It needs no new read path.

For `morphology_mip.ome.tif` the result is **1,237 references across 8 levels and no copied bytes
at all**. There is not even a tail. A chunk is a whole codestream, not a fixed slice of a file.
So `reference_file`'s padding problem does not occur. Level 0 has 910 of those references.
One 1024×1024 tile out of its 25,778 × 35,416 costs one range request. That tile is identical to
tifffile's own decode.

The code measures the per-level scale from the shapes. An OME-TIFF pyramid halves with rounding,
so level 2 of a 25,778-row image is 4.0003× and not 4×.

**The prototype and the upload script keep both representations**, because each one is good at
different things:

| | opaque file | image element |
|---|---|---|
| needs a JPEG 2000 codec installed | no | **yes** |
| readable by anything that reads an OME-TIFF | yes | no |
| is a SpatialData / OME-NGFF element | no | yes |
| cheap full-resolution random access | no | yes |
| copied bytes | one tail per file | none |

That first row is the real cost. It also conflicts with a rule that this project follows
elsewhere. *Unmodified* `anndata` reads a table's `X`, but this image needs a third-party package.
It is not a private encoding: a URL-named codec is exactly Zarr v3's extension mechanism. The
package is Apache 2.0 on PyPI. But "needs a codec installed" is weaker than "needs nothing".
Arraylake's viewer cannot render the image either. The opaque file keeps the bundle legible
without the codec.

## S5 as measured

S5 is not code. It is the full hackathon preprint (`doi:10.37044/osf.io/s6bph_v1`, 612 lines of
extracted text), plus the pull requests it cites. It gave two findings, and they point in opposite
directions.

### Contribution 1 is already theirs, with a better scope than this spike reached

The report has a section titled *"Submit a PR for using icechunk for incremental IO"*. It names
Icechunk and identifies the same extension point that S1 found. It also goes further:

> By presenting itself as a standard Zarr V3 store via the `session.store` interface, Icechunk can
> be integrated into the SpatialData ecosystem. […] To bridge the gap in stateful write lifecycles,
> we propose two core hooks and a dedicated `spatialdata-icechunk` extension. These include ensuring
> `spatialdata._io` writers dynamically access the active store and implementing a
> `ParallelWriteBackend` protocol […] This architecture enables a transaction-based API—exemplified
> by `with sdi.transaction(sdata):`

"Ensuring writers dynamically access the active store" is exactly the S1a failure, the type check
on `file_path`. They identified it independently, and they attached a design. So S1 is a
rediscovery, and it is useful only as confirmation.

**But none of it exists as code.** `spatialdata-icechunk` appears exactly once in the report and
nowhere else. GitHub repository search returns 0 results, and PyPI returns 404. Its prerequisite is
an open PR, and `main` still cannot write geometry to any remote store. So "already theirs" means
*designed and intended*, not *implemented*. This project should still cede it. A duplicate of a
published design that its own maintainers intend to execute is waste. But the plan must not imply
that the code exists.

**The report treats the prerequisites as done, and they are not.** It says that the read path
supports Icechunk snapshots "following the finalization of cloud IO improvements [#1087]". Those
improvements move `sdata.path` to a generic `sdata.store` handle. They also migrate parquet-based
elements to native Zarr. A check gave this status:

| | |
|---|---|
| PR #1087, *Cloud storage support (Azure, S3, GCS)* | **closed, unmerged** |
| PR #1107, *generalize Zarr I/O … remote (fsspec / UPath) backends* | **open**, last updated 2026-06-12, +1157/−276 |
| `main` today | still writes `shapes.parquet` via `group.store_path.store.root` |

The summary of #1107 itself also describes *"Arrow-filesystem I/O for points / shapes Parquet"*.
That design keeps Parquet and reaches it through an Arrow filesystem. It makes geometry writable
to S3, but the geometry stays outside a Zarr store. That is not the "migrates parquet-based
elements to native Zarr" that the Icechunk section assumes. Maybe the intent changed when another
PR replaced PR #1087. Or maybe the migration is a separate piece that nobody has started. The
sources do not say which, and this plan does not guess.

Either way, this **confirms S3 and does not overturn it**. On the current trajectory, geometry
stays Parquet. So it stays outside any Icechunk transaction.

### Contribution 2 is not theirs, and is a different mechanism

"Lazy file linking" makes soft links to whole files. It does not virtualize chunks:

> Prototype 1 [#12]: A new class of `LazyContainer` that only stores the location of external files
> (local or remote) will be added. This will only be serialized to JSON format. Once SpatialData
> gets initialized, it will mount the `LazyContainer`s to SpatialData without materializing them.
> The data will only be parsed when the user accesses it explicitly […]

Four differences matter:

| | lazy file linking | virtual chunk references |
|---|---|---|
| granularity | whole file | per chunk, `(url, offset, length)` |
| needs at read time | the source format's own reader (they name CSV, OME-TIFF, proprietary formats) | a Zarr codec |
| serialization | JSON beside the store | chunk manifests inside it |
| expected cost | *"would improve ergonomics at a potential performance cost"* (their words) | Zarr-native chunk reads, no reader detour |

Note the third row. A `LazyContainer` serialized to JSON has exactly the problem that S3 hit,
because Icechunk does not hold a non-Zarr key. Also, `VirtualiZarr` and `kerchunk` appear **zero
times** in the report, and Icechunk appears five times.

So the two mechanisms complement each other and do not compete. Nobody in this ecosystem claims
byte-range references. The kill criterion is "if lazy file linking covers referencing, contribution
2 is gone". It **does not fire**.

## Re-checked against PR #1107

This project ran the spikes first against `spatialdata` 0.8.0. Then it ran them again against
[#1107](https://github.com/scverse/spatialdata/pull/1107) (`selmanozleyen/spatialdata@5443b05`).
That run made about half of the written diagnostics obsolete. It confirmed the rest:

**Fixed by #1107:** the dead `zarr.storage.ConsolidatedMetadataStore` reference, `read_zarr`'s
eager `.root`, and the path assumptions in `io_zarr.py`, `io_shapes.py` and `io_points.py`. #1107
reduces those path assumptions from eight sites to four, and all four are in `_io/_utils.py`.
`write()` and the geometry writers refuse a pathless store with deliberate, informative messages,
not `AttributeError`s. `path_from_store` documents that it returns `None` for pathless stores.

**Unchanged by #1107:** every functional outcome. The prototype's 56 tests pass identically on
both. The exception is the one test that exercises the fsspec extension point, which skips on the
release. Element writers work against a group on an Icechunk store. `write()` and `read_zarr()`
still refuse one. Geometry still cannot enter one, for two reasons. `parquet_fs_and_path` raises
for any store that is not `LocalStore` or `FsspecStore`. Icechunk also refuses non-Zarr keys
regardless.

**And one blocker moved to `ome-zarr-py`, and then back to SpatialData.** With #1107, `read_zarr`
reaches the raster reader. Before `ome-zarr` 0.21.0, it then failed inside `ome-zarr-py`: `ZarrLocation` rejected a
store. `ome-zarr-py` merged a fix as [#674](https://github.com/ome/ome-zarr-py/pull/674) and
released it in 0.21.0. The raster read now fails in SpatialData. SpatialData gives `ZarrLocation`
the container root. [`upstream/0003`](upstream/0003-keep-the-element-location.patch) fixes that.

**The negative tests first pinned exception types. #1107 changes every one of those types, and it
changes no outcome.** So four tests reported regressions that were not regressions. The tests
assert that a capability is still missing. They also list the characterised failure modes per
version. So they are valid against both versions. They still fail if upstream actually adds the
capability.

## How far this goes without upstream

The answer: further than expected, and then one blocker remains.

### What works today, with no upstream change

| | |
|---|---|
| rasters and tables written to an Icechunk store | ✔ SpatialData's own element writers, unmodified |
| multiscale pyramids, the AnnData table, `coordinateTransformations` | ✔ byte-identical through a commit |
| ACID commits, branches, time travel, a failed write that leaves no snapshot | ✔ |
| a store-clean read that rebuilds real `SpatialData` objects | ✔ this prototype's reader |
| geometry inside the transaction | ✔ but in a non-standard encoding |
| **a table whose `X` is byte ranges in a public `.h5ad`** | ✔ **and unmodified `anndata` reads it** |

That last row is the furthest result. It is also the one thing here that SpatialData has no plan
for. An `.h5ad` stores `X` as `data`/`indices`/`indptr`, and AnnData-in-Zarr uses *the same three
names*. So the Zarr arrays can be references into the HDF5 file's own chunks. The measurement used
a public CELLxGENE Visium h5ad: 4,992 × 32,397, 8,990,335 stored values, 1,540 references. The
whole repository is **0.08 MB**. `anndata.io.read_elem` returns a genuine `csr_matrix`. That is
not a private encoding. It is a standard AnnData element that holds no bytes of its own.

So this approach can assemble a versioned SpatialData-shaped dataset over somebody else's immutable
files. That is this project's thesis.

### Three blockers, and only one of them is upstream's

**1. Interop: the real limit.** No unmodified tool can open the store. `SpatialData.write()`
refuses it, and `read_zarr()` refuses it. On #1107 the raster reader fails on it. So only
this prototype and `anndata` (for the table) can read the store. napari and squidpy cannot.
**This is the only blocker that an upstream change would remove.** Nothing more is possible until
the read path accepts a store.

**2. Geometry format.** ~~Icechunk refuses non-Zarr keys, so geometry can be in the transaction
only if it is not Parquet.~~ **Solved: see [the fix for blocker 2](#the-fix-for-blocker-2).** The
fix needed no Icechunk change and no SpatialData format change.

**3. ~~References cannot transform bytes.~~** **Both halves of this blocker were wrong, and the
second half stayed wrong for longer.** ~~OME-TIFF images need a Zarr v3 JPEG 2000 codec that does
not exist (S4).~~ The codec exists: see [the codec, found](#the-codec-found). A reference skips the
JP2 wrapper with a later start. ~~And the images inside a Visium h5ad cannot become elements.
AnnData writes them channel-last, but `Image2DModel` requires `("c", "y", "x")`. A transpose means
a rewrite of the bytes.~~ **The bytes never needed a transpose.** Zarr v3 has a `transpose` codec
in its core spec. So an element declares `(c, y, x)`, and the stored chunks stay channel-last. The
read pipeline does the permutation. A test on 10x's interleaved RGB H&E verified this: 731
references across six levels, bit-identical to tifffile after the transpose. A test on a public
Visium h5ad's `hires` image also verified it, at 384 references.

A reference genuinely cannot **re-encode**. An array keeps the source's dtype and compression.
That is the real limit, and it is narrower than "cannot transform bytes". A codec can express a
transpose. A change of compression or dtype has no codec form.

### The fix for blocker 2

Two questions remain: what a fix looks like, and whether a change to Icechunk for non-Zarr keys is
an option. Both are the same question, and neither project needs a change.

Icechunk refuses non-Zarr keys, so a Parquet *file* cannot go in a repository. But PR #1107
already puts geometry I/O behind an **fsspec filesystem**. `io_shapes` and `io_points` call
`parquet_fs_and_path(group, "shapes.parquet")` and then `fs.open(...)`. They never touch a real
path. Zarr accepts an array named `shapes.parquet`, at exactly that path. So a *file* can be a 1-D
`uint8` Zarr array. The mapping between the fsspec namespace and the Zarr namespace is then the
**identity**.

`_filesystem.py` implements that in about 120 lines. With it, on the #1107 branch:

```
shapes/blobs_circles/shapes.parquet                array (3210,) uint8
shapes/blobs_polygons/shapes.parquet               array (3065,) uint8
points/blobs_points/points.parquet/part.0.parquet  array (6854,) uint8
```

The result is geometry in **SpatialData's own format**. SpatialData's own writers and readers write
it and read it back, entirely inside the Icechunk transaction. Nothing goes to any filesystem. The
dask-partitioned points case works too. `points.parquet` becomes a *group* that holds its parts,
because the filesystem implements directory semantics.

Upstream, the change is one extra branch in `parquet_fs_and_path`. For stores with no path, it
returns a filesystem and does not raise. That is a far smaller ask than the format change that this
plan assumed.

### Icechunk can support non-Zarr keys, but it should not

It is an option, but this evidence says not to take it. The capability is reachable without it, and
the reachable version is *better*.

**What the array route gives that an opaque key does not.** File bytes as a Zarr array are ordinary
chunks. So they get compression, per-chunk conflict detection, and **virtual chunk references**. A
repository could reference a remote `.parquet` and not copy it. An opaque blob could not do that
unless someone built the same machinery again.

**What an opaque key gives that the array route does not.** It gives literal key names, visible to
consumers that bypass the adapter. But nothing bypasses the adapter. Icechunk's stored objects are
internal, and no external tool reads them as files. So the unique benefit is close to zero.

**What it would cost.** It would need a spec version bump and a new node type. Every implementation
would then have to handle both. It would also need new conflict semantics. An opaque object can
only be last-write-wins, because nothing can merge two edits to a Parquet file. New reachability
and garbage-collection rules would follow. It would also shift the positioning from "transactional
Zarr" to "transactional object store". That shift makes every sidecar format acceptable. An easy
sidecar path removes the reason to make formats Zarr-native. That last point is the
[NGFF #64](../docs/zarr-soma/README.md) argument in reverse. It is a product decision, not a
technical one.

**The one real argument to standardise something.** An adapter is a convention that only its users
share. Two tools that store sidecars as `uint8` arrays with different conventions cannot read each
other's data. That problem needs a fix, but at the **Zarr or NGFF level**. The fix would be "file
bytes in a `uint8` array with a declared `encoding` attribute". At that level it would help every
Zarr store, not only Icechunk.

**Known limitation of the implementation here**, because it affects the recommendation.
`_WriteFile` buffers a whole file in memory before it flushes, because a Parquet writer seeks back
to fix its footer. That is fine for geometry, and not fine for a 670 MB `transcripts.parquet`. A
chunk-at-a-time writer with a footer patch is possible. The question did not need it.

### References to Parquet too

The next question is whether the Parquet in a Xenium bundle can be references and not copies. The
bundle has four Parquet files, and `transcripts.parquet` alone is 670 MB. The answer is yes: **a
`uint8` array has no codec, so a chunk is exactly a byte range.** A codec-bearing array needs the
source's own encoding to match. That requirement is the whole reason JPEG 2000 blocks the images.
An opaque byte array needs nothing to match at all. This method works for any format.

The measurement used 10x's published `cell_boundaries.parquet`, 8,807,145 bytes:

| | |
|---|---|
| whole file as one referenced chunk | repository is **3.1 kB** |
| 1 MiB chunks, 8 references plus a materialized tail | repository is **1.05 MB** (the tail) |
| `pq.read_table` output | identical to a direct read of the file |

The tail is the one complication. Zarr chunks have a fixed size. So the final chunk of a file
whose length is not a multiple of the chunk size needs padding. A byte range cannot pad. So
`n - 1` chunks are references, and the tail is a copy of at most one chunk. A smaller chunk size
shrinks the copy and raises the reference count.

Multiple chunks help on read, because pyarrow fetches slices on demand:

| what pyarrow requested | bytes read |
|---|---|
| metadata only | 0.07 MB, **0.7%** of the file |
| one row group | 4.13 MB, 47% |
| the whole table | 8.87 MB, 100% |

So a SpatialData store over a whole Xenium bundle could hold almost none of the bytes. The table's
`X` is references into the h5ad. The geometry and transcripts are references into the published
Parquet. Only the images are outside this method, for the codec reason, which is a separate issue.

`reference_file` in [`_reference.py`](icechunk_spatialdata/_reference.py) implements this, with two
tests.

**An incidental finding, which a test pins.** 10x's `cell_boundaries.parquet` declares
`num_rows = 1,000,000` in its footer, but its three row groups sum to 2,181,086. fastparquet 1.0.0
wrote it. An independent ranged read of the published file confirmed this. So the error is in the
file and not in the reader. Anything that trusts `metadata.num_rows` for that file gets a wrong
answer.

### And the images, as files

The same method reaches the OME-TIFFs. The difference between the two routes is the entire content
of the codec gap.

A reference to the *file* needs no codec, so it works. `morphology_mip.ome.tif` takes 598
references. The repository is 1.06 MB against 627.8 MB, or 0.17%. `tifffile` reads it through the
same lazy handle, and decodes JPEG 2000 itself through `imagecodecs`. Partial reads are cheap:

| | bytes read |
|---|---|
| the pyramid structure: 8 levels, 25778 × 35416, uint16 | 0.65 MB, **0.10%** |
| pyramid level 5, 805 × 1106 | 0.92 MB, **0.15%** |

The pixels are identical to a direct ranged read of the published file. A browsable overview for a
fraction of a percent is exactly what a viewer wants.

**This is not** an image *element*. The pixels are not a Zarr array, so no Zarr-native tool can see
them. SpatialData cannot, and napari cannot. A Zarr v3 JPEG 2000 codec adds exactly that and
nothing else, because the file is already reachable without it. That codec exists. See
[the codec, found](#the-codec-found), where the same image is a Zarr array of byte ranges.

One limit: a *full-resolution tile* needs `tifffile`'s own Zarr view. zarr 3 cannot open a
`ZarrTiffStore`, which is a v2-style mapping and not a `Store`. A route through `asarray()` decodes
the whole level, and for level 0 that read 450 MB. So **this route** gives no cheap random access at
full resolution. That is the argument for the other route. As an image element, the same level 0 is
a chunk grid, and one tile is one range request. See [the codec, found](#the-codec-found).

### On Arraylake

The upload is complete. Of the four blockers, three were trivial and none was substantive for this
dataset. The repository is `earthmover-demos/spatialdata-visium-virtual`.
[`../scripts/upload_spatialdata_arraylake.py`](../scripts/upload_spatialdata_arraylake.py) builds
it.

It holds a real Visium dataset, 4,992 spots × 32,397 genes. `tables/table` has an `X` of **1,540
virtual chunk references** into CZI's public h5ad. `shapes/spots` is a materialized copy. The
repository holds no expression data. The read-back goes through `client.get_repo`. That is exactly
the call that returns HTTP 400 when the access policy is missing. So the read-back exercises the
whole path: `csr_matrix`, 8,990,335 values, and per-spot totals that match the local run.

What it needed:

* The three-piece setup from [[arraylake-virtual-chunk-setup]]. `earthmover-demos` already had it
  from the earlier Braun work. It includes a bucket config for the census bucket with anonymous
  auth. It also includes a public Virtual Chunk Access Policy over
  `s3://cellxgene-census-public-us-west-2/`.
* `arraylake` in the `spatial` pixi feature. That feature takes no default features, and the
  SpatialData write has to run from there. There was no version conflict.

**The one real blocker was about Xenium, not this dataset.** A later section retires the workaround
below, because the objects were in a public bucket from the start. Arraylake's bucket configs
accept `Platform = Literal['s3', 's3-compatible', 'minio', 'gs', 'azure']`.
`authorize_virtual_chunk_access` maps a URL prefix to a bucket *nickname*. An
`https://cf.10xgenomics.com/` prefix has no nickname to map to. So nobody could authorize the 10x
Parquet and OME-TIFF references. A plain S3 URI does not serve the data either. Both addressing
styles return 404.

**The workaround works for the full read path.** CloudFront serves plain path GETs, which have the
shape of path-style S3. The workaround registers CloudFront as an `s3-compatible` bucket:

```python
client.create_bucket_config(
    org=..., nickname="tenx-cloudfront",
    uri="s3://samples",                          # the first path segment of the URL
    endpoint_url="https://cf.10xgenomics.com",   # marks it s3-compatible
    force_path_style=True,
    auth_config={"method": "anonymous"},
)
```

A public VCAP over `s3://samples/` completes the setup. With both, references written as
`s3://samples/xenium/…` resolve to the real URL. Icechunk only ever issues ranged GETs for virtual
chunks, so nothing needs the S3 semantics that CloudFront lacks.

`earthmover-demos/xenium-virtual-bundle` is the result.
[`../scripts/upload_xenium_arraylake.py`](../scripts/upload_xenium_arraylake.py) builds it against
the #1107 branch. **It addresses 1.33 GB across five published files with 313 references. It
copies only each file's short tail:**

| | |
|---|---|
| `transcripts.parquet` | 669.8 MB, 159 references |
| `morphology_mip.ome.tif` | 627.8 MB, 149 references |
| `cell_feature_matrix.h5` | 12.1 MB, 2 references |
| `cell_boundaries.parquet` | 8.8 MB, 2 references |
| `nucleus_boundaries.parquet` | 8.3 MB, 1 reference |

The read-back goes through `client.get_repo`, the call that returns 400 without the access policy:

| | |
|---|---|
| transcripts metadata | 42,638,083 rows, 43 row groups, for 0.07 MB, **0.01%** |
| morphology pyramid + level 5 overview | 8 levels, 25778 × 35416, for 1.57 MB, **0.25%** |
| `shapes/cell_boundaries` | 167,780 polygons, read by **SpatialData's own reader** |

The repository is older than the JPEG 2000 codec finding, so a fourth commit added
`images/morphology_mip`. That element holds the same OME-TIFF's pixels as Zarr arrays: **1,237 more
references and no copied bytes**.
[`../scripts/add_xenium_image_element.py`](../scripts/add_xenium_image_element.py)
(`pixi run xenium-al-image`) adds it. A new element is a commit. The three earlier snapshots are
unchanged. The script asserts that the first snapshot still does not have the element.

| | |
|---|---|
| built from | the *referenced* file already in the repository, for 2.21 MB of the 627.8 MB it describes |
| `images/morphology_mip` | 8 levels, `(1, 25778, 35416)` at full resolution |
| one full-resolution 1024×1024 tile | one range request |

That last row is what the opaque file cannot do cheaply. It is the whole reason to keep both.
`upload_xenium_arraylake.py` writes the element itself, so a build from scratch produces the
complete repository in one pass.

[`../notebooks/xenium_from_arraylake.ipynb`](../notebooks/xenium_from_arraylake.ipynb) is the read
half. It opens the repository and prunes transcripts with the Parquet footer. Then it pulls two
pyramid levels and draws the cell boundaries over the tissue.

The `shapes/cell_boundaries` row is the part that needed the #1107 branch. The polygons come from
the *referenced* vertex table. SpatialData's own `write_shapes` wrote them through the #1107 fsspec
extension point. So the element is in SpatialData's format, inside the transaction, beside the
references that it came from.

**This project retired the CloudFront workaround, because it was never necessary.** The same
objects are in a bucket that 10x owns: `s3://10x.files/samples/…`. That bucket is public and
allows anonymous path-style reads. So a container can name the real bucket. Both stores point at
that bucket, and the upload scripts use it by default.

The workaround also had a failure mode. CloudFront returns `x-amz-checksum-type: FULL_OBJECT` for
`transcripts.zarr.zip`, and the origin returns no such header. So an S3 client validated a
whole-object checksum against a ranged body, and every reference into that object failed. The lung
store's transcripts became unreadable, although nothing about the store changed. The workaround put
an S3 client in front of a CDN. That is the only reason the failure could happen. See
[`upstream/`](upstream).

Two facts applied to the workaround while it was in use. CloudFront is not S3. The workaround
depended on 10x's paths that begin `/samples/`, so the `uri` had to match that first path segment.
The write step fetches the tail of each file over plain HTTPS in both setups. The `s3://` form
serves Icechunk in both setups.

### The remaining limit

This project assembles a fully versioned spatial dataset over public files. The dataset holds no
expression data. It keeps every coordinate transformation intact, and **its geometry stays in
SpatialData's own format**. Only this code can *open* it, because SpatialData's public read and
write functions refuse a store.

So work outside SpatialData removed two of the three blockers. Geometry needs an fsspec adapter.
The table can hold no counts at all. What remains is interop, and only interop: no unmodified tool
opens the store. This project cannot close that gap from its side. It is also the smallest of the
three asks. The read path must accept a store. `ome-zarr-py`'s `ZarrLocation` accepts one since
0.21.0.

## Conclusion

The spike is complete. The answer is: do not build a package.

**Contribution 1, versioning: cede it.** SpatialData scoped an Icechunk integration in more detail
than this spike reached. That scope includes the failure mode that S1 found. A competing
implementation would duplicate work that the format maintainers already designed.

**Contribution 2, references: real, unclaimed, and no longer blocked.** OME-Zarr sources work as
references natively today. OME-TIFF sources are 90% of a Xenium bundle by bytes (S3). They needed
a Zarr v3 JPEG 2000 codec. S4 found the codec missing, but `osml-imagery-io` ships one: see
[the codec, found](#the-codec-found). So all of a Xenium bundle works as references: table,
geometry, transcripts and images. None of it is a SpatialData contribution.

So the result is this write-up plus two narrow findings for upstream:

1. ~~**zarr cannot read through `osml-imagery-io`'s codecs as shipped.**~~ Their numcodecs
   compatibility `decode` shadowed `BaseCodec.decode`. The whole fix was one guard per codec,
   [merged as PR #9](https://github.com/awslabs/osml-imagery-io/pull/9). This project deleted the
   patch and its verifier. `virtual-tiff` reads the images, and osml is out of the environment.
   [`upstream/`](upstream) keeps the shape of the mistake, because the mistake is about
   subclassing, not about that library.
2. **S3's measurement**, for the geometry question. At Xenium scale, with the same codec, geometry
   as Zarr arrays is 11.4 MB against GeoParquet's 12.2 MB. So "native Zarr for shapes and points"
   is not the size regression that a reader might assume.

This project keeps the measurements. Nobody else has written them down:

* The writers that work against a store today, and the exact way the public API refuses one.
* Geometry in Zarr is free in bytes.
* A JPEG2000-tiled OME-TIFF is a Zarr array of byte ranges, once one codec stops shadowing its own
  read path.

## The spike, cheapest first

Each step has a stop condition. The goal is to stop early on a failure, not to build.

**S1: test whether Icechunk can back a raster-only SpatialData at all. Done, passed.**
See [S1 as measured](#s1-as-measured). The public `write()` rejects a store on a type check. But
the element writers work against groups on an Icechunk session. The result commits and
round-trips.

**S2: test whether versioning works through a full write, commit and read cycle. S1b answered
it in passing.**
Two commits: the second adds an attribute, and the first snapshot is unchanged. The rest of S2 is
narrower, and it is worth doing only with S3. It asks whether a *transformation* in particular
stays intact through a rewrite and a re-commit. Analysts actually edit that metadata. That test is
cheap once S3 decides where geometry goes.

**S3: decide what to do about Parquet. Done.** See [S3 as measured](#s3-as-measured). The spike
tried all three options, and none is good. The three, as the plan first framed them:
  * *(a) upstream.* Route Parquet writes through the store (`to_parquet` to a buffer, then
    `store.set()`). This is the cleanest option, but it changes SpatialData. That makes it a
    contribution there, not a project here. It also changes the on-disk format, so it needs their
    format versioning.
  * *(b) blob-in-Zarr.* Write the Parquet bytes as a 1-D `uint8` Zarr array inside the store.
    Everything stays transactional, and no upstream change is necessary. But only this code can
    read the store, and that forfeits the interoperability that is SpatialData's whole point.
  * *(c) split.* Leave Parquet on the filesystem beside the Icechunk repository. This needs no
    work. But the dataset then versions everything except the geometry. For Xenium the geometry is
    the interesting part.

**S4: find which elements can become virtual references.** Element by element, for a Xenium
bundle:
  * `cell_feature_matrix.h5` → **yes**, and its strings too.
    [`../probes/tenx_matrix_virtualization.py`](../probes/tenx_matrix_virtualization.py) already
    measured this.
  * `transcripts.parquet`, `cell_boundaries.parquet` → **no**. Parquet row groups are not Zarr
    chunks, and a chunk manifest cannot address them.
  * `morphology*.ome.tif` → **answered, see [S4](#s4-as-measured)**. `tifffile` does produce
    loadable references, and [the codec](#the-codec-found) to read them back exists.

  In a Xenium bundle the *largest* elements are the OME-TIFFs and the transcript Parquet. For
  Xenium in particular, contribution 2 depends on those two. Both work as references: the Parquet
  as opaque `uint8`, and the images through a JPEG 2000 codec.

**S4: find which elements can become virtual references. Done.** See
[S4 as measured](#s4-as-measured).

**S5: compare against lazy file linking. Done.** See [S5 as measured](#s5-as-measured). It does not
make references to foreign files in place. It makes soft links to whole files and defers to their
native readers. Contribution 2 is not theirs. Contribution 1 is.

## Kill criteria

This plan wrote these criteria before the spike started, so that sunk cost does not make the
decision:

* ~~**S1 fails** → the answer is upstream in `spatialdata`, not in a project here.~~
  **Did not fire.** S1 passed for rasters and tables.
* ~~**S4 shows only the count matrix is referenceable**~~ **Did not fire, with a caveat.**
  OME-Zarr sources work as references natively. OME-TIFF sources need only one codec wrapper.
  Contribution 2 survives, but a blocker stops it for 10x data in particular today.
* ~~**S5 shows lazy file linking covers referencing**~~ **Did not fire.** It makes soft links to
  whole files, which is a different mechanism. But S5 fired a criterion that the plan had not
  written down. *Versioning* is already upstream's project, in more detail than this spike
  reached. Cede it.
* ~~**S3 concludes that only a change to SpatialData's IO can version geometry**~~
  **Fired, in a worse form than expected.** A change to SpatialData's IO cannot version geometry
  either, because Icechunk refuses non-Zarr keys. Only a change to the *format* can, as geometry
  in Zarr arrays. That change forfeits interoperability. So this directory will become a write-up
  and not a package, unless S4 makes the second contribution viable.
* **All remaining steps fail** → write up why, the way [`../findings.md`](../findings.md) does for
  10x, and stop. In that case, a recorded negative result is the deliverable.

## Layout

The layout after S1:

A demonstration notebook is with the others:
[`../notebooks/spatialdata_on_icechunk.ipynb`](../notebooks/spatialdata_on_icechunk.ipynb). It
detects whether the installed SpatialData has #1107's fsspec extension point. With the extension
point, it demonstrates the geometry fix. Without it, the notebook uses the array encoding and says
why.

**The committed outputs come from a run against #1107's branch.** So the geometry section shows
the real fix and not the fallback. Both runs are clean. `pixi run spatialdata-run` reproduces the
release version. The notebook's header cell reports which version it loaded, so nobody confuses
the two:

```shell
pixi run spatialdata-run                    # against the 0.8.0 release: fallback path
pixi run sdpr        # clones into vendor/spatialdata-1107, which /tmp cleanup cannot reach
PYTHONPATH=$PWD/vendor/spatialdata-1107/src pixi run -e spatial jupyter nbconvert --to notebook \
    --execute --inplace notebooks/spatialdata_on_icechunk.ipynb   # the committed version
```

```
icechunk-SpatialData/
  README.md                        this plan and the spike results
  UPSTREAM.md                      the ask, written for a SpatialData maintainer
  pyproject.toml
  icechunk_spatialdata/            the prototype: parquet_in_store, transaction, references
  spikes/s1_icechunk_store.py      pixi run spike-s1
  spikes/s3_geometry_options.py    pixi run spike-s3
  spikes/s4_image_references.py    pixi run spike-s4
  tests/test_roundtrip.py          pixi run spike-test
```

The prototype implements the API that the hackathon report proposes: `transaction()`, plus
store-clean `write`/`read`. So a reader can evaluate that design against code that runs. It is
explicitly not for publication: see [`UPSTREAM.md`](UPSTREAM.md).

Its tests include the **negative** claims that the patches in `upstream/` depend on. There are
three claims. `write()` still refuses a store. `read_zarr` still fails on `.root`. The resolver
passthrough alone is not sufficient. The tests run against a spatialdata without the patches. If
upstream fixes any of them, the suite fails, and that failure shows that the document is stale.
Against the patched checkout that `pixi run sdpr` produces, the tests skip.

The `spatial` pixi feature and environment exist, with `no-default-feature = true`, as `census`
does. The reason is dependency weight, not a resolver conflict, per the correction above.

## Open questions

1. ~~Does a TIFF-to-references path exist that VirtualiZarr can consume?~~ **S4 answered it:**
   yes, through `tifffile`. ~~Would numcodecs or imagecodecs take a Zarr-v3 JPEG 2000 codec
   wrapper?~~ **No longer relevant: `osml-imagery-io` already has one.** See
   [the codec, found](#the-codec-found). ~~Would AWS Labs take the fix for its `decode`
   shadowing?~~ **They did**, as [PR #9](https://github.com/awslabs/osml-imagery-io/pull/9). Then
   the question no longer applied. `virtual-tiff` reads the images, and its codec comes from
   imagecodecs. osml is out of the environment.
2. ~~What does "lazy file linking" actually do?~~ **S5 answered it:** soft links to whole files,
   not byte ranges.
3. Would upstream accept Parquet writes through the Zarr store, given that the change alters the
   on-disk format?
4. Does any published benchmark compare GeoParquet shapes against the same geometry as Zarr arrays?
   The `zarr-SOMA` plan notes that no benchmark compares AnnData-in-Zarr against Parquet either.
   This looks like the same gap for a different data type.

## Sources

- [SpatialData design doc](https://spatialdata.scverse.org/en/latest/design_doc.html)
- [`spatialdata/_io/io_shapes.py`](https://github.com/scverse/spatialdata/blob/main/src/spatialdata/_io/io_shapes.py)
- [`spatialdata/_io/_utils.py`](https://github.com/scverse/spatialdata/blob/main/src/spatialdata/_io/_utils.py)
- [spatialdata_io.xenium](https://spatialdata.scverse.org/projects/io/en/latest/generated/spatialdata_io.xenium.html)
- [2nd SpatialData Hackathon](https://index.biohackrxiv.org/2026/06/07/s6bph.html): full text
  through `doi:10.37044/osf.io/s6bph_v1`.
- [spatialdata PR #1107](https://github.com/scverse/spatialdata/pull/1107), open: remote Zarr I/O.
- [spatialdata PR #1087](https://github.com/scverse/spatialdata/pull/1087), closed unmerged.
- [zarr-conventions/multiscales](https://github.com/zarr-conventions/multiscales): the layout
  convention, written explicitly for both the geospatial and bioimaging communities.
