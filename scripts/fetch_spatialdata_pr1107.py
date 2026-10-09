"""Keep the spatialdata PR #1107 branch on a path that persists across reboots, with our patches.

Run: pixi run sdpr        (clone or update, then apply icechunk-SpatialData/upstream/000*.patch)

No dependency pin can hold the branch, for three reasons. It is a fork branch. Its tags are stale.
A name for it in the conda solve conflicts with the released `spatialdata` in the environment. So
Python reads it from disk through `PYTHONPATH`. Every notebook generator and the shapes tests
expect that.

`vendor/` is inside the project, and git ignores it. So the checkout persists across reboots, and
it never enters version control. A checkout in `/tmp` does not persist. A cleared `/tmp` leaves a
tree of empty directories that still imports. Thus a missing seam looks like a code bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REMOTE = "https://github.com/selmanozleyen/spatialdata.git"
BRANCH = "feat/zarr-store-class"
CHECKOUT = Path(__file__).resolve().parents[1] / "vendor" / "spatialdata-1107"
#: The file that must import, or the checkout has no use.
SEAM = "src/spatialdata/_store.py"
#: The patch series that the extension needs. The script applies it in order after each clone
#: or update.
PATCHES = sorted((Path(__file__).resolve().parents[1] / "icechunk-SpatialData" / "upstream").glob("000*.patch"))


def run(*command: str, at: Path | None = None) -> str:
    done = subprocess.run(["git", *(["-C", str(at)] if at else []), *command],
                          capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"git {' '.join(command)} failed:\n{done.stderr.strip()}")
    return done.stdout.strip()


def main() -> None:
    if (CHECKOUT / ".git").is_dir():
        print(f"updating {CHECKOUT}")
        run("fetch", "origin", BRANCH, at=CHECKOUT)
        run("checkout", BRANCH, at=CHECKOUT)
        run("reset", "--hard", f"origin/{BRANCH}", at=CHECKOUT)
    else:
        # A partial tree from a /tmp cleanup is worse than no tree: it imports and misleads.
        if CHECKOUT.exists():
            print(f"{CHECKOUT} exists without a .git; remove it and re-run")
            raise SystemExit(1)
        CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
        print(f"cloning {BRANCH} into {CHECKOUT}")
        run("clone", "-q", "--depth", "1", "-b", BRANCH, REMOTE, str(CHECKOUT))

    commit = run("rev-parse", "--short", "HEAD", at=CHECKOUT)
    if not (CHECKOUT / SEAM).is_file():
        raise SystemExit(f"{BRANCH} at {commit} has no {SEAM}; the seam this project patches has "
                         "moved, and the patch and its verifier need revisiting")

    for patch in PATCHES:
        run("apply", str(patch), at=CHECKOUT)
    source = CHECKOUT / "src"
    print(f"  {BRANCH} at {commit}, {SEAM} present, patched with {', '.join(p.name for p in PATCHES)}")
    # Always use an absolute path. nbconvert runs a kernel in the notebook's directory. So a
    # relative PYTHONPATH silently resolves to notebooks/vendor/..., and the seam is missing.
    # The error message then names the branch as the cause.
    print(f"\nUse it with:\n  PYTHONPATH={source} pixi run -e spatial <command>")
    if "--path" in sys.argv:
        print(source)


if __name__ == "__main__":
    main()
