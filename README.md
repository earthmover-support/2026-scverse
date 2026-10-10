# 2026-scverse

Icechunk gives Zarr a commit log. It adds branches, tags and ACID transactions over object
storage. A chunk in an Icechunk store can also be a byte range into a file that someone else
published.

This repository puts AnnData and SpatialData on Icechunk. It references `.h5ad` and 10x
matrices by byte range instead of copying them. It supports a three-minute talk at the scverse
2026 conference. The talk is "Versioning and Virtualizing Single-cell and Spatial Data with
Icechunk".

## What this repository claims

Each row names the command, or the committed notebook, that supports it.

| claim | how to check it |
|---|---|
| An `.h5ad` matrix virtualizes into Icechunk | `pixi run check-s3` |
| It reads back identical to h5py, when `h5ads/` holds the source file | `pixi run check-s3` |
| scanpy gets the same answers from the virtual AnnData and from the `.h5ad` | `pixi run equivalence-run` |
| A 10x Xenium matrix is already CSR over cells, so it needs no transpose | `pixi run check-tenx` |
| A dense Zarr chunk grid cannot encode single-cell sparsity | `pixi run check-sparsity` |
| Icechunk gives a SpatialData store commits and history | `pixi run -e spatial versioning-run` |
| An image writes to an Icechunk store and reads back | `pixi run check-store-path` |
| Labels and tables write through the fork's `SpatialData.write()` | `pixi run -e spatial versioning-run` |
| Shapes need a filesystem path on released packages | `pixi run check-store-path` |
| The Braun atlas store holds no expression bytes | `notebooks/virtualize_braun.ipynb`, the `all_virtual_chunk_locations()` assertion |
| 1.33 GB of a published 10x Xenium bundle is addressable by reference | `notebooks/xenium_from_arraylake.ipynb`, committed |
| The scverse Xenium tutorial runs against a store holding almost none of its data | `notebooks/xenium_tutorial_virtual.ipynb`, committed |
| The squidpy Xenium tutorial runs the same way | `notebooks/squidpy_xenium_virtual.ipynb`, committed |
| One 89 GB published object opens as a SpatialData store | `notebooks/atera_from_arraylake.ipynb`, committed |

### The tutorial notebooks are not unmodified

Each tutorial notebook keeps the tutorial's text and its calls. Each lists every difference it
makes, under a heading of its own. Two differences are substantive. The virtualization causes
the first. `morphology_focus` holds one channel, not four, because 10x deflate the other three
inside a zip. No reference can point into a deflated member. The second is in the squidpy
notebook. Its two gene figures plot `MET` only, because `AREG` is not in this sample's panel.

### Two reference stores, measured

`notebooks/xenium_from_arraylake.ipynb` addresses 1.33 GB of published Xenium files with 313
references. It copies 14.0 MB of that, which is 1.05%. The copies are the chunk tails and
nothing else.

`notebooks/atera_from_arraylake.ipynb` opens one published 89 GB `outs.zip`. The store holds
47,599 element byte ranges. It holds no copy of the pixels and no copy of the counts. 29 GB of
the archive is deflated, so no reference can reach the morphology images.

### The Braun atlas, measured

The virtualized atlas lives in the Arraylake repository
`earthmover-demos/cellxgene-braun-atlas`. Two Icechunk calls measure it.

The four figures below differ from every other number in this file. No committed output holds
them. We measured them against the published repository with the two calls named below. A
reader needs an Arraylake account to repeat that measurement.

`repo.chunk_storage_stats()` reports 11,309,388,995 virtual bytes, which is 11.31 GB. Those
bytes are the CSR chunks of eleven source files, and nothing else. The same call reports
19,988,843 native bytes, which is 19.99 MB. Those are `obs` and `var`, written as real chunks.
`repo.list_manifest_files()` reports 287 manifest files holding 15,165,946 bytes, which is
15.17 MB.

Neither call counts snapshots. The store therefore holds at least 35 MB, and that figure is a
lower bound rather than a total. The ratio of referenced bytes to stored bytes is about
320 to 1. That ratio is an upper bound, because the divisor is a lower bound.

The eleven source files total 11.95 GB on disk. That number is not the referenced number. The
difference is `obs`, `var`, `uns` and `layers`, which no reference covers.

### Two more measured results

`pixi run equivalence-run` runs scanpy twice on one Braun cell class. It runs once on the
virtual AnnData and once on the `.h5ad` the references point at. Both runs pick the same 2,000
highly variable genes, at a Jaccard index of 1.0000. The dispersion correlation is 1.000000
over the 26,743 genes with a defined dispersion. The other 31,483 genes hold NaN at the same
positions on both sides.

`pixi run check-sparsity` measures two cell classes at four chunk grids. ClassErythrocyte is
1.01% dense and ClassFibroblast is 8.11% dense. Every block of every grid still holds a stored
value. A dense grid therefore stores every block.

