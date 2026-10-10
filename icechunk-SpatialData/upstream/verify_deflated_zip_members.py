# /// script
# requires-python = ">=3.9"
# dependencies = ["requests"]
# ///
"""Deflate removes all addressability of an already-compressed archive member and saves nothing.

Run: pixi run -e spatial python icechunk-SpatialData/upstream/verify_deflated_zip_members.py
The inline header above also lets `uv run` execute it outside this project.

A zip's central directory locates every member. Thus a **stored** member is a contiguous byte
range. All data inside that member keeps its offsets. For this reason, a reader can read a
published `.zarr.zip` as a virtual Zarr store. The reader reads it chunk by chunk and does not
download it. A **deflated** member is one Huffman-coded stream. To read byte N of the decompressed
file, a reader must inflate all bytes before it. Thus no data *inside* the member has an
addressable offset. The three bundles below store their `.zarr.zip` outputs. They deflate their
OME-TIFF imagery, which already has internal compression. The deflate saves a fraction of a percent
at best. On the Atera imagery, the deflate adds bytes.

The script reads all data directly from the `10x.files` S3 bucket. That bucket serves byte ranges.
"""

from __future__ import annotations

import io
import zipfile

import requests

S3 = "https://s3-us-west-2.amazonaws.com/10x.files/samples/"
SAMPLES = {
    "Human Lung Cancer, Xenium v2.0.0":
        S3 + "xenium/2.0.0/Xenium_V1_humanLung_Cancer_FFPE/Xenium_V1_humanLung_Cancer_FFPE_outs.zip",
    "Human Kidney FFPE Protein, Xenium v4.0.0":
        S3 + "xenium/4.0.0/Xenium_V1_Human_Kidney_FFPE_Protein_updated/"
             "Xenium_V1_Human_Kidney_FFPE_Protein_updated_outs.zip",
    "Human Cervical Cancer, Atera WTA preview":
        S3 + "atera/dev/WTA_Preview_FFPE_Cervical_Cancer/WTA_Preview_FFPE_Cervical_Cancer_outs.zip",
}
METHODS = {0: "STORED", 8: "DEFLATE"}


class RangedFile(io.RawIOBase):
    """A seekable read-only file over HTTP ranges."""

    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()
        head = self.session.head(url)
        head.raise_for_status()
        self.size = int(head.headers["Content-Length"])
        self.loc = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.loc

    def seek(self, offset: int, whence: int = 0) -> int:
        self.loc = {0: offset, 1: self.loc + offset, 2: self.size + offset}[whence]
        return self.loc

    def read(self, length: int = -1) -> bytes:
        if length < 0:
            length = self.size - self.loc
        if not length or self.loc >= self.size:
            return b""
        end = min(self.loc + length, self.size) - 1
        # Stream the response, so that the reader can drop any non-206 response unread.
        # A 200 is the whole object, and that is 36 GB in the kidney bundle.
        with self.session.get(self.url, headers={"Range": f"bytes={self.loc}-{end}"},
                              stream=True) as answer:
            answer.raise_for_status()
            if answer.status_code != 206:
                raise OSError(f"range {self.loc}-{end} of {self.url} was answered with "
                              f"{answer.status_code}")
            payload = answer.content
        self.loc += len(payload)
        return payload

    def readinto(self, buffer) -> int:
        chunk = self.read(len(buffer))
        buffer[:len(chunk)] = chunk
        return len(chunk)


def published_alone(prefix: str, member: zipfile.ZipInfo, client: requests.Session) -> bool:
    """Return True if this member also exists as its own object, beside the bundle.

    These publishers name a standalone file `<sample prefix>_<basename>`. Thus the function tries
    the bundle's own URL minus `outs.zip` as the prefix. A deflated member with its own URL loses
    nothing. A deflated member without its own URL is available only inside the archive.
    """
    basename = member.filename.rsplit("/", 1)[-1]
    return client.head(prefix + basename).status_code == 200


