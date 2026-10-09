"""Assert the account notice sits first in each notebook that writes to Arraylake."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTICED = ["virtualize_braun.ipynb"]
ANON = ["compare_backends_object_store.ipynb", "compare_backends_public_s3.ipynb",
        "compare_backends_spatial.ipynb", "merfish_scene.ipynb"]
NEEDLE = "This notebook needs an Arraylake account."

def first_markdown(nb):
    for cell in nb["cells"]:
        if cell["cell_type"] == "markdown":
            return "".join(cell["source"])
    return ""

def has_outputs(nb):
    return any(c["cell_type"] == "code" and c.get("outputs") for c in nb["cells"])

def main():
    bad = []
    for name in NOTICED + ANON:
        if not (ROOT / "notebooks" / name).is_file():
            bad.append(f"{name}: no such notebook")
    if bad:
        print("NOTEBOOK PROBLEMS")
        for line in bad:
            print(" ", line)
        return 1
    for name in NOTICED:
        nb = json.loads((ROOT / "notebooks" / name).read_text())
        if NEEDLE not in first_markdown(nb):
            bad.append(f"{name}: no account notice in the first markdown cell")
        if not has_outputs(nb):
            bad.append(f"{name}: committed outputs are gone")
    for name in ANON:
        nb = json.loads((ROOT / "notebooks" / name).read_text())
        if NEEDLE in json.dumps(nb):
            bad.append(f"{name}: carries an account notice but reads anonymously")
        if not has_outputs(nb):
            bad.append(f"{name}: committed outputs are gone")
    if bad:
        print("NOTEBOOK PROBLEMS")
        for line in bad:
            print(" ", line)
        return 1
    print(f"notebook notices OK ({len(NOTICED) + len(ANON)} notebooks)")
    return 0

sys.exit(main())