## The upstream ask

SpatialData on Icechunk needs
[pull request #1107](https://github.com/scverse/spatialdata/pull/1107) and five more commits.
#1107 is not merged. The five commits sit on top of its branch. Compare them against that
branch at
[feat/zarr-store-class...li-em:spatialdata:li-em/store-without-a-path](https://github.com/selmanozleyen/spatialdata/compare/feat/zarr-store-class...li-em:spatialdata:li-em/store-without-a-path?expand=1).

| commit | what it does | files it touches |
|---|---|---|
| 0001 | require ome-zarr 0.21.0, which 0003 needs | `pyproject.toml` |
| 0002 | add a fallback hook for the parquet filesystem | `_store.py` |
| 0003 | keep the element location in a store that cannot be re-rooted | `_io/io_raster.py`, `_io/io_zarr.py` |
| 0004 | let a write target a store that has no path | `_core/spatialdata.py`, `_io/io_zarr.py`, `_store.py` |
| 0005 | count points rows through the frame's own filesystem | `_core/spatialdata.py`, `_io/_utils.py` |

0003 and 0005 are bug fixes. Each verifier asserts the failure before its patch and the fix
after it. 0002 adds one module attribute and no dependency. 0004 reverses a restriction that
`test_write_to_memory_store_raises` asserts, so it is a proposal rather than a fix.

[`icechunk-SpatialData/UPSTREAM.md`](icechunk-SpatialData/UPSTREAM.md) holds the detail, the
diff sizes and the reproduction scripts. It also records a sixth limit that the patches do not
fix. `SpatialData.write_element` still raises on a store without a path.

## What this repository does not claim

Two limits shape everything else here.

- SpatialData support depends on an unmerged pull request plus five commits on a fork. No
  SpatialData write path reproduces with released packages alone.
- Arraylake has no anonymous read, so five notebooks ship as committed outputs. A reader
  without an account sees every value those runs produced, and cannot repeat them.

The store-path limit has two stops, and the order matters to a maintainer. On released
spatialdata 0.8.0 the shapes writer fails first. It reads `store.root` in
`spatialdata/_io/io_shapes.py`, and raises an `AttributeError`. `pixi run check-store-path`
asserts that type and that message. The second stop belongs to #1107, which refuses a store
that is neither a `LocalStore` nor an `FsspecStore`. The five commits remove that second stop.

The carried limits, each with the mechanism that causes it.

- `obs` and `var` do not virtualize. AnnData writes categories and the dataframe index as HDF5
  variable-length strings. numpy reads those as the object dtype, which Zarr v3 rejects on
  purpose ([zarr-python#3077](https://github.com/zarr-developers/zarr-python/issues/3077)). No
  automatic map exists from the HDF5 type to a concrete Zarr type. The notebooks read these
  columns eagerly and write them as native chunks.
- Matrices cannot concatenate while virtual. VirtualiZarr requires uniform chunk shapes when it
  combines manifests. A CSR concatenation joins along nnz, which the data fixes and the writer
  does not control. The Zarr data model is not the blocker. A rectilinear chunk grid describes
  this concatenation, and zarr-python already ships one. `pixi run check-concat` asserts both
  halves.
- The source owns the chunk grid. A reference keeps the source row order, so no re-sort is
  possible without a copy. DataScales measured what that costs. Over about 200,000 B cells in
  one chunk layout, a cell-type query took 37.2 s on unsorted rows. The same query took 2.04 s
  on rows sorted by cell type. That 18x difference is their measurement, not ours. A virtual
  reference cannot have the sorted case.
- Every reference needs a checksum, and `last_updated_at` must round up. Icechunk stores that
  timestamp in whole seconds. A value below the object's real modification time makes every
  read fail. `checks/virtualize_cellxgene.py` adds a second and drops the microseconds.
- An HDF5 COMPACT dataset reads back as zeros with no error.
  [VirtualiZarr#527](https://github.com/zarr-developers/VirtualiZarr/issues/527) gives such a
  dataset an empty manifest. `pixi run check-s3` asserts that the arrays hold a nonzero value,
  because nothing else would catch this.

One disclosure about a committed output. We corrected one label of the final cell of
`notebooks/virtualize_braun.ipynb` after the run. It read "source bytes referenced" and now
reads "source file bytes", because the first wording was false. We changed no value. That
notebook needs an Arraylake account, so a re-run could not produce the corrected label.

A second disclosure about a committed output. `scripts/build_atera_notebook.py` no longer
prints a line that named a viewer feature this repository removed. The committed output of
`notebooks/atera_from_arraylake.ipynb` still holds that line. That notebook needs an
Arraylake account, so no re-run could remove it.

## Reproducing

Three tracks. Track 1 needs nothing but this repository. Track 2 needs the fork. Track 3 needs
an Arraylake account, and ships executed instead.

| track | what it needs | what runs |
|---|---|---|
| 1 | `pixi install` | the eight checks and the extension test suite |
| 2 | track 1, plus the fork that `sdpr` fetches | the two local SpatialData notebooks |
| 3 | an Arraylake account | nothing: five notebooks ship as committed outputs |

Track 1:

```shell
pixi install
pixi run check             # virtualize a synthetic h5ad, bit for bit
pixi run check-s3          # a CELLxGENE h5ad into Icechunk, references only
pixi run check-tenx        # a 10x Xenium matrix, CSR over cells
pixi run check-concat      # why two virtual CSR matrices cannot concatenate
pixi run check-icechunk    # stored size against commit count
pixi run check-manifest    # manifest size against reference count, the slowest check
pixi run check-sparsity    # a dense grid stores every block
pixi run check-store-path  # images work, shapes need a filesystem path
pixi run -e spatial extension-test
```

Two of those checks read a remote object. `pixi run check-s3` reads chunk metadata from CZI's
public bucket, over 1,522 byte ranges. `pixi run check-tenx` reads about 24 MB from the public
10x bucket, because it reads one 12.1 MB file twice. The rest run offline.

A slow link to the 10x bucket makes `pixi run check-tenx` fail. It then raises
`fsspec.exceptions.FSTimeoutError` after about five minutes. The check reads the whole matrix
twice. The first read goes through `fsspec` with a 4 MB block, to compare the references
against h5py. That read reaches the cap first. `aiohttp` ends a request after 300 seconds, and
a slow bucket does not deliver 4 MB in that time. We met this twice on osx-arm64 on 2026-10-09.
A plain `curl` range request for the same 4 MB took 385 seconds from the same host. That rate
is about 11 kB/s. The second read copies the file for `read_10x_h5`. It calls `remote.read()`
with no length, so `fsspec` issues one GET for the whole 12.1 MB file. That request ignores the
block size, so a smaller block cannot help it. The third run of the same check passed, about an
hour later. `tools/verify.sh` prints `FAILED: pixi run check-tenx` and exits 1 when this
happens. The check passes when the link carries 4 MB in under 300 seconds.

Two checks measure more with local data. `pixi run check-sparsity` needs two Braun `.h5ad`
files in `h5ads/`, and prints their download URLs when they are missing. `pixi run check-s3`
compares its virtual read against h5py only when `h5ads/` holds the same file.

Track 2 needs the fork, because pixi cannot pin it. See [`docs/fork-pin.md`](docs/fork-pin.md)
for the reason.

```shell
pixi run -e spatial sdpr
PYTHONPATH=$PWD/vendor/spatialdata-1107/src pixi run -e spatial spatialdata-run
PYTHONPATH=$PWD/vendor/spatialdata-1107/src pixi run -e spatial versioning-run
```

`pixi run equivalence-run` regenerates the scanpy comparison. It downloads one Braun `.h5ad` of
about 25 MB.

`tools/verify.sh` runs the manifest check, a locked install, all six gates, the extension test
suite and all eight checks. It names what it skipped. It also says whether `check-s3` compared
its read against h5py. It covers no notebook. With `--with-data` it demands the local `.h5ad`
files, and it also runs `versioning-run`.

## Layout

| path | what is in it |
|---|---|
| `braun.py` | the Braun atlas source files, their URLs and their readers |
| `checks/` | eight standalone checks, one claim each |
| `notebooks/` | eight committed notebooks, outputs included |
| `scripts/` | the generators that build those notebooks |
| `icechunk-SpatialData/` | the SpatialData extension, its tests and the upstream patches |
| `tools/` | six gates, the manifest check and the verify script |
| `docs/` | why the SpatialData fork is not a pixi pin |
| `h5ads/` | local source files, untracked, for the data-dependent checks |
| `vendor/` | the fetched fork, untracked |

## Related work

The Allen Institute benchmarked this storage layer for single-cell analysis. Their poster is
"Implementing and benchmarking capabilities of Zarr, Icechunk, and Rapids-singlecell for large
scale omic analysis". The authors are Alexander Holly, Christian La France and Aishwarya
Chander.

- [DataScales](https://github.com/aifimmunology/DataScales) is the code behind that poster.
- DataScales lists [annizarr](https://github.com/A-Jolly-Holly/annizarr) among its own tools.
  annizarr writes AnnData to Zarr and Icechunk.

The two approaches are complementary. annizarr writes data that the reader owns. This
repository references data that the reader does not own.

## Citation and licence

Braun, Emelie et al. "Comprehensive cell atlas of the developing human brain." *Science*
(2023). [doi:10.1126/science.adf1226](https://doi.org/10.1126/science.adf1226)

MIT. See [`LICENSE`](LICENSE).
