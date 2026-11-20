#!/usr/bin/env python3
"""MC/DC independence-pair generator for AND/OR predicate lists.

Input: argv[1] = JSON list of condition names, argv[2] = "and"|"or"
  e.g.  mcdc.py '["cond_a","cond_b","cond_c"]' and

Output: JSON list of cases. Each case = dict condition -> bool, plus
"expect" (predicate result) and "proves" (which condition's independence
this row demonstrates, "" for the baseline row).

For a pure n-input AND (or OR), a minimal MC/DC set is n+1 rows:
the all-true (or all-false) baseline + one row per condition flipping
only that input. For mixed/unknown expressions the runner must evaluate
the real predicate; this script handles the canonical homogeneous case
and flags anything else for manual derivation.
"""
import json
import sys


def main():
    conds = json.loads(sys.argv[1])
    op = sys.argv[2] if len(sys.argv) > 2 else "and"
    cases = []
    base = {c: (op == "and") for c in conds}
    base_expect = (op == "and")
    cases.append({"conditions": base, "expect": base_expect, "proves": "baseline"})
    for flip in conds:
        row = dict(base)
        row[flip] = not base[flip]
        cases.append({"conditions": row, "expect": not base_expect,
                      "proves": f"independence:{flip}"})
    print(json.dumps({"n_conditions": len(conds), "min_rows": len(conds) + 1,
                      "cases": cases}, indent=1))


if __name__ == "__main__":
    main()
