# Pairwise / Combinatorial Testing

When a function has many independent-ish parameters, all-pairs
coverage finds most interaction bugs at a fraction of exhaustive cost.

## Method
1. Use only when: >3 parameters with >2 classes each AND the
   requirements don't specify a full decision table (if they do, use
   decision-table category instead — it is stronger).
2. Reduce each parameter to 2-4 representative classes first (EP).
3. `scripts/decision_table.py` mode=pairwise emits the covering set.
4. One test per emitted row.

## Budget
typically ~6-12 rows vs hundreds exhaustive. Report coverage level
(2-way) in TEST_DESIGN.

## Checklist
- [ ] justified over full table (table too large, no stronger spec)
- [ ] every pair of (param,class) x (param,class) appears in some row
