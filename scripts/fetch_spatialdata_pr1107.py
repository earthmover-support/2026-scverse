"""Check out the spatialdata PR #1107 tree at a pinned commit, on a path that persists.

Run: pixi run -e spatial sdpr        (clone, then check out the pinned commit)
The `--path` flag also prints the source path alone, for use in scripts.

No dependency pin can hold the tree. The fork's tags are stale, so its version reads below the
one that `icechunk-spatialdata` requires. Python reads the tree from disk through `PYTHONPATH`.

`vendor/` is inside the project, and git ignores it. So the checkout persists across reboots, and
it never enters version control. A checkout in `/tmp` does not persist. A cleared `/tmp` leaves a
tree of empty directories that still imports. Thus a missing store module looks like a code bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REMOTE = "https://github.com/li-em/spatialdata.git"
BRANCH = "li-em/store-without-a-path"
#: PR #1107 plus the five commits that lift the store-path limit.
COMMIT = "391427b274e046b7068348aa68987589e3773748"
CHECKOUT = Path(__file__).resolve().parents[1] / "vendor" / "spatialdata-1107"
#: The store module. The checkout has no use without it.
STORE_MODULE = "src/spatialdata/_store.py"


def run(*command: str, at: Path | None = None) -> str:
    done = subprocess.run(["git", *(["-C", str(at)] if at else []), *command],
                          capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"git {' '.join(command)} failed:\n{done.stderr.strip()}")
    return done.stdout.strip()


def main() -> None:
    if not (CHECKOUT / ".git").is_dir():
        # A partial tree from a /tmp cleanup is worse than no tree: it imports and misleads.
        if CHECKOUT.exists():
            print(f"{CHECKOUT} exists without a .git; remove it and re-run")
            raise SystemExit(1)
        CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
        print(f"cloning {BRANCH} into {CHECKOUT}")
        run("clone", "-q", "-b", BRANCH, REMOTE, str(CHECKOUT))
    run("checkout", "-q", COMMIT, at=CHECKOUT)

    head = run("rev-parse", "HEAD", at=CHECKOUT)
    if head != COMMIT:
        raise SystemExit(f"checkout is at {head[:7]}, not {COMMIT[:7]}")
    if not (CHECKOUT / STORE_MODULE).is_file():
        raise SystemExit(f"{COMMIT[:7]} has no {STORE_MODULE}; the checkout is wrong")

    source = CHECKOUT / "src"
    print(f"  {COMMIT[:7]}, {STORE_MODULE} present")
    # Always use an absolute path. nbconvert runs a kernel in the notebook's directory. So a
    # relative PYTHONPATH silently resolves to notebooks/vendor/..., and the store module is missing.
    print(f"\nUse it with:\n  PYTHONPATH={source} pixi run -e spatial <command>")
    if "--path" in sys.argv:
        print(source)


if __name__ == "__main__":
    main()
