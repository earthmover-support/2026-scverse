"""Assert that every repository-relative path named in prose resolves."""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".git", ".pixi", "tools", "vendor", "__pycache__"}
# A leading dot is allowed, so a relative path in backticks is checked like a link target.
PATH_RE = re.compile(r"`([A-Za-z0-9_.][A-Za-z0-9_./-]*\.(?:py|md|ipynb|toml|lock))`")
# Paths outside this repository. A name here must belong to a third party's source tree, not to
# a file this repository ought to carry.
ALLOW = {
    "abstract_specification.md",  # an external abstract specification
    # spatialdata's own modules, named so a maintainer can find the line under discussion.
    "_store.py", "spatialdata/_store.py",
    "_io/_utils.py", "spatialdata/_io/_utils.py",
    "io_shapes.py", "spatialdata/_io/io_shapes.py",
    "io_points.py", "io_zarr.py", "_io/io_zarr.py", "_io/io_raster.py",
    "_core/spatialdata.py",
    "render.py",  # spatialdata-plot's renderer, cited by line number at 0.4.0
    # The scverse and squidpy tutorial notebooks that two notebooks here replace.
    "technology_xenium.ipynb", "tutorial_xenium.ipynb",
    "tests/test_ome_tiff_microscopy.py",  # virtual-tiff's suite, carried by its PR #107
    "tests/unit/test_zarr_codecs.py",  # osml-imagery-io's suite, which missed the codec bug
}
LINK_RE = re.compile(r"\]\(([^)]+\.(?:py|md|ipynb|toml|lock))\)")
# The gate walks the whole tree. A floor catches a skip bug that silently narrows the scan.
MINIMUM_FILES = 45  # The tree holds 50 prose files. A collapsed scan falls under this.

def basenames():
    return {p.name for p in ROOT.rglob("*") if p.is_file() and not any(x in SKIP for x in p.relative_to(ROOT).parts)}

def files():
    for p in ROOT.rglob("*"):
        if any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix in {".md", ".py", ".ipynb"} and p.is_file():
            yield p

def main():
    bad = []
    scanned = 0
    names = basenames()
    for p in files():
        scanned += 1
        text = p.read_text(errors="ignore")
        for pattern in (PATH_RE, LINK_RE):
            for m in pattern.finditer(text):
                target = m.group(1)
                if target.startswith(("http", "s3:")):
                    continue
                bare = "/" not in target
                if target in ALLOW:
                    continue
                candidates = [ROOT / target, p.parent / target]
                if not any(c.exists() for c in candidates) and not (bare and target in names):
                    bad.append(f"{p.relative_to(ROOT)}: {target}")
    # A gate that walks nothing, or too little, passes for the wrong reason. Fail instead.
    if scanned < MINIMUM_FILES or not names:
        print("UNRESOLVED PATHS")
        print(f"  the gate scanned {scanned} prose files and indexed {len(names)} names")
        return 1
    if bad:
        print("UNRESOLVED PATHS")
        for line in sorted(set(bad)):
            print(" ", line)
        return 1
    print(f"paths OK ({scanned} files)")
    return 0

sys.exit(main())
