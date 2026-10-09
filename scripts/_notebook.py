"""Cell accumulator shared by the notebook generators.

Each build_*.py appends to `C` through `md`/`code` and finishes with `write("name.ipynb")`.
"""

import ast
import pathlib

import nbformat as nbf

C = []

# Notebooks are in notebooks/, so the first code cell finds the project root and puts it on
# sys.path. BOOTSTRAP_TERSE is the same block without the explanatory comments.
BOOTSTRAP = """
import pathlib
import sys

# Notebooks are in notebooks/, so find the project root. Do not assume the cwd.
# The name is not REPO, because in this project REPO means an Arraylake repo.
PROJECT_ROOT = next(p for p in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]
                    if (p / "pixi.toml").exists())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
"""

BOOTSTRAP_TERSE = """
import pathlib
import sys

PROJECT_ROOT = next(p for p in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]
                    if (p / "pixi.toml").exists())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
"""


def md(source: str) -> None:
    C.append(nbf.v4.new_markdown_cell(source.strip()))


def code(source: str, *, tags: tuple[str, ...] = ()) -> None:
    # Parse each cell before the write. Otherwise a quoting error in a generator shows only as a
    # SyntaxError halfway through a long execution. Magics are not Python, so blank them first.
    ast.parse("\n".join("" if line.lstrip().startswith("%") else line
                        for line in source.splitlines()))
    cell = nbf.v4.new_code_cell(source.strip())
    if tags:
        # nbclient skips a cell with the tag `skip-execution`. Thus a GUI cell stays in the
        # notebook, and a reader runs it by hand.
        cell.metadata["tags"] = list(tags)
    C.append(cell)


def write(filename: str) -> None:
    nb = nbf.v4.new_notebook()
    nb["cells"] = C
    nb.metadata.kernelspec = {"display_name": "Python 3", "language": "python", "name": "python3"}
    out = pathlib.Path(__file__).parent.parent / "notebooks" / filename
    nbf.write(nb, str(out))
    print(f"wrote {out} ({len(C)} cells)")
