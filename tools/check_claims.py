"""Assert that no file states a primacy or conformance claim as a flat fact, and holds no em-dash.

`tools/` is skipped, like the other gates skip it. This file must hold the banned phrases in
order to search for them, so a scan of itself would always fail.

The phrases are matched across a line break, because a wrapped paragraph can split one. The
bare word "conformant" stays usable, because it describes the SOMA spec's extension mechanism.

The em-dash scan reads a notebook's cell sources only. Its outputs carry machine text, and
icechunk's own warnings hold em-dashes.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".git", ".pixi", "tools", "__pycache__"}
SUFFIXES = {".md", ".py", ".ipynb", ".toml"}
BANNED = [
    "this is the first",
    "the first soma implementation",
    "conforming backend",
    "conformant backend",
    "no other soma implementation exists",
    "found no other soma implementation",
    "contains exactly one implementation",
    "no other forum could hold",
    "no second implementation has ever",
    "the search found no competitor",
]
# The gate walks the whole tree. A floor catches a skip bug that silently narrows the scan.
MINIMUM_FILES = 55


def flatten(text):
    """Return the text as one lowercase line, with a line number per character."""
    chars, lines = [], []
    for n, line in enumerate(text.splitlines(), 1):
        for ch in " ".join(line.split()) + " ":
            chars.append(ch.lower())
            lines.append(n)
    return "".join(chars), lines


def files():
    for p in sorted(ROOT.rglob("*")):
        if any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix in SUFFIXES and p.is_file():
            yield p


def em_dashes(p):
    """Yield the author-written places in one file that hold an em-dash."""
    if p.suffix == ".ipynb":
        try:
            cells = json.loads(p.read_text(errors="ignore")).get("cells", [])
        except ValueError:
            cells = []
        for i, cell in enumerate(cells, 1):
            if "\u2014" in "".join(cell.get("source", [])):
                yield f"cell {i}"
        return
    for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
        if "\u2014" in line:
            yield n


def main():
    bad = []
    scanned = 0
    for p in files():
        scanned += 1
        for where in em_dashes(p):
            bad.append(f"{p.relative_to(ROOT)}:{where}: em-dash")
        flat, lines = flatten(p.read_text(errors="ignore"))
        for phrase in BANNED:
            for m in re.finditer(re.escape(phrase), flat):
                bad.append(f"{p.relative_to(ROOT)}:{lines[m.start()]}: {phrase}")
    # A gate that walks nothing, or too little, passes for the wrong reason. Fail instead.
    if scanned < MINIMUM_FILES:
        print("CLAIM PROBLEMS")
        print(f"  the gate scanned {scanned} files, floor {MINIMUM_FILES}")
        return 1
    if bad:
        print("CLAIM PROBLEMS")
        for line in sorted(bad):
            print(" ", line)
        return 1
    print(f"claims OK ({scanned} files)")
    return 0

sys.exit(main())
