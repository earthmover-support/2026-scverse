"""Elements whose bytes stay in the source file: a table's `X`, and an image's pixels.

This module does what SpatialData has no plan for. It needs no upstream change.
It uses coincidences between the formats, not an API.

**The table.** An `.h5ad` stores `X` as CSR: `X/data`, `X/indices`, `X/indptr`. AnnData-in-Zarr
stores `X` as a group with the same three array names and an `encoding-type` of `csr_matrix`.
Thus the Zarr arrays can be virtual chunk references into the chunks of the HDF5 file.
Unmodified `anndata.io.read_elem` reads the result. The result is a standard AnnData element,
not a private encoding. We measured a public CELLxGENE Visium h5ad: 4,992 x 32,397 with
8,990,335 stored values. It gave 1,540 references. The Icechunk repository was 0.08 MB and held
no expression data.

**The image.** A JPEG2000-tiled OME-TIFF is already a Zarr chunk grid. Its pyramid uses
1024x1024 tiles, so each tile can be one chunk reference. `virtual-tiff` supplies both parts.
It maps the tiles to references. It publishes the codec that decodes them through the
`zarr.codecs` entry points. Its references point at each tile as the file stores it. The decoder
returns `(bands, y, x)`. `Image2DModel` requires that axis order.

This module copies nothing for an image, not even a tail. A chunk is a whole codestream, not a
fixed slice of the file. Thus the padding problem of `_reference.reference_file` does not occur.

One limit remains. It is narrower than "cannot transform bytes". A reference gives bytes and
cannot re-encode them. An array keeps the dtype and compression of the source. Thus this module
cannot recompress or retype anything. But it can present the bytes differently. A Zarr codec is
part of the read pipeline, and a transpose is a codec. Thus channel-last sources become
`(c, y, x)` elements, and the stored bytes do not change. This applies to the interleaved RGB H&E
from 10x and to the images inside an h5ad. See `images_in_h5ad_are_channel_last`.
"""

from __future__ import annotations

import json

import icechunk
import zarr

CSR_MEMBERS = ("data", "indices", "indptr")


def virtual_table(
    root: zarr.Group,
    name: str,
    session,
    url: str,
    registry,
    *,
    obs=None,
    var=None,
    obsm=None,
    group: str = "X",
    layout: str = "anndata",
    handle=None,
    annotates: str | None = None,
    last_updated_at=None,
) -> zarr.Group:
    """Write an AnnData table at `root[name]` whose `X` references `url`.

    This function writes `obs` and `var` natively, for two reasons. They are small. An h5ad
    stores its dataframes as variable-length strings, and Zarr v3 does not virtualize those.
    All other arrays are references.

    This function writes `obsm` natively with `obs` and `var`. Squidpy reads cell coordinates
    from `obsm["spatial"]`. Squidpy cannot compute spatial statistics on a table without it,
    even when the counts are complete.

    `layout` tells how to recognise the `X` of the source. `"anndata"` requires an
    `encoding-type` of `csr_matrix`, which an `.h5ad` carries. `"tenx"` accepts the 10x file
    `cell_feature_matrix.h5`. That file stores the same three arrays under `matrix/` with no
    encoding metadata. Thus the caller must name this layout, and this function does not infer
    it. `../../findings.md` records the decision not to infer it. With that layout, pass `handle`.
    This function then reads the cell ids and gene names from the file. They are fixed-length
    strings, unlike the strings of an h5ad.

    Returns the table group. The caller commits the session.
    """
    from anndata import AnnData
    from anndata.io import write_elem

    _check_element_name(name)
    if layout not in ("anndata", "tenx"):
        raise ValueError(f"unknown layout {layout!r}; expected 'anndata' or 'tenx'")

    if layout == "tenx":
        source, n_obs, n_vars = _tenx_source(url, registry, group)
        if handle is not None and (obs is None or var is None):
            obs, var = _tenx_frames(handle, group)
    else:
        source = _source_group(url, registry, group)
        n_obs, n_vars = (int(s) for s in dict(source.metadata.attributes)["shape"])

    if annotates is not None:
        import pandas as pd

        if obs is None:
            raise ValueError("`annotates` needs an `obs` whose index identifies the instances")
        # A table must name the element its rows annotate before a reader can colour it by a gene.
        # The instance key is the row index. For a 10x matrix, the row index is the cell id.
        # A shapes element from the 10x vertex table uses the same cell id as its index.
        obs = obs.copy()
        obs["region"] = pd.Categorical([annotates] * len(obs))
        obs["cell_id"] = obs.index.astype(str)

    skeleton = AnnData(
        obs=obs if obs is not None else {"index": [str(i) for i in range(n_obs)]},
        var=var if var is not None else {"index": [str(j) for j in range(n_vars)]},
        obsm=obsm,
    )
    if annotates is not None:
        # SpatialData reads these keys from `adata.uns`, not from the group attributes.
        # If a table carries them elsewhere, SpatialData reports "no table keys found".
        # It reports this when a caller asks what the table annotates.
        skeleton.uns["spatialdata_attrs"] = {
            "region": annotates, "region_key": "region", "instance_key": "cell_id",
        }

    write_elem(root, name, skeleton)
    table = root[name]
    _declare_table(table, skeleton)

    # `write_elem` wrote an empty X. This code replaces it with references.
    if "X" in table:
        del table["X"]
    x_group = table.create_group("X")
    x_group.attrs["encoding-type"] = "csr_matrix"
    x_group.attrs["encoding-version"] = "0.1.0"
    x_group.attrs["shape"] = [n_obs, n_vars]
    x_group.attrs["virtual_source"] = f"{url}/{group}"

    store = getattr(session, "store", session)
    for member in CSR_MEMBERS:
        _virtual_array(x_group, member, source.arrays[member], store,
                       last_updated_at=last_updated_at)
    return table


