"""The Braun first-trimester human brain atlas, as hosted on CZI's public S3.

Braun, Emelie et al. "Comprehensive cell atlas of the developing human brain."
Science (2023). doi:10.1126/science.adf1226
CELLxGENE collection 4d8fed08-2d6d-4692-b5ea-464f1d072077

The collection has 18 h5ads in two overlapping shardings and one whole-atlas file.
One sharding has 12 files by cell class. The other has 5 files by brain region.
This module exposes the cell-class sharding, because it is the finer of the two.

This module excludes ClassGlioblastOligo. Its 138,610 cells are exactly ClassGlioblast
(132,420) plus ClassOligo (6,190), so it would count those cells twice.

All files share one gene space: an identical var index of 58,226 entries.
Thus the per-class matrices have aligned columns.
"""

from dataclasses import dataclass

CENSUS_RELEASE = "2025-11-08"
BUCKET = "cellxgene-census-public-us-west-2"
REGION = "us-west-2"
PREFIX = f"s3://{BUCKET}/"

COLLECTION_ID = "4d8fed08-2d6d-4692-b5ea-464f1d072077"
CITATION = "Braun, Emelie et al., Science (2023), doi:10.1126/science.adf1226"
N_GENES = 58226


@dataclass(frozen=True)
class ClassFile:
    """One cell-class shard of the atlas."""

    cell_class: str
    dataset_id: str
    dataset_version_id: str
    n_bytes: int
    n_cells: int

    @property
    def group(self):
        return f"classes/{self.cell_class.removeprefix('Class').lower()}"

    @property
    def local_name(self):
        return f"{self.dataset_id}.h5ad"

    @property
    def census_url(self):
        """Anonymous S3, keyed on dataset_id. Region us-west-2."""
        return f"{PREFIX}cell-census/{CENSUS_RELEASE}/h5ads/{self.dataset_id}.h5ad"

    @property
    def https_url(self):
        """The same object over HTTPS, for the h5py ros3 driver."""
        return (
            f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
            f"cell-census/{CENSUS_RELEASE}/h5ads/{self.dataset_id}.h5ad"
        ).encode()

    @property
    def permalink(self):
        """CELLxGENE Discover permalink, keyed on dataset_version_id. CZI documents it
        as permanent. The citation of the dataset contains this URL."""
        return f"https://datasets.cellxgene.cziscience.com/{self.dataset_version_id}.h5ad"


# n_bytes is the size of the Census copy, which the virtual references address.
# The Discover CDN serves a rewritten copy that differs by a few kB.
# Byte offsets from one copy are thus not valid for the other.
CLASSES = [
    ClassFile("ClassPlacodes", "a24ecf77-c059-4dc5-8ca4-3b89d667b7f8",
              "50edf503-4e5b-4cfb-b0aa-1f5de43f1a4d", 19_262_034, 873),
    ClassFile("ClassNeuralCrest", "6701d782-76f2-40e6-82f1-495350dd9a63",
              "66f033db-2260-49c8-8f1a-eb63bb3d2d20", 19_575_498, 871),
    ClassFile("ClassErythrocyte", "8775a6c6-b960-43ae-9f76-45c4acda3621",
              "e7d61ad9-e039-47e7-a98c-73e8f992c5a2", 25_549_494, 8_959),
    ClassFile("ClassOligo", "91b2327d-e3f3-4f63-b446-20774d20fc33",
              "983f502d-016d-412d-b9fe-9949e5d2f116", 55_681_697, 6_190),
    ClassFile("ClassImmune", "ea7b95cf-1967-4431-9ee8-ec85ff793360",
              "bbeed4eb-3b42-43f0-a3ef-4e7ab37bd6f1", 70_543_337, 8_102),
    ClassFile("ClassFibroblast", "ea251de5-c764-4f7c-add0-8141b1061faf",
              "b9fbe872-910d-4e2b-9c2d-e5c9b25f1d87", 222_223_616, 19_161),
    ClassFile("ClassNeuronalIPC", "48c4a72a-bc2a-4d7c-9146-a7c2ab1d7d9f",
              "f7a29bcc-4de8-4c01-9d1d-eab9ac28f222", 839_248_749, 110_260),
    ClassFile("ClassGlioblast", "059022cf-885a-4ef8-944b-d9e5381aa1c6",
              "0713fbc5-51d9-441a-9ffc-36e306050492", 1_066_515_804, 132_420),
    ClassFile("ClassNeuroblast", "e59a4394-80db-42e4-85e6-8f0e59b81f42",
              "10d36870-cb38-45ab-bb97-583849b5c257", 1_997_695_096, 285_699),
    ClassFile("ClassNeuron", "1b52ee22-c71a-4a0f-a4d2-c1be36d0b82a",
              "489b22f6-61cd-4ec2-a48b-390bd0a00f80", 3_770_119_917, 561_754),
    ClassFile("ClassRadialGlia", "598100f7-01da-4de4-998a-05917fd6c446",
              "e9697a7a-f6fd-4011-994e-2bc116a0000e", 3_865_281_731, 519_908),
]

