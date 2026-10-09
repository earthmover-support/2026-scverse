"""Settings for reads that fetch virtual chunks over the network.

A virtual chunk read is one range request to a published file. Two settings bound the number of
requests in flight. dask runs one task per worker thread, and zarr issues up to `async.concurrency`
chunk requests per task. With fifteen cores and the zarr default of ten, one compute opens up to
150 connections. Some networks drop connections above about that number.

Icechunk retries a failed request with exponential backoff. The settings here name the retry
count, the backoff and the timeouts. A dropped connection then costs one retry, not the read.
"""

from __future__ import annotations

import icechunk

#: Requests in flight per object, and the retry and timeout budget of each request.
MAX_CONCURRENT_REQUESTS_FOR_OBJECT = 4
MAX_TRIES = 10
INITIAL_BACKOFF_MS = 200
MAX_BACKOFF_MS = 10_000
CONNECT_TIMEOUT_MS = 10_000
READ_TIMEOUT_MS = 60_000


def repository_config(*containers: icechunk.VirtualChunkContainer) -> icechunk.RepositoryConfig:
    """Return a `RepositoryConfig` that retries and bounds virtual chunk reads.

    Each container's fetcher shares the repository's storage settings. So the retries and the
    timeouts apply to the published files and to the repository. Pass the config to
    `Repository.create`, `Repository.open` or Arraylake's `get_repo`. Icechunk merges it with the
    stored config, so a config without containers keeps the containers the repository holds.
    """
    config = icechunk.RepositoryConfig.default()
    config.storage = icechunk.StorageSettings(
        concurrency=icechunk.StorageConcurrencySettings(
            max_concurrent_requests_for_object=MAX_CONCURRENT_REQUESTS_FOR_OBJECT,
        ),
        retries=icechunk.StorageRetriesSettings(
            max_tries=MAX_TRIES,
            initial_backoff_ms=INITIAL_BACKOFF_MS,
            max_backoff_ms=MAX_BACKOFF_MS,
        ),
        timeouts=icechunk.StorageTimeoutSettings(
            connect_timeout_ms=CONNECT_TIMEOUT_MS,
            read_timeout_ms=READ_TIMEOUT_MS,
        ),
    )
    for container in containers:
        config.set_virtual_chunk_container(container)
    return config


class bounded_reads:
    """Bound the connections a compute opens to `zarr_concurrency` times `dask_workers`.

    The bound takes effect on construction, so a notebook calls `bounded_reads()` once. As a
    context manager, it restores the previous values on exit. zarr reads the setting on each
    call, and dask sizes its thread pool on each compute.
    """

    def __init__(self, zarr_concurrency: int = 4, dask_workers: int = 8):
        import dask
        import zarr

        self._zarr = zarr.config.set({"async.concurrency": zarr_concurrency})
        self._dask = dask.config.set(num_workers=dask_workers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._dask.__exit__(*exc)
        self._zarr.__exit__(*exc)
