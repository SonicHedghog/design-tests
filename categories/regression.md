# Regression / Characterization

Guard behaviors that are easy to silently break. This category is
what keeps a generated suite REPLACEMENT-grade vs an existing suite.

## Method
1. If the repo has an existing test suite: diff the generated
   inventory against it — any behavior the old suite pins that the
   generated suite omits is a regression hole; add a test or write a
   justification for dropping it in TEST_DESIGN.
2. Idempotence: calling the same op twice == once (where sensible).
3. Determinism: only worth a row when the spec pins a STABLE value a
   second call could break (cache pollution, module-state mutation,
   RNG seeding). f(x)==f(x) alone is a tautology — always true for
   pure functions, forbidden by oracle lint.
4. Deprecation paths, documented quirks, platform edge behavior in
   README/CHANGELOG — pin them if specified.

## Budget
whatever the diff/holes require; typically 3-10.

## Checklist
- [ ] existing-suite behavior list reconciled (when suite exists)
- [ ] every dropped old-test behavior justified in writing
- [ ] determinism rows only where spec pins a breakable stable value