# Developmental order as stored in the files' categorical, earliest first.
DEVELOPMENT_STAGES = [
    "Carnegie stage 15",
    "Carnegie stage 16",
    "Carnegie stage 18",
    "Carnegie stage 20",
    "Carnegie stage 22",
    "9th week post-fertilization stage",
    "10th week post-fertilization stage",
    "11th week post-fertilization stage",
    "12th week post-fertilization stage",
    "13th week post-fertilization stage",
    "14th week post-fertilization stage",
    "15th week post-fertilization stage",
]


def registry():
    """An obstore registry that reads CZI's bucket without credentials."""
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import S3Store

    return ObjectStoreRegistry(
        {PREFIX: S3Store(BUCKET, region=REGION, skip_signature=True)}
    )


def virtual_matrix(url, registry):
    """X/{data,indices,indptr} as virtual references into the source h5ad.

    Only chunk metadata goes over the network. The matrix bytes stay in the CZI bucket.
    Each array gets its own dim name because h5ad has no HDF5 dimension scales.
    Without this, xarray names every axis phony_dim_0.
    That shared name then conflicts with the different lengths of data, indices and indptr.
    """
    import xarray as xr

    from virtualizarr.parsers import HDFParser

    manifest = HDFParser(group="X")(url, registry)
    return xr.Dataset(
        {n: xr.Variable((f"{n}_dim",), a) for n, a in manifest._group.arrays.items()},
        attrs=dict(manifest._group.metadata.attributes),
    )


def virtual_matrix_from_local(class_file, directory):
    """Build the manifest from a local copy, then repoint the references at S3.

    A build over S3 reads the HDF5 chunk B-tree through a Python file-object adapter.
    It does one network round-trip per read: ~250 refs/s against ~28,000 refs/s on local disk.
    At that rate, a remote build of the big shards takes too long.
    A manifest holds only (path, offset, length).
    Thus a local build with a rewritten path gives the same manifest.
    This is true only if the local copy and the referenced object have identical bytes.
    `check_local_copy` confirms that condition.
    """
    import os

    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import LocalStore

    path = os.path.abspath(os.path.join(directory, class_file.local_name))
    ds = virtual_matrix("file://" + path, ObjectStoreRegistry({"file://": LocalStore()}))
    return ds.vz.rename_paths(lambda _: class_file.census_url)


def check_local_copy(class_file, directory):
    """Confirm the local copy is the same bytes as the object we will reference.

    The sizes must match. Census objects under ~64 MB are single-part uploads.
    Their ETag is the md5, so this function does a full content check on them.
    The larger objects are multipart uploads, with up to 58 parts.
    Their ETag is a digest of the part digests, not of the content.
    For them, the size is the only low-cost check. `spot_check_refs` does the remaining check.
    """
    import hashlib
    import os
    import urllib.request

    path = os.path.join(directory, class_file.local_name)
    size = os.path.getsize(path)
    if size != class_file.n_bytes:
        raise ValueError(f"{class_file.local_name}: {size} bytes locally, "
                         f"expected {class_file.n_bytes}")

    request = urllib.request.Request(class_file.https_url.decode(), method="HEAD")
    etag = urllib.request.urlopen(request).headers["ETag"].strip('"')
    if "-" in etag:
        return f"size ok ({size:,} bytes); etag multipart ({etag.split('-')[1]} parts)"

    with open(path, "rb") as f:
        md5 = hashlib.file_digest(f, "md5").hexdigest()
    if md5 != etag:
        raise ValueError(f"{class_file.local_name}: md5 {md5} != etag {etag}")
    return f"size and md5 both match ({size:,} bytes)"


