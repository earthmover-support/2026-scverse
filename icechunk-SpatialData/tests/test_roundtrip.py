"""Tests that show which parts of a SpatialData survive a round trip through Icechunk.

`../UPSTREAM.md` depends on these claims. Each test fails with a clear message when its claim
becomes false. The negative tests assert that spatialdata without the patch series in
`../upstream/` still refuses a store. They skip when spatialdata has the series.
"""

from __future__ import annotations

import warnings

warnings.simplefilter("ignore")

import numpy as np
import pandas as pd
import pytest
import zarr

import icechunk_spatialdata as isd
from spatialdata import SpatialData


def write(sdata: SpatialData, session) -> None:
    """Writes `sdata` and its geometry to the session's store with `SpatialData.write`."""
    if not isd.parquet_in_store_available():
        pytest.skip("needs `parquet_fs_fallback` from the patch series in upstream/")
    with isd.parquet_in_store():
        sdata.write(session.store)


def read(session) -> SpatialData:
    if not isd.parquet_in_store_available():
        pytest.skip("needs `parquet_fs_fallback` from the patch series in upstream/")
    with isd.parquet_in_store():
        return SpatialData.read(session.store)


@pytest.fixture(autouse=True)
def bounded():
    """Caps the connections a compute opens. The network tests read chunks through dask."""
    with isd.bounded_reads():
        yield


@pytest.fixture
def sdata():
    """Returns a separate `blobs()` for each test.

    The fixture has function scope on purpose. Each call costs about one second.
    One object shared across the module made the suite results depend on test order.
    A test that set `attrs` or repointed a table's `region` corrupted every later test.
    The failure then appeared in an unrelated test.

    A copy costs less but gives wrong results: `copy.deepcopy` drops the dask frames' `.attrs`.
    The points then lose `feature_key` and `instance_key`.
    A test that asserts on these keys then passes without a real check.
    SpatialData has no `copy()` method that the fixture can use.
    """
    from spatialdata.datasets import blobs

    return blobs()


@pytest.fixture
def repo(tmp_path):
    import icechunk

    return icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "repo"))
    )


# --- the transaction --------------------------------------------------------


def test_a_clean_block_commits(repo, sdata):
    with isd.transaction(repo, "main", "blobs") as tx:
        write(sdata, tx.session)
    assert tx.snapshot, "a clean exit should have committed"
    root = zarr.open_group(repo.readonly_session("main").store, mode="r")
    assert sorted(root.group_keys()) == ["images", "labels", "points", "shapes", "tables"]


def test_a_failed_block_leaves_no_snapshot(repo, sdata):
    """A failed write leaves no data in the repository. A filesystem store cannot offer this."""
    before = [entry.id for entry in repo.ancestry(branch="main")]

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with isd.transaction(repo, "main", "doomed") as tx:
            write(sdata, tx.session)
            raise Boom
    assert tx.snapshot is None
    assert [entry.id for entry in repo.ancestry(branch="main")] == before


# --- round trips ------------------------------------------------------------


def test_rasters_and_tables_round_trip(repo, sdata):
    with isd.transaction(repo, "main", "write") as tx:
        write(sdata, tx.session)
    back = read(repo.readonly_session("main"))

    assert sorted(back.images) == sorted(sdata.images)
    assert sorted(back.labels) == sorted(sdata.labels)
    assert sorted(back.tables) == sorted(sdata.tables)
    # A pyramid reads back as a pyramid. The test compares the finest level of each side.
    for name in sdata.images:
        got = _finest(back.images[name])
        expected = _finest(sdata.images[name])
        assert got.shape == expected.shape, name
        assert np.allclose(got, expected), name
        assert _levels(back.images[name]) == _levels(sdata.images[name]), name
    for name in sdata.labels:
        assert np.array_equal(_finest(back.labels[name]),
                              _finest(sdata.labels[name])), name
        assert _levels(back.labels[name]) == _levels(sdata.labels[name]), name
    assert back.tables["table"].shape == sdata.tables["table"].shape


def test_transformations_survive(repo, sdata):
    """SpatialData keeps the coordinate model in Zarr attributes. Icechunk versions them with no
    extra code.
    """
    from spatialdata.transformations import get_transformation

    with isd.transaction(repo, "main", "write") as tx:
        write(sdata, tx.session)
    back = read(repo.readonly_session("main"))

    for name in sdata.images:
        assert get_transformation(back.images[name]) == get_transformation(
            sdata.images[name]
        ), name


def test_it_is_a_real_spatialdata(repo, sdata):
    import spatialdata

    with isd.transaction(repo, "main", "write") as tx:
        write(sdata, tx.session)
    back = read(repo.readonly_session("main"))
    assert isinstance(back, spatialdata.SpatialData)
    # SpatialData's own validation also accepts it.
    back.validate_table_in_spatialdata(back.tables["table"])


# --- versions: the contribution most likely to stay true --------------------


def test_two_snapshots_are_independently_readable(repo, sdata):
    with isd.transaction(repo, "main", "first") as first:
        write(sdata, first.session)

    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="a").attrs["annotated_by"] = "a later pass"
    second = session.commit("annotate")

    before = zarr.open_group(repo.readonly_session(snapshot_id=first.snapshot).store,
                             mode="r")
    after = zarr.open_group(repo.readonly_session(snapshot_id=second).store, mode="r")
    assert "annotated_by" not in dict(before.attrs)
    assert dict(after.attrs)["annotated_by"] == "a later pass"


def test_geoarrow_shapes_round_trip(repo, sdata):
    """The store holds GeoArrow polygons. Arrow clients read them and do not decode WKB."""
    if not isd.parquet_in_store_available():
        pytest.skip("needs `parquet_fs_fallback` from the patch series in upstream/")
    from spatialdata.testing import assert_spatial_data_objects_are_identical

    session = repo.writable_session("main")
    with isd.parquet_in_store():
        sdata.write(session.store, shapes_geometry_encoding="geoarrow")
    session.commit("shapes as geoarrow")

    back = read(repo.readonly_session("main"))
    assert_spatial_data_objects_are_identical(sdata, back)


def test_the_csc_layer_matches_x(repo, sdata):
    """`layers/X_csc` holds the values of `X` in column-major order. SpatialData reads it as a
    layer.
    """
    import scipy.sparse

    with isd.transaction(repo, "main", "blobs") as tx:
        write(sdata, tx.session)
    session = repo.writable_session("main")
    layer = isd.write_csc_layer(zarr.open_group(session.store, mode="a")["tables"]["table"])
    assert dict(layer.attrs)["encoding-type"] == "csc_matrix"
    session.commit("X as a CSC layer")

    table = read(repo.readonly_session("main")).tables["table"]
    csc = table.layers["X_csc"]
    assert scipy.sparse.isspmatrix_csc(csc)
    np.testing.assert_array_equal(csc.toarray(), scipy.sparse.csr_matrix(table.X).toarray())


