# Control-Flow / Basis-Path Coverage

Cyclomatic complexity (CC) sets the floor: you need at least CC
independent execution paths through each function to cover all
branches.

## Method
1. `scripts/analyze_repo.py` reports cc per function. cc = 1 +
   decisions. A cc=8 function needs >=8 path-distinct tests for full
   branch coverage.
2. For each function, enumerate basis paths (distinct decision
   outcomes), then pick inputs forcing each. Merge with BVA/EP
   cases — the same test often covers a boundary and a path.
3. Targets: 100% statement AND 100% branch coverage of the units you
   test. Measure with `coverage run --branch` (py) / jacoco (java) /
   equivalent. Report uncovered lines in TEST_DESIGN if some are
   unreachable-by-contract (defensive code) — list them, don't fake
   tests for them.
4. Loop paths: zero iterations, one, many, and early-exit (break) —
   each is a distinct basis path.

## Budget
sum over functions of cc, minus paths already covered by other
categories' tests (count each test once against all criteria it
satisfies).

## Checklist
- [ ] branch coverage measured, not assumed
- [ ] every uncovered line has a written disposition (dead code,
      defensive, or genuinely missed -> add test)
- [ ] loop 0/1/many/early-exit covered
