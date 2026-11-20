#!/usr/bin/env bash
# Run all seven design-tests checkers against a run dir, tolerating
# missing inputs (each checker is skipped with a note when its inputs
# are absent).
#
# Usage: test_checkers.sh <run_dir> [--src SRC_DIR] [--tests TESTS_DIR]
#                         [--spec boundaries.json]
#
#   run_dir   contains TEST_DESIGN.md and (usually) tests/; journal.txt
#             and metrics.json are picked up for claim_reconcile.py
#   --src     implementation source dir for surface_closure.py and
#             guard_census.py (required for both to run)
#   --tests   tests dir override (default: <run_dir>/tests)
#   --spec    boundaries.py-shaped JSON spec for boundary_audit.py
#
# Exit: 0 if every checker that ran was clean (skipped checkers don't
# fail), 1 if any ran and reported findings, 2 on usage error.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ $# -lt 1 ]; then
    sed -n '2,15p' "$0"
    exit 2
fi
RUN="$1"; shift
SRC=""; TESTS=""; SPEC=""
while [ $# -gt 0 ]; do
    case "$1" in
        --src)   SRC="$2";   shift 2 ;;
        --tests) TESTS="$2"; shift 2 ;;
        --spec)  SPEC="$2";  shift 2 ;;
        *) echo "test_checkers: unknown arg '$1'" >&2; exit 2 ;;
    esac
done
DESIGN="$RUN/TEST_DESIGN.md"
[ -z "$TESTS" ] && TESTS="$RUN/tests"

fail=0; ran=0
run() {  # run <label> <cmd...>
    label="$1"; shift
    ran=$((ran + 1))
    echo "=== $label"
    if "$@"; then
        echo "--- $label: clean"
    else
        rc=$?
        echo "--- $label: findings (exit $rc)"
        fail=1
    fi
    echo
}

if [ -f "$DESIGN" ]; then
    args=("$DESIGN")
    [ -d "$TESTS" ] && args+=(--tests "$TESTS")
    run ledger_reconcile python3 "$HERE/ledger_reconcile.py" "${args[@]}"
else
    echo "=== ledger_reconcile: skipped (no $DESIGN)"; echo
fi

if [ -d "$TESTS" ]; then
    run oracle_lint python3 "$HERE/oracle_lint.py" "$TESTS"
else
    echo "=== oracle_lint: skipped (no $TESTS)"; echo
fi

if [ -d "$TESTS" ]; then
    run dup_sweep python3 "$HERE/dup_sweep.py" "$TESTS"
else
    echo "=== dup_sweep: skipped (no $TESTS)"; echo
fi

if [ -n "$SRC" ] && [ -d "$SRC" ] && [ -d "$TESTS" ]; then
    run surface_closure python3 "$HERE/surface_closure.py" "$SRC" "$TESTS"
else
    echo "=== surface_closure: skipped (need --src dir and tests dir)"; echo
fi

if [ -f "$DESIGN" ] || [ -n "$SPEC" ]; then
    args=()
    [ -f "$DESIGN" ] && args+=(--design "$DESIGN")
    [ -d "$TESTS" ] && args+=(--tests "$TESTS")
    [ -n "$SPEC" ] && args+=(--spec "$SPEC")
    run boundary_audit python3 "$HERE/boundary_audit.py" "${args[@]}"
else
    echo "=== boundary_audit: skipped (no TEST_DESIGN.md, no --spec)"; echo
fi

if [ -f "$DESIGN" ] && [ -n "$SRC" ] && [ -d "$SRC" ]; then
    run guard_census python3 "$HERE/guard_census.py" "$DESIGN" \
        --case-dir "$SRC"
else
    echo "=== guard_census: skipped (need TEST_DESIGN.md and --src dir)"; echo
fi

if [ -f "$DESIGN" ]; then
    args=("$DESIGN")
    [ -f "$RUN/journal.txt" ] && args+=(--journal "$RUN/journal.txt")
    [ -f "$RUN/metrics.json" ] && args+=(--metrics "$RUN/metrics.json")
    [ -d "$TESTS" ] && args+=(--tests "$TESTS")
    run claim_reconcile python3 "$HERE/claim_reconcile.py" "${args[@]}"
else
    echo "=== claim_reconcile: skipped (no $DESIGN)"; echo
fi

if [ "$fail" -eq 0 ]; then
    echo "test_checkers: OK ($ran checker(s) run)"
else
    echo "test_checkers: FAIL — findings above"
fi
exit "$fail"