def spot_check_refs(ds, class_file, directory, n=6, seed=0):
    """Fetch a sample of the manifest's byte ranges from S3 and compare them locally.

    This function validates a locally built manifest against the remote object.
    It proves that the recorded offsets address the same bytes on both.
    The cost is low: a few range requests, for any file size.
    """
    import os
    import random

    import obstore
    from obstore.store import S3Store

    store = S3Store(BUCKET, region=REGION, skip_signature=True)
    key = class_file.census_url.removeprefix(PREFIX)
    refs = [r for v in ds.variables.values() for r in v.data.manifest.dict().values()]
    sample = random.Random(seed).sample(refs, min(n, len(refs)))

    path = os.path.join(directory, class_file.local_name)
    with open(path, "rb") as f:
        for ref in sample:
            remote = bytes(
                obstore.get_range(store, key, start=ref["offset"], length=ref["length"])
            )
            f.seek(ref["offset"])
            if remote != f.read(ref["length"]):
                raise ValueError(
                    f"{class_file.local_name}: bytes differ at offset {ref['offset']}"
                )
    return f"{len(sample)} sampled byte ranges identical on S3 and locally"


def census_h5ad_url(dataset_id, scheme="s3"):
    """Return the URL where the Census publishes the h5ad of any CELLxGENE dataset.

    The bucket constants above apply to all of the Census, not only to this atlas.
    This function uses them, so it is in this module.
    """
    key = f"cell-census/{CENSUS_RELEASE}/h5ads/{dataset_id}.h5ad"
    if scheme == "s3":
        return f"{PREFIX}{key}"
    return f"https://{BUCKET}.s3.{REGION}.amazonaws.com/{key}"


def read_elements_at(https_url, paths, local=None):
    """Read named AnnData elements out of an h5ad, keyed by their path within it.

    The function reads a local copy if the caller gives one and it exists.
    Otherwise it uses the h5py ros3 driver, which does range requests in C.
    That driver is much faster than a Python file-like adapter, but takes ~30s on a large file.

    ros3 parses an S3 object key from the URL.
    Thus it cannot read a CloudFront-style host such as `datasets.cellxgene.cziscience.com`.
    For those hosts, the function uses fsspec.
    fsspec is slower, but it reads from any HTTP server that supports range requests.
    """
    import os

    import h5py
    from anndata.io import read_elem

    if local and os.path.exists(local):
        with h5py.File(local, "r") as h:
            return {path: read_elem(h[path]) for path in paths}

    url = https_url.decode() if isinstance(https_url, bytes) else https_url
    try:
        with h5py.File(url, "r", driver="ros3",
                       aws_region=REGION.encode()) as h:
            return {path: read_elem(h[path]) for path in paths}
    except OSError:
        import fsspec

        filesystem = fsspec.filesystem("http", block_size=8 * 1024 * 1024)
        with filesystem.open(url, "rb") as handle, h5py.File(handle, "r") as h:
            return {path: read_elem(h[path]) for path in paths}


def read_elements(class_file, paths, directory=None):
    """`read_elements_at`, for one of this atlas's shards."""
    import os

    local = directory and os.path.join(directory, class_file.local_name)
    return read_elements_at(class_file.https_url, paths, local)


def read_obs(class_file, directory=None, columns=("development_stage", "Age")):
    """Read obs columns out of the h5ad, from a local copy when one is available.

    VirtualiZarr cannot virtualize these columns.
    AnnData stores categorical `categories` and the dataframe index as HDF5 variable-length strings.
    numpy reads these as the object dtype.
    Zarr v3 rejects object on purpose, because it is ambiguous (zarr-python#3077).
    Zarr v3 holds variable-length strings with the dtype that it writes as "string" on disk.
    But no automatic map exists from the HDF5 type to a concrete Zarr type.
    Thus the caller reads these columns eagerly and writes them as native chunks.
    """
    elements = read_elements(class_file, [f"obs/{name}" for name in columns], directory)
    return {name: elements[f"obs/{name}"] for name in columns}


def directory_size(path):
    """Total bytes of every file under a directory."""
    import os

    return sum(os.path.getsize(os.path.join(d, f))
               for d, _, fs in os.walk(path) for f in fs)
