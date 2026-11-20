#!/usr/bin/env python3
"""Decision-table column enumerator + pairwise reducer. Stdlib only.

Input: JSON on argv[1]:
  {"factors": {"size": ["s","m","l"], "region": ["us","eu"]},
   "mode": "full" | "pairwise"}

full     -> every combination (cartesian product) — each is a test column
pairwise -> smallest set covering every pair of factor values
            (greedy; good enough for test planning)

Output: JSON {"n_cases": N, "cases": [{factor: value, ...}]}
"""
import itertools
import json
import sys


def full(factors):
    keys = list(factors)
    return [dict(zip(keys, combo))
            for combo in itertools.product(*(factors[k] for k in keys))]


def pairwise(factors):
    keys = list(factors)
    pairs = set()
    for a, b in itertools.combinations(keys, 2):
        for va in factors[a]:
            for vb in factors[b]:
                pairs.add((a, va, b, vb))
    cases = []
    pool = full(factors)
    covered = set()
    while pairs - covered:
        best, best_cov = None, -1
        for c in pool:
            cov = {(a, c[a], b, c[b])
                   for a, b in itertools.combinations(keys, 2)} - covered
            if len(cov) > best_cov:
                best, best_cov = c, len(cov)
        cases.append(best)
        pool.remove(best)
        covered |= {(a, best[a], b, best[b])
                    for a, b in itertools.combinations(keys, 2)}
    return cases


def main():
    spec = json.load(open(sys.argv[1]) if sys.argv[1] != "-" else sys.stdin)
    factors = spec["factors"]
    cases = pairwise(factors) if spec.get("mode") == "pairwise" else full(factors)
    print(json.dumps({"n_cases": len(cases), "cases": cases}, indent=1))


if __name__ == "__main__":
    main()
