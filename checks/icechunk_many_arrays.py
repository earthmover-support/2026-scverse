"""Icechunk stored size grows with commit count when the array count stays fixed.

Run: pixi run check-icechunk

A SOMA dataframe is one array per column plus a zone map. An experiment holds several
dataframes. Each write also adds a delta block of `ndim + 1` arrays, and this count has no upper
limit. A repo with a thousand writes before compaction therefore holds thousands of arrays.

The script prints commit time, reopen time, listing time and stored size at 64 to 4,096 blocks
of three arrays. It asserts that the listing returns every block. It then fixes 1,024 blocks and
varies the commit count. It asserts that 64x more commits store more than 2x the bytes, so
snapshots accumulate. The printed curve shows how commit time scales, and the design does not
assume it.
"""

import os
import tempfile
import time
import warnings

warnings.simplefilter("ignore")

import icechunk
import numpy as np
import zarr

ARRAY_COUNTS = [64, 256, 1024, 4096]
VALUES_PER_ARRAY = 512


def build(path, n_arrays, per_commit):
    """Write n_arrays small arrays in a nested layout like SOMA, with a commit per batch."""
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(path))
    data = np.arange(VALUES_PER_ARRAY, dtype=np.int32)

    commit_times = []
    written = 0
    while written < n_arrays:
        session = repo.writable_session("main")
        root = zarr.open_group(session.store, mode="a")
        batch = min(per_commit, n_arrays - written)
        for i in range(batch):
            index = written + i
            # Copy the real shape: delta blocks under one group, with a few arrays each.
            block = root.require_group(f"soma_delta/d{index:06d}")
            for name in ("soma_dim_0", "soma_dim_1", "soma_data"):
                block.create_array(name, shape=data.shape, dtype=data.dtype,
                                   chunks=data.shape, overwrite=True)[:] = data
        start = time.perf_counter()
        session.commit(f"add {batch} blocks")
        commit_times.append(time.perf_counter() - start)
        written += batch
    return repo, commit_times


def size_of(path):
    return sum(os.path.getsize(os.path.join(d, f))
               for d, _, fs in os.walk(path) for f in fs)


def main():
    print(f"icechunk {icechunk.__version__}, zarr {zarr.__version__}")
    print(f"each block is 3 arrays of {VALUES_PER_ARRAY} int32 values\n")
    print(f"{'blocks':>8s} {'arrays':>8s} {'commits':>8s} {'commit p50':>12s} "
          f"{'commit max':>12s} {'reopen':>9s} {'list all':>9s} {'store':>9s}")
    print("-" * 86)

    per_commit = 32
    curve = []
    for n in ARRAY_COUNTS:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "repo")
            repo, commit_times = build(path, n, per_commit)

            start = time.perf_counter()
            reopened = icechunk.Repository.open(icechunk.local_filesystem_storage(path))
            session = reopened.readonly_session("main")
            root = zarr.open_group(session.store, mode="r")
            reopen = time.perf_counter() - start

            start = time.perf_counter()
            names = list(root["soma_delta"].keys())
            listing = time.perf_counter() - start
            assert len(names) == n, f"{len(names)} != {n}"

            p50 = float(np.median(commit_times))
            print(f"{n:>8,} {n * 3:>8,} {len(commit_times):>8,} "
                  f"{p50 * 1e3:>10.1f}ms {max(commit_times) * 1e3:>10.1f}ms "
                  f"{reopen * 1e3:>7.1f}ms {listing * 1e3:>7.1f}ms "
                  f"{size_of(path) / 1e6:>7.1f}MB")
            curve.append((n * 3, p50, max(commit_times), size_of(path), n * 3 * VALUES_PER_ARRAY * 4))
            del repo, reopened, session, root

    # Keep the array count fixed and change the commit count. If cost follows commit count,
    # each commit writes a snapshot of the full hierarchy, not only the change.
    print()
    print("same 1,024 blocks, varying how many commits they arrived in:")
    print(f"  {'commits':>8s} {'commit p50':>12s} {'store':>9s}")
    fixed = 1024
    sizes = {}
    for batch in [16, 64, 256, 1024]:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "repo")
            _, times = build(path, fixed, batch)
            size = size_of(path)
            sizes[batch] = size
            print(f"  {len(times):>8,} {np.median(times) * 1e3:>10.1f}ms "
                  f"{size / 1e6:>7.1f}MB")

    ratio = sizes[16] / sizes[1024]
    print()
    assert ratio > 2, (
        f"stored size barely varied with commit count ({ratio:.1f}x). The "
        "snapshot-per-commit explanation no longer holds: revisit it"
    )
    first, last = curve[0], curve[-1]
    print(f"Splitting the same work across 64x more commits stores {ratio:.1f}x more bytes.")
    print(f"Commit p50 went from {first[1] * 1e3:.0f}ms at {first[0]:,} arrays to "
          f"{last[1] * 1e3:.0f}ms at {last[0]:,} arrays.")
    print(f"The worst single commit took {max(c[2] for c in curve) * 1e3:.0f}ms.")
    print(f"{last[0]:,} arrays holding {last[4] / 1e6:.0f}MB of data occupied "
          f"{last[3] / 1e6:.0f}MB.")
    print()
    print("Design consequence for zarr-SOMA: compact delta blocks on a schedule. Reads scan")
    print("every delta, and the table above shows how commit time scales with array count.")


if __name__ == "__main__":
    main()
