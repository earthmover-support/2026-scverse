"""SpatialData on Icechunk: a prototype to inform an upstream conversation.

Do not depend on this package. The
[2nd SpatialData Hackathon report](https://index.biohackrxiv.org/2026/06/07/s6bph.html) proposes an
Icechunk integration. Nobody had built code to test that design, so this prototype exists.

With PR #1107 and the patch series in `../upstream/`, `SpatialData.write` and `SpatialData.read`
take an Icechunk store directly. Geometry needs one addition: `parquet_in_store`. It stores each
Parquet file as a `uint8` Zarr array at the same path. SpatialData's own writers and readers do the
I/O. See `_filesystem`.

This package also holds the parts that SpatialData has no plan for:

* `virtual_table`: a table whose `X` holds byte-range references into a published `.h5ad` or 10x
  matrix. Unmodified `anndata` reads it back. See `_virtual`.
* `virtual_image`: an OME-TIFF as an image element. Its chunks are byte ranges in the published
  file. A reader needs the Zarr v3 codec that `virtual-tiff` publishes.
* `reference_file`: a `uint8` array that holds a whole published file by reference.
* `write_csc_layer`: writes a CSC copy of `X` at `layers/X_csc`. A query for one gene then reads
  one column.
* `transaction`: commits on a clean exit. On an exception, it leaves the branch unchanged.
* `repository_config`: retries and timeouts for virtual chunk reads over the network.
* `bounded_reads`: a cap on the connections one compute opens. See `_network`.

Usage:

```python
import icechunk_spatialdata as isd
from spatialdata import SpatialData

with isd.transaction(repo, "main", "ingest") as tx, isd.parquet_in_store():
    sdata.write(tx.session.store)

with isd.parquet_in_store():
    back = SpatialData.read(repo.readonly_session("main").store)
```
"""

from __future__ import annotations

from ._network import bounded_reads, repository_config
from ._filesystem import (
    ZarrArrayFileSystem,
    available as parquet_in_store_available,
    parquet_in_store,
)
from ._reference import reference_file
from ._transaction import transaction
from ._virtual import (
    _declare_container as declare_container,
    images_in_h5ad_are_channel_last,
    reference_count,
    virtual_image,
    virtual_table,
    write_csc_layer,
)

__all__ = [
    "ZarrArrayFileSystem",
    "bounded_reads",
    "declare_container",
    "images_in_h5ad_are_channel_last",
    "parquet_in_store",
    "parquet_in_store_available",
    "reference_count",
    "reference_file",
    "repository_config",
    "transaction",
    "virtual_image",
    "virtual_table",
    "write_csc_layer",
]
