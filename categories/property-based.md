# Property-Based Testing

For pure functions with stated invariants, generated inputs multiply
confidence cheaply. Complement — never replace — deterministic
boundary tests (PBT is weak exactly at named boundaries).

## Method
1. Identify invariants from requirements: output ranges, roundtrips,
   monotonicity (more X -> not-less Y), invariants under permutation,
   algebraic laws.
2. Python: `hypothesis` (@given + strategies constrained to valid
   domains). Java: jqwik. If the lib isn't a project dep, write the
   property test but mark it OPTIONAL in TEST_DESIGN.
3. Always include `example()`/seed cases for the known boundary
   values so PBT can't skip the edges.
4. One property = one test. Max ~5 properties per function.

## Budget
one per identified invariant. If invariants already covered
deterministically AND domain is small, mark category "(none)
justified" in TEST_DESIGN.

## Checklist
- [ ] strategies restricted to the VALID domain (invalid-domain
      strategies belong to exception tests)
- [ ] boundary examples pinned
- [ ] no property that just re-implements the function under test
