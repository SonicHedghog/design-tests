#!/usr/bin/env python3
"""Self-review / journal numeric-claim reconciler. Stdlib only (uses
ledger_reconcile.py for ledger parsing and pytest collection when
available).

Usage: claim_reconcile.py TEST_DESIGN.md [--journal journal.txt]
                          [--metrics metrics.json] [--tests DIR]
                          [--json out.json]

The design doc's self-review section and the run journal make numeric
claims — "402 collected items", "399 pass, 3 fail", "126 obligations,
403 members". This checker extracts every `N <count-noun>` (and the
`<noun> [=:] N` / `budget N` reverse spellings) from the Self-review
section plus the whole journal, and diffs each against ground truth:

  claim kind          ground truth (first available)
  collected/items/    metrics.json collected -> pytest --collect-only
  tests/cases         -> ledger budget -> #witnesses
  witnesses           #ledger witness entries
  members             #ledger obligation members
  obligations         #ledger obligations
  budget/total        ledger `budget:`
  passed              metrics passed (or collected - failed)
  failed/failing      metrics failed
  errors/skipped/     metrics errors / skipped / xfailed
  xfail/xpass

A claim whose ground truth is unavailable is reported as unchecked,
never a finding. A mismatch is a `claim-mismatch` finding. Also
checks consistency between claimed pass+fail and claimed/measured
collected when all three are known.

Exit: 0 clean, 1 findings, 2 usage/fatal error.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger_reconcile import (extract_fenced, load_ledger,
                                  normalize, collect_tests)
except Exception:
    extract_fenced = load_ledger = normalize = collect_tests = None


# ----------------------------------------------------------------- sections

def self_review_section(md_text):
    """Body of the '## N. Self-review' section, stopping at the next
    heading or fenced block (the ```ledger fence would inject its own
    numbers)."""
    m = re.search(r"^#{1,6}[^\n]*self[- ]?review[^\n]*\n",
                  md_text, re.M | re.I)
    if not m:
        return None
    body = md_text[m.end():]
    stop = re.search(r"^#{1,6}\s|^```", body, re.M)
    return body[:stop.start()] if stop else body


# ------------------------------------------------------------------- claims

NOUN = (r"collected|collection|items?|tests?|test[- ]?cases|cases|"
        r"members?|obligations?|witnesses?|budget|totals?|"
        r"passed?|passing|fail(?:ed|ing|ures?|s)?|errors?|"
        r"skipped?|xfail(?:ed)?|xpass(?:ed)?|assertions?")

# "402 collected items", "3 plain failing assertions", "399 pass";
# a trailing hyphen means the noun is a compound ('0 fail-shapes')
NUM_FIRST = re.compile(
    r"\b(\d+)\s+((?:[a-zA-Z][a-zA-Z0-9_.-]*[ \t]+){0,3}?)"
    r"(" + NOUN + r")(?![\w-])", re.I)
# "budget: 402", "collected=402" — only unambiguous nouns word-first
# ('items: 399 pass' is prose, not a claim)
WORD_FIRST = re.compile(
    r"\b(collected|members?|obligations?|witnesses?|budget|totals?|"
    r"passed?|failed?|errors?|skipped|xfail|xpass)\s*[=:]\s*"
    r"\**\s*(\d+)(?![\w-])", re.I)
BUDGET_LOOSE = re.compile(r"\b(budget|total)\s+(\d+)\b", re.I)

# claims like "399 pass" where the count FOLLOWS a result verb are
# covered by NUM_FIRST already; "N failed, M passed" pytest tails too.

KIND_MAP = [
    (re.compile(r"^(collected|collection|items?|tests?|"
                r"test[- ]?cases|cases)$", re.I), "collected"),
    (re.compile(r"^members?$", re.I), "members"),
    (re.compile(r"^obligations?$", re.I), "obligations"),
    (re.compile(r"^witnesses?$", re.I), "witnesses"),
    (re.compile(r"^(budget|totals?)$", re.I), "budget"),
    (re.compile(r"^pass(ed|ing)?$", re.I), "passed"),
    (re.compile(r"^fail(ed|ing|ures?|s)?$", re.I), "failed"),
    (re.compile(r"^errors?$", re.I), "errors"),
    (re.compile(r"^skipped?$", re.I), "skipped"),
    (re.compile(r"^xfail(ed)?$", re.I), "xfailed"),
    (re.compile(r"^xpass(ed)?$", re.I), "xpassed"),
]


def kind_of(noun, middle=""):
    """Map the claim noun to a truth key; 'N failing assertions' keys
    on the adjective, not the noun."""
    if re.fullmatch(r"assertions?", noun, re.I):
        if re.search(r"fail", middle, re.I):
            return "failed"
        if re.search(r"pass", middle, re.I):
            return "passed"
        return None
    for pat, kind in KIND_MAP:
        if pat.fullmatch(noun):
            return kind
    return None


def extract_claims(text, source):
    """(source, line_no, claimed_kind, n, raw_text) tuples."""
    claims = []
    for ln, line in enumerate(text.splitlines(), 1):
        for m in NUM_FIRST.finditer(line):
            kind = kind_of(m.group(3), m.group(2))
            if kind:
                claims.append((source, ln, kind, int(m.group(1)),
                               m.group(0).strip()))
        for m in WORD_FIRST.finditer(line):
            kind = kind_of(m.group(1))
            if kind:
                claims.append((source, ln, kind, int(m.group(2)),
                               m.group(0).strip()))
        for m in BUDGET_LOOSE.finditer(line):
            claims.append((source, ln, "budget", int(m.group(2)),
                           m.group(0).strip()))
    return claims


# ------------------------------------------------------------- ground truth

def ledger_truth(md_text, errors):
    """dict of known quantities from the ```ledger block (or {})."""
    if extract_fenced is None or load_ledger is None:
        errors.append("ledger_reconcile.py not importable — ledger "
                      "truth unavailable")
        return {}
    blocks = extract_fenced(md_text, "ledger")
    if not blocks:
        return {}
    try:
        raw = load_ledger(blocks[0])
    except Exception as e:
        errors.append(f"ledger block unparseable: {e}")
        return {}
    if normalize is not None:
        led, errs = normalize(raw)
        if led is None:
            errors.append(f"ledger normalize failed: {errs[0]}")
            return {}
        return {
            "obligations": len(led["obligations"]),
            "members": sum(len(o["members"]) for o in led["obligations"]),
            "witnesses": len(led["witnesses"]),
            "budget": led["budget"] if isinstance(
                led["budget"], (int, float)) else None,
        }
    return {}


def metrics_truth(path):
    """collected/passed/failed/errors from metrics.json (nested 'main'
    or flat)."""
    try:
        m = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {}, f"cannot parse metrics: {e}"
    main = m.get("main") if isinstance(m.get("main"), dict) else m
    out = {}
    for k in ("collected", "passed", "failed", "errors", "skipped",
              "xfailed", "xpassed"):
        v = main.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = int(v)
    return out, None


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Reconcile numeric claims in TEST_DESIGN.md's "
                    "self-review section and journal.txt against the "
                    "ledger, metrics.json, and pytest collection.")
    ap.add_argument("design", help="path to TEST_DESIGN.md")
    ap.add_argument("--journal", help="journal.txt to scan for claims")
    ap.add_argument("--metrics", help="metrics.json ground truth")
    ap.add_argument("--tests", help="tests dir for pytest --collect-only")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()
    try:
        md_text = open(args.design, encoding="utf-8").read()
    except OSError as e:
        print(f"error: cannot read {args.design}: {e}")
        return 2

    errors = []
    truth = ledger_truth(md_text, errors)
    met, met_err = {}, None
    if args.metrics:
        met, met_err = metrics_truth(args.metrics)
        if met_err:
            errors.append(met_err)
    truth.update({k: v for k, v in met.items()})
    collected_n = None
    if args.tests and collect_tests is not None:
        collected_n, cerr = collect_tests(args.tests)
        if cerr:
            errors.append(cerr)
    if "collected" not in truth:
        truth["collected"] = collected_n if collected_n is not None \
            else truth.get("budget") or truth.get("witnesses")
    # collect_tests returns a nodeid list; claims compare against the count.
    for _k in ("collected", "passed", "failed", "errors", "skipped"):
        if isinstance(truth.get(_k), list):
            truth[_k] = len(truth[_k])
    if "passed" not in truth and truth.get("collected") is not None \
            and truth.get("failed") is not None:
        truth["passed"] = truth["collected"] - truth["failed"]

    claims = []
    section = self_review_section(md_text)
    if section:
        claims += extract_claims(section, "self-review")
    if args.journal:
        try:
            claims += extract_claims(
                open(args.journal, encoding="utf-8").read(), "journal")
        except OSError as e:
            print(f"error: cannot read {args.journal}: {e}")
            return 2

    print(f"claim_reconcile: design={args.design} "
          f"journal={args.journal} metrics={args.metrics}")
    for e in errors:
        print(f"  warning: {e}")
    print("  truth: " + (", ".join(f"{k}={v}" for k, v in
                                 sorted(truth.items())
                                 if v is not None) or "none"))
    if section is None and not args.journal:
        print("  no self-review section and no journal — nothing to "
              "reconcile")
        return 0
    if not claims:
        print("  no numeric claims found")
        return 0

    findings = []
    n_checked = 0
    for src, ln, kind, n, raw in claims:
        exp = truth.get(kind)
        if exp is None:
            print(f"  {src}:{ln}: '{raw}' -> {kind}: unchecked "
                  f"(no ground truth)")
            continue
        n_checked += 1
        if int(exp) != n:
            findings.append({"source": src, "line": ln, "kind": kind,
                             "claimed": n, "expected": int(exp),
                             "raw": raw})
            print(f"  {src}:{ln}: '{raw}' -> {kind}: claimed {n}, "
                  f"actual {int(exp)}  MISMATCH")
        else:
            print(f"  {src}:{ln}: '{raw}' -> {kind}: {n} ok")

    # cross-check: claimed pass + fail vs collected
    cp = next((n for s, l, k, n, r in claims if k == "passed"), None)
    cf = next((n for s, l, k, n, r in claims if k == "failed"), None)
    cc = truth.get("collected")
    if cp is not None and cf is not None and cc is not None \
            and cp + cf != int(cc):
        findings.append({"source": "cross", "line": 0,
                         "kind": "pass+fail-vs-collected",
                         "claimed": cp + cf, "expected": int(cc),
                         "raw": f"passed {cp} + failed {cf}"})
        print(f"  cross: passed {cp} + failed {cf} = {cp + cf} "
              f"!= collected {int(cc)}  MISMATCH")

    if args.json:
        json.dump({"design": args.design, "truth": truth,
                   "claims_checked": n_checked,
                   "findings": findings},
                  open(args.json, "w"), indent=1)
        print(f"  json -> {args.json}")
    if findings:
        print(f"  FAIL — {len(findings)} claim-mismatch finding(s) "
              f"({len(claims)} claims, {n_checked} checked)")
        return 1
    print(f"  OK — {n_checked}/{len(claims)} claim(s) reconcile")
    return 0


if __name__ == "__main__":
    sys.exit(main())
