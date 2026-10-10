# Upstream problems and the actions for them

This document records eight findings. Each has a reproduction that patches nothing at runtime. The
findings carry seven pieces of code that other projects can take. The seven are a four-patch series
against `spatialdata`, one fix for `osml-imagery-io`, and two open pull requests. `osml-imagery-io`
merged its fix, and we deleted the fix here. The two pull requests close the five TIFF-reader gaps.
They are [virtual-tiff #107](https://github.com/virtual-zarr/virtual-tiff/pull/107) and
[async-tiff #328](https://github.com/developmentseed/async-tiff/pull/328). The second is in
Rust.

Of the other findings, one has a fix in a release, so we deleted its workaround. During the
write-up, one finding no longer reproduced. We recorded it as lapsed. In fact, it had moved to
another object in the same bundle. The last finding is not a code change. It is a publishing
choice.

The four `spatialdata` patches are a **series**, and they apply in order. 0001 only raises the
`ome-zarr` requirement. Each other patch adds tests to that project's own suite, not to the
verifiers here. This package's store I/O code and `_filesystem.py` exist as a workaround.
Together, the four patches remove the need for them.

| finding | project | state |
|---|---|---|
| [`0002-parquet-fs-resolver-hook.patch`](0002-parquet-fs-resolver-hook.patch) | `spatialdata`, [PR #1107](https://github.com/scverse/spatialdata/pull/1107)'s branch | **patch**, verified sufficient |
| [`0003-keep-the-element-location.patch`](0003-keep-the-element-location.patch), after [`0001-require-ome-zarr-0.21.0.patch`](0001-require-ome-zarr-0.21.0.patch) | `spatialdata`, the same branch | **patch**, verified two-sided; reproduces on a `MemoryStore`; needs the `ZarrLocation` change that `ome-zarr-py` merged as [#674](https://github.com/ome/ome-zarr-py/pull/674) and released in 0.21.0 |
| [`0004-write-to-a-store-without-a-path.patch`](0004-write-to-a-store-without-a-path.patch) | `spatialdata`, the same branch | **patch**, verified two-sided; **reverses a tested restriction**, so it is a proposal, not a bug report |
| [a `decode` shim shadowing the codec it complements](#osml-imagery-io-a-shim-that-shadows-the-method-it-complements) | `osml-imagery-io` | **merged** as [PR #9](https://github.com/awslabs/osml-imagery-io/pull/9); we deleted the patch and removed osml from the environment |
| [a FULL_OBJECT checksum applied to a partial response](#a-full_object-checksum-makes-an-object-unreadable-by-range) | an S3 client, reached through `icechunk` | **finding**, live: the header moved to `transcripts.zarr.zip`, and the verifier scans the whole bundle |
| [`AnnData(dtype=)` in the point renderer](#spatialdata-plots-point-renderer-cannot-run-against-current-anndata) | `spatialdata-plot` 0.4.0 | **fixed and released in 0.4.1**; we deleted the workaround |
| [deflate on already-compressed archive members](#deflate-on-an-already-compressed-member-costs-its-addressability-and-saves-nothing) | 10x Genomics, as a publisher | **finding**, in two Xenium bundles, and the cheapest to fix |
| [OME-TIFFs a TIFF parser could not read](#where-virtual_image-belongs-and-what-blocks-it) | `virtual-tiff` and `async-tiff` | **five gaps**, fixed and submitted: [virtual-tiff #107](https://github.com/virtual-zarr/virtual-tiff/pull/107) and [async-tiff #328](https://github.com/developmentseed/async-tiff/pull/328), both open |

None of them is about virtualization. They are ordinary defects, plus one publishing habit. They
appear only when a current stack reads published data by range.

## The convention: a script, or a label

Every finding here has a script that reproduces it. The scripts assert results. They do not only
print them. If a finding becomes false, its script therefore fails. The finding does not go stale
without notice. **A claim with no script must say so in the text**, in those words: *not verified*.

For the findings that carry a patch, the script **applies that patch itself**. It clones upstream
into a temporary checkout and applies the file, or the series in order. It then runs itself again
against the result. Run any of them with no arguments, and it does all of these steps. Where a
finding has two sides, the script runs both.

The verifiers once ran against whatever a caller put on `PYTHONPATH`. Because of that,
the parquet hook patch stayed broken for a day. Its header declared
`@@ -1,7 +1,7 @@` over a 39-line body. The patch was malformed, and git could never apply it.
Nobody noticed, because the verification started one step after the artefact. If you corrupt a
hunk header, the verifier exits non-zero with `corrupt patch`. We checked this.

This project recorded three claims with confidence. Each was false when someone ran it. Each started
from a true premise and reached an unchecked conclusion. Several documents then repeated it:

| the claim | why we believed it | what was true |
|---|---|---|
| A channel-last image cannot be an element | `Image2DModel` needs `(c, y, x)` and a byte range cannot transpose | it need not: Zarr v3's `transpose` codec permutes on read, so the stored bytes stay as published |
| JPEG2000-tiled OME-TIFFs cannot be read | Zarr v3 shipped no JPEG 2000 codec | `osml-imagery-io` had one; the references were already correct |
| A deflated zip member cannot be referenced | a raw deflate stream "would need a zlib header prepended" | framing is a codec detail; the real obstacle is that deflate destroys interior offsets |

We reasoned each false claim from a true premise and never tested it. We noticed the middle one
only because the image test asserted that the codec did not resolve. That assertion failed.

The negative findings carry assertions too, and **both assertions failed**. The image test
asserted that no Zarr v3 name reached imagecodecs' JPEG 2000. A parser then published one, and
the assertion failed.

`verify_full_object_checksum.py` also failed, and our response was wrong. The script refuses to pass
if its comparison object loses its checksum header. That happened. The write-up took the failure as
proof that the finding had lapsed. The header had moved to another object in the same bundle. The
script did not name that object, and so never checked it. **A script that enumerates its subjects
fails only on those subjects.** The write-up trusted the failure more than the enumeration behind
it. The script scans the whole bundle.


## spatialdata: a hook for stores without a path

The patch adds one hook in `spatialdata/_store.py`. We verified that the hook is sufficient. It
applies against [PR #1107](https://github.com/scverse/spatialdata/pull/1107)'s branch
(`selmanozleyen/spatialdata@5443b05`). `parquet_fs_and_path` is on that branch.

### Why a hook rather than a filesystem

`parquet_fs_and_path` derives an fsspec filesystem for `LocalStore` and `FsspecStore`. It raises for
any other store. SpatialData therefore cannot write geometry to a store with no filesystem path. An
Icechunk session store is one example.

No other code blocks the write. `io_shapes` and `io_points` only call `fs.open(path, ...)`. Any
object that implements that method suffices. Two designs can fix this:

* **spatialdata owns a filesystem**: add a `ZarrArrayFileSystem` (~120 lines) plus one branch. This
  gives a bigger surface and a new component to maintain. It also needs a policy decision about how
  files map into a Zarr hierarchy.
* **spatialdata owns a hook**: one module attribute and no new dependency. The mapping stays with
  the code that chose the store. The patch does this. It assumes that a maintainer prefers not to
  own the filesystem.

### The patch

[`0002-parquet-fs-resolver-hook.patch`](0002-parquet-fs-resolver-hook.patch) adds the module
attribute `parquet_fs_fallback` and calls it before it raises. That is the entire change.

The first commit of this file did not apply. Its hunk headers declared
`@@ -1,7 +1,7 @@` over a body of 39 lines, so `git apply` refused it as malformed. Somebody made the
change by hand and then wrote the patch to match it. They did not generate the patch from the
change. We regenerated it against `5443b05` and checked it against a fresh clone.

### What an extension then does

```python
def icechunk_resolver(store, group, child):
    if not isinstance(store, icechunk.store.IcechunkStore):
        return None
    # Respect the store's own read-only flag: a read session's store refuses mode="a".
    root = zarr.open_group(store, mode="r" if getattr(store, "read_only", False) else "a")
    path = f"{group.path}/{child}" if child else group.path
    return ZarrArrayFileSystem(root), path

spatialdata._store.parquet_fs_fallback = icechunk_resolver
```

`ZarrArrayFileSystem` stores each file as a 1-D `uint8` Zarr array at the identical path. Zarr
accepts an array named `shapes.parquet`. The fsspec namespace and the Zarr namespace therefore
coincide. Its source is
[`../icechunk_spatialdata/_filesystem.py`](../icechunk_spatialdata/_filesystem.py).

### Verification

[`verify_geometry_hook.py`](verify_geometry_hook.py) applies nothing and patches nothing at runtime.
It registers the resolver above. It then calls SpatialData's own `write_shapes` / `write_points` /
`_read_shapes` / `_read_points`. The output against a patched checkout:

```
committed Q071QNX28A29Q4S117N0

  points/blobs_points/points.parquet/part.0.parquet    6,854 bytes
  shapes/blobs_circles/shapes.parquet                  3,210 bytes
  shapes/blobs_multipolygons/shapes.parquet            3,350 bytes
  shapes/blobs_polygons/shapes.parquet                 3,065 bytes
  read shapes/blobs_circles            identical=True
  read shapes/blobs_polygons           identical=True
  read shapes/blobs_multipolygons      identical=True
  read points/blobs_points             columns match=True

nothing outside the repo: True
VERDICT: the hook alone is sufficient
```

The geometry is in SpatialData's own format, and SpatialData's own writers and readers handle it.
It stays inside an Icechunk transaction. Nothing goes to a filesystem. The dask-partitioned points
case works too. `points.parquet` becomes a group that holds its parts, because the filesystem
implements directory semantics.

The full reproduction:

```shell
pixi run -e spatial python icechunk-SpatialData/upstream/verify_geometry_hook.py
```

### Two caveats, stated in advance

* A `.parquet` array is opaque to a generic Zarr consumer. A file beside the store has the same
  property, no worse and no better. The bytes have meaning only to a reader that reads them as
  Parquet.
* `ZarrArrayFileSystem` buffers a whole file in memory before it flushes. The cause: a Parquet
  writer seeks back to fix its footer. That is acceptable for geometry. It is not acceptable for a
  670 MB `transcripts.parquet`. A chunk-at-a-time writer with a footer patch-up is possible. The
  question did not need it.

## spatialdata: read an element from a store that it cannot re-root

The patch changes two files, and we verified it on both sides. The case that reproduces it needs
nothing from this project. Take `spatialdata.datasets.blobs()` and write it with
`SpatialData.write()`. Copy it key for key into a `zarr.storage.MemoryStore`. Read it back with
`read_zarr`. That function's own docstring lists the store as supported. It raises:

```
OSError: Image location / [zgroup] exists, but len(nodes) = 0, expected 1.
```

### Two conversions, one assumption

Both places take a group that is already open and convert it back into a store. They then
re-derive the element from that store. The conversion works only for a store that a path can
re-root. `store_from_group` *documents* that it returns the parent unchanged for any other store.

* **`_read_multiscale`** gives that store to `ome_zarr.io.ZarrLocation`. Since `ome-zarr` 0.21.0,
  the class takes any store. It reads the container root and finds no image there. The reader
  then raises the `OSError` above. Before 0.21.0, the class rejected the store with `TypeError: not
  expecting`.
* **`_read_zarr_group_spatialdata_element`** re-opens the element from that store. A re-open
  yields the container root. The points, shapes and table readers each get the whole SpatialData.
  `anndata.read_zarr` then raises ``IORegistryError: No read method registered for
  IOSpec(encoding_type='ngff:points', ...)``. The message names a different element, so it misleads
  a developer at the start of the debug.

Neither conversion has to lose the element's location. For the rasters, the patch passes
`StorePath(group.store, group.path)` to `ZarrLocation`. `ome-zarr-py` merged that support as
[#674](https://github.com/ome/ome-zarr-py/pull/674), and 0001 requires the release that carries it.
For the other elements, the patch keeps the element group.

### Why only a store that cannot be re-rooted gets a `StorePath`

`get_dask_backing_files` looks for a graph layer named `original-from-zarr` and reads the store
from it. It ignores the component inside that store. **The store on that layer must be the
re-rooted one.** With a `StorePath` on the container store, every backing file is the container,
not the element. Three tests assert exactly that. They fail if every store gets a `StorePath`.

The patch thus re-roots where the store allows it. Where the store does not allow it, the patch
names the prefix. Against `tests/io`, with 0001 to 0003 applied: **222 passed, 46 errors**.
Unpatched: **218 passed, 46 errors**. The four extra passes are the tests that 0002 and 0003 add.
The errors are the same in both runs. The 46 collection errors existed before all of this.

### Verification

```shell
pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_read.py
```

The script runs both sides, each in its own clone. Without the patch, it asserts that the failure
*is* the documented one. A checkout that fails in a different way thus gets a report. It does not
pass as a reproduction. With the patch, it compares each raster and table from the `MemoryStore`
with the same element from disk. "No exception" is not the claim.

This patch does not cover geometry. Geometry needs a filesystem, and
[`0002-parquet-fs-resolver-hook.patch`](0002-parquet-fs-resolver-hook.patch) supplies it. With both
applied, every element type reads from a store with no path. An Icechunk-backed SpatialData
needs exactly that. It is the reason this package carries its own store reader.

## spatialdata: write to a store that has no path

This patch covers the other half of that store I/O code. It is the one finding here that is
**not** a bug report. `write()` accepts a store and derives a path from it. If there is no path, it refuses:

```
NotImplementedError: Writing to a store of type MemoryStore is not supported because it
does not expose a filesystem path.
```

That refusal is deliberate, and a test covers it: `test_write_to_memory_store_raises` asserts it.
This patch therefore reverses a decision. It does not fix a mistake. That changes who has to agree.
spatialdata's own docstring supports the read patch. It does not support this one.

The stated reason for the refusal is that "the per-element machinery currently re-opens stores from
the path". The machinery does not need to. `_get_groups_for_element` resolves any input that it
gets. `_resolve_zarr_store` already returns a store unchanged. The patch thus gives the store to the
element writers as the target. It skips the steps that really need a path. Those steps are: the
safety checks on a directory that may already hold data, `sdata.path` itself, and consolidation.
Consolidation re-opens by path. Two tests replace `test_write_to_memory_store_raises`. They assert
that `sdata.path` stays `None`. They also assert that the object can afterwards write to a real
path.

The motivating case is a transactional store, not an in-memory one: an Icechunk session. There, the
write becomes a commit. A failure leaves the branch unchanged. That is the purpose of
`_transaction.py` here. The patch does not know about any of that. `MemoryStore` reproduces the
case.

```shell
pixi run -e spatial python icechunk-SpatialData/upstream/verify_store_write.py
```

## The transaction is the store's, not a wrapper's

`_transaction.py` here is 37 lines. It is a context manager that yields a writable session. It
commits on a clean exit and drops the session on any other exit. The hackathon report proposes
exactly this form, `with sdi.transaction(sdata):`. The report presents it as the ergonomic benefit
of an Icechunk backend. Its docstring makes a claim that it never checked: *"The discard is the
necessary capability. A filesystem store cannot offer it."*

[`verify_transaction_semantics.py`](verify_transaction_semantics.py) runs the ordinary two-step job:
write a dataset, then make the next step of the work fail. It runs against both stores, with the
patch series applied. **No code from this project takes part.** The script induces nothing inside
`write()` and monkeypatches nothing. The question is only what survives:

```
  path        on_disk.zarr exists: True, holding ['images', 'labels', 'tables']
  icechunk    branch has 1 snapshot(s), unchanged: True
              the store holds []
```

The claim holds. `write(session.store)` stages, and the branch moves only at `commit`. An exception
between the two therefore discards the work with no extra action. On a path, each element is
durable as soon as its write ends. A path store thus has no mechanism to discard the work.

**The wrapper is therefore not the contribution.** When 0004 lets `write()` take a session store,
the transactional property already exists. It applies to anyone who does not call `commit`. A
`transaction` context manager is a convenience over `session.commit`. It has value for the
ergonomics that the report describes. It does not make the write atomic. It also does not need to
be in `spatialdata` to work. This answers the question of the right location for
`_transaction.py`: no particular location. With the series applied, a user can write it in 37
lines. Its behaviour comes from Icechunk.

The verifier showed one detail, and we did not assume it: `write()` calls
`zarr.create_group(overwrite=overwrite)`. `write()` therefore refuses a session store that already
holds a root group, exactly as it refuses an occupied path. A transactional store does not make the
write less careful.

## osml-imagery-io: a shim that shadows the method it complements

**Merged and removed.** [PR #9, *fix: disambiguate numcodecs and zarr v3's `BytesBytesCodec`
`decode` calls*](https://github.com/awslabs/osml-imagery-io/pull/9), `daa4a0f5`, 2026-08-11. We
deleted the patch file, the workaround, the probe that found the bug and the verifier that proved
it. Upstream carries the fix. This project does not depend on the package. This project reads
images through `virtual-tiff`. Its JPEG 2000 codec comes from imagecodecs and never had the shim.

This section stays because the mistake is not specific to that library. Each codec subclassed
`BytesBytesCodec` and then defined its own `decode(self, buf, out=None)` for numcodecs consumers.
That is the same name as `async def decode(self, chunks_and_specs)`, so the shim shadowed the
inherited method. zarr's pipeline calls the batch form and reaches the shim. It stops in the first
line with `TypeError: 'tuple' object cannot be interpreted as an integer`, before any decode starts.
The pipeline never reaches `_decode_single`, which does the work correctly. All five codecs carried
the shim. **In the released package, no Zarr v3 read of any of them could succeed.**

The fix checks whether the input is one buffer, not whether it is a batch. A buffer is a stable
type that code can check. The batch is any iterable that zarr builds. In zarr 3.3, that is a `zip`
object. A first attempt got exactly this wrong. It checked for a sequence of pairs. The check
looked reasonable and passed a visual review, but it never matched.

### Why their own tests missed it

`tests/unit/test_zarr_codecs.py`
passed identically with and without the fix: 38 passed, 1 skipped in both runs. The whole Python
unit suite did too. Those tests assert `isinstance(codec, BytesBytesCodec)` and that the entry
points resolve. They also assert that the underlying `decode_jpeg2000` / `decode_jpeg` /
`decode_jbp_block` bindings return the right shapes and values.

None of them reads a Zarr array. The tests covered the codecs thoroughly as decoders and not at all
as *codecs*. One `zarr.open_array(...)[:]` through the pipeline shows the bug.


## A `FULL_OBJECT` checksum makes an object unreadable by range

**Live, and it moved.** We found it on `transcripts.parquet`. That object does not advertise the
header any more. `transcripts.zarr.zip` in the same bundle advertises it, with
`crc64nvme=a8abeb03eb458643`. A reference into it fails exactly as the text below describes. Both
objects have a last-modified date of 2025-11-24, so 10x re-uploaded nothing. Only the object that
serves the header changed.

An earlier revision of this page said the opposite. The verifier named two objects,
`transcripts.parquet` and `he_image.ome.tif`. It found the header on neither and refused to pass. We
read that as a lapsed finding and wrote it up as *not verified*. It had not lapsed. The header was
on a third object that the script never checked. Meanwhile, the store that references that object
was unreadable. A notebook execution failed with
`body checksum mismatch. expected body checksum to be a8abeb03eb458643`. That failure revealed the
problem. The expected value is the same value that the header carries.

The verifier scans **every object the bundle publishes** and reports how many carry the header:

```
  1 of 9 objects carry the header: ['transcripts.zarr.zip']
  s3-compatible   transcripts.zarr.zip     StorageError: body checksum mismatch
```

**The header comes from the CDN, not from the publisher.** We sent a HEAD request for the same
object in two ways. Both responses give the same length, byte for byte:

```
s3-us-west-2.amazonaws.com/10x.files/…transcripts.zarr.zip   200, no x-amz-checksum-type
cf.10xgenomics.com/samples/…transcripts.zarr.zip             200, x-amz-checksum-type: FULL_OBJECT
```

10x's origin bucket is public, and anonymous path-style reads work. A reference into the origin
therefore reads. The identical reference through CloudFront fails. This fact gives both the
diagnosis and the repair. We re-derived the lung store's transcript references against
`s3://10x.files/samples/…`. The store reads again: 12 tiles, 190,077 transcripts.

It also removes the need for a workaround. `../README.md` documented an `s3-compatible` container
pointed at `cf.10xgenomics.com`. That was the way to reach a CDN-published object through an
`s3://` reference. It worked, but it was never necessary. The objects were always in a bucket. The
workaround put an S3 client in front of a CDN. That is the only reason this finding could occur.

An object that a client uploads to S3 with a full-object checksum carries
`x-amz-checksum-crc64nvme` and `x-amz-checksum-type: FULL_OBJECT` in its GET responses. S3 also
returns those headers on a **ranged `206`**. There, the checksum still describes the *whole*
object. A client that validates the body against it therefore fails on every partial read. A
virtual chunk reference is only a partial read.

The script shows that the cause is the client, not the object, the CDN or the range:

```
transcripts.parquet     228.3 MB  checksum-type=FULL_OBJECT  crc64nvme=7b1811d1f072ebc3
he_image.ome.tif       1190.8 MB  checksum-type=none

a plain ranged GET of the first chunk, for each:
  transcripts.parquet      HTTP 206, 4,194,304 bytes
  he_image.ome.tif         HTTP 206, 4,194,304 bytes

the same range as a virtual chunk reference, per client:
  http            transcripts.parquet      read 4,194,304 bytes
  http            he_image.ome.tif         read 4,194,304 bytes
  s3-compatible   transcripts.parquet      StorageError: body checksum mismatch. expected body
                                           checksum to be 7b1811d1f072ebc3 but it was 448663c9e147c228
  s3-compatible   he_image.ome.tif         read 4,194,304 bytes
```

The bytes, the offsets and the repository layout are the same. The HTTP client reads it, because it
never looks at `x-amz-*`. The S3 client refuses it, because it does look. `7b1811d1f072ebc3` is
exactly the decoded value of the object's own header. The partial body thus could never match.

**The effect beyond one file.** An increasing number of new uploads carry a full-object checksum.
An affected object gives no sign of the problem. A reference to it succeeds, and the commit
succeeds. It fails only when a reader reads it back. In the source bundle, exactly one file of
eight carries the header. That file holds 12 million transcripts.

The workaround available to a *user* is to reach the object over plain HTTP instead. That is not
always possible. A hosted catalogue can require an `s3://` URL. That requirement forced this
project to take the transcripts from a completely different published file.

## spatialdata-plot's point renderer cannot run against current anndata

This finding needs no patch, and it is not a live problem. **0.4.1 fixed it.** This project uses
that release and deleted its runtime workaround. This section stays because any user of 0.4.0
meets the problem.

`spatialdata_plot.pl.render` builds a temporary `AnnData` for the point coordinates. It passes
`dtype=`, which `anndata` removed:

```python
AnnData(
    X=points[["x", "y"]].values,
    obs=points[coords],
    dtype=points[["x", "y"]].values.dtype,   # render.py:1122 and :1136, in 0.4.0
)
```

`render_points` thus raises
`TypeError: AnnData.__init__() got an unexpected keyword argument 'dtype'`
against `spatialdata-plot` 0.4.0 with `anndata` 0.13.2. It raises **on
`spatialdata.datasets.blobs()`**, with no virtual data. The tutorial's own transcript figure does
not run on a current stack. No code in `spatialdata` does this, on the release or on #1107.

0.4.1 has no `AnnData(` construction in `render.py`. The release contains the fix, and the gap came
only from release timing.

Before that release, a workaround module in this package rebound `AnnData`. The binding pointed
to a constructor that drops the argument. That was safe, because `X` already carried the dtype that
the call passed. Two tests covered it. One asserted that the argument was still stale. The other
asserted that the patch made a *stock* render succeed. We deleted both, together with the module.
One test replaces them. It runs `render_points` on `blobs()`, with no code of ours. It fails if an
environment returns to 0.4.0.

**One environment changed to 0.4.1 later.** 0.4.1 is on PyPI, and conda-forge is still on 0.4.0.
The environment that squidpy composes therefore resolved 0.4.0 through its conda package.
`render_points` raised there, on `blobs()`, with no code from this project. The same call worked in
all other environments. No failure occurred, because that notebook renders images and shapes and
never points. That environment takes squidpy from PyPI, so both environments hold 0.4.1. The
renderer works in both.


## Deflate on an already-compressed member costs its addressability and saves nothing

[`verify_deflated_zip_members.py`](verify_deflated_zip_members.py) reproduces it. Run
`pixi run -e spatial python icechunk-SpatialData/upstream/verify_deflated_zip_members.py`. The
script also carries its own dependencies inline, so `uv run` executes it outside this project.
It needs nothing from this project's environments. It is the one artefact here for the publisher
to run. It has no patch, because the fix is not a code
change. The fix is one flag at packaging time. The same archive already uses that flag both ways.

A zip's central directory locates every member. A **stored** member is thus a contiguous byte
range, and all data inside it keeps its offsets. Thus a reader can take a published `.zarr.zip`
as a virtual Zarr store, chunk by chunk, with no download. A **deflated** member is a
single Huffman-coded stream. Its compressed bytes are contiguous, but byte N of the decompressed
file needs an inflate of all bytes before it. No data inside such a member has an addressable
offset any more.

10x's Xenium `outs.zip` uses both methods, and the split is unfortunate. Human Lung Cancer, Onboard
Analysis 2.0.0:

```
  method         stored     original     saved  member
  DEFLATE      499.6 MB     499.6 MB  0.0023%  morphology_focus/morphology_focus_0002.ome.tif
  DEFLATE      479.2 MB     479.2 MB  0.0038%  morphology_focus/morphology_focus_0003.ome.tif
  DEFLATE      446.7 MB     446.7 MB  0.0067%  morphology_focus/morphology_focus_0001.ome.tif
  DEFLATE      414.4 MB     414.4 MB  0.0086%  morphology_focus/morphology_focus_0000.ome.tif
  STORED       275.5 MB     275.5 MB  0.0000%  transcripts.zarr.zip
  STORED       147.1 MB     147.1 MB  0.0000%  cells.zarr.zip
  STORED         9.1 MB       9.1 MB  0.0000%  cell_feature_matrix.zarr.zip
  STORED         1.4 MB       1.4 MB  0.0000%  analysis.zarr.zip
```

Because of the stored members, this project can present Xenium segmentation masks and transcripts
with no copy. The deflated members are 1.84 GB of imagery that no reference can reach. The deflate
saves **at most 0.0086%**. An OME-TIFF already has internal compression. The deflate saves 35 KB on
a 414 MB file, and costs every interior offset.

10x publishes those four files nowhere else. The server refuses every individual URL for them, so
the archive is the only copy. For that reason alone, nobody can reproduce the tutorial figure that
needs all four channels from published data.

The `morphology.ome.tif` in the same archive is also deflated, but that costs nothing. It is
4.76 GB with its own URL, which serves ranges. The verifier checks that distinction per member and
does not assume it. A deflated image is unreadable only when it is deflated **and** has no other
copy.

### The same split, an order of magnitude larger

Human Kidney FFPE Protein, Onboard Analysis 4.0.0, is a 36 GB bundle of 58 members. The four
`.zarr.zip` outputs are again stored members, and **all 35 `morphology_focus` protein channels are
deflated**:

```
  method         stored     original     saved  member
  DEFLATE      760.7 MB     760.7 MB -0.0064%  morphology_focus/ch0031_vimentin.ome.tif
  DEFLATE      720.2 MB     720.2 MB  0.0044%  morphology_focus/ch0016_cd16.ome.tif
  DEFLATE      699.0 MB     699.1 MB  0.0021%  morphology_focus/ch0000_dapi.ome.tif
  DEFLATE      679.1 MB     679.2 MB  0.0225%  morphology_focus/ch0019_pd-1.ome.tif
  STORED      1574.2 MB    1574.2 MB  0.0000%  transcripts.zarr.zip
  STORED       492.0 MB     492.0 MB  0.0000%  cells.zarr.zip
  STORED        57.1 MB      57.1 MB  0.0000%  cell_feature_matrix.zarr.zip
  STORED         9.0 MB       9.0 MB  0.0000%  analysis.zarr.zip
  ...      31 further deflated channels, all alike
```

The bundle has 17.12 GB of protein imagery, and none of it is referenceable. The best saving is
0.0508%. The largest channel is 49 KB *bigger* as a deflated member than as a stored member. As in
the lung bundle, those channels exist in no other object. The server refuses every standalone URL
for them. The counts, cells, transcripts, boundaries, H&E and the 15 GB `morphology.ome.tif` each
have their own URL. Each is readable by range. Protein imagery makes this sample different, and it
is the one part that only the archive holds.

### A third platform, where the compression is only a loss

Human Cervical Cancer, Atera WTA preview, has 23 members in an 89 GB bundle:

```
  method         stored     original     saved  member
  STORED     36263.9 MB   36263.9 MB   0.0000%  transcripts.zarr.zip
  DEFLATE    21499.7 MB   21499.4 MB  -0.0016%  morphology.ome.tif
  DEFLATE     2053.1 MB    2052.8 MB  -0.0120%  morphology_focus/ch0002_18s.ome.tif
  DEFLATE     1988.1 MB    1987.8 MB  -0.0120%  morphology_focus/ch0000_dapi.ome.tif
  DEFLATE     1892.3 MB    1892.1 MB  -0.0114%  morphology_focus/ch0001_atp1a1_cd45_e-cadherin.ome.tif
  DEFLATE     1699.3 MB    1699.1 MB  -0.0108%  morphology_focus/ch0003_alphasma_vimentin.ome.tif
  STORED      1565.2 MB    1565.2 MB   0.0000%  cell_feature_matrix.zarr.zip
  STORED       809.1 MB     809.1 MB   0.0000%  cells.zarr.zip
  STORED         5.9 MB       5.9 MB   0.0000%  analysis.zarr.zip
```

Every saving on the imagery rows is **negative**. All five images are bigger as deflated members
than as stored members. The deflate on 29.1 GB of imagery costs its addressability and adds bytes.

The stored side is the largest of the three bundles: 38.6 GB. The transcripts alone are 36.3 GB of
it. It is also the only data available. Unlike the Xenium samples, this bundle publishes nothing
separately. Both hosts refuse every standalone URL, except the 17.7 GB H&E and the supplemental
CSVs. A reader can thus read only the four stored members of this dataset without an 89 GB
download.

Both Atera bundles exceed CloudFront's object-size limit. `cf.10xgenomics.com` answers a plain `400`
for them. 10x publishes them from S3 instead. S3 honoured every range request.

**The fix:** store members that are already compressed. Do not deflate them. Use `zip -0` for those
entries, or the equivalent. These outputs already do this for their `.zarr.zip` members.

### A codec chain cannot restore the offsets

A Zarr codec chain can hold more than one stage. It can therefore run the member's DEFLATE and then
the tile's JPEG 2000. This does not make the tile readable. A chain changes bytes. The missing part
here is an address.

Zarr resolves a chunk's `(path, offset, length)` before the pipeline starts. A deflated member
resolves to one range only: the whole member. The first stage therefore inflates all 499.6 MB of
`morphology_focus_0002.ome.tif`. It gives the second stage a TIFF container: a header, the IFDs and
every JP2 tile. The JPEG 2000 codec needs one codestream at buffer offset 0.

Zarr has no stage that cuts at an interior offset. A `BytesBytesCodec` takes one `Buffer` and
returns one `Buffer`. It reads all of the bytes from the stage before it. The deflate covers the
file and not each tile, so the chain starts at the wrong granularity.

The chain mechanism is not the gap. `virtual-tiff`'s `_get_codecs` already builds one: a predictor
codec, then a transpose and `ChunkyCodec` for interleaved samples, then the compression codec.
DEFLATE plus JPEG 2000 works only if each tile has its own deflate stream at its own offset. TIFF
cannot record that, because Compression is one tag with one value per IFD.

Partial decode does not help either. The mixin `ArrayBytesCodecPartialDecodeMixin` exists only for
the array-to-bytes stage. It has no bytes-to-bytes counterpart. It reads sub-ranges of the stored
chunk. Sharding uses it. Sharding needs the property that this member does not have. A shard index
holds real byte offsets into a container that has no compression of its own. The compression
applies to each inner chunk.

The general form of the idea is a zran-style index over the deflate stream. Such an index gives
per-tile entry points. Each one needs its own 32 KB history window as a preset dictionary. Zarr
configures codecs per array, not per chunk. Zarr thus has no place to keep a window.

The `BytesBytesCodec` contract, the absent bytes-to-bytes partial-decode mixin and `_get_codecs`
come from the source of the installed `zarr` and `virtual-tiff`. The zran conclusion is *not
verified*: no script here runs it.

### The earlier explanation and its error

The earlier explanation here said a deflate stream "would need a zlib header prepended, which is
the one thing a reference cannot do". It contrasted this with JPEG 2000 tiles. A reference skips
their JP2 wrapper when it starts 85 bytes later.

Raw-deflate versus zlib framing is a codec detail. A raw-inflate codec does not help. The real
asymmetry is seekability: a stored member keeps it and a deflated one destroys it. We also checked
the obvious exception. SOzip announces independent deflate blocks in the extra field. These members
carry only Info-ZIP timestamps and Zip64 there. They thus have no index for a seek.


## Where `virtual_image` belongs, and what blocks it

`_virtual.py` builds Zarr arrays whose chunks are byte ranges in an OME-TIFF. That sounds like a
VirtualiZarr contribution and is not one. **VirtualiZarr keeps format parsers out of tree.** Its own
`parsers/` holds the core parsers and the kerchunk-backed ones. The TIFF parser is
[`virtual-tiff`](https://github.com/virtual-zarr/virtual-tiff), and the GRIB parser is
`gribberish`. VirtualiZarr documents each of them and ships neither. The destination for the image
half is thus `virtual-tiff`. On paper, its parser is a superset of ours. It has fourteen
compressions against our two, including the four JPEG 2000 tags Xenium uses. It also takes both
planar configurations, and every IFD as a level.

In practice, it read none of the three OME-TIFFs that this project handles. The reasons were not
codecs. The two pull requests fix each gap. The work on them found two more gaps that had no
relation to these files. That makes five in all, across the two pull requests:

| file | what happens |
|---|---|
| Xenium morphology, JPEG 2000 tiles, BigTIFF | **fixed in `async-tiff` #328.** `PyValue` had no conversion for `TagValue::Ifd` or `IfdBig`, so a tag of either type raised an error during the directory read. One tag made the file unopenable. The Rust core already parsed both, and only the binding refused them |
| Xenium H&E, interleaved RGB | **fixed in `virtual-tiff` #107.** The parser refused any file with tag 330. That tag lists *other* IFDs, so the requested one was always mappable. With the fix, the parser maps it and warns that the five reduced levels are absent |
| Atera H&E, 17.7 GB, uncompressed, planar | **fixed in the same `async-tiff` PR.** Its metadata cache fills sequentially from offset 0. That suits a COG. This file's first IFD is at byte 17,731,963,126. A read of that IFD asked for the whole object in one request |

Two of them were the *same* limitation in different layers. Tag 330 has type IFD in a classic TIFF
and IFD8 in a BigTIFF. `async-tiff` refused the tag, and `virtual-tiff` refused any file that
carried it. With both changed, the Xenium morphology image reads. It has 11 focal planes of
17098 x 51187, JPEG 2000 tiles, 7 SubIFD levels each. A window of it is byte-identical to
tifffile's own read.

The SubIFD fix also uncovered a *fourth* problem, with no relation to microscopy. Without the
refusal, chunky multi-sample files reach `ChunkyCodec` and fail with `TypeError: Endian() takes no
arguments`. zarr 3.3 replaced `zarr.codecs.bytes.Endian` with a deprecation shim: a class with no
members, and no constructor. The PR stores the endianness as a plain string instead, as `BytesCodec`
does there. **Any** chunky TIFF read with zarr 3.3 meets this. It is a compatibility break, not a
microscopy problem.

The next gap was of a different type. It was not a refusal but an assumption about the location of
metadata. Writers that stream image data put their IFDs after that data. The fixed reader reads a
distant range at its position, through its own window cache. Exact-sized reads alone were not
enough. A metadata read can be as small as one tag entry. This image has 12,549 tiles' worth of
them. Each read therefore became a request, and the open still hung. With the fix, the 17.7 GB
image opens in 40 seconds. Without it, the image could not open.

The *fifth* gap stayed longest, because it does not affect the open of a file. It concerns what
the references say after the open. It fails only for the second reader. `ChunkyCodec` and
`HorizontalDeltaCodec` wrote themselves into array metadata by bare name. The `zarr.codecs` entry
points let zarr find the classes. They published the classes with a namespace, as
`virtual_tiff.ChunkyCodec`. Only the `register_codec` calls linked the two names. Those calls run
at package import. An array thus decoded in a process that had imported `virtual_tiff`. In a
process that had not imported it, the same array raised `UnknownCodecError`. That includes
`spatialdata.read`, and any reader that gets only the store. The PR writes the namespaced name. The
sibling `imagecodecs_*` codecs do the same. Zarr v3 asks for this form for names outside the core
set. Its test resolves each codec **in a subprocess**. The import of the test module already
registers both by hand.

A notebook found it, not a probe. The image read in the environment that wrote it, and in no
other. A reproduction run beside the writer cannot see a case like that. The name is also not only
in the code. It is in every store that the code already wrote. We therefore rewrote the H&E of
`xenium-lung-virtual` from the same byte ranges. Only then could a reader read it again. A codec
name is published data.

We verified all of them against the files, not against the absence of an exception. We read a
64 x 64 window of the 45087 x 11580 image. It is byte-identical to tifffile's own read of that
window. The four reproductions pass here. Their full suite gave 180 passed and two failures. The
failures existed before the branch, on geo key attributes and a prefixed local store. We measured
that once, in their own environment, on 2026-08-10. **We did not verify it again.** The run needs
test dependencies that this project does not carry.

The work is two open pull requests against the projects themselves. They are
[virtual-tiff #107](https://github.com/virtual-zarr/virtual-tiff/pull/107), *SubIFD support for
OME-TIFF microscopy images with pyramid levels*, and
[async-tiff #328](https://github.com/developmentseed/async-tiff/pull/328), *Expose more IFD tags
machinery to Python*. This project **pins their head commits in `pixi.toml`**. The environment that
reads these images thus uses exactly the code under review, not a hand-made checkout. If a review
changes the approach, we move the pin and re-execute the notebooks against it. The `async-tiff`
build needs a Rust toolchain, which this repository does not declare. `maturin build --release`
from `python/` produces the wheel. Initialise its submodules first. Otherwise, the build fails after a
successful compile with a bare `No such file or directory`.

The reproductions are in `tests/test_ome_tiff_microscopy.py`, which #107 carries. There is one test
per file, plus one that asserts the pixels are byte-identical to tifffile's own read. We wrote them
to assert the *failures*. We inverted each one when its fix arrived. A regression thus makes them
fail. Run them in `virtual-tiff`'s own pixi environment. Its test feature carries `rasterio` and
`rioxarray`, which this project's environments deliberately do not. The tests download nothing,
because a parser reads only the directory. The three files are 1.2 GB, 4.8 GB and 17.7 GB.

This has a consequence for the goal to remove this package. `virtual_image` does not read TIFF at
all. It asks `virtual-tiff` for the IFDs and for the levels that a SubIFD chain points to. The
remaining part is really about SpatialData. That part has three items. The first is names for the
levels `s0..sN`. The second is the multiscale metadata. The third is the refusal of a focal stack
with no chosen plane. The environment pins
both branches by commit, so the whole path is reproducible. The path has no release. Two of the
five gaps are in `async_tiff`, the Rust reader beneath it, not in Python.


## Where `virtual_table` belongs: mostly nowhere, because it is already upstream

The other half of `_virtual.py` reads a table's `X` from an `.h5ad` or from 10x's
`cell_feature_matrix.h5`. It writes `X` as references. The same question as for the image half gives
a shorter answer here. **For an h5ad, this project has nothing to contribute, because it already
works.**

VirtualiZarr's in-tree `HDFParser` maps the three CSR arrays *and* keeps the group's attributes.
`anndata` therefore reads the result directly, with no code from this project:

```python
store = HDFParser(group="X")(url, registry)
X = read_elem(zarr.open_group(store, mode="r"))
# csr_matrix (8959, 58226) float32, nnz 5,257,861
```

The attributes survive the parse: `{'encoding-type': 'csr_matrix', 'encoding-version': '0.1.0',
'shape': [8959, 58226]}`. That is the complete mechanism. Anything this project does for an h5ad
beyond this is redundant.

**The declaration is also present upstream.** scanpy's `_read_v3_10x_h5` already contains it. That
includes the orientation that this project used a probe to establish:

```python
n_cols, n_rows = dsets["shape"]  # transposed
matrix = csr_matrix((data, dsets["indices"], dsets["indptr"]), shape=(n_rows, n_cols))
```

It uses the same three arrays, unchanged. It reaches the same conclusion about the axis that
`indptr` indexes. That code was always there. `pixi run check-tenx` asserts that the virtualized
matrix equals `scanpy.read_10x_h5` on the same file. Both are 167,780 x 541 with 10,640,759 stored
values, identical. The check thus uses a reader that nobody here wrote, not another read of ours.
One difference exists. scanpy defaults to `gex_only=True`, which keeps 313 of the 541 features and
drops Xenium's control probes. References cannot do that, because a byte range is the whole array.

No upstream gap thus remains. This project applies the declaration to a *parsed manifest*, not to
materialised h5py datasets. scanpy does not do that. That is a bridge between VirtualiZarr and
AnnData, not a missing 10x reader.

10x's own file is the exception in a narrower sense. The reason is a missing declaration *in the
file*, not a missing capability. `HDFParser` maps it completely: `data`, `indices`, `indptr`,
`barcodes`, `features`, `shape`, with Shuffle and Zlib codecs. 10x write **no encoding metadata at
all**. `read_elem` thus returns a plain `dict` of six arrays instead of a matrix. The fix only
supplies what they omit:

* `encoding-type: csr_matrix`, which the file does not state;
* `shape` transposed: they store `[541, 162254]`, features first, and as an *array*, not an
  attribute. `indptr` indexes barcodes, so the bytes are already CSR over cells;
* `obs` and `var` names from `barcodes` and `features`, which are fixed-length strings.

A hand assembly of those three arrays gives `(162254, 541) int32` with 4,901,617 stored values. Its
first fifty cells are identical to the published store. The only difference is thus the
declaration.

The remaining work thus differs from the image half. There is no parser to write. It is a
convention shim over a format that already parses. Its size is about that of the list above. Add
the Icechunk-side write to that.
[The `icechunk.files` proposal](https://github.com/earth-mover/filestore) already covers that write
in its own terms. `virtual_table` is a few dozen lines that state what 10x did not state. These
lines wrap machinery that upstream already has.


## What each module here waits for

The prototype exists so that we can delete it. This section gives the destination of each of its
six modules and the obstacle for each. It holds the same information as the sections above. It
sorts that information by our cost, not by the owner.

| module | lines | destination | state |
|---|---|---|---|
| `_filesystem.py` | 103 | `spatialdata`, via a registered resolver | [`0002`](0002-parquet-fs-resolver-hook.patch), verified |
| store read path | in the total below | `spatialdata`, reads from a store | [`0003`](0003-keep-the-element-location.patch), verified two-sided |
| store write path | 326 total | `spatialdata`, writes to a store | [`0004`](0004-write-to-a-store-without-a-path.patch), a proposal, not a fix |
| `_virtual.py` (image) | 453 total | `virtual-tiff` | reads through it already; the five fixes are in review as #107 and #328, not yet released |
| `_virtual.py` (table) | in the total above | nowhere obvious | scanpy already declares 10x's layout; the remaining work applies it to a manifest, not to h5py, as a VirtualiZarr-to-AnnData bridge |
| `_reference.py` | 66 | [`icechunk.files`](https://github.com/earth-mover/filestore) | that proposal covers it, in its own terms |
| `_transaction.py` | 37 | nowhere in particular | [demonstrated](#the-transaction-is-the-stores-not-a-wrappers): with 0004 applied the property is Icechunk's, and the wrapper is a convenience |
| geometry as Zarr arrays | 161 | nowhere | not a fix that waits for anyone: an alternative encoding, kept while the Parquet route needs an unmerged patch |

Every row has either an artifact or a demonstration. Two rows were not upstream gaps after all. A
check against somebody else's code showed that. scanpy already declares 10x's matrix layout, and
Icechunk already makes a write atomic with no wrapper around it. Geometry as Zarr arrays is the
only row that is a decision, not a wait. It is also the largest single deletion available.