def write_csc_layer(table: zarr.Group) -> zarr.Group:
    """Write `X` as a CSC matrix at `layers/X_csc`.

    The layer answers a query for one gene from one column. This function does not change `X`.
    Thus a table whose `X` is references keeps them. Returns the layer.
    """
    import scipy.sparse
    from anndata.io import read_elem, write_elem

    csc = scipy.sparse.csc_matrix(read_elem(table["X"]))
    if "layers" not in table:
        layers = table.create_group("layers")
        layers.attrs.update({"encoding-type": "dict", "encoding-version": "0.1.0"})
    write_elem(table["layers"], "X_csc", csc)
    return table["layers"]["X_csc"]


def reference_count(url: str, registry, group: str = "X") -> int:
    """Return the number of chunk references an `X` needs. This function writes nothing."""
    source = _source_group(url, registry, group)
    return sum(len(list(source.arrays[m].manifest.values())) for m in CSR_MEMBERS)


def virtual_image(
    root: zarr.Group,
    name: str,
    session,
    *,
    location: str,
    registry,
    plane: int | None = None,
    transform=None,
    channel_names: list[str] | None = None,
    last_updated_at=None,
) -> zarr.Group:
    """Write a SpatialData image element at `root["images"][name]` that references an OME-TIFF.

    `virtual-tiff` reads the file. It maps each IFD and the pyramid levels that its tag 330
    points at. It keeps the codec chain that the file uses: JPEG 2000, deflate, and the
    interleave permutation for a chunky RGB. `virtual-tiff` parses `location`, and the
    references contain `location`. `registry` resolves it. Thus `location` can be an `s3://`
    form that Icechunk can authorize. Reads then go to the store that `registry` maps that
    prefix to.

    Each level becomes one array, named `s0`, `s1`, ... as SpatialData names them. Returns the
    element group. The caller commits the session.

    `plane` selects one plane of a focal stack. A Xenium `morphology.ome.tif` is a focal stack.
    Its planes are separate top-level IFDs, and each plane has its own pyramid. Such a source
    requires `plane`, for two reasons. A true 3-D element needs `(z, y, x)` axis handling, and
    this function does not have it. A label of planes as channels is worse than a refusal.

    `transform` is the element's own transformation. The default is identity. Pass a
    `spatialdata.transformations` object when the pixel grid is not the world grid.
    """
    _check_element_name(name)
    levels = _pyramid(location, registry, plane)

    _declare_container(root)
    element = root.require_group("images").require_group(name)
    store = getattr(session, "store", session)
    shapes = []
    for order, array in enumerate(levels):
        spatial = tuple(int(s) for s in array.shape[-2:])
        _virtual_array(element, f"s{order}", array, store, last_updated_at=last_updated_at,
                       channel_axis=len(array.shape) == 2)
        shapes.append((order, spatial))

    element.attrs["ome"] = _multiscales(name, shapes, transform, channel_names=channel_names)
    element.attrs["spatialdata_attrs"] = {"version": "0.3"}
    element.attrs["virtual_source"] = location
    return element


