"""Icechunk manifest size grows about linearly with virtual chunk reference count, up to about 37 million references.

Run: pixi run check-manifest

A materialized Census X["raw"] is three aligned COO columns (soma_dim_0, soma_dim_1, soma_data).
Take about 2k nonzeros per cell and 1M values per chunk. Mouse (43.6M cells) then needs about 90k
chunk refs per column. Human (159M cells) needs about 400k. The check `icechunk_many_arrays` measures many
small arrays. This check measures few arrays with millions of references.

The top scale is 12.3M refs per column, about 37M across three columns. It matches the Marson
perturb-seq cell-level h5ads (s3://genome-scale-tcell-perturb-seq/, 1.6 TiB, 12 files). Their CSR
X chunks at about 7k elements, which is 23x past human Census scale.

Chunks are virtual refs into local scratch files. The manifest carries realistic entries, and
the script writes no data. A native run at the smallest scale calibrates the virtual entry size
against the materialized one. The script measures append time, commit time, manifest bytes,
reopen time and a cold random chunk read. It verifies the chunk bytes against the source file. It asserts that manifest bytes per ref at
the largest scale are under twice the bytes per ref at the smallest. That test does not depend on machine speed.
The timings are printed and not asserted, because they depend on the machine.

Needs no local data.
"""

import os
import secrets
import tempfile
import time
import warnings

warnings.simplefilter("ignore")
os.environ.setdefault("ICECHUNK_LOG", "off")

import icechunk
import numpy as np
import zarr

COLUMNS = ("soma_dim_0", "soma_dim_1", "soma_data")
CHUNK_BYTES = 1024          # each zarr chunk is (1024,) uint8, uncompressed
SHARD_COUNT = 64            # distinct source files the refs point into
SHARD_BYTES = 1 << 20
# Chunks per COO column: mouse-like, between, human-like, 4x human headroom, and the
# Marson perturb-seq cell-level scale (~37M refs across three columns).
CHUNKS_PER_COLUMN = [30_000, 100_000, 400_000, 1_600_000, 12_300_000]


def make_shards(tmp):
    shard_dir = os.path.join(tmp, "shards")
    os.makedirs(shard_dir)
    for i in range(SHARD_COUNT):
        with open(os.path.join(shard_dir, f"s{i:03d}.bin"), "wb") as f:
            f.write(secrets.token_bytes(SHARD_BYTES))
    return shard_dir


def open_args(tmp, path):
    config = icechunk.RepositoryConfig.default()
    prefix = f"file://{tmp}/shards/"
    config.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(prefix, icechunk.local_filesystem_store(tmp)))
    storage = icechunk.local_filesystem_storage(path)
    access = icechunk.Credentials.LocalFileSystemAccess()
    return dict(storage=storage, config=config,
                authorize_virtual_chunk_access={prefix: access})


def build_virtual(tmp, path, chunks_per_column):
    """One experiment-shaped group of three COO columns, every chunk a virtual ref."""
    repo = icechunk.Repository.create(**open_args(tmp, path))
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    x = root.require_group("ms/RNA/X/raw")
    for name in COLUMNS:
        x.create_array(name, shape=(chunks_per_column * CHUNK_BYTES,), dtype="uint8",
                       chunks=(CHUNK_BYTES,), compressors=None)

    max_offset = SHARD_BYTES - CHUNK_BYTES
    urls = [f"file://{tmp}/shards/s{i:03d}.bin" for i in range(SHARD_COUNT)]
    locations = [urls[i % SHARD_COUNT] for i in range(chunks_per_column)]
    offsets = (np.arange(chunks_per_column, dtype=np.uint64) * CHUNK_BYTES) % max_offset
    lengths = np.full(chunks_per_column, CHUNK_BYTES, dtype=np.uint64)

    start = time.perf_counter()
    for name in COLUMNS:
        session.store.set_virtual_refs_arr(
            f"/ms/RNA/X/raw/{name}", (chunks_per_column,), locations, offsets, lengths)
    append = time.perf_counter() - start

    start = time.perf_counter()
    session.commit("reference every chunk")
    commit = time.perf_counter() - start
    return append, commit, offsets


def build_native(tmp, path, chunks_per_column):
    """The same shape with materialized chunks, to calibrate manifest bytes per ref."""
    repo = icechunk.Repository.create(**open_args(tmp, path))
    session = repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    x = root.require_group("ms/RNA/X/raw")
    payload = np.frombuffer(secrets.token_bytes(chunks_per_column * CHUNK_BYTES),
                            dtype=np.uint8)
    for name in COLUMNS:
        arr = x.create_array(name, shape=(chunks_per_column * CHUNK_BYTES,),
                             dtype="uint8", chunks=(CHUNK_BYTES,), compressors=None)
        arr[:] = payload
    session.commit("materialize every chunk")


