"""Clone an upstream project, apply a patch or a series from this directory, and run under it.

Each verifier that carries a patch proves that a *fix* works. Such a verifier did not prove that
the **patch file** produces that fix. It ran against the tree that a caller put on `PYTHONPATH`.
The caller patched that tree by hand or by other means. The verifier can then report success
against a tree that the patch never produced. Thus the verifier must check the step that applies
the patch. Only then can a reader trust the result of the verifier.

Each verifier thus re-executes itself in a subprocess. The subprocess runs against a new clone that
the verifier patched. The patch file is then the item under test. A defect in the patch file shows
as a verifier failure, not as an error in the README.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: The parent sets this variable in the child. The child then runs the checks and does not
#: bootstrap again.
MARKER = "VERIFY_UPSTREAM_SRC"


def clone(url: str, ref: str | None, into: Path) -> str:
    """Shallow-clone `url` at `ref`. Return the short hash of the commit that the clone got."""
    command = ["git", "clone", "-q", "--depth", "1"]
    if ref:
        command += ["-b", ref]
    subprocess.run([*command, url, str(into)], check=True)
    return subprocess.run(["git", "-C", str(into), "rev-parse", "--short", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def apply(patch: Path, into: Path) -> None:
    """Apply `patch` to a checkout. Exit with the git error if the patch does not apply cleanly.

    `git apply --check` runs first. Thus a malformed or stale patch shows as that error, not as a
    half-applied tree.
    """
    for stage in (["--check"], []):
        done = subprocess.run(["git", "-C", str(into), "apply", *stage, str(patch)],
                              capture_output=True, text=True)
        if done.returncode:
            raise SystemExit(
                f"{patch.name} does not apply to this checkout:\n{done.stderr.strip()}"
            )


def under_patched_clone(url: str, ref: str | None, patch_name: str | list[str] | None = None, *,
                        subdir: str = "src", prepare=None) -> Path:
    """Return the source root to run against. Re-execute this script if necessary.

    A verifier calls this function at its top. In the parent, the function clones the upstream and
    applies the named patch. It then re-runs the caller with `PYTHONPATH` set to the patched source.
    In the child, the function only returns that source path.

    `patch_name=None` gives an unpatched checkout. A two-sided verifier uses it for its negative
    case. A list applies a series in order. Thus the function verifies a patch that depends on
    another patch against that series. It does not use a stack prepared by hand.

    `prepare(source)` runs after the patch step and before re-execution. It is for a project whose
    source tree alone is not importable. An example is a compiled extension that only ships in the
    wheel.

    `subdir` names the importable directory. The caller states it, and the function does not guess.
    osml-imagery-io has a `src/` of Rust and a `python/` of Python. A guess picks the wrong one.
    """
    existing = os.environ.get(MARKER)
    if existing:
        return Path(existing)

    workdir = Path(tempfile.mkdtemp(prefix="verify-upstream-"))
    commit = clone(url, ref, workdir)
    label = "unpatched"
    if patch_name:
        names = [patch_name] if isinstance(patch_name, str) else list(patch_name)
        for name in names:
            apply(Path(__file__).parent / name, workdir)
        label = f"patched with {', '.join(names)}"
    print(f"cloned {url.rsplit('/', 1)[-1]} at {commit} into a temporary checkout, {label}\n",
          flush=True)

    source = workdir / subdir
    if not source.is_dir():
        raise SystemExit(f"{url} has no {subdir}/ to import from")
    if prepare is not None:
        prepare(source)
    environment = dict(os.environ, **{MARKER: str(source),
                                      "PYTHONPATH": str(source)})
    raise SystemExit(subprocess.run([sys.executable, *sys.argv], env=environment).returncode)