# --- the negative claims the patches in upstream/ depend on -----------------
#
# These tests assert that a *capability is still missing*. They do not assert a specific failure.
# This difference is important. PR #1107 changes every one of these error types.
# It changes none of the outcomes.
# A suite that checked exception classes would report four regressions that do not exist.
#
# Each test lists each known failure mode with the version that produces it.
# A failure that matches no known mode is a result of its own.
# It means that the capability arrived upstream, or that the failure changed.
# So the test asserts on the message, and an unknown message fails the test.


def still_blocked(call, known: dict[str, str]):
    """Asserts that `call` still fails with one of the known failure modes."""
    try:
        call()
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        for fragment, provenance in known.items():
            if fragment in text:
                return provenance, text
        raise AssertionError(
            f"failed in an uncharacterised way, which needs looking at:\n  {text}\n"
            f"known modes: {list(known)}"
        ) from exc
    raise AssertionError(
        "this now SUCCEEDS. The capability has landed upstream and UPSTREAM.md is stale."
    )


# The patch series in upstream/ removes each of these restrictions.
# They apply only without the series.
unpatched_only = pytest.mark.skipif(
    isd.parquet_in_store_available(), reason="the patch series in upstream/ removes this restriction"
)


@unpatched_only
def test_spatialdata_write_still_refuses_a_store(repo, sdata):
    session = repo.writable_session("main")
    provenance, text = still_blocked(
        lambda: sdata.write(session.store),
        {
            "must be a string or a Path": "spatialdata 0.8.0: a type check",
            "does not expose a filesystem path": "PR #1107: a deliberate NotImplementedError",
        },
    )
    print(f"\n  write(store) blocked by {provenance}\n    {text[:120]}")


@unpatched_only
def test_read_zarr_still_cannot_take_an_icechunk_group(repo, sdata):
    import spatialdata

    with isd.transaction(repo, "main", "write") as tx:
        write(sdata, tx.session)
    group = zarr.open_group(repo.readonly_session("main").store, mode="r")
    provenance, text = still_blocked(
        lambda: spatialdata.read_zarr(group),
        {
            # 0.8.0 raises on a zarr-v2 name that no longer exists, before it gives a reason.
            "ConsolidatedMetadataStore": "spatialdata 0.8.0: dead zarr-v2 reference",
            # #1107 reaches the raster reader. Then ome-zarr-py refuses the store.
            "not expecting": "PR #1107: ome-zarr-py's ZarrLocation refuses the store",
        },
    )
    print(f"\n  read_zarr(group) blocked by {provenance}\n    {text[:120]}")


@unpatched_only
def test_spatialdata_cannot_write_geometry_to_a_store(repo, sdata):
    """S3 depends on this claim. PR #1107 does not change it."""
    from spatialdata._io import write_shapes
    from spatialdata._io.format import _parse_formats

    session = repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    name, element = next(iter(sdata.shapes.items()))
    group = root.require_group("shapes").require_group(name)
    provenance, text = still_blocked(
        lambda: write_shapes(shapes=element, group=group,
                            element_format=_parse_formats(None)["shapes"]),
        {
            "has no attribute 'root'": "spatialdata 0.8.0: reaches for store.root",
            "Cannot derive a filesystem": "PR #1107: parquet_fs_and_path refuses it",
        },
    )
    print(f"\n  geometry blocked by {provenance}\n    {text[:120]}")


def _levels(element) -> int:
    """Returns the number of pyramid levels in an element. A plain DataArray has one."""
    from xarray import DataTree

    return len(element) if isinstance(element, DataTree) else 1


def _one_tile(page, *, row: int, col: int) -> np.ndarray:
    """Decodes one tile of a tiled page. `asarray` reads every tile of the page first."""
    index = row * -(-page.imagewidth // page.tilewidth) + col
    handle = page.parent.filehandle
    handle.seek(page.dataoffsets[index])
    tile, _, shape = page.decode(handle.read(page.databytecounts[index]), index)
    return tile.reshape(shape[1:3])


def _finest(element) -> np.ndarray:
    """Returns the data of a DataArray, or the finest scale of a multiscale DataTree."""
    if hasattr(element, "children") and element.children:
        dataset = element["scale0"].ds
        return np.asarray(next(iter(dataset.values())).data)
    return np.asarray(element.data)


@unpatched_only
def test_a_store_tolerant_resolver_is_not_sufficient(repo, sdata, monkeypatch):
    """A `_resolve_zarr_store` that accepts a store does not complete the read path.

    On spatialdata 0.8.0, the test monkeypatches the passthrough in.
    `read_zarr` then fails one line later on its own `.root`.
    On PR #1107, upstream already has the passthrough.
    The read still fails, inside `ome-zarr-py`, because its `ZarrLocation` type-checks its input.
    Each version gives the same conclusion, one layer further out.
    """
    import spatialdata
    import spatialdata._io.io_zarr as io_zarr
    from spatialdata._io import _utils

    original = _utils._resolve_zarr_store

    def passthrough(path, **kwargs):
        if isinstance(path, zarr.Group) and not isinstance(
            path.store, (zarr.storage.LocalStore, zarr.storage.FsspecStore)
        ):
            return path.store if not path.path else path
        if isinstance(path, zarr.abc.store.Store):
            return path
        return original(path, **kwargs)

    monkeypatch.setattr(_utils, "_resolve_zarr_store", passthrough)
    monkeypatch.setattr(io_zarr, "_resolve_zarr_store", passthrough)

    with isd.transaction(repo, "main", "write") as tx:
        write(sdata, tx.session)
    group = zarr.open_group(repo.readonly_session("main").store, mode="r")
    provenance, text = still_blocked(
        lambda: spatialdata.read_zarr(group),
        {
            "has no attribute 'root'": "spatialdata 0.8.0: read_zarr's own .root access",
            "not expecting": "PR #1107: ome-zarr-py's ZarrLocation",
        },
    )
    print(f"\n  with a store-tolerant resolver, still blocked by {provenance}")


# --- how far it goes without upstream: a table that holds no counts ---------

VISIUM_H5AD = ("s3://cellxgene-census-public-us-west-2/cell-census/2025-11-08/h5ads/"
               "993cf43f-3b5b-424e-a67a-6ccf0a328450.h5ad")
CENSUS_PREFIX = "s3://cellxgene-census-public-us-west-2/"


@pytest.fixture(scope="module")
def census_registry():
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import S3Store

    return ObjectStoreRegistry(
        {CENSUS_PREFIX: S3Store("cellxgene-census-public-us-west-2",
                                region="us-west-2", skip_signature=True)}
    )


@pytest.fixture
def referencing_repo(tmp_path):
    """Returns a repository that can reference CZI's public bucket."""
    import icechunk

    config = isd.repository_config(
        icechunk.VirtualChunkContainer(
            CENSUS_PREFIX, icechunk.s3_store(region="us-west-2", anonymous=True)
        )
    )
    return icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "repo")),
        config=config,
        authorize_virtual_chunk_access=icechunk.containers_credentials(
            {CENSUS_PREFIX: icechunk.s3_anonymous_credentials()}
        ),
    )


