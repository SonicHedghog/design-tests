# Mutation Testing (suite self-audit)

Coverage shows what runs; mutation shows what is VERIFIED. A line can
be executed and still untested. Use mutation thinking to audit the
suite — code coverage is evidence, not proof.

## Method
1. Mental mutants per unit (no tool needed): flip a comparison
   (>= -> >), drop a term in an AND, off-by-one a bound, remove a
   rounding/clamping step, swap a return constant. For each, ask:
   which test kills it? If none -> that's a hole; add the test.
2. Mechanical pass when time allows: `mutmut`/`cosmic-ray` (py) or
   PIT (java) if already installed — do NOT install new deps. Sample
   on core logic units; report killed/survived counts.
3. Oracle discipline (the #1 surviving-mutant cause): expected values
   must be hand-derived constants from the requirements model — never
   compute the oracle with the same formula the impl uses.
4. Boundary-adjacent inputs are what kill boundary mutants: use the
   exact edge and exactly-one-step-off values, not arbitrary interior
   values ("a=-3" does not kill a clamp-boundary mutant; "a=-1" does).

## Budget
one mental-mutant audit line per unit in TEST_DESIGN (mutant -> killer
test id, or HOLE->new test). Tool runs optional.

## Checklist
- [ ] every comparison operator has a killing pair (edge+adjacent)
- [ ] every removable step (round, clamp, normalize) pinned by a test
      whose oracle is a literal
- [ ] no oracle computed by duplicating impl logic
- [ ] surviving mutants dispositioned in TEST_DESIGN

## Mutation menu additions
Beyond arithmetic/relational/boolean swaps, include:
- Predicate narrowing: any membership/predicate test made STRICTER
  (a larger accepted set shrunk to a subset, a prefix test becoming
  exact equality) — needs a witness drawn from the removed part.
- Removable-step identity: any value-transforming step elided to
  identity — needs a witness where the step changes the value.
