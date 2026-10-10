"""Assert that no file states a primacy or conformance claim as a flat fact, and holds no em-dash.

`tools/` is scanned too, so a leak there cannot pass every gate. PATTERN_HOLDERS names the
gates that must hold the banned phrases in order to search for them. A scan of them would
always fail, so the gate skips them by name.

The phrases are matched across a line break, because a wrapped paragraph can split one. The
bare word "conformant" stays usable, because it describes the SOMA spec's extension mechanism.

The em-dash scan reads a notebook's cell sources only. Its outputs carry machine text, and
icechunk's own warnings hold em-dashes.

BANNED also holds "zep003". The README bans that term, because a rectilinear chunk grid
already describes the concatenation. This gate stops a notebook or a generator from stating
the opposite.

One notebook needs an Arraylake account and prints a line holding an em-dash. Its committed
output carries the same character. Editing the source without a re-run would put the two out of
step, and a re-run needs an account. EM_DASH_EXEMPT names that notebook and its generator, and
the scan stays on every other file.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".git", ".pixi", "vendor", "__pycache__",
        ".pytest_cache", ".ipynb_checkpoints", "h5ads"}
# The gates that carry the banned phrases as detection patterns.
PATTERN_HOLDERS = {"tools/check_claims.py", "tools/check_readme.py",
                   "tools/check_manifest.sh"}
SUFFIXES = {".md", ".py", ".ipynb", ".toml", ".sh"}
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
    # A fix the README refutes. The Zarr data model is not the blocker.
    "zep003",
    "zep0003",
]
# The only two files that carry an em-dash a re-run cannot remove, with the reason above.
# The generator is here too, because it must match its notebook character for character.
EM_DASH_EXEMPT = {
    "notebooks/xenium_from_arraylake.ipynb",
    "scripts/build_arraylake_xenium_notebook.py",
}
# The gate walks the whole tree. A floor catches a skip bug that silently narrows the scan.
MINIMUM_FILES = 55  # The tree holds 59 scanned files. A collapsed scan falls under this.


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


def author_chunks(p):
    """Yield (label, text) for the author-written parts of one file.

    A notebook yields one chunk per cell source. Outputs stay out, because a
    re-run owns them and an account-gated notebook cannot be re-run.
    """
    if p.suffix != ".ipynb":
        yield "", p.read_text(errors="ignore")
        return
    try:
        cells = json.loads(p.read_text(errors="ignore")).get("cells", [])
    except ValueError:
        return
    for i, cell in enumerate(cells, 1):
        yield f"cell {i}", "".join(cell.get("source", []))


def main():
    bad = []
    scanned = dashed = 0
    for p in files():
        scanned += 1
        rel = p.relative_to(ROOT).as_posix()
        if rel in PATTERN_HOLDERS:
            continue
        check_dash = rel not in EM_DASH_EXEMPT
        dashed += check_dash
        for label, text in author_chunks(p):
            flat, lines = flatten(text)
            for phrase in (BANNED + ["\u2014"] if check_dash else BANNED):
                name = "em-dash" if phrase == "\u2014" else phrase
                for m in re.finditer(re.escape(phrase), flat):
                    bad.append(f"{rel}:{label or lines[m.start()]}: {name}")
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
    print(f"claims OK ({scanned} files, {dashed} of them scanned for em-dashes)")
    return 0

sys.exit(main())
