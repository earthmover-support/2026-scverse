#!/usr/bin/env bash
# Assert that the repository holds the published subset and nothing excluded.
set -u
cd "$(dirname "$0")/.." || exit 1
fail=0

required=(
  LICENSE README.md .gitignore pixi.toml braun.py
  checks/_shards.py checks/h5ad_virtualization.py checks/virtualize_cellxgene.py
  checks/virtual_csr_concat.py checks/icechunk_many_arrays.py
  checks/census_manifest_scale.py checks/block_sparsity.py
  checks/tenx_matrix_virtualization.py checks/spatialdata_store_path.py
  notebooks/virtualize_braun.ipynb
  scripts/build_notebook.py scripts/_notebook.py
  tools/check_manifest.sh tools/check_paths.py tools/check_tasks.py
  tools/check_docstrings.py tools/check_notices.py tools/check_readme.py
  tools/check_claims.py tools/verify.sh
  icechunk-SpatialData/pyproject.toml
  icechunk-SpatialData/UPSTREAM.md
  icechunk-SpatialData/README.md
  icechunk-SpatialData/icechunk_spatialdata/__init__.py
  icechunk-SpatialData/tests/test_roundtrip.py
  icechunk-SpatialData/tests/test_exports.py
  icechunk-SpatialData/upstream/0001-require-ome-zarr-0.21.0.patch
  icechunk-SpatialData/upstream/0005-points-rows-through-the-frame-filesystem.patch
  notebooks/spatialdata_on_icechunk.ipynb
  notebooks/xenium_tutorial_virtual.ipynb
  notebooks/squidpy_xenium_virtual.ipynb
  notebooks/xenium_from_arraylake.ipynb
  notebooks/atera_from_arraylake.ipynb
  scripts/build_spatialdata_notebook.py
  scripts/fetch_spatialdata_pr1107.py
)
# An empty list would pass for the wrong reason.
[ "${#required[@]}" -eq 0 ] && { echo "REQUIRED LIST EMPTY"; fail=1; }
for p in "${required[@]}"; do
  [ -e "$p" ] || { echo "MISSING $p"; fail=1; }
done

forbidden=(
  zarr-SOMA docs/zarr-soma probes vendor patches data findings.md talk.md
  notebooks/compare_backends.ipynb notebooks/compare_backends_public_s3.ipynb
  notebooks/compare_backends_object_store.ipynb notebooks/compare_backends_spatial.ipynb
  notebooks/merfish_scene.ipynb
  checks/census_gene_space.py checks/chunk_policy.py checks/codec_policy.py
  checks/delta_decode_cost.py checks/gene_axis_amplification.py
  checks/rectilinear_chunks.py checks/soma_sparse_prototype.py
  scripts/_soma_side.py scripts/census_s3_side.py scripts/tiledbsoma_side.py
  icechunk-SpatialData/FLUX.md icechunk-SpatialData/TILES.md
  icechunk-SpatialData/spikes docs/superpowers
)
for p in "${forbidden[@]}"; do
  [ -e "$p" ] && { echo "PRESENT $p"; fail=1; }
done

# h5ads/ holds the downloaded source data that several checks measure. A reader is meant to
# have it, so the gate asserts only that git does not track it.
if git ls-files --error-unmatch h5ads >/dev/null 2>&1; then
  echo "TRACKED h5ads"; fail=1
fi

# No file may name the work that stays private.
if grep -rIlw -i \
    -e 'virtual_omics' -e 'soma-on-icechunk' -e 'zarr-SOMA' -e 'zarr_soma' \
    -e 'somacore' -e 'tiledbsoma' -e 'h5mu' -e 'mudata' -e 'findings.md' \
    -e 'datascale-poster' -e 'probes/' -e 'seam' \
    . --exclude-dir=.git --exclude-dir=.pixi --exclude-dir=tools \
    --exclude=pixi.lock >/tmp/soma_excluded_hits.txt 2>/dev/null; then
  if [ -s /tmp/soma_excluded_hits.txt ]; then
    echo "EXCLUDED TERMS IN:"; cat /tmp/soma_excluded_hits.txt; fail=1
  fi
fi
# A stale probes/ path must not survive the rename in Task 2.
if grep -rIl -e 'probes/' . --exclude-dir=.git --exclude-dir=.pixi --exclude-dir=tools \
    --exclude=pixi.lock >/tmp/soma_probe_hits.txt 2>/dev/null; then
  if [ -s /tmp/soma_probe_hits.txt ]; then
    echo "STALE probes/ PATH IN:"; cat /tmp/soma_probe_hits.txt; fail=1
  fi
fi

# The manifest must name the workspace, both platforms, and exactly the expected tasks.
for f in tiff plot squidpy tiffparser tiles lamin rust census; do
  grep -q "feature\.$f" pixi.toml && { echo "FEATURE LEFT: $f"; fail=1; }
done
grep -q 'platforms = \["osx-arm64", "linux-64"\]' pixi.toml || { echo "WORKSPACE PLATFORMS WRONG"; fail=1; }
python3 - <<'PY' || fail=1
import sys, tomllib
m = tomllib.load(open("pixi.toml", "rb"))
if m["workspace"]["name"] != "2026-scverse":
    print("WORKSPACE NAME:", m["workspace"]["name"]); sys.exit(1)
if sorted(m["workspace"]["platforms"]) != ["linux-64", "osx-arm64"]:
    print("PLATFORMS:", m["workspace"]["platforms"]); sys.exit(1)
envs = set(m.get("environments", {}))
if envs != {"spatial"}:
    print("ENVIRONMENTS:", envs); sys.exit(1)
tasks = set(m.get("tasks", {}))
for feat in m.get("feature", {}).values():
    tasks |= set(feat.get("tasks", {}))
expected = {"lab","check","check-s3","check-concat","check-icechunk",
 "check-manifest","check-sparsity","check-tenx","check-store-path",
 "equivalence","equivalence-run","versioning","versioning-run",
 "notebook","notebook-run","spatialdata","spatialdata-run","sdpr","spike-test"}
if tasks != expected:
    print("TASKS extra:", sorted(tasks-expected), "missing:", sorted(expected-tasks))
    sys.exit(1)
PY

[ "$fail" -eq 0 ] && echo "manifest OK (${#required[@]} required, ${#forbidden[@]} forbidden)"
exit "$fail"