def _pyramid(location: str, registry, plane: int | None = None) -> list:
    """Return the pyramid levels of an OME-TIFF as manifest arrays, finest first.

    `plane` selects one plane of a focal stack. The planes of a stack are separate top-level IFDs.
    This function requires `plane` for a stack and rejects it for a single-IFD file.
    """
    from virtual_tiff import VirtualTIFF

    ifds = VirtualTIFF()(location, registry)._group.arrays
    if plane is None and len(ifds) > 1:
        raise ValueError(
            f"{location} has {len(ifds)} top-level IFDs, which for a focal stack are planes; pass "
            "`plane` to reference one of them as a 2-D image. A 3-D element would need (z, y, x) "
            "axis handling this does not have."
        )
    if plane is not None and len(ifds) == 1:
        raise ValueError(
            f"{location} has one top-level IFD, so it is not a focal stack and `plane` does not "
            "apply. Its reduced levels, if any, are SubIFDs of that one."
        )
    if plane is not None and plane >= len(ifds):
        raise ValueError(f"{location} has {len(ifds)} IFDs, so plane {plane} does not exist")

    levels = VirtualTIFF(ifd=plane or 0, subifds=True)(location, registry)._group.arrays
    if not levels:
        raise ValueError(f"{location} has no pyramid levels")
    return [levels[key] for key in sorted(levels, key=_level_order)]


def _level_order(key: str) -> tuple[int, int]:
    """Sort `0` before `0.0` before `0.1`: first the IFD, then the SubIFD level it points at."""
    ifd, _, level = key.partition(".")
    return int(ifd), int(level) if level else -1


def images_in_h5ad_are_channel_last(url: str, registry,
                                    image_group: str) -> tuple[bool, str]:
    """Tell whether the images of a Visium h5ad are channel-last, and what that costs.

    Returns `(channel_last, description)`. The images are `(y, x, c)`. `Image2DModel` requires
    `("c", "y", "x")`. The bytes do not need a transpose. The Zarr v3 `transpose` codec permutes
    axes in the read pipeline. Thus the element is `(c, y, x)`, and the stored chunks stay
    exactly as AnnData wrote them. We measured a public Visium h5ad. Its `hires` image is 384
    references. It reads back identical to the stored image transposed.

    This check is a function and not a comment, for two reasons. The layout claim stays
    checkable. The function fails with a clear message if a future AnnData writes the images
    channel-first.
    """
    from virtualizarr.parsers import HDFParser

    source = HDFParser(group=image_group)(url, registry)._group
    reasons = []
    for name, array in source.arrays.items():
        shape = tuple(int(s) for s in array.shape)
        if len(shape) != 3:
            continue
        channel_last = shape[2] < shape[0] and shape[2] < shape[1]
        if channel_last:
            reasons.append(f"{name} is {shape}, channel-last")
    if not reasons:
        return False, "no channel-last 3-D image found; the premise no longer holds"
    return True, (
        f"{'; '.join(reasons)}. Image2DModel requires ('c', 'y', 'x'). A transpose codec "
        "supplies that order and does not change the stored bytes"
    )


# --- internals -------------------------------------------------------------


def _declare_table(table: zarr.Group, adata) -> None:
    """Set the group attrs that `spatialdata._io.write_table` sets. Its reader requires them."""
    from spatialdata._io.format import CurrentTablesFormat
    from spatialdata.models import TableModel

    keys = adata.uns.get(TableModel.ATTRS_KEY, {})
    table.attrs.update({
        "spatialdata-encoding-type": "ngff:regions_table",
        "region": keys.get("region"),
        "region_key": keys.get("region_key"),
        "instance_key": keys.get("instance_key"),
        "version": CurrentTablesFormat().spatialdata_format_version,
    })


def _declare_container(root: zarr.Group) -> None:
    """Write the container metadata that `SpatialData.read` requires, once.

    This function keeps the other root attrs. Upstream SpatialData reads a root without
    `spatialdata_attrs` as format 0.1. It then fails on v3 metadata.
    """
    if "spatialdata_attrs" in root.attrs:
        return
    from spatialdata._io.format import CurrentSpatialDataContainerFormat

    container = CurrentSpatialDataContainerFormat()
    root.attrs["spatialdata_attrs"] = {
        "version": container.spatialdata_format_version
    } | container.attrs_to_dict()


def _check_element_name(name: str) -> None:
    """Reject a name that SpatialData would reject, at the call that supplies it.

    A write with an invalid name succeeds. The failure occurs much later, when `read` reaches
    `SpatialData(...)`. That point is far from the responsible code. Upstream SpatialData owns
    the rules, so this docstring does not repeat them.
    """
    from spatialdata._core.validation import check_valid_name

    check_valid_name(name)