@pytest.mark.network
def test_a_table_can_hold_no_counts_at_all(referencing_repo, census_registry, tmp_path):
    """The limit without upstream changes. X holds references, and plain anndata reads it."""
    from anndata.io import read_elem

    session = referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    isd.virtual_table(root, "table", session, VISIUM_H5AD, census_registry)
    session.commit("a table whose X is somebody else's file")

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())

    back = read_elem(
        zarr.open_group(referencing_repo.readonly_session("main").store, mode="r")["table"]
    )
    assert back.shape == (4992, 32397)
    assert back.X.nnz == 8990335
    # Unmodified anndata produced a real csr_matrix from bytes it never stored.
    import scipy.sparse as sp

    assert sp.issparse(back.X) and back.X.format == "csr"
    # 8.99M float32 values plus int64 indices take ~100 MB. This store holds only metadata.
    assert stored < 2_000_000, f"{stored} bytes is too many to be references"


@pytest.mark.network
def test_the_images_in_that_h5ad_are_channel_last(census_registry):
    """The limit of virtualization: a byte range cannot transpose.

    The Visium images are chunked and referenceable.
    AnnData stores them channel-last, but `Image2DModel` requires channel-first.
    If AnnData writes them as `(c, y, x)`, this test fails and the limit no longer applies.
    """
    library = "spaceranger110_count_36173_Pla_Camb9518737_GRCh38-3_0_0_premrna"
    channel_last, description = isd.images_in_h5ad_are_channel_last(
        VISIUM_H5AD, census_registry, f"uns/spatial/{library}/images"
    )
    assert channel_last, description
    # A transpose is a codec: the stored bytes stay channel-last and the element is (c, y, x).
    # The project verified this at 384 references on this image.
    assert "transpose codec" in description
    assert "cannot" not in description


# --- the fix for the geometry blocker ---------------------------------------


def test_geometry_in_spatialdatas_own_format_inside_the_store(repo, sdata):
    """The transaction writes geometry in SpatialData's format. SpatialData's readers read it.

    The complete blocker is one fact: "Icechunk has no fsspec view".
    PR #1107 routes geometry I/O through an fsspec filesystem.
    Zarr names an array `shapes.parquet` at the exact path that SpatialData asks for.
    So a file becomes a uint8 array, and no other code has to change.
    """
    from icechunk_spatialdata._filesystem import available

    if not available():
        pytest.skip("needs `parquet_fs_fallback` from the patch series in upstream/")

    with isd.transaction(repo, "main", "geometry inside the repo") as tx:
        write(sdata, tx.session)

    root = zarr.open_group(repo.readonly_session("main").store, mode="r")
    parquet = [p for p, _ in root.members(max_depth=4) if p.endswith(".parquet")]
    assert parquet, "no parquet landed in the store"

    back = read(repo.readonly_session("main"))
    assert sorted(back.shapes) == sorted(sdata.shapes)
    for name, frame in sdata.shapes.items():
        assert np.array_equal(frame.geometry.to_wkb().to_numpy(),
                              back.shapes[name].geometry.to_wkb().to_numpy()), name
    assert sorted(back.points) == sorted(sdata.points)


def test_the_zarr_array_filesystem_round_trips_bytes(tmp_path):
    """Tests the primitive alone, independent of SpatialData."""
    from icechunk_spatialdata._filesystem import FILE_CONVENTION, ZarrArrayFileSystem

    root = zarr.create_group(store=str(tmp_path / "t.zarr"), zarr_format=3)
    fs = ZarrArrayFileSystem(root)
    payload = bytes(range(256)) * 40

    with fs.open("shapes/x/shapes.parquet", "wb") as sink:
        sink.write(payload)
    assert fs.exists("shapes/x/shapes.parquet")
    assert fs.info("shapes/x/shapes.parquet")["size"] == len(payload)
    assert fs.isdir("shapes/x") and fs.isfile("shapes/x/shapes.parquet")
    with fs.open("shapes/x/shapes.parquet", "rb") as src:
        assert src.read() == payload
    # It is an ordinary Zarr array, at the path the filename implies.
    stored = root["shapes/x/shapes.parquet"]
    assert stored.dtype == np.uint8 and stored.shape == (len(payload),)
    attrs = dict(stored.attrs)
    assert any(d.get("uuid") == FILE_CONVENTION["uuid"]
               for d in attrs["zarr_conventions"])
    assert attrs["file:name"] == "shapes.parquet"


# --- a Parquet file by reference, not by copy -------------------------------

BOUNDARIES_HOST = "https://s3-us-west-2.amazonaws.com/10x.files/"
BOUNDARIES = (BOUNDARIES_HOST + "samples/xenium/1.0.1/"
              "Xenium_FFPE_Human_Breast_Cancer_Rep1/"
              "Xenium_FFPE_Human_Breast_Cancer_Rep1_cell_boundaries.parquet")


@pytest.fixture
def http_referencing_repo(tmp_path):
    import icechunk

    config = isd.repository_config(
        icechunk.VirtualChunkContainer(BOUNDARIES_HOST, icechunk.http_store())
    )
    return icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "repo")),
        config=config,
        authorize_virtual_chunk_access={
            BOUNDARIES_HOST: icechunk.credentials.HttpAccess
        },
    )


