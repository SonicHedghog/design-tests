# MC/DC — Modified Condition/Decision Coverage

For a decision of n atomic conditions, MC/DC requires every condition
to independently affect the outcome. Minimum set: n+1 rows for a pure
AND/OR chain.

## Method
1. From analyze output: decisions containing boolop (and/or) mark
   candidate predicates. Extract atomic conditions per decision.
2. Use `scripts/mcdc.py '["c1","c2",...]' and|or` for the canonical
   independence set: all-true row (AND) or all-false (OR) + one row
   per condition flipping only it.
3. Mixed expressions (a and (b or c)): derive pairs manually —
   for each condition, find the two rows differing only in it that
   flip the outcome. Keep the row count minimal (reuse rows across
   pairs).
4. Conditions built on ranges: pick values on the range side that
   make the atomic condition true/false as needed; reuse boundary
   test points when valid.

## Budget
n+1 minimum; up to 2n for irreducible mixed forms. Never more than
2^n.

## Checklist
- [ ] every atomic condition in each decision has a proving pair
- [ ] rows cite which condition they prove
- [ ] expected outcome verified against REQUIREMENTS not the impl
