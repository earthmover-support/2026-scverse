"""A virtual reference cannot read a published object that has a FULL_OBJECT checksum.

Run: pixi run -e spatial python icechunk-SpatialData/upstream/verify_full_object_checksum.py

This verifier uses nothing specific to this project. It uses two public files and two virtual
chunk references. One of the references is never readable. A response header is the only
difference between them.

An upload can give an S3 object a full-object checksum. GET responses for that object then carry
`x-amz-checksum-crc64nvme` together with `x-amz-checksum-type: FULL_OBJECT`. S3 also returns those
headers on a **ranged** `206` response. There, the checksum still describes the whole object.
Thus a validation of the partial body against it fails every time, deterministically. A virtual
chunk reference is by definition a ranged read.

One comparison isolates the cause. The *same object, same byte range, same repository shape* reads
correctly through Icechunk's plain HTTP store. It fails through Icechunk's S3-compatible store.
Only the S3-compatible store parses `x-amz-checksum-*`. Thus the cause is not the CDN, the range
or the reference. The cause is checksum validation on a partial response.

The comparison below also includes an object with no such header. That object shows that the S3
path otherwise works correctly.
"""

from __future__ import annotations

import base64
import warnings

warnings.simplefilter("ignore")

import icechunk
import numpy as np
import requests
import zarr

HOST = "https://cf.10xgenomics.com/"
SAMPLE = ("samples/xenium/2.0.0/Xenium_V1_humanLung_Cancer_FFPE/"
          "Xenium_V1_humanLung_Cancer_FFPE_")
#: Every object that the bundle publishes, not a chosen pair. A list of two objects let this
#: verifier report "no longer reproduces" while the finding held on a third. The header moved
#: from `transcripts.parquet` to `transcripts.zarr.zip`, and the script did not check that file.
BUNDLE = (
    "morphology.ome.tif", "he_image.ome.tif", "cells.zarr.zip", "transcripts.zarr.zip",
    "cell_feature_matrix.h5", "cells.parquet", "cell_boundaries.parquet",
    "nucleus_boundaries.parquet", "transcripts.parquet",
)
CASES = {name: SAMPLE + name for name in BUNDLE}
CHUNK = 1 << 22


def describe(url: str) -> dict:
    headers = requests.head(url).headers
    checksum = headers.get("x-amz-checksum-crc64nvme")
    return {
        "size": int(headers["Content-Length"]),
        "checksum_type": headers.get("x-amz-checksum-type", "none"),
        "crc64nvme": base64.b64decode(checksum).hex() if checksum else None,
    }


# The S3-compatible client reads a CDN-published object when the reference must be an `s3://` URL.
# Arraylake's virtual chunk containers require an `s3://` URL.
CLIENTS = {
    "http": (HOST, lambda: icechunk.http_store(), lambda: icechunk.credentials.HttpAccess),
    "s3-compatible": (
        "s3://samples/",
        lambda: icechunk.s3_store(endpoint_url=HOST.rstrip("/"), s3_compatible=True,
                                  force_path_style=True, anonymous=True),
        lambda: icechunk.credentials.Credentials.S3(icechunk.s3_anonymous_credentials()),
    ),
}


def referencing_repo(client: str) -> tuple[icechunk.Repository, str]:
    prefix, store, credentials = CLIENTS[client]
    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(icechunk.VirtualChunkContainer(prefix, store()))
    repo = icechunk.Repository.create(
        icechunk.in_memory_storage(), config=config,
        authorize_virtual_chunk_access={prefix: credentials()},
    )
    return repo, prefix


def main() -> None:
    print(f"zarr {zarr.__version__}, icechunk {icechunk.__version__}\n")

    facts = {name: describe(HOST + key) for name, key in CASES.items()}
    for name, fact in facts.items():
        print(f"{name}")
        print(f"  {fact['size'] / 1e6:>8.1f} MB  checksum-type={fact['checksum_type']}"
              f"{'  crc64nvme=' + fact['crc64nvme'] if fact['crc64nvme'] else ''}")

    print("\na plain ranged GET of the first chunk, for each:")
    for name, key in CASES.items():
        response = requests.get(HOST + key, headers={"Range": f"bytes=0-{CHUNK - 1}"})
        print(f"  {name:<24} HTTP {response.status_code}, {len(response.content):,} bytes")

    print("\nthe same range as a virtual chunk reference, per client:")
    outcomes = {}
    for client in CLIENTS:
        for name, key in CASES.items():
            repo, prefix = referencing_repo(client)
            session = repo.writable_session("main")
            # Size the array per object. Some files in the bundle are smaller than CHUNK.
            # A request past the end of an object gets a 416, which has no relation to checksums.
            length = min(CHUNK, facts[name]["size"])
            zarr.create_group(store=session.store, zarr_format=3).create_array(
                "bytes", shape=(length,), dtype=np.uint8, chunks=(length,), compressors=None,
            )
            # The bucket *is* the first path segment, so it must not appear twice in the key.
            location = (prefix + key.removeprefix("samples/") if prefix.startswith("s3://")
                        else HOST + key)
            session.store.set_virtual_ref("bytes/c/0", location, offset=0, length=length)
            session.commit("one reference")
            try:
                got = np.asarray(zarr.open_group(
                    repo.readonly_session("main").store, mode="r")["bytes"][:])
                outcomes[client, name] = f"read {got.nbytes:,} bytes"
            except Exception as error:
                outcomes[client, name] = f"{type(error).__name__}: {str(error).splitlines()[0]}"
            print(f"  {client:<15} {name:<24} {outcomes[client, name]}")

    checksummed = [n for n, f in facts.items() if f["checksum_type"] == "FULL_OBJECT"]
    plain = [n for n, f in facts.items() if f["checksum_type"] == "none"]
    assert checksummed and plain, "both cases are needed for the comparison to mean anything"

    print(f"\n  {len(checksummed)} of {len(CASES)} objects carry the header: {checksummed}")

    # Each object without the header must read on every client.
    # Each checksummed object must fail on the S3 client, and only there.
    for (client, name), outcome in outcomes.items():
        if client == "s3-compatible" and name in checksummed:
            continue
        assert outcome.startswith("read "), f"{client}/{name} failed unexpectedly: {outcome}"

    survivors = [n for n in checksummed if outcomes["s3-compatible", n].startswith("read ")]
    if survivors == checksummed:
        print("\nVERDICT: every checksummed object now reads on the S3 client. Fixed; delete this.")
        return
    assert not survivors, f"some checksummed objects read and some do not: {survivors}"

    for name in checksummed:
        failure = outcomes["s3-compatible", name]
        assert "checksum mismatch" in failure, f"{name} failed, but not on the checksum: {failure}"
        expected = facts[name]["crc64nvme"]
        assert expected in failure, f"the checksum reported is not {name}'s own {expected}"
        print(f"\n  {name} reads through the HTTP client and not the S3 one, and the checksum it")
        print(f"  expected, {expected}, is exactly the whole-object value from its header, so a")
        print("  partial body could never match it.")

    print("\nVERDICT: an S3 client applies a FULL_OBJECT checksum to partial responses, so any\n"
          "         virtual reference into such an object is unreadable")


if __name__ == "__main__":
    main()
