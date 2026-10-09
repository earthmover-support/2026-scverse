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
  checks/tenx_matrix_virtualization.py
  notebooks/virtualize_braun.ipynb
  scripts/build_notebook.py scripts/_notebook.py
  tools/check_manifest.sh tools/check_paths.py tools/check_tasks.py
  tools/check_docstrings.py tools/check_notices.py tools/check_readme.py
  tools/check_claims.py tools/verify.sh
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

# The manifest must hold only the census feature, and census must cover both platforms.
for f in spatial tiff plot squidpy tiffparser tiles lamin rust; do
  grep -q "feature\.$f" pixi.toml && { echo "FEATURE LEFT: $f"; fail=1; }
done
grep -q 'platforms = \["osx-arm64", "linux-64"\]' pixi.toml || { echo "WORKSPACE PLATFORMS WRONG"; fail=1; }
python3 - <<'PY' || fail=1
import sys, tomllib
m = tomllib.load(open("pixi.toml", "rb"))
plats = m["feature"]["census"].get("platforms", [])
if sorted(plats) != ["linux-64", "osx-arm64"]:
    print("CENSUS PLATFORMS:", plats); sys.exit(1)
envs = set(m.get("environments", {}))
if envs != {"census"}:
    print("ENVIRONMENTS:", envs); sys.exit(1)
tasks = set(m.get("tasks", {}))
expected = {"lab","test","test-slow","compare-public","compare-public-run",
 "compare-spatial","compare-spatial-run","merfish","merfish-run",
 "compare-s3","compare-s3-run","notebook","notebook-run",
 "check","check-tenx","check-concat","check-s3","check-sparsity","check-soma",
 "check-policy","check-codecs","check-rectilinear","check-delta","check-icechunk",
 "check-manifest","check-gene-axis"}
if tasks != expected:
    print("TASKS extra:", sorted(tasks-expected), "missing:", sorted(expected-tasks)); sys.exit(1)
PY

[ "$fail" -eq 0 ] && echo "manifest OK (${#required[@]} required, ${#forbidden[@]} forbidden)"
exit "$fail"
