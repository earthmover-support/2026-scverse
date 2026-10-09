"""Assert the README carries the ledger, the upstream ask, the limits and the three tracks.

Every required phrase is a claim a run supports, or a command that reproduces one. The banned
patterns are corrections this repository already made. A pattern stops the old wording from
returning quietly: 11.95 GB called "referenced", and `parquet_fs_and_path` blamed for the
released-package failure. Released spatialdata fails earlier, at `store.root`.

Two cross-checks compare the README against something outside it. One reads the equivalence
figures out of the committed notebook that produced them. The other recomputes the Braun
ratio from the two byte counts the README prints. A banned string cannot catch a number that
is merely wrong, and these two can.
"""

import json
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()

REQUIRED_SECTIONS = [
    "## What this repository claims",
    "## What this repository does not claim",
    "## The upstream ask",
    "## Reproducing",
]
REQUIRED_PHRASES = [
    "pixi run check-s3",
    "pixi run check-tenx",
    "pixi run check-sparsity",
    "pixi run check-store-path",
    "pixi run equivalence-run",
    "pixi run -e spatial versioning-run",
    "pixi run -e spatial extension-test",
    "pull request #1107",
    "feat/zarr-store-class...li-em:spatialdata:li-em/store-without-a-path",
    "Arraylake has no anonymous read",
    # The measured Braun figures, and the two calls that produce them.
    "repo.chunk_storage_stats()",
    "repo.list_manifest_files()",
    "11.31 GB",
    "at least 35 MB",
    # Another group's measurement, which must stay attributed.
    "DataScales",
]
# The last five are claims that measurement refuted, or names that stay out of this tree.
BANNED = [
    "—", "TBD", "TODO", "virtual_omics", "<N>", "<LIST HERE", "<IF the",
    "ZEP003", "ZEP0003", "supersedes", "grows at most linearly",
    "works on Linux", "tested on Linux", "172 tests",
    "seam", "compare/main...", "SOMA", "tiledbsoma", "somacore",
]
# A stale claim that a nearby word makes false. Each pattern stays inside one sentence.
BANNED_PATTERNS = [
    (r"referenc\w*[^.]{0,160}11\.95\s*GB", "11.95 GB called referenced"),
    (r"11\.95\s*GB[^.]{0,160}referenc", "11.95 GB called referenced"),
    (r"releas\w*[^.]{0,200}parquet_fs_and_path", "parquet_fs_and_path cited for released"),
    (r"parquet_fs_and_path[^.]{0,200}releas", "parquet_fs_and_path cited for released"),
    (r"0\.8\.0[^.]{0,200}parquet_fs_and_path", "parquet_fs_and_path cited for released"),
]
# A truncated or emptied README would pass every other rule. Fail instead.
MINIMUM_WORDS = 900
MINIMUM_CLAIM_ROWS = 8

# The equivalence figures the README quotes come from one committed run. Each pattern reads a
# value out of that notebook's outputs, and the README must carry the same value.
EQUIVALENCE_NB = ROOT / "notebooks" / "scanpy_equivalence.ipynb"
EQUIVALENCE_FIGURES = [
    (r"(\d+) genes have a defined dispersion", "genes with a defined dispersion"),
    (r"defined dispersion, (\d+) have none", "genes without a dispersion"),
    (r"highly variable genes: (\d+) virtual", "highly variable genes"),
    (r"Jaccard: ([\d.]+)", "Jaccard index"),
    (r"dispersion correlation: ([\d.]+)", "dispersion correlation"),
]
# The Braun ratio a reader recomputes by dividing two figures the README prints. The divisor
# counts no snapshot, so the quotient is an upper bound and the README must say so.
RATIO_TERMS = [
    r"([\d,]+) virtual bytes",
    r"([\d,]+) native bytes",
    r"287 manifest files holding ([\d,]+) bytes",
]
RATIO_CLAIM = r"ratio of referenced bytes to stored bytes is about (\d+) to 1"
RATIO_TOLERANCE = 5


def notebook_text(path):
    """Return every output of one committed notebook as one string."""
    nb = json.loads(path.read_text())
    out = []
    for cell in nb["cells"]:
        for o in cell.get("outputs", []):
            out.append("".join(o.get("text", [])))
            out.append("".join(o.get("data", {}).get("text/plain", [])))
    return "\n".join(out)


def equivalence_problems(digits):
    """Yield each measured figure of the committed run that the README does not carry."""
    text = notebook_text(EQUIVALENCE_NB)
    for pattern, what in EQUIVALENCE_FIGURES:
        found = re.search(pattern, text)
        if found is None:
            yield f"{EQUIVALENCE_NB.name} states no {what}"
        # A bare substring test passes 1.0000 against 1.000000, so the value stands alone.
        elif not re.search(rf"(?<![\d.]){re.escape(found.group(1))}(?!\d)", digits):
            yield f"README omits the measured {what}: {found.group(1)}"


def ratio_problems():
    """Yield the ratio problems: a missing figure, a wrong quotient, or a missing bound."""
    # A wrapped line splits a phrase across a newline, so the search reads one flat line.
    flat = " ".join(README.split())
    values = []
    for pattern in RATIO_TERMS:
        found = re.search(pattern, flat)
        if found is None:
            yield f"README states no figure matching {pattern}"
            return
        values.append(int(found.group(1).replace(",", "")))
    stated = re.search(RATIO_CLAIM, flat)
    if stated is None:
        yield "README states no referenced-to-stored ratio"
        return
    computed = values[0] / (values[1] + values[2])
    if abs(computed - int(stated.group(1))) > RATIO_TOLERANCE:
        yield (f"README says {stated.group(1)} to 1, the printed figures give "
               f"{computed:.1f} to 1")
    if "upper bound" not in flat:
        yield "README does not call the ratio an upper bound"


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


def claim_rows():
    """Count the data rows of the table under the claims heading."""
    section = README.split("## What this repository claims", 1)[-1].split("\n## ", 1)[0]
    rows = [ln for ln in section.splitlines() if ln.lstrip().startswith("|")]
    return max(0, len([r for r in rows if set(r.strip()) - set("|-: ")]) - 1)


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
    for pattern, why in BANNED_PATTERNS:
        for m in re.finditer(pattern, README, flags=re.S):
            bad.append(f"banned claim ({why}): {' '.join(m.group(0).split())[:90]}")

    words = len(README.split())
    if words < MINIMUM_WORDS:
        bad.append(f"README holds {words} words, floor {MINIMUM_WORDS}")
    rows = claim_rows()
    if rows < MINIMUM_CLAIM_ROWS:
        bad.append(f"the claims table holds {rows} rows, floor {MINIMUM_CLAIM_ROWS}")

    # The README groups its digits, so the comparison drops the separators.
    bad.extend(equivalence_problems(README.replace(",", "")))
    bad.extend(ratio_problems())

    # Every pixi task the README names must exist in the manifest.
    manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
    known = set(manifest.get("tasks", {}))
    for feat in manifest.get("feature", {}).values():
        known |= set(feat.get("tasks", {}))
    for task in set(re.findall(r"pixi run (?:-e \w+ )?([A-Za-z0-9-]+)", README)):
        if task not in known:
            bad.append(f"README names unknown task: {task}")

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
    print(f"README OK ({words} words, {rows} claim rows)")
    return 0

sys.exit(main())
