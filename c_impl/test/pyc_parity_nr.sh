#!/bin/bash
# pyc_parity_nr.sh -- Python<->C numeric parity check for the NR library.
#
# Compares the C library with the Python reference on fixed inputs, in two layers:
#   L1  std-math C (SIMD=0, -DUSE_STANDARD_MATH, none of the six USE_* optimizations) vs Python.
#       A deviation is a Python<->C sync bug.
#   L2  shipping C (Makefile default: SIMD=1, fast math, six USE_* flags) vs the std-math C.
#       This is the accepted fast-math approximation; its tolerance is fixed.
# Scenarios: 5 grids (8k/128, 8k/256, 16k/256, 16k/512, 48k/1024) x 4 strengths x inputs (speech in
# noise, scene change, music, synthetic digital-silence gaps, zeroed bins, level scaling, int16
# rounding, babble at -80 dBFS, make-up gain on), as gain-level and as end-to-end waveform
# comparisons. See python/tools/pyc_parity_nr.py for the scenario table, metrics and verdicts.
#
# Known gaps are listed in test/pyc_parity/expected_red.json. They may exceed the tolerance without
# failing the run; a listed scenario that turns green fails the run (delete its entry).
#
# Exit code: 0 pass, 1 failure (unexpected red / unexpected green / driver error), 2 infrastructure
# error (missing inputs, bad build flags, build failure).
#
# Usage: test/pyc_parity_nr.sh [options]
#   --json FILE            machine-readable result (default: ./pyc_parity_nr.json)
#   --work DIR             build/scratch directory (default: a fresh mktemp dir, removed at exit
#                          unless --keep). Must not be inside this repository.
#   --keep                 keep the scratch directory
#   --only REGEX           run only the scenario ids matching REGEX (see --list)
#   --no-e2e               skip the end-to-end waveform scenarios
#   --list                 print the scenario ids and exit
#   --brief                table: print only rows that are not GREEN / RED_EXPECTED
#   --progress             print one line per scenario to stderr
#   --expected-red FILE    registry of expected-red scenarios (default: test/pyc_parity/expected_red.json)
#   --emit-expected-red F  write the current red set as a registry candidate (see the tool's docstring)
#   --c-impl DIR           build the C library from another c_impl tree (mutation experiments)
#   --ac-dir DIR           audiolib checkout for that build (make COMMON_DIR=...)
#   --python PY            interpreter with numpy/scipy/pyyaml (default: $PYC_PARITY_PYTHON or python3)
# The Python reference, the pinned inputs and the registry always come from the tree this script lives
# in; the C library and its two drivers come from --c-impl.

set -u
set -o pipefail

die() { echo "pyc_parity_nr: $*" >&2; exit 2; }

SELF_DIR=$(cd "$(dirname "$0")" && pwd -P)
TOOL=$SELF_DIR/../../python/tools/pyc_parity_nr.py
DATA=$SELF_DIR/pyc_parity/data
C_IMPL=$(cd "$SELF_DIR/.." && pwd -P)
REGISTRY=$SELF_DIR/pyc_parity/expected_red.json
PY=${PYC_PARITY_PYTHON:-python3}
JSON=./pyc_parity_nr.json
WORK=
KEEP=0
AC_DIR_OPT=
PASS_THROUGH=()

while [ $# -gt 0 ]; do
  case $1 in
    --json) JSON=${2:?}; shift 2 ;;
    --work) WORK=${2:?}; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --only) PASS_THROUGH+=(--only "${2:?}"); shift 2 ;;
    --no-e2e) PASS_THROUGH+=(--no-e2e); shift ;;
    --list) PASS_THROUGH+=(--list); shift ;;
    --brief) PASS_THROUGH+=(--brief); shift ;;
    --progress) PASS_THROUGH+=(--progress); shift ;;
    --expected-red) REGISTRY=${2:?}; shift 2 ;;
    --emit-expected-red) PASS_THROUGH+=(--emit-expected-red "${2:?}"); shift 2 ;;
    --c-impl) C_IMPL=$(cd "${2:?}" && pwd -P) || die "no such c_impl dir"; shift 2 ;;
    --ac-dir) AC_DIR_OPT=$(cd "${2:?}" && pwd -P) || die "no such audiolib dir"; shift 2 ;;
    --python) PY=${2:?}; shift 2 ;;
    -h|--help) sed -n '2,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option '$1' (try --help)" ;;
  esac
done

# A stray DEBUG=release or CFLAGS in the caller's environment would otherwise be rejected by (or
# silently change) the Makefile.
export LC_ALL=C TZ=UTC PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1
unset DEBUG SIMD BACKEND EXTRA_CFLAGS EXTRA_LDFLAGS CFLAGS CXXFLAGS CPPFLAGS LDFLAGS WERROR NO_STDIO \
      TOOLCHAIN_CHECK CC CXX AR RANLIB OBJ_ROOT BIN_ROOT COMMON_DIR COMMON_LIB MAKEFLAGS MFLAGS MAKELEVEL \
      DIST_ROOT HOSTCC ALLOW_DIRTY_PUBLISH ALLOW_UNTRACKED_PUBLISH ATTEST_STAMP