@pytest.mark.network
def test_a_parquet_file_can_be_referenced_not_copied(http_referencing_repo, tmp_path):
    """A uint8 array has no codec, so a chunk is a byte range. A reference can hold any format.

    The filesystem slices each read on demand, so pyarrow fetches the footer without the body.
    This part is important for a 670 MB `transcripts.parquet`.
    """
    import pyarrow.parquet as pq
    import requests

    from icechunk_spatialdata._filesystem import ZarrArrayFileSystem
    from icechunk_spatialdata._reference import reference_file

    size = int(requests.head(BOUNDARIES).headers["content-length"])
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    references = reference_file(
        root, "shapes/cell_boundaries/shapes.parquet", BOUNDARIES, size, session
    )
    session.commit("a published GeoParquet, referenced")
    assert references >= 1

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())
    # n-1 chunks are references. `reference_file` copies only the short tail.
    assert stored < size, f"{stored} of {size} bytes stored. Nothing was referenced"

    read_only = zarr.open_group(
        http_referencing_repo.readonly_session("main").store, mode="r"
    )
    filesystem = ZarrArrayFileSystem(read_only)
    with filesystem.open("shapes/cell_boundaries/shapes.parquet", "rb") as handle:
        parquet = pq.ParquetFile(handle)
        groups = [parquet.metadata.row_group(i).num_rows
                  for i in range(parquet.metadata.num_row_groups)]
        table = parquet.read()
    assert sum(groups) == 2_181_086
    assert table.num_rows == sum(groups)
    assert [column.name for column in table.schema] == ["cell_id", "vertex_x", "vertex_y"]


@pytest.mark.network
def test_that_published_parquet_misreports_its_own_row_count():
    """The file's footer contradicts its row groups. This side finding gets its own test.

    10x's `cell_boundaries.parquet` declares `num_rows = 1,000,000`.
    Its three row groups sum to 2,181,086. fastparquet 1.0.0 wrote the file.
    Code that trusts `metadata.num_rows` for a plan or a row count gets a wrong answer.
    For this reason, the test above sums the groups.
    """
    import fsspec
    import pyarrow.parquet as pq

    filesystem = fsspec.filesystem("http", block_size=1 << 20)
    with filesystem.open(BOUNDARIES, "rb") as handle:
        metadata = pq.ParquetFile(handle).metadata
    groups = [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)]
    assert sum(groups) == 2_181_086
    assert metadata.num_rows == 1_000_000, (
        f"the footer now says {metadata.num_rows}; if 10x have rewritten the file this note "
        "is obsolete"
    )
    assert "fastparquet" in (metadata.created_by or "")


MORPHOLOGY = (BOUNDARIES_HOST + "samples/xenium/1.0.1/"
              "Xenium_FFPE_Human_Breast_Cancer_Rep1/"
              "Xenium_FFPE_Human_Breast_Cancer_Rep1_morphology_mip.ome.tif")


@pytest.mark.network
def test_an_ome_tiff_can_be_referenced_as_an_opaque_file(http_referencing_repo, tmp_path):
    """The store holds the file with no codec. An array of its pixels needs a codec.

    A reference needs no codec, because a uint8 chunk is a byte range.
    tifffile decodes JPEG 2000 itself.
    So the store holds the file, and a read of it has a low cost.
    Any tool that can read an OME-TIFF can read it.
    The pixels as a Zarr array are a separate matter and a separate representation.
    See `test_an_ome_tiff_becomes_a_real_image_element`.
    The project keeps both representations. This one needs nothing installed.
    That one gives low-cost random access at full resolution.
    """
    import requests
    import tifffile

    from icechunk_spatialdata._filesystem import ZarrArrayFileSystem
    from icechunk_spatialdata._reference import reference_file

    size = int(requests.head(MORPHOLOGY).headers["content-length"])
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    references = reference_file(
        root, "images/morphology.ome.tif", MORPHOLOGY, size, session, chunk=1 << 20
    )
    session.commit("an OME-TIFF, referenced")
    assert references > 100

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())
    assert stored < size / 100, f"{stored} of {size} bytes stored. The file was copied"

    read_only = zarr.open_group(
        http_referencing_repo.readonly_session("main").store, mode="r"
    )
    handle = ZarrArrayFileSystem(read_only).open("images/morphology.ome.tif", "rb")
    with tifffile.TiffFile(handle) as tif:
        series = tif.series[0]
        assert len(series.levels) == 8
        assert series.dtype == np.dtype("uint16")
        structure_cost = handle.raw.bytes_read
        overview = series.levels[5].asarray()
    assert overview.shape == (805, 1106)
    # A read of the structure and one coarse level must not fetch the whole file.
    assert structure_cost < size / 100, structure_cost
    assert handle.raw.bytes_read < size / 50, handle.raw.bytes_read


LUNG_MORPHOLOGY = (BOUNDARIES_HOST + "samples/xenium/2.0.0/"
                   "Xenium_V1_humanLung_Cancer_FFPE/"
                   "Xenium_V1_humanLung_Cancer_FFPE_morphology.ome.tif")


@pytest.fixture
def tenx_registry():
    """Maps the published URLs for the parser. The references contain the same URLs."""
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import HTTPStore

    return ObjectStoreRegistry({BOUNDARIES_HOST: HTTPStore(BOUNDARIES_HOST.rstrip("/"))})


@pytest.fixture
def tenx_registry():
    """Maps the published URLs for the parser. The references contain the same URLs."""
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import HTTPStore

    return ObjectStoreRegistry({BOUNDARIES_HOST: HTTPStore(BOUNDARIES_HOST.rstrip("/"))})


@pytest.fixture
def morphology_handle():
    """Opens a lazy HTTP file over the published OME-TIFF, to read its structure only.

    The fixture yields a factory, not one handle. tifffile takes ownership of each handle it gets.
    No code can read a handle again after tifffile uses it.
    """
    import fsspec

    filesystem = fsspec.filesystem("http", block_size=1 << 20)
    opened = []

    def open_handle():
        handle = filesystem.open(MORPHOLOGY, "rb")
        opened.append(handle)
        return handle

    yield open_handle
    for handle in opened:
        handle.close()


@pytest.mark.network
def test_an_ome_tiff_becomes_a_real_image_element(tenx_registry, http_referencing_repo, morphology_handle,
                                                 tmp_path):
    """The other representation: the pixels as a Zarr array, so it is an image *element*.

    This test needs the Zarr v3 JPEG 2000 codec that `virtual-tiff` publishes.
    `virtual_image` copies no bytes, not even a tail.
    Each chunk is a whole codestream, not a fixed slice of the file.
    The result parses as a `SpatialData` image, with its coordinate system intact.
    """
    from spatialdata.models import get_axes_names

    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    element = isd.virtual_image(root, "morphology", session,
                               registry=tenx_registry, location=MORPHOLOGY)
    assert sorted(element.array_keys()) == [f"s{i}" for i in range(8)]
    session.commit("morphology_mip as an image element, by reference")

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())
    # Metadata only: no pixel bytes, and no materialized tail either.
    assert stored < 2_000_000, f"{stored} bytes stored. Pixels were copied"

    image = read(http_referencing_repo.readonly_session("main")).images["morphology"]
    assert get_axes_names(image) == ("c", "y", "x")
    # A pyramid reads back as a pyramid. Its levels carry the shape.
    assert _levels(image) == 8
    assert _finest(image).shape == (1, 25778, 35416)


