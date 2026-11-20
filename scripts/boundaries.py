#!/usr/bin/env python3
"""Boundary-value generator. Stdlib only.

Input: JSON spec on argv[1] (file path or '-' for stdin):
[
  {"name": "count", "type": "int",   "min": 0, "max": 100},
  {"name": "rate",  "type": "float", "min": 0, "max": 1, "max_exclusive": true},
  {"name": "token", "type": "str",   "len_min": 8, "len_max": 64},
  {"name": "kind",  "type": "enum",  "values": ["a","b","c"]},
  {"name": "tags",  "type": "list",  "len_min": 0, "len_max": 3}
]

Output: JSON test-point list per param:
  valid boundary points (min-1? no — boundaries are ON the edges),
  plus invalid just-outside points.

Rules (robust BVA, 2-value per bound):
  numeric [lo,hi]: lo, lo+eps, hi-eps, hi  valid;  lo-eps, hi+eps invalid
  exclusive bound: the bound itself invalid, +/- eps valid side
  str length [lo,hi]: strings of len lo, lo+1, hi-1, hi valid;
                      len lo-1, hi+1 invalid (if representable)
  enum: each value valid; one non-member invalid
  list len: same as str length
"""
import json
import sys


def points(spec):
    t = spec["type"]
    out = {"name": spec["name"], "valid": [], "invalid": []}
    if t in ("int", "float"):
        eps = 1 if t == "int" else spec.get("eps", 0.01)
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None:
            if spec.get("min_exclusive"):
                out["invalid"].append(lo)
                out["valid"] += [lo + eps]
            else:
                out["valid"] += [lo, lo + eps]
                out["invalid"].append(lo - eps)
        if hi is not None:
            if spec.get("max_exclusive"):
                out["invalid"].append(hi)
                out["valid"] += [hi - eps]
            else:
                out["valid"] += [hi - eps, hi]
                out["invalid"].append(hi + eps)
        if lo is None and hi is None:
            out["valid"] += [0, 1, -1]
            out["invalid"].append(None)
    elif t == "str":
        lo, hi = spec.get("len_min"), spec.get("len_max")
        fill = spec.get("fill", "a")
        if lo is not None:
            if lo > 0:
                out["invalid"].append(fill * (lo - 1))
            out["valid"] += [fill * lo] + ([fill * (lo + 1)] if lo + 1 <= (hi or lo + 1) else [])
        if hi is not None:
            if hi - 1 >= (lo or 0):
                out["valid"].append(fill * (hi - 1))
            out["valid"].append(fill * hi)
            out["invalid"].append(fill * (hi + 1))
        if lo is None and hi is None:
            out["valid"] += ["", fill, fill * 10]
    elif t == "enum":
        out["valid"] = list(spec["values"])
        out["invalid"] = [spec.get("invalid_sample", "__not_a_member__")]
    elif t == "list":
        lo, hi = spec.get("len_min", 0), spec.get("len_max")
        if lo is not None:
            if lo > 0:
                out["invalid"].append([0] * (lo - 1))
            out["valid"] += [[0] * lo, [0] * (lo + 1)]
        if hi is not None:
            out["valid"] += [[0] * max(hi - 1, 0), [0] * hi]
            out["invalid"].append([0] * (hi + 1))
    elif t == "bool":
        out["valid"] = [True, False]
    elif t == "optional":
        out["valid"] = ["<inner-valid>", None]
        out["invalid"] = ["<inner-invalid>"]
    # dedupe preserving order
    for k in ("valid", "invalid"):
        seen, dedup = set(), []
        for v in out[k]:
            key = json.dumps(v)
            if key not in seen:
                seen.add(key); dedup.append(v)
        out[k] = dedup
    return out


def main():
    src = sys.argv[1]
    spec = json.load(open(src) if src != "-" else sys.stdin)
    result = [points(p) for p in spec]
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