def _multiscales(name: str, levels: list[tuple[int, tuple[int, ...]]], transform=None, *,
                 dims: tuple[str, ...] = ("c", "y", "x"),
                 element_type: str = "images",
                 channel_names: list[str] | None = None) -> dict:
    """Return OME metadata in the form that the SpatialData `write_image` produces.

    This function writes the metadata by hand. `write_image` writes pixels, and there are no
    pixels to write. This function measures the per-level scale from the shapes. It does not
    assume a power of two. An OME-TIFF pyramid halves with rounding. Thus level 4 of a
    25,778-row image is 1,611, not 1,611.125. The half-pixel translation that goes with a scale
    is a SpatialData convention.

    `dims` carries the axis names, because labels are `(y, x)` and an image is `(c, y, x)`.
    A labels element has no channel axis. If a labels element has one, `Labels2DModel` rejects it.
    """
    axes = [{"name": axis, "type": "channel" if axis == "c" else "space"} for axis in dims]
    spatial = [{**axis, "unit": "unit"} if axis["type"] == "space" else axis for axis in axes]
    leading = len(dims) - 2          # 1 for (c, y, x), 0 for (y, x)

    _, finest = levels[0]
    datasets = []
    for level, shape in levels:
        if len(shape) != 2:
            raise ValueError(
                f"level {level} has shape {shape}; levels carry spatial (y, x) shapes, or the "
                "per-level scale gains an entry per extra axis and every reader mis-scales"
            )
        ratios = [full / current for full, current in zip(finest, shape)]
        scale = [1.0] * leading + ratios
        datasets.append({
            "path": f"s{level}",
            "coordinateTransformations": [
                {"type": "scale", "scale": scale},
                {"type": "translation",
                 "translation": [0.0] * leading + [(factor - 1) / 2 for factor in ratios]},
            ],
        })

    if transform is None:
        from spatialdata.transformations import Identity

        transform = Identity()
    # SpatialData's reader asserts that the input and output coordinate systems are present.
    # Thus a bare {"type": "scale"} fails on read, not on write.
    # This code gets the output axes from the transformation. It does not assume they equal the
    # input. A MapAxis or a non-square Affine changes them. A forced match serialises a transform
    # with a different meaning, and nothing fails.
    from spatialdata.transformations.transformations import _get_current_output_axes

    element_transform = transform.to_ngff(
        input_axes=dims,
        output_axes=tuple(_get_current_output_axes(transform, dims)),
        output_coordinate_system_name="global",
    ).to_dict()

    metadata = {
        "version": "0.5-dev-spatialdata",
        "multiscales": [{
            "name": f"/{element_type}/{name}",
            "axes": axes,
            "datasets": datasets,
            "coordinateTransformations": [element_transform],
        }],
    }
    if "c" in dims:
        # `get_channel_names` reads these labels. A channel name must be here for it to return it.
        labels = channel_names if channel_names is not None else [0]
        metadata["omero"] = {"channels": [{"label": label} for label in labels]}
    return metadata


def _tenx_source(url: str, registry, group: str):
    """Parse the 10x `cell_feature_matrix.h5`: the same three arrays, with no metadata for them.

    Returns the parsed group and the matrix shape as `(cells, genes)`.

    The important check is on `indptr`. 10x labels the matrix `[n_features, n_barcodes]` and
    calls it CSC. That label suggests a transpose into an `X` of `(cells, genes)`. The bytes do
    not need a transpose. `indptr` indexes barcodes, so the same bytes are already CSR over cells.
    But 10x also ships the same data as `cell_feature_matrix.zarr.zip`, where `indptr` indexes
    genes. That file needs a transpose. A codec cannot do a CSR transpose as an axis permutation.
    The transpose gives a different sparse structure, so a rebuild is necessary. The file names
    do not show the orientation. Thus this function verifies the orientation and does not assume it.
    """
    from virtualizarr.parsers import HDFParser

    store = HDFParser(group=group)(url, registry)
    source = store._group
    missing = [member for member in CSR_MEMBERS if member not in source.arrays]
    if missing:
        raise ValueError(f"{url}/{group} has no {', '.join(missing)}; not a 10x matrix layout")

    n_genes, n_cells = (int(s) for s in zarr.open_group(store, mode="r")["shape"][:])
    entries = int(source.arrays["indptr"].shape[0])
    if entries != n_cells + 1:
        raise ValueError(
            f"{url}/{group} has an indptr of {entries:,} against {n_cells:,} cells and "
            f"{n_genes:,} genes, so it indexes genes rather than cells. That is CSR over genes; "
            "making it an X of (cells, genes) needs a rebuild, which a byte range cannot do."
        )
    return source, n_cells, n_genes


