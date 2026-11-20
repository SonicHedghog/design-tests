# Fuzzing / Robustness Input Testing

Systematically malformed and adversarial inputs beyond the documented
error classes. Distinct from exception-negative: that category tests
SPECIFIED errors; this one probes UNSPECIFIED robustness.

## Method
1. Input-mutation tests on parsers/validators: truncation, extra
   delimiters, unbalanced nesting, embedded NUL/whitespace, unicode
   confusables, case variants, very long inputs (~10k).
2. Type-adjacent values: float where int expected, negative zero,
   inf/nan for floats, empty containers, single-char strings.
3. Invariant fuzz: random valid inputs must never crash with an
   UNDOCUMENTED exception type (ValueError ok, IndexError not).
   Use `random` with a FIXED SEED — the suite must stay deterministic.
4. Report each crash/hang-class found as a suspected defect; do not
   write tests that assert undocumented crashes are "correct".

## Budget
~3-8 per parser/validator/public entry; 0 for pure arithmetic units.
Deterministic seeds only.

## Checklist
- [ ] mutated inputs keep to the function's stated input type unless
      spec says otherwise
- [ ] every crash class recorded in Suspected defects
- [ ] seeds fixed; no wall-clock/network dependence

## Oracle requirement
A fuzz test needs an oracle that DISCRIMINATES the unit's own output
classes — not just "does not crash" and not a codomain check that
every possible return satisfies (result-is-a-member checks where all
returns are members = crash-only). Allowed oracles, in order:
(a) an invariant from the model (result satisfies P, where P is
    falsifiable on some inputs);
(b) an exception-allowance: only exceptions of documented classes
    may be raised, and any value produced must satisfy the output
    contract;
(c) for crash-only targets (parsers whose only contract is
    no-crash), document WHY a/b don't apply — a bare try/except body
    is not a fuzz test.