@pytest.mark.network
def test_the_image_element_reads_the_same_pixels_tifffile_does(tenx_registry, http_referencing_repo,
                                                               morphology_handle):
    """The pixels also match at full resolution. The opaque-file representation cannot do this
    at low cost.

    `tifffile`'s own Zarr view cannot read one level-0 tile, because zarr 3 cannot open a
    `ZarrTiffStore`. So that route decodes a whole level. Here a tile is a chunk.
    """
    import tifffile

    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    isd.virtual_image(root, "morphology", session,
                      registry=tenx_registry, location=MORPHOLOGY)
    session.commit("morphology_mip as an image element, by reference")

    read_only = zarr.open_group(
        http_referencing_repo.readonly_session("main").store, mode="r"
    )
    group = read_only["images"]["morphology"]

    with tifffile.TiffFile(morphology_handle()) as tif:
        levels = tif.series[0].levels
        coarse = levels[5].asarray()
        full_tile = _one_tile(levels[0].pages[0], row=4, col=4)

    assert np.array_equal(group["s5"][0], coarse)
    assert np.array_equal(group["s0"][0, 4096:5120, 4096:5120], full_tile)


@pytest.mark.network
def test_the_pyramid_scales_are_measured_not_assumed(tenx_registry, http_referencing_repo, morphology_handle):
    """An OME-TIFF pyramid halves with rounding, so a power-of-two scale is wrong.

    25,778 rows become 12,889, 6,444, 3,222 and 1,611. Level 2 is 4.0003x, not 4x.
    The metadata records the scales that the shapes give.
    """
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    element = isd.virtual_image(root, "morphology", session,
                               registry=tenx_registry, location=MORPHOLOGY)

    datasets = dict(element.attrs)["ome"]["multiscales"][0]["datasets"]
    scales = {d["path"]: d["coordinateTransformations"][0]["scale"] for d in datasets}
    assert scales["s0"] == [1.0, 1.0, 1.0]
    assert scales["s2"][1] != 4.0, "a rounded pyramid was recorded as an exact power of two"
    assert abs(scales["s2"][1] - 4.0) < 0.01
    # No scale applies to the channel axis.
    assert all(scale[0] == 1.0 for scale in scales.values())


@pytest.mark.network
def test_the_image_element_can_be_built_from_the_referenced_file(tenx_registry, http_referencing_repo):
    """One source gives both representations, through one path to the published bytes.

    The upload script holds the OME-TIFF as an opaque file.
    It then reads *that* file to build the image element.
    So the structure read goes through the store, not through a second HTTP client.
    The two steps work together because the lazy file is seekable, and tifffile needs that.
    """
    import requests

    from icechunk_spatialdata._filesystem import ZarrArrayFileSystem
    from icechunk_spatialdata._reference import reference_file

    size = int(requests.head(MORPHOLOGY).headers["content-length"])
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    reference_file(
        root, "files/morphology.ome.tif", MORPHOLOGY, size, session, chunk=1 << 22
    )
    session.commit("the file, referenced")

    session = http_referencing_repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    # The parser reads the structure from the published object, not from this store's copy.
    # So this test has no handle whose reads it can count. The element still holds references:
    # `test_the_repository_holds_no_pixels` asserts that.
    element = isd.virtual_image(root, "morphology", session,
                                location=MORPHOLOGY, registry=tenx_registry)
    session.commit("and the same bytes as an image element")

    assert sorted(element.array_keys()) == [f"s{i}" for i in range(8)]
    read_only = zarr.open_group(
        http_referencing_repo.readonly_session("main").store, mode="r"
    )
    assert read_only["images"]["morphology"]["s5"][0].shape == (805, 1106)


@pytest.mark.network
def test_a_focal_stack_refuses_rather_than_guessing(tenx_registry, http_referencing_repo):
    """A 3-D source needs a chosen plane, because both alternatives are wrong.

    Xenium's morphology.ome.tif is a stack of focal planes with the keys z.row.column.
    The stack as channels renders, but it labels z as c.
    A true 3-D element needs (z, y, x) axis support, and virtual_image does not have it.
    So virtual_image refuses and says which case applies.
    """
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    with pytest.raises(ValueError, match="focal stack"):
        isd.virtual_image(root, "morphology", session,
                          location=LUNG_MORPHOLOGY, registry=tenx_registry)


@pytest.mark.network
def test_plane_does_not_apply_to_a_flat_image(tenx_registry, http_referencing_repo, morphology_handle):
    """The inverse case, so a caller cannot pass `plane` where it has no meaning."""
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    with pytest.raises(ValueError, match="not a focal stack"):
        isd.virtual_image(root, "morphology", session, registry=tenx_registry, location=MORPHOLOGY, plane=0)


def test_an_element_transform_can_be_set(repo, sdata):
    """virtual_image uses identity by default. A pixel grid unlike the world grid needs a scale."""
    from spatialdata.transformations import Scale

    from icechunk_spatialdata._virtual import _multiscales

    identity = _multiscales("m", [(0, (10, 10))])
    scaled = _multiscales("m", [(0, (10, 10))],
                          Scale([0.2125, 0.2125], axes=("y", "x")))
    element = identity["multiscales"][0]["coordinateTransformations"][0]
    assert element["type"] == "identity"
    element = scaled["multiscales"][0]["coordinateTransformations"][0]
    assert element["type"] == "scale"
    # The scale applies only to y and x, never to the channel axis.
    assert element["scale"] == [1.0, 0.2125, 0.2125]


TENX_MATRIX = (BOUNDARIES_HOST + "samples/xenium/2.0.0/"
               "Xenium_V1_humanLung_Cancer_FFPE/"
               "Xenium_V1_humanLung_Cancer_FFPE_cell_feature_matrix.h5")


def test_an_unknown_table_layout_is_refused(repo):
    """The caller must ask for the 10x layout, because nothing in the file declares it."""
    session = repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    with pytest.raises(ValueError, match="unknown layout"):
        isd.virtual_table(root, "table", session, "unused", None, layout="guess")