def _tenx_frames(handle, group: str):
    """Return the cell ids and gene names from the file. This function does not invent them.

    A 10x matrix stores these as `|S` fixed-length strings. An h5ad writes variable-length
    strings. Thus these labels can be virtual, unlike the labels of an h5ad. This function still
    writes them natively, for two reasons. A few MB of labels is not the purpose of this module.
    AnnData needs them as a real index.
    """
    import h5py
    import pandas as pd

    with h5py.File(handle, "r") as source:
        matrix = source[group]
        barcodes = [value.decode() for value in matrix["barcodes"][:]]
        features = matrix["features"]
        names = [value.decode() for value in features["name"][:]]
        ids = [value.decode() for value in features["id"][:]]
        kinds = [value.decode() for value in features["feature_type"][:]]

    # Use real indexes, not columns called "index". AnnData reads the "index" key of a mapping as
    # a column and leaves the names as 0..n. A gene lookup then fails.
    return (pd.DataFrame(index=pd.Index(barcodes)),
            pd.DataFrame({"gene_id": ids, "feature_type": kinds},
                         index=pd.Index(names, name="gene")))


def _source_group(url: str, registry, group: str):
    from virtualizarr.parsers import HDFParser

    source = HDFParser(group=group)(url, registry)._group
    encoding = dict(source.metadata.attributes).get("encoding-type")
    if encoding != "csr_matrix":
        raise ValueError(
            f"{url}/{group} is {encoding!r}; only 'csr_matrix' shares a layout with "
            "AnnData-in-Zarr. A CSC matrix would need transposing, which a byte range cannot do."
        )
    return source


def _virtual_array(group: zarr.Group, name: str, manifest_array, store, *,
                   last_updated_at, channel_axis: bool = False,
                   dimension_names: tuple[str, ...] | None = None) -> None:
    """Recreate a parsed array as references, and keep the codec pipeline of the source.

    `channel_axis` prepends a length-1 axis. A single-sample image needs it to show the
    `(c, y, x)` form that a SpatialData element requires. The stored bytes do not change. Only
    the shape in the chunk grid description changes, and the chunk keys get a leading zero.

    `dimension_names` labels the axes in the array metadata. xarray needs these labels to open
    the array. A SpatialData element leaves them unset. Its readers take the axes from the OME
    attributes.
    """
    from zarr.abc.codec import ArrayArrayCodec, ArrayBytesCodec

    metadata = manifest_array.metadata.to_dict()
    # Split the chain by the role of each codec, not by position. A source can put an
    # array-to-array step first, for example the transpose of an interleaved TIFF.
    # A split by position takes that step as the serializer.
    filters, serializer, compressors = [], None, []
    for codec, form in zip(manifest_array.metadata.codecs, metadata["codecs"]):
        if isinstance(codec, ArrayArrayCodec):
            filters.append(form)
        elif isinstance(codec, ArrayBytesCodec):
            serializer = form
        else:
            compressors.append(form)
    if serializer is None:
        raise ValueError(f"{name} has no array-to-bytes codec; its chunks cannot be decoded")

    leading = (1,) if channel_axis else ()
    chunks = tuple(metadata["chunk_grid"]["configuration"]["chunk_shape"])
    array = group.create_array(
        name, shape=leading + tuple(manifest_array.shape), dtype=manifest_array.dtype,
        chunks=leading + chunks,
        serializer=serializer, compressors=compressors, filters=filters,
        fill_value=metadata["fill_value"],
        dimension_names=dimension_names,
    )
    specs = [
        icechunk.VirtualChunkSpec(
            index=(0,) * len(leading) + tuple(int(i) for i in key.split(".")),
            location=entry["path"], offset=int(entry["offset"]),
            length=int(entry["length"]), last_updated_at_checksum=last_updated_at,
        )
        for key, entry in manifest_array.manifest.items()
    ]
    rejected = store.set_virtual_refs(array.path, specs, validate_containers=True)
    if rejected:
        raise ValueError(
            f"{len(rejected)} of {len(specs)} references to {name} fall outside every "
            f"configured virtual chunk container; the repository needs one covering "
            f"{specs[0].location}"
        )
