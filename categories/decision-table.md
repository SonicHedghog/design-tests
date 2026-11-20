# Decision Table Testing

When output depends on combinations of conditions (not single
parameters), enumerate condition combinations as table columns; each
column is a test.

## Method
1. Extract conditions (independent predicates) and actions (outcomes/
   side effects) from the requirements.
2. Full table = one column per feasible combination. Feasible = not
   ruled out by condition dependencies (impossible combos -> omit, but
   document why).
3. If the table is large (>~16 columns) and conditions interact only
   pairwise per requirements, use `scripts/decision_table.py` with
   mode=pairwise.
4. Minimize only when two columns produce identical actions AND the
   requirements say the differing condition is irrelevant to the
   outcome. Record merges.
5. Each column = exactly one test (or one parametrize row).

## Budget
number of feasible columns. Full if <= ~16 columns, else pairwise,
else explicit selection with justification in TEST_DESIGN.

## Checklist
- [ ] conditions listed before columns generated
- [ ] impossible combinations removed and documented
- [ ] one test per remaining column; action asserted per column
- [ ] every condition flips both ways across the surviving columns