command -v "$PY" >/dev/null 2>&1 || die "python '$PY' not found"
[ -f "$TOOL" ] || die "missing $TOOL"
[ -f "$REGISTRY" ] || die "missing $REGISTRY"
[ -f "$DATA/SHA256SUMS" ] || die "missing $DATA/SHA256SUMS"

LISTING=0
for a in ${PASS_THROUGH[@]+"${PASS_THROUGH[@]}"}; do [ "$a" = --list ] && LISTING=1; done
if [ $LISTING = 1 ]; then
  exec "$PY" -B "$TOOL" --data "$DATA" --expected-red "$REGISTRY" ${PASS_THROUGH[@]+"${PASS_THROUGH[@]}"}
fi

# The pinned wavs are not tracked (large, derived from the fixed NR regression inputs):
# rebuild them with test/pyc_parity/make_pyc_parity_data.py <dir holding the source wavs>.
( cd "$DATA" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1 ) || die "input wavs in $DATA are missing or do not match SHA256SUMS (rebuild with test/pyc_parity/make_pyc_parity_data.py <source wav dir>)"

# ---- scratch directory (never inside the repository) -------------------------------------------------
OWN_WORK=0
REPO_ROOT=$(cd "$SELF_DIR/../.." && pwd -P)
inside_repo() { case $1/ in "$REPO_ROOT"/*|"$C_IMPL"/*) return 0 ;; esac; return 1; }
if [ -z "$WORK" ]; then
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/pyc_parity_nr.XXXXXX") || die "cannot create scratch directory"
  OWN_WORK=1
else
  case $WORK in /*) ;; *) WORK=$PWD/$WORK ;; esac
  inside_repo "$WORK" && die "scratch directory $WORK is inside the repository"
  mkdir -p "$WORK" || die "cannot create $WORK"
fi
WORK=$(cd "$WORK" && pwd -P)
if inside_repo "$WORK"; then
  [ $OWN_WORK = 1 ] && rm -rf "$WORK"
  die "scratch directory $WORK is inside the repository"
fi
cleanup() { if [ $OWN_WORK = 1 ] && [ $KEEP = 0 ]; then rm -rf "$WORK"; fi; }
trap cleanup EXIT
mkdir -p "$WORK/logs" "$WORK/tmp"
export OBJ_ROOT=$WORK/obj BIN_ROOT=$WORK/bin

# ---- builds -------------------------------------------------------------------------------------------
MAKE_EXTRA=()
[ -n "$AC_DIR_OPT" ] && MAKE_EXTRA+=("COMMON_DIR=$AC_DIR_OPT")

# build_layer <name> <make args...>: builds parity_runner (self-check reference) and the two drivers,
# then sets BD (bin dir) and DEFS (the -D flags the objects were compiled with, from config.manifest).
build_layer() {
  local name=$1; shift
  if ! make -C "$C_IMPL" BACKEND=ne10 ${MAKE_EXTRA[@]+"${MAKE_EXTRA[@]}"} "$@" parity pyc-parity \
        >"$WORK/logs/build_$name.log" 2>&1; then
    tail -20 "$WORK/logs/build_$name.log" >&2
    die "build of layer $name failed (log: $WORK/logs/build_$name.log)"
  fi
  BD=$(make -s --no-print-directory -C "$C_IMPL" BACKEND=ne10 ${MAKE_EXTRA[@]+"${MAKE_EXTRA[@]}"} "$@" print-bin-dir) \
    || die "cannot locate the $name bin dir"
  [ -f "$BD/config.manifest" ] || die "no config.manifest in $BD"
  DEFS=$(grep -o -- '-D[A-Za-z0-9_]*' "$BD/config.manifest" | sort -u | tr '\n' ' ')
}

build_layer L1 DEBUG=1 SIMD=0;   BD1=$BD; DEFS1=$DEFS
build_layer L2;                  BD2=$BD; DEFS2=$DEFS
[ "$BD1" != "$BD2" ] || die "L1 and L2 resolved to the same build directory"

mkdir -p "$(dirname "$JSON")"
rm -f "$JSON"
"$PY" -B "$TOOL" \
  --data "$DATA" --expected-red "$REGISTRY" --json "$JSON" --work "$WORK/tmp" --clean-work \
  --gain-l1 "$BD1/pyc_gain_driver" --gain-l2 "$BD2/pyc_gain_driver" \
  --e2e-l1 "$BD1/pyc_e2e_driver" --e2e-l2 "$BD2/pyc_e2e_driver" \
  --runner-l1 "$BD1/parity_runner" --runner-l2 "$BD2/parity_runner" \
  --defines-l1 "$DEFS1" --defines-l2 "$DEFS2" \
  ${PASS_THROUGH[@]+"${PASS_THROUGH[@]}"}
rc=$?
[ -f "$JSON" ] && echo "pyc_parity_nr: JSON written to $JSON" >&2
exit $rc
