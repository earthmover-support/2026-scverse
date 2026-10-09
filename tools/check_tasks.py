"""Assert that every `pixi run <task>` in the documentation names a task that pixi.toml defines."""

import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".git", ".pixi", "tools", "vendor", "__pycache__"}
RUN_RE = re.compile(r"pixi run (?:(?:-e|--environment)[ =]\S+\s+)?([A-Za-z0-9][A-Za-z0-9_-]*)")
# `pixi run python x.py` runs the environment's interpreter, not a task the manifest defines.
INTERPRETERS = {"python"}

def defined_tasks():
    manifest = tomllib.loads((ROOT / "pixi.toml").read_text())
    tasks = set(manifest.get("tasks", {}))
    for feature in manifest.get("feature", {}).values():
        tasks |= set(feature.get("tasks", {}))
    return tasks

def files():
    for p in ROOT.rglob("*"):
        if any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix in {".md", ".py", ".ipynb"} and p.is_file():
            yield p

def main():
    known = defined_tasks()
    bad = []
    scanned = 0
    for p in files():
        scanned += 1
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            for m in RUN_RE.finditer(line):
                if m.group(1) in INTERPRETERS:
                    continue
                if m.group(1) not in known:
                    bad.append(f"{p.relative_to(ROOT)}:{n}: {m.group(1)}")
    # A gate that walks nothing passes for the wrong reason. Fail instead.
    if not scanned:
        print("UNKNOWN TASKS")
        print("  the gate scanned no files")
        return 1
    if bad:
        print("UNKNOWN TASKS")
        for line in sorted(bad):
            print(" ", line)
        return 1
    print(f"tasks OK ({scanned} files)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