def manifest_stats(path):
    d = os.path.join(path, "manifests")
    sizes = [os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)]
    return len(sizes), sum(sizes)


def read_one(tmp, path, chunks_per_column, offsets):
    """Reopen cold and read one chunk mid-array, verifying it against its shard."""
    start = time.perf_counter()
    repo = icechunk.Repository.open(**open_args(tmp, path))
    session = repo.readonly_session("main")
    root = zarr.open_group(session.store, mode="r")
    reopen = time.perf_counter() - start

    index = chunks_per_column // 2 + 1
    arr = root["ms/RNA/X/raw/soma_data"]
    start = time.perf_counter()
    got = arr[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
    first_read = time.perf_counter() - start

    shard = os.path.join(tmp, "shards", f"s{index % SHARD_COUNT:03d}.bin")
    with open(shard, "rb") as f:
        f.seek(int(offsets[index]))
        expected = np.frombuffer(f.read(CHUNK_BYTES), dtype=np.uint8)
    assert np.array_equal(got, expected), "virtual chunk bytes do not match their shard"

    start = time.perf_counter()
    arr[(index + 7) * CHUNK_BYTES:(index + 8) * CHUNK_BYTES]
    warm_read = time.perf_counter() - start
    return reopen, first_read, warm_read


def main():
    print(f"icechunk {icechunk.__version__}, zarr {zarr.__version__}")
    print(f"three COO columns per repo, {CHUNK_BYTES}-byte uncompressed chunks, "
          f"virtual refs into {SHARD_COUNT} scratch files\n")
    print(f"{'refs':>10s} {'append':>8s} {'commit':>8s} {'manifests':>10s} "
          f"{'bytes/ref':>10s} {'reopen':>8s} {'read cold':>10s} {'read warm':>10s}")
    print("-" * 82)

    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        make_shards(tmp)
        for chunks_per_column in CHUNKS_PER_COLUMN:
            refs = chunks_per_column * len(COLUMNS)
            path = os.path.join(tmp, f"repo-{chunks_per_column}")
            append, commit, offsets = build_virtual(tmp, path, chunks_per_column)
            n_files, manifest_bytes = manifest_stats(path)
            reopen, cold, warm = read_one(tmp, path, chunks_per_column, offsets)
            results[refs] = (commit, manifest_bytes / refs, cold, warm)
            print(f"{refs:>10,} {append:>7.2f}s {commit:>7.2f}s "
                  f"{n_files:>3d} files {manifest_bytes / refs:>9.1f}B "
                  f"{reopen * 1e3:>6.1f}ms {cold * 1e3:>8.1f}ms {warm * 1e3:>8.1f}ms")

        native_chunks = CHUNKS_PER_COLUMN[0]
        path = os.path.join(tmp, "repo-native")
        build_native(tmp, path, native_chunks)
        _, native_manifest = manifest_stats(path)
        native_per_ref = native_manifest / (native_chunks * len(COLUMNS))
        native_refs = native_chunks * len(COLUMNS)
        print(f"\nat {native_refs:,} refs: native chunks {native_per_ref:.1f}B of manifest "
              f"per ref, virtual {results[native_refs][1]:.1f}B per ref")

    small, large = min(results), max(results)
    growth = results[large][0] / results[small][0]
    assert results[large][1] < 2 * results[small][1], (
        f"manifest bytes per ref rose from {results[small][1]:.1f}B to {results[large][1]:.1f}B. "
        "Manifest size is no longer linear in ref count: revisit the flat-manifest explanation.")
    print(f"\nCommit time grew {growth:.1f}x over a {large / small:.0f}x ref increase. "
          f"The largest commit took {results[large][0]:.2f}s.")
    per_ref = results[large][1]
    mouse = 90_000 * len(COLUMNS) * per_ref
    human = 400_000 * len(COLUMNS) * per_ref
    print(f"At {per_ref:.0f}B/ref a mouse-scale X manifest is ~{mouse / 1e6:.0f}MB "
          f"and a human-scale one ~{human / 1e6:.0f}MB.")
    print(f"At {large:,} refs (perturb-seq cell-level scale) the manifest is "
          f"{large * per_ref / 1e6:.0f}MB. A cold read took {results[large][2] * 1e3:.0f}ms "
          f"and a warm read {results[large][3] * 1e3:.1f}ms.")


if __name__ == "__main__":
    main()