def report(label: str, url: str) -> tuple[int, float]:
    """Print one archive's split.

    Return the imagery bytes that the archive makes unreachable, and the best saving.
    """
    handle = RangedFile(url)
    with zipfile.ZipFile(io.BufferedReader(handle, buffer_size=1 << 22)) as archive:
        members = archive.infolist()

    # Take every OME-TIFF, not only `morphology_focus/`. Each bundle also has a top-level
    # `morphology.ome.tif`, deflated like the rest. A check below tests if that costs anything.
    imagery = [m for m in members if m.filename.endswith(".ome.tif") and m.file_size]
    archives = [m for m in members if m.filename.endswith(".zarr.zip") and m.file_size]
    print(f"\n{label}: {url.rsplit('/', 1)[-1]}, {len(members)} members\n")
    print(f"  {'method':8} {'stored':>12} {'original':>12} {'saved':>9}  member")
    for m in sorted(imagery, key=lambda m: -m.file_size)[:4] + sorted(archives,
                                                                      key=lambda m: -m.file_size):
        saved = 1 - m.compress_size / m.file_size
        print(f"  {METHODS.get(m.compress_type, m.compress_type):8} "
              f"{m.compress_size / 1e6:>9.1f} MB {m.file_size / 1e6:>9.1f} MB "
              f"{saved:>8.4%}  {m.filename}")
    if len(imagery) > 4:
        print(f"  {'...':8} {len(imagery) - 4} further deflated channels, all alike")

    deflated = [m for m in members if m.compress_type == 8 and m.file_size]
    stored = [m for m in members if m.compress_type == 0 and m.file_size]
    assert deflated and stored, "the comparison needs one of each to mean anything"
    assert all(m.compress_type == 8 for m in imagery), "some imagery here is stored after all"
    assert all(m.compress_type == 0 for m in archives), "some `.zarr.zip` here is deflated"

    # No member is seek-optimised. SOzip announces independent deflate blocks in the extra field.
    # These members carry only Info-ZIP timestamps and Zip64, so they have no index for a seek.
    for m in deflated:
        assert b"SOZ" not in m.extra, f"{m.filename} looks seek-optimised; re-check this finding"

    # Compute the savings over the imagery only. The archive also holds deflated CSVs and JSON.
    # For those, the compression saves real bytes and removes no offset that a reader could use.
    savings = [1 - m.compress_size / m.file_size for m in imagery]
    best, worst = max(savings), min(savings)
    earns = (f"saves at most {best:.4%} of one" if best > 0
             else f"makes every one of them larger, by {-best:.4%} to {-worst:.4%}")
    print(f"\n  the {len(imagery)} deflated images hold "
          f"{sum(m.file_size for m in imagery) / 1e9:.2f} GB and the compression {earns},")
    print("  at the cost of every interior byte offset: no tile of any of them can be referenced")

    client = requests.Session()
    prefix = url[:-len("outs.zip")]
    elsewhere = [m for m in imagery if published_alone(prefix, m, client)]
    lost = sum(m.file_size for m in imagery if m not in elsewhere)
    if elsewhere:
        print(f"\n  {len(elsewhere)} of them are published standalone as well and lose nothing "
              f"({sum(m.file_size for m in elsewhere) / 1e9:.2f} GB):")
        for m in elsewhere:
            print(f"    {m.filename}")
    remaining = len(imagery) - len(elsewhere)
    print(f"\n  the archive is the only copy of {'the other' if elsewhere else 'all'} {remaining}, "
          f"{lost / 1e9:.2f} GB")
    print(f"\n  the {len(stored)} stored members keep their byte offsets addressable, "
          f"{len(archives)} of them the `.zarr.zip`")
    print("  outputs, which is why the masks, the counts and the transcripts *are* reachable")

    assert best < 0.01, f"the deflate saves {best:.2%}, which is more than this finding assumes"
    return lost, best


def main() -> None:
    measured = [report(label, url) for label, url in SAMPLES.items()]
    lost = sum(image for image, _ in measured)
    best = max(saving for _, saving in measured)
    print(f"\nVERDICT: storing these members instead of deflating them would make {lost / 1e9:.1f} GB")
    print(f"         of otherwise unpublished imagery byte-range addressable across the "
          f"{len(SAMPLES)} bundles,")
    print(f"         at a cost of at most {best:.4%} in archive size")


if __name__ == "__main__":
    main()
