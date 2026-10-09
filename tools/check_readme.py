"""Assert the README carries the ledger, the limits, the scope and the account split.

It also asserts that the design document quotes the same test count as the README. The two
drifted apart once, because nothing compared them.
"""

import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
DESIGN = ROOT / "docs" / "zarr-soma" / "README.md"

REQUIRED_SECTIONS = [
    "## What this repository claims",
    "## What this repository does not claim",
    "## Scope",
    "## Icechunk and Arraylake",
    "## Reproducing",
]
REQUIRED_PHRASES = [
    "Every SOMA backend we found is TileDB-backed",
    "pixi run test",
    "pixi run compare-public-run",
    "pixi run check-s3",
    "pixi run compare-spatial-run",
    "pixi run merfish-run",
    "Arraylake has no anonymous read",
    "Icechunk on S3 needs no account",
    "CELLxGENE Discover holds no Xenium dataset",
]
# The last seven are claims that measurement refuted. They must not come back.
BANNED = [
    "—", "TBD", "TODO", "virtual_omics", "<N>", "<LIST HERE", "<IF the",
    "ZEP003", "ZEP0003", "supersedes", "grows at most linearly",
    "works on Linux", "tested on Linux", "172 tests",
    "first SOMA implementation that is not TileDB",
]


def over_long(text):
    """Yield each sentence of one prose chunk that passes the 20-word limit."""
    for sentence in re.split(r"(?<=[.:])\s+", text):
        words = [w for w in re.split(r"\s+", sentence.strip()) if w]
        if len(words) > 20:
            yield " ".join(words)


def chunks(body):
    """Split the README into prose and into one chunk per table cell."""
    prose, cells = [], []
    for line in body.splitlines():
        if line.lstrip().startswith("|"):
            for cell in line.strip().strip("|").split("|"):
                if cell.strip() and set(cell.strip()) - set("-: "):
                    cells.append(cell)
        else:
            prose.append(line)
    return ["\n".join(prose)] + cells


def main():
    bad = []
    for s in REQUIRED_SECTIONS:
        if s not in README:
            bad.append(f"missing section: {s}")
    for s in REQUIRED_PHRASES:
        if s not in README:
            bad.append(f"missing phrase: {s}")
    for s in BANNED:
        if s in README:
            bad.append(f"banned string present: {s}")

    # Every pixi task the README names must exist in the manifest.
    manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
    known = set(manifest.get("tasks", {}))
    for feat in manifest.get("feature", {}).values():
        known |= set(feat.get("tasks", {}))
    for task in set(re.findall(r"pixi run (?:-e \w+ )?([A-Za-z0-9-]+)", README)):
        if task not in known:
            bad.append(f"README names unknown task: {task}")

    # The design document's phase table counts tests per phase, so the earlier rows hold
    # smaller numbers. Its largest count is the current suite, and must match the ledger.
    match = re.search(r"(\d+) collected", README)
    cited = [int(n) for n in re.findall(r"(\d+) tests", DESIGN.read_text())]
    if match is None:
        bad.append("README states no collected test count")
    elif not cited:
        bad.append("docs/zarr-soma/README.md states no test count")
    elif max(cited) != int(match.group(1)):
        bad.append(f"docs/zarr-soma/README.md says {max(cited)} tests, "
                   f"README says {match.group(1)} collected")

    # Sentence length, the STE limit. Table cells count as prose.
    body = re.sub(r"```.*?```", "", README, flags=re.S)
    for chunk in chunks(body):
        for sentence in over_long(chunk):
            bad.append(f"sentence over 20 words: {sentence[:90]}")

    if bad:
        print("README PROBLEMS")
        for line in bad:
            print(" ", line)
        return 1
    print("README OK (1 file)")
    return 0

sys.exit(main())
