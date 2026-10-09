"""Register a published file's bytes as Icechunk virtual chunk references.

This module is the only part of the file-as-array encoding that needs Icechunk.
`_filesystem` reads and writes convention arrays against any Zarr group. This module fills
one with references instead of copies. The module boundary matches the package boundary
that the pieces would have upstream. The convention and the filesystem are store-agnostic.
This module is not.
"""

from __future__ import annotations

import numpy as np
import zarr

from ._filesystem import CHUNK, declare_file


def reference_file(group: zarr.Group, path: str, url: str, size: int, session, *,
                   chunk: int = CHUNK, fetch_tail=None) -> int:
    """Register `url` as a file at `path` under `group`, and return the reference count.

    The function references the file and copies only the tail.
    A `uint8` array has no codec, so a chunk *is* a byte range. The mapping from file
    offsets to chunk indices is thus exact. That property makes any format referenceable
    this way. A codec-bearing array, by contrast, needs the source's own encoding to match.

    Zarr chunks have a fixed size. If the file length is not a multiple of `chunk`, the final
    chunk needs padding. A byte range cannot pad. So the function copies the tail: `n - 1`
    references plus at most `chunk` bytes of copy.
    """
    import icechunk

    key = path.lstrip("/")
    parent, _, name = key.rpartition("/")
    target = group.require_group(parent) if parent else group
    if name in target:
        del target[name]
    array = target.create_array(name, shape=(size,), dtype=np.uint8,
                                chunks=(chunk,), compressors=None)
    declare_file(array, name)
    array.attrs["file:virtual_source"] = url

    whole = -(-size // chunk)
    specs = [
        icechunk.VirtualChunkSpec(index=(i,), location=url, offset=i * chunk,
                                  length=chunk)
        for i in range(whole - 1)
    ]
    store = getattr(session, "store", session)
    if specs:
        rejected = store.set_virtual_refs(array.path, specs, validate_containers=True)
        if rejected:
            raise ValueError(
                f"{len(rejected)} of {len(specs)} references to {name} fall outside every "
                f"configured virtual chunk container; one covering {url} is needed"
            )
    start = (whole - 1) * chunk
    array[start:] = np.frombuffer(
        (fetch_tail or _http_range)(url, start, size - 1), dtype=np.uint8
    )
    return len(specs)


def _http_range(url: str, start: int, end: int) -> bytes:
    import requests

    return requests.get(url, headers={"Range": f"bytes={start}-{end}"}).content
