"""Assert each check states its claim, names the task that runs it, and reaches verify.sh."""

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASKS = {
    "h5ad_virtualization": "check",
    "virtualize_cellxgene": "check-s3",
    "virtual_csr_concat": "check-concat",
    "icechunk_many_arrays": "check-icechunk",
    "census_manifest_scale": "check-manifest",
    "block_sparsity": "check-sparsity",
    "tenx_matrix_virtualization": "check-tenx",
    "spatialdata_store_path": "check-store-path",
}
BANNED = ("research", "this project", "spike", "probe", "findings.md",
          "investigat", "we decided", "later", "originally")

MAX_FIRST_SENTENCE_WORDS = 20
VERIFY = ROOT / "tools" / "verify.sh"


def verify_lists():
    """Return the check tasks verify.sh runs, and the ones it names NOT COVERED."""
    text = VERIFY.read_text()
    m = re.search(r"\nfor t in ((?:[^;]|\n)*?);\s*do\s*\n\s*run_check", text)
    ran = (set(m.group(1).split()) - {"\\"}) if m else set()  # drop line continuations
    covered = set(re.findall(r"check[A-Za-z0-9_-]*|census-vars",
                             " ".join(re.findall(r"NOT COVERED:[^\"]*", text))))
    return ran, covered


def task_name(task):
    """Strip the environment prefix, so '-e census census-vars' becomes 'census-vars'."""
    return task.split()[-1]


def first_sentence(doc):
    return re.split(r"(?<=[.:?!])\s", " ".join(doc.split("\n\n")[0].split()), maxsplit=1)[0]


def main():
    bad = []
    for mod, task in TASKS.items():
        p = ROOT / "checks" / f"{mod}.py"
        if not p.is_file():
            bad.append(f"{mod}: no such file")
            continue
        doc = ast.get_docstring(ast.parse(p.read_text())) or ""
        if not doc.strip():
            bad.append(f"{mod}: no docstring")
            continue
        if not re.search(rf"pixi run {re.escape(task)}(?![\w-])", doc):
            bad.append(f"{mod}: docstring does not name 'pixi run {task}'")
        words = len(first_sentence(doc).split())
        if words > MAX_FIRST_SENTENCE_WORDS:
            bad.append(f"{mod}: first sentence has {words} words, limit {MAX_FIRST_SENTENCE_WORDS}")
        low = doc.lower()
        for word in BANNED:
            if word in low:
                bad.append(f"{mod}: docstring uses '{word}'")
    # verify.sh must either run each published check or say it does not cover it.
    ran, not_covered = verify_lists()
    if not ran:
        bad.append("verify.sh: could not read its check list")
    names = {task_name(t) for t in TASKS.values()}
    for task in sorted(names - ran - not_covered):
        bad.append(f"verify.sh neither runs {task} nor names it NOT COVERED")
    for task in sorted(ran - names):
        bad.append(f"verify.sh runs {task}, which TASKS does not name")

    scanned = sorted((ROOT / "checks").glob("*.py"))
    # A gate that reads nothing passes for the wrong reason. Fail instead.
    if not scanned:
        print("DOCSTRING PROBLEMS")
        print("  the gate found no check scripts")
        return 1
    if bad:
        print("DOCSTRING PROBLEMS")
        for line in bad:
            print(" ", line)
        return 1
    print(f"docstrings OK ({len(TASKS)} docstrings, {len(scanned)} files, "
          f"{len(ran)} of them run by verify.sh)")
    return 0

sys.exit(main())