@pytest.mark.network
def test_a_tenx_matrix_can_hold_no_counts(http_referencing_repo, tmp_path):
    """A Xenium expression table whose X is byte ranges in 10x's published h5.

    The h5ad path detects an `encoding-type` of `csr_matrix`. A 10x matrix has no such metadata.
    For this reason, the caller names the layout explicitly.
    The method works because `indptr` indexes barcodes.
    So the bytes are already CSR over cells, and no transpose is necessary.
    """
    import fsspec
    from anndata.io import read_elem
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import HTTPStore

    registry = ObjectStoreRegistry({BOUNDARIES_HOST: HTTPStore(BOUNDARIES_HOST.rstrip("/"))})
    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    handle = fsspec.filesystem("http", block_size=1 << 20).open(TENX_MATRIX, "rb")
    isd.virtual_table(root, "table", session, TENX_MATRIX, registry,
                      group="matrix", layout="tenx", handle=handle)
    session.commit("a Xenium table holding no counts")

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())
    adata = read_elem(zarr.open_group(
        http_referencing_repo.readonly_session("main").store, mode="r")["table"])

    assert adata.shape == (162254, 541)
    assert adata.X.nnz == 4901617
    # Unmodified anndata reads it as a real sparse matrix.
    assert type(adata.X).__name__ == "csr_matrix"
    # Real labels, not 0..n: a gene lookup needs them to work at all.
    assert adata.obs_names[0] == "aaaadpbp-1"
    assert "EPCAM" in adata.var_names
    assert (np.asarray(adata[:, "EPCAM"].X.todense()).ravel() > 0).sum() == 87642
    # The store holds the labels but not the counts.
    assert stored < 20_000_000, f"{stored} bytes stored. The matrix was copied"


@pytest.mark.network
def test_a_gene_major_matrix_is_refused_rather_than_transposed():
    """10x ship the same counts twice. A reference can hold only one orientation.

    cell_feature_matrix.zarr.zip is CSR over genes.
    An X of (cells, genes) from it needs a transpose, and a byte range cannot transpose.
    So the code checks the orientation and does not trust it.
    The names of the two files do not show the difference.
    """
    import json
    import zipfile

    import fsspec

    url = TENX_MATRIX.replace("cell_feature_matrix.h5", "cell_feature_matrix.zarr.zip")
    with fsspec.filesystem("http", block_size=1 << 20).open(url, "rb") as handle:
        with zipfile.ZipFile(handle) as archive:
            indptr = json.loads(archive.read("cell_features/indptr/.zarray"))
    # 543 entries index 542 rows. These rows are genes, not the 162,254 cells.
    assert indptr["shape"] == [543], indptr["shape"]


CELLS_ZARR_ZIP = (BOUNDARIES_HOST + "samples/xenium/2.0.0/"
                  "Xenium_V1_humanLung_Cancer_FFPE/"
                  "Xenium_V1_humanLung_Cancer_FFPE_cells.zarr.zip")


@pytest.mark.network
def test_a_zipped_zarr_store_becomes_a_labels_element(http_referencing_repo, tmp_path):
    """References to segmentation masks in a published .zarr.zip, with no new codec.

    A zip's central directory locates every member. A STORED member is a contiguous range.
    So a zipped Zarr store is a virtual Zarr store.
    VirtualiZarr's ZippedZarrParser does the read and the V2-to-V3 conversion.
    This test writes the references and the OME metadata.

    The masks use blosc, which is a core Zarr v3 codec.
    So, unlike the JPEG 2000 images, this test needs nothing installed beyond zarr itself.
    """
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import HTTPStore
    from spatialdata.transformations import Scale
    from virtualizarr.parsers import ZippedZarrParser

    from icechunk_spatialdata._virtual import _multiscales, _virtual_array

    registry = ObjectStoreRegistry({BOUNDARIES_HOST: HTTPStore(BOUNDARIES_HOST.rstrip("/"))})
    parsed = ZippedZarrParser(group="masks")(CELLS_ZARR_ZIP, registry)._group
    assert sorted(parsed.arrays) == ["0", "1", "homogeneous_transform"]

    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    isd.declare_container(root)
    group = root.require_group("labels").require_group("cell_masks")
    _virtual_array(group, "s0", parsed.arrays["0"], session.store, last_updated_at=None)
    shape = tuple(int(s) for s in parsed.arrays["0"].shape)
    # 1/0.2125 is the masks' own homogeneous_transform, so microns is the global frame.
    group.attrs["ome"] = _multiscales(
        "cell_masks", [(0, shape)], Scale([0.2125, 0.2125], axes=("y", "x")),
        dims=("y", "x"), element_type="labels")
    group.attrs["spatialdata_attrs"] = {"version": "0.3"}
    session.commit("cell masks, by reference into a zipped zarr store")

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())
    assert stored < 1_000_000, f"{stored} bytes stored. Mask chunks were copied"

    labels = read(http_referencing_repo.readonly_session("main")).labels["cell_masks"]
    # Labels have no channel axis. Labels2DModel rejects labels that have one.
    assert labels.dims == ("y", "x")
    assert labels.shape == (17098, 51187)
    assert labels.dtype == np.uint32
    crop = np.asarray(labels[8000:8535, 24000:25600])
    assert len(np.unique(crop)) - 1 == 453, len(np.unique(crop)) - 1


def test_every_exported_name_resolves():
    """`__all__` and the module agree.

    The deletion of `_plotting.py` removed its import. It left `dtype_argument_is_stale` in
    `__all__`. In that state, `from icechunk_spatialdata import *` raises for a name that no
    module provides. The design moves modules out of this package.
    So the test checks the list, and nobody has to remember it.
    """
    import icechunk_spatialdata as isd

    missing = [name for name in isd.__all__ if not hasattr(isd, name)]
    assert not missing, f"exported but absent: {missing}"


def test_the_point_renderer_runs_unpatched():
    """`render_points` works with no code from this project. This test replaced two guard tests.

    spatialdata-plot 0.4.0 passed `dtype=` to `AnnData`. anndata had removed that argument.
    So this call raised on SpatialData's own `blobs()`.
    0.4.1 builds no `AnnData`, and `_plotting.py` does not exist.
    If an environment installs 0.4.0 again, this test fails where the notebooks would fail.
    """
    import tempfile

    import matplotlib

    matplotlib.use("Agg")
    pytest.importorskip("spatialdata_plot")
    import spatialdata_plot  # noqa: F401
    from spatialdata.datasets import blobs

    blobs().pl.render_points("blobs_points").pl.show(
        dpi=40, save=tempfile.mkstemp(suffix=".png")[1])


HE_IMAGE = (BOUNDARIES_HOST + "samples/xenium/2.0.0/"
            "Xenium_V1_humanLung_Cancer_FFPE/"
            "Xenium_V1_humanLung_Cancer_FFPE_he_image.ome.tif")


@pytest.fixture
def he_handle():
    """Opens a lazy HTTP file over the published H&E, to read its structure only."""
    import fsspec

    filesystem = fsspec.filesystem("http", block_size=1 << 20)
    opened = []

    def open_handle():
        handle = filesystem.open(HE_IMAGE, "rb")
        opened.append(handle)
        return handle

    yield open_handle
    for handle in opened:
        handle.close()


