#!/usr/bin/env bash
# Run every gate, the test suite and 13 of the 14 published checks.
#
# It leaves out census-vars, which needs the census environment, and names it NOT COVERED.
#
# With no argument it runs what a clean clone can run. The seven data-dependent checks then
# measure nothing, and the script names each one in a SKIPPED summary at the end.
#
# With --with-data it demands the local h5ads, fails if any data-dependent check still skips,
# and also runs compare-s3-run and versioning-run. It does not run the other notebooks.
#
# compare-s3-run regenerates its notebook. In a git checkout the script restores the committed
# version after, and refuses to run at all when that notebook holds uncommitted changes.
# Elsewhere it can do neither, and says so before the run.
# versioning-run follows the same rule, and it needs the fork from 'pixi run -e spatial sdpr'.
set -u
cd "$(dirname "$0")/.." || exit 1

with_data=0
case "${1:-}" in
  "") ;;
  --with-data) with_data=1 ;;
  *) echo "usage: tools/verify.sh [--with-data]"; exit 2 ;;
esac

ERYTHROCYTE=h5ads/8775a6c6-b960-43ae-9f76-45c4acda3621.h5ad
if [ "$with_data" -eq 1 ]; then
  if [ ! -d h5ads ] || [ -z "$(ls -A h5ads 2>/dev/null)" ]; then
    echo "--with-data: h5ads/ is missing or empty."
    echo "Run 'pixi run check-sparsity' to print the file names and the download URLs."
    exit 1
  fi
fi

fail=0
skipped=""
s3_state=""
SKIP_MARK="skipping: no local copy"
S3_MARK="no h5py comparison"
DATA_CHECKS=" check-sparsity check-soma check-policy check-codecs check-rectilinear check-delta check-gene-axis "

run() { echo "=== $*"; "$@" || { echo "FAILED: $*"; fail=1; }; }

run_check() {
  # Run one check and note when a data-dependent one measured nothing.
  echo "=== pixi run $1"
  out=$(pixi run --frozen "$1" 2>&1)
  status=$?
  echo "$out"
  if [ "$status" -ne 0 ]; then echo "FAILED: pixi run $1"; fail=1; return; fi
  case "$DATA_CHECKS" in
    *" $1 "*)
      case "$out" in *"$SKIP_MARK"*) skipped="$skipped $1" ;; esac
      ;;
  esac
  # check-s3 rebuilds the matrix either way, and compares it against h5py only when h5ads/
  # holds the same file.
  if [ "$1" = "check-s3" ]; then
    case "$out" in
      *"$S3_MARK"*) s3_state=unverified ;;
      *) s3_state=verified ;;
    esac
  fi
}

run bash tools/check_manifest.sh
run pixi install --locked
# The gates import nothing outside the standard library, but pixi gives a known interpreter.
for gate in check_paths check_docstrings check_notices check_readme check_tasks check_claims; do
  run pixi run --frozen python "tools/${gate}.py"
done

echo "=== pixi run test"
test_out=$(pixi run --frozen test 2>&1)
status=$?
echo "$test_out"
if [ "$status" -ne 0 ]; then echo "FAILED: pixi run test"; fail=1; fi
# Three tests read the local Braun h5ad and skip without it.
test_skips=$(echo "$test_out" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) skipped.*/\1/p' | tail -1)

for t in check check-tenx check-concat check-s3 check-sparsity check-soma \
         check-policy check-codecs check-rectilinear check-delta check-icechunk \
         check-manifest check-gene-axis; do
  run_check "$t"
done

if [ "$with_data" -eq 1 ]; then
  nb=notebooks/compare_backends_object_store.ipynb
  tracked=0
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 && tracked=1
  if [ ! -f "$ERYTHROCYTE" ]; then
    echo "FAILED: compare-s3-run needs $ERYTHROCYTE"; fail=1
  elif [ "$tracked" -eq 1 ] && ! git diff --quiet -- "$nb"; then
    echo "FAILED: $nb has uncommitted changes."
    echo "compare-s3-run regenerates it, and those changes cannot be recovered."
    echo "Commit or discard them first."
    fail=1
  else
    if [ "$tracked" -eq 0 ]; then
      echo "WARNING: this is not a git checkout, so the script cannot guard or restore $nb."
      echo "compare-s3-run will overwrite its committed outputs, and nothing can put them back."
    fi
    run pixi run --frozen compare-s3-run
    # The notebook was clean before the run, so git restores the committed outputs exactly.
    if [ "$tracked" -eq 1 ]; then
      if git checkout -- "$nb"; then
        echo "RESTORED: $nb, which compare-s3-run had regenerated."
      else
        echo "FAILED: could not restore $nb. It still holds the fresh outputs."
        fail=1
      fi
    fi
  fi

  nb=notebooks/spatialdata_versioning.ipynb
  fork=$PWD/vendor/spatialdata-1107/src
  if [ ! -d "$fork" ]; then
    echo "FAILED: versioning-run needs the SpatialData fork at $fork"
    echo "Run 'pixi run -e spatial sdpr' first. See docs/fork-pin.md."
    fail=1
  elif [ "$tracked" -eq 1 ] && ! git diff --quiet -- "$nb"; then
    echo "FAILED: $nb has uncommitted changes."
    echo "versioning-run regenerates it, and those changes cannot be recovered."
    fail=1
  else
    run env PYTHONPATH="$fork" pixi run -e spatial --frozen versioning-run
    if git checkout -- "$nb"; then
      echo "RESTORED: $nb, which versioning-run had regenerated."
    else
      echo "FAILED: could not restore $nb."; fail=1
    fi
  fi
fi

echo
if [ -n "$skipped" ]; then
  n=$(echo $skipped | wc -w | tr -d ' ')
  echo "SKIPPED: $n of 7 data-dependent checks measured nothing, because h5ads/ holds no copy."
  for t in $skipped; do echo "  $t"; done
  echo "  Each one printed its download URL. A green run here is not a measured run."
  echo "  Run 'tools/verify.sh --with-data' once the files are in place."
  if [ "$with_data" -eq 1 ]; then echo "FAILED: --with-data asked for a measured run"; fail=1; fi
else
  echo "MEASURED: all 7 data-dependent checks ran against local h5ads."
fi
if [ -n "$test_skips" ] && [ "$test_skips" != "0" ]; then
  echo "SKIPPED: $test_skips tests, which read the same local h5ad."
fi
# An empty state means check-s3 never reported, so the script says nothing about it.
if [ "$s3_state" = "unverified" ]; then
  echo "NOT VERIFIED: check-s3 rebuilt the matrix but did not compare it against h5py."
  echo "  That comparison needs the same h5ad in h5ads/, which holds no copy."
elif [ "$s3_state" = "verified" ]; then
  echo "VERIFIED: check-s3 compared its virtual read against h5py, on the local copy."
fi
if [ "$with_data" -eq 0 ]; then
  echo "NOT COVERED: census-vars, compare-s3-run and every other notebook."
else
  echo "NOT COVERED: census-vars, compare-public-run, compare-spatial-run, merfish-run,"
  echo "  notebook-run."
fi

exit "$fail"
