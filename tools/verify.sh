#!/usr/bin/env bash
# Run every gate, the test suite and all eight published checks.
#
# With no argument it runs what a clean clone can run. The one data-dependent check then
# measures nothing, and the script names it in a SKIPPED summary at the end.
#
# With --with-data it demands the local h5ads, fails if that check still skips, and also runs
# versioning-run. It does not run the notebooks.
#
# versioning-run regenerates its notebook. In a git checkout the script restores the committed
# version after, and refuses to run at all when that notebook holds uncommitted changes.
# It needs the fork from 'pixi run -e spatial sdpr'.
set -u
cd "$(dirname "$0")/.." || exit 1

with_data=0
case "${1:-}" in
  "") ;;
  --with-data) with_data=1 ;;
  *) echo "usage: tools/verify.sh [--with-data]"; exit 2 ;;
esac

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
DATA_CHECKS=" check-sparsity "

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

echo "=== pixi run -e spatial extension-test"
test_out=$(pixi run -e spatial --frozen extension-test 2>&1)
status=$?
echo "$test_out"
if [ "$status" -ne 0 ]; then echo "FAILED: pixi run -e spatial extension-test"; fail=1; fi
# Several tests need the fork on PYTHONPATH and skip without it. See docs/fork-pin.md.
test_skips=$(echo "$test_out" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) skipped.*/\1/p' | tail -1)

for t in check check-tenx check-concat check-s3 check-sparsity check-icechunk \
         check-manifest check-store-path; do
  run_check "$t"
done

if [ "$with_data" -eq 1 ]; then
  tracked=0
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 && tracked=1

  nb=notebooks/spatialdata_versioning.ipynb
  fork=$PWD/vendor/spatialdata-1107/src
  if [ "$tracked" -eq 0 ]; then
    # Outside a git tree the committed outputs are the only copy, and a run destroys them.
    echo "FAILED: --with-data regenerates a notebook and this is not a git checkout."
    echo "The run is skipped, because nothing could restore $nb. Use a git clone."
    fail=1
  elif [ ! -d "$fork" ]; then
    echo "FAILED: versioning-run needs the SpatialData fork at $fork"
    echo "Run 'pixi run -e spatial sdpr' first. See docs/fork-pin.md."
    fail=1
  elif ! git diff --quiet HEAD -- "$nb"; then
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
  echo "SKIPPED: $n of 1 data-dependent check measured nothing, because h5ads/ holds no copy."
  for t in $skipped; do echo "  $t"; done
  echo "  It printed its download URL. A green run here is not a measured run."
  echo "  Run 'tools/verify.sh --with-data' once the files are in place."
  if [ "$with_data" -eq 1 ]; then echo "FAILED: --with-data asked for a measured run"; fail=1; fi
else
  echo "MEASURED: the data-dependent check ran against local h5ads."
fi
if [ -n "$test_skips" ] && [ "$test_skips" != "0" ]; then
  # Two reasons produce a skip: the absent fork, and an optional package the lock omits.
  fork_skips=$(echo "$test_out" |
    awk '/^SKIPPED \[/ && /pinned fork on PYTHONPATH/ {gsub(/[^0-9]/, "", $2); n += $2}
         END {print n + 0}')
  # The awk matches one skip reason. A reworded reason prints a meaningless zero, so a zero
  # fails unless the caller already put the fork on PYTHONPATH, where zero is the right count.
  pp="${PYTHONPATH:-}"
  if [ "$fork_skips" -eq 0 ] && [ "${pp#*spatialdata-1107}" = "$pp" ]; then
    echo "FAILED: $test_skips tests skipped and none names the fork on PYTHONPATH."
    echo "  The skip reason changed, so tools/verify.sh cannot classify these skips."
    fail=1
  else
    echo "SKIPPED: $test_skips tests. $fork_skips of them need the fork on PYTHONPATH."
    echo "  See docs/fork-pin.md. The rest need a package this environment does not hold."
  fi
fi
# An empty state means check-s3 never reported, so the script says nothing about it.
if [ "$s3_state" = "unverified" ]; then
  echo "NOT VERIFIED: check-s3 rebuilt the matrix but did not compare it against h5py."
  echo "  That comparison needs the same h5ad in h5ads/, which holds no copy."
elif [ "$s3_state" = "verified" ]; then
  echo "VERIFIED: check-s3 compared its virtual read against h5py, on the local copy."
fi
if [ "$with_data" -eq 0 ]; then
  echo "NOT COVERED: every notebook."
else
  echo "NOT COVERED: equivalence-run, notebook-run and spatialdata-run."
fi

exit "$fail"