@pytest.mark.network
def test_an_interleaved_image_becomes_a_channel_first_element(tenx_registry, http_referencing_repo, he_handle,
                                                              tmp_path):
    """A byte range cannot transpose, but a Zarr codec can. So channel-last is not a blocker.

    10x publish the H&E as interleaved RGB, stored as `(y, x, c)`.
    An image element must be `(c, y, x)`. The element declares `(c, y, x)`.
    A `transpose` codec permutes the axes in the read pipeline.
    So the bytes on 10x's server stay exactly as 10x published them.
    """
    from spatialdata.models import get_axes_names

    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    element = isd.virtual_image(root, "he_image", session, registry=tenx_registry, location=HE_IMAGE, channel_names=["r", "g", "b"])
    assert sorted(element.array_keys()) == [f"s{i}" for i in range(6)]
    session.commit("the H&E as a (c, y, x) element")

    stored = sum(f.stat().st_size for f in (tmp_path / "repo").rglob("*") if f.is_file())
    assert stored < 2_000_000, f"{stored} bytes stored. Pixels were copied to transpose them"

    image = read(http_referencing_repo.readonly_session("main")).images["he_image"]
    assert get_axes_names(image) == ("c", "y", "x")
    assert _finest(image).shape == (3, 45087, 11580)
    assert _levels(image) == 6


@pytest.mark.network
def test_the_transposed_element_reads_the_same_pixels_tifffile_does(tenx_registry, http_referencing_repo,
                                                                   he_handle):
    """The permutation is correct, not only the shape.

    A wrong transpose order gives an image with the right dimensions and the wrong colours.
    A shape assertion misses exactly this failure.
    """
    import tifffile

    session = http_referencing_repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    isd.virtual_image(root, "he_image", session, registry=tenx_registry, location=HE_IMAGE)
    session.commit("the H&E as a (c, y, x) element")

    read_only = zarr.open_group(
        http_referencing_repo.readonly_session("main").store, mode="r"
    )
    # A coarse level, so the whole level is a few references.
    got = np.asarray(read_only["images"]["he_image"]["s4"][:])
    with tifffile.TiffFile(he_handle()) as tif:
        direct = tif.series[0].levels[4].pages[0].asarray()
    assert direct.shape == (2818, 724, 3), direct.shape
    assert np.array_equal(got, direct.transpose(2, 0, 1))


@pytest.mark.network
def test_a_focal_stack_and_an_interleaved_source_are_told_apart(he_handle, morphology_handle):
    """`plane` applies to a stack but not to interleaved samples. Both have 3-D shapes."""
    import tifffile

    with tifffile.TiffFile(he_handle()) as tif:
        page = tif.series[0].levels[0].pages[0]
        assert int(page.samplesperpixel) == 3
        assert tuple(int(s) for s in tif.series[0].levels[0].shape)[-1] == 3
    with tifffile.TiffFile(morphology_handle()) as tif:
        # The breast morphology mip: 2-D, one sample, so neither path applies.
        assert int(tif.series[0].levels[0].pages[0].samplesperpixel) == 1


def test_an_unrecognised_tile_codec_is_refused():
    """The parser refuses a compressor that has no mapping. It does not guess.

    The wrong codec does not raise. It decodes to plausible but wrong values.
    Only here can a guess produce a store that returns wrong data without an error.
    The table of compressors belongs to `virtual-tiff`.
    It covers fourteen compressors, and this project verified two.
    This test checks that an unknown compressor still stops the parser.
    The parser does not use an approximation.
    """
    pytest.importorskip("virtual_tiff")
    from virtual_tiff.parser import _get_compression

    class Unmapped:
        other_tags: dict = {}

    with pytest.raises(ValueError, match="not recognized"):
        _get_compression(Unmapped(), 65000)


# --- alignment with the SpatialData data model -------------------------------


def test_the_element_transform_asks_for_its_output_axes():
    """Output axes forced to equal the input axes drop each axis that the transform adds.

    Each transformation in the model round-trips either way if it keeps its dimensionality.
    This project writes only such transformations.
    But an affine that adds an axis loses that axis without an error.
    This test prevents that failure.
    """
    import numpy as np
    from spatialdata.transformations import Affine, Identity, MapAxis, Scale, Sequence

    from icechunk_spatialdata._virtual import _multiscales

    dims = ("c", "y", "x")
    adding = Affine(np.array([[0, 0, 5.0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]),
                    input_axes=("y", "x"), output_axes=("z", "y", "x"))
    transform = _multiscales("m", [(0, (10, 10))], adding)[
        "multiscales"][0]["coordinateTransformations"][0]
    assert [axis["name"] for axis in transform["output"]["axes"]] == ["c", "z", "y", "x"]

    # The full transformation set also survives the round trip unchanged.
    from spatialdata._io._utils import _get_transformations_from_ngff_dict

    for element in (Identity(), Scale([0.2125, 0.2125], axes=("y", "x")),
                    MapAxis({"x": "y", "y": "x"}),
                    Sequence([Scale([2.0, 2.0], axes=("y", "x")), Identity()])):
        written = _multiscales("m", [(0, (10, 10))], element)["multiscales"][0]
        back = _get_transformations_from_ngff_dict(written["coordinateTransformations"])["global"]
        assert np.allclose(
            element.to_affine_matrix(input_axes=dims, output_axes=dims),
            back.to_affine_matrix(input_axes=dims, output_axes=dims),
        ), type(element).__name__


def test_a_single_scale_image_keeps_its_channel_names(repo):
    """`omero` labels apply with or without a pyramid. The reader read them only with one."""
    from spatialdata.models import Image2DModel, get_channel_names

    from icechunk_spatialdata._virtual import _multiscales

    session = repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)
    isd.declare_container(root)
    group = root.require_group("images").require_group("stain")
    group.create_array("s0", shape=(2, 4, 4), chunks=(2, 4, 4), dtype="uint8")
    group.attrs["ome"] = _multiscales("stain", [(0, (4, 4))],
                                      channel_names=["DAPI", "18S"])
    group.attrs["spatialdata_attrs"] = {"version": "0.3"}
    session.commit("a single-scale image with named channels")

    image = read(repo.readonly_session("main")).images["stain"]
    assert _levels(image) == 1, "this case is about the single-scale branch"
    assert list(get_channel_names(image)) == ["DAPI", "18S"]
    # It is also a parsed Image2DModel element, not a bare DataArray.
    assert image.dims == Image2DModel.parse(
        np.zeros((2, 4, 4)), dims=("c", "y", "x")
    ).dims


