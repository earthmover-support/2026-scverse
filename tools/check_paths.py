"""Assert that every repository-relative path named in prose resolves."""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".git", ".pixi", "tools", "vendor", "__pycache__"}
PATH_RE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|md|ipynb|toml|lock))`")
# Documents outside this repository. The SOMA abstract spec, and somacore's own modules.
ALLOW = {
    "abstract_specification.md",  # the SOMA abstract specification
    "scene.py",  # somacore module, named at docs/zarr-soma/README.md:376
    "spatial.py",  # somacore module, named at docs/zarr-soma/README.md:376
    "coordinates.py",  # somacore module, named at docs/zarr-soma/README.md:376
}
LINK_RE = re.compile(r"\]\(([^)]+\.(?:py|md|ipynb|toml|lock))\)")
# The gate walks the whole tree. A floor catches a skip bug that silently narrows the scan.
MINIMUM_FILES = 20  # Catches a collapsed scan. Task 7 raises it to the final count.

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
                if bare and target in ALLOW:
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