@pytest.mark.parametrize("name", ["", ".", "..", "__x", "a/b", "a b"])
def test_an_invalid_element_name_is_refused_where_it_is_supplied(tenx_registry, repo, sdata, name):
    """The call enforces SpatialData's naming rules. `read` does not have to enforce them.

    Without this check, the call writes an invalid name. The name fails much later, when `read`
    reaches `SpatialData(...)`. That point is far from the responsible code.
    """
    session = repo.writable_session("main")
    root = zarr.create_group(store=session.store, zarr_format=3)

    with pytest.raises((ValueError, TypeError)):
        isd.virtual_image(root, name, session, registry=tenx_registry, location="s3://nowhere/x.tif")
    with pytest.raises((ValueError, TypeError)):
        isd.virtual_table(root, name, session, "s3://nowhere/x.h5ad", None)


def test_a_valid_name_still_passes(repo, sdata):
    """The guard must not reject the names this project actually uses."""
    from icechunk_spatialdata._virtual import _check_element_name

    for name in ("he_image", "morphology_focus", "cell_labels", "cell_circles", "table",
                 "blobs_multiscale_image", "a.b-c_1"):
        _check_element_name(name)


def test_spatialdata_attrs_round_trip(repo, sdata):
    """`write` put these attrs on the root. `read` did not look, so it dropped them silently."""
    sdata.attrs["provenance"] = {"built_by": "a test", "run": 3}
    with isd.transaction(repo, "main", "attrs on the container") as tx:
        write(sdata, tx.session)

    back = read(repo.readonly_session("main"))
    assert back.attrs["provenance"] == {"built_by": "a test", "run": 3}
    # `read` does not leak the container metadata into attrs.
    assert "spatialdata_attrs" not in back.attrs


def test_points_keep_their_feature_and_instance_keys(repo, sdata):
    """`feature_key` and `instance_key` survive the Parquet-in-store path.

    `feature_key` names the feature column. `instance_key` names the column that identifies the
    instance. SpatialData's own Parquet writer preserves them.
    The fallback must not lose them on write or on read.
    """
    from spatialdata.models import PointsModel

    name = sorted(sdata.points)[0]
    before = sdata.points[name].attrs.get(PointsModel.ATTRS_KEY, {})
    assert before, f"points/{name} carries no attrs to preserve; this test needs a fixture that does"

    with isd.transaction(repo, "main", "geometry in the store") as tx:
        write(sdata, tx.session)

    back = read(repo.readonly_session("main"))
    assert back.points[name].attrs.get(PointsModel.ATTRS_KEY) == before


# --- the published store ------------------------------------------------------
#
# The other tests cover the mechanisms and do not read their output.
# A change to the published repository then appears in a notebook run, not here.
# These tests read that repository.

LUNG_REPO = "earthmover-demos/xenium-lung-virtual"
#: The repo is on production, whatever endpoint the local arraylake config selects.
ARRAYLAKE_URI = "https://api.earthmover.io"


@pytest.fixture
def lung_session():
    """Returns a read-only session on the published lung store, or skips the test.

    Without an Arraylake login, the fixture skips and does not fail.
    The rest of the suite reads anonymously from public buckets.
    This fixture is the only part that needs credentials.
    """
    arraylake = pytest.importorskip("arraylake")
    # No codec install is necessary. The store's images use the parser's codec, from imagecodecs.
    try:
        repo = arraylake.Client(service_uri=ARRAYLAKE_URI).get_repo(
            LUNG_REPO, config=isd.repository_config()
        )
        return repo.readonly_session("main")
    except Exception as error:                      # auth, network, or a missing repo
        pytest.skip(f"cannot open {LUNG_REPO}: {type(error).__name__}: {error}")


@pytest.mark.arraylake
def test_the_published_lung_store_still_holds_every_element(lung_session):
    """Asserts what the drop-in notebook depends on, and does not execute a notebook.

    The names and the axis order come from the tutorial, because the notebook runs its calls
    verbatim. If an element name or a coordinate system changes here, the notebook cells fail.
    """
    if not isd.parquet_in_store_available():
        pytest.skip("shapes need `parquet_fs_fallback` from the patch series in upstream/")
    from spatialdata.models import get_axes_names

    sdata = read(lung_session)

    assert sorted(sdata.images) == ["he_image", "morphology_focus"]
    assert sorted(sdata.labels) == ["cell_labels", "nucleus_labels"]
    assert sorted(sdata.shapes) == ["cell_boundaries", "cell_circles"]
    assert sorted(sdata.tables) == ["table"]

    for name in sdata.images:
        assert get_axes_names(sdata.images[name]) == ("c", "y", "x"), name
    for name in sdata.labels:
        assert get_axes_names(sdata.labels[name]) == ("y", "x"), name

    # Pixel space puts the tutorial's own crop coordinates in the correct place.
    assert _finest(sdata.labels["cell_labels"]).shape == (17098, 51187)
    assert _finest(sdata.images["morphology_focus"]).shape == (1, 17098, 51187)
    # The H&E is interleaved RGB at the source and (c, y, x) here, via a transpose codec.
    assert _finest(sdata.images["he_image"]).shape == (3, 45087, 11580)

    table = sdata.tables["table"]
    assert table.shape == (162254, 541)
    assert "EPCAM" in table.var_names


@pytest.mark.arraylake
def test_the_published_store_holds_almost_none_of_the_data(lung_session):
    """The whole demo depends on this claim: the store holds references, not bytes."""
    locations = lung_session.all_virtual_chunk_locations()
    assert len(locations) > 4_000, len(locations)
    # Every reference points at 10x's own bucket, not their CDN.
    # The CDN returns a whole-object checksum, and then ranged reads of one object fail.
    # The bucket serves the same bytes without that header.
    assert all(location.startswith("s3://10x.files/samples/xenium/") for location in locations)


@pytest.mark.arraylake
def test_a_full_resolution_tile_costs_one_chunk(lung_session):
    """A read at level 0 must not fetch the whole level. The pyramid exists for this purpose."""
    import zarr

    root = zarr.open_group(lung_session.store, mode="r")
    finest = root["images"]["morphology_focus"]["s0"]
    assert finest.shape == (1, 17098, 51187)
    assert finest.chunks == (1, 1024, 1024)
    # The window is inside the notebook's own crop, where the tissue is.
    # About a quarter of this slide is background and reads as true zeros.
    # So an arbitrary tile cannot tell empty tissue from a reference that resolved to nothing.
    tile = np.asarray(finest[0, 8000:9024, 20000:21024])
    assert tile.shape == (1024, 1024)
    assert tile.dtype == np.uint16
    assert tile.max() > 0, "an all-zero tile here means the references resolved to nothing"
    assert np.count_nonzero(tile) == tile.size, "this window should be entirely tissue"
