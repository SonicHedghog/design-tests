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

Also audits the checker-evidence seal (r38 seal-mutation): a formal
sealed_at+content_hash in metrics.json must match ledger.json + test
files on disk (mismatch => FAIL), and no ledger/test/metrics file may
postdate the seal (stale evidence => FAIL). A checkers block with no
formal seal falls back to metrics.json's own mtime as seal time;
a run with no seal at all earns a `seal-missing` warning only.

Exit: 0 clean, 1 findings, 2 usage/fatal error.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

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


# ------------------------------------------------------------- seal-mutation
# (r38: validators_r38 resealed metrics.json's checker evidence twice
# mid-grading — the sealed checker outputs stopped matching the ledger,
# tests, and journal on disk. A run's checker evidence must carry a
# content seal; artifacts rewritten after the seal make it stale.)

SEAL_TEST_DIRS = ("tests", "junit", "test")
SEAL_MTIME_SLOP = 1.0   # seconds; filesystem granularity tolerance


def _seal_field(metrics, key):
    """Find `key` at metrics top level or inside a named evidence
    object (seal/evidence/checker_evidence/checkers)."""
    for obj in (metrics, metrics.get("seal"), metrics.get("evidence"),
                metrics.get("checker_evidence"),
                metrics.get("checkers")):
        if isinstance(obj, dict) and obj.get(key) is not None:
            return obj[key]
    return None


def _seal_artifacts(run_dir):
    """ledger.json + every file under the run's test dirs — the
    artifacts a checker-evidence seal covers."""
    paths = [os.path.join(run_dir, "ledger.json")]
    for d in SEAL_TEST_DIRS:
        td = os.path.join(run_dir, d)
        if not os.path.isdir(td):
            continue
        for root, dns, fns in os.walk(td):
            dns[:] = [x for x in dns if x not in
                      ("__pycache__", ".git", "target", "build")]
            paths += [os.path.join(root, f) for f in fns]
    return [p for p in paths if os.path.isfile(p)]


def content_hash(run_dir):
    """sha256 over the sealed corpus: sorted
    'relpath\\0sha256(file bytes)\\n' lines for ledger.json + all test
    files. Deterministic for a fixed tree; a byte changed anywhere
    breaks the seal."""
    entries = []
    for p in _seal_artifacts(run_dir):
        try:
            with open(p, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            continue
        entries.append(os.path.relpath(p, run_dir).replace("\\", "/")
                       + "\0" + digest)
    h = hashlib.sha256()
    for e in sorted(entries):
        h.update(e.encode())
        h.update(b"\n")
    return h.hexdigest()


def audit_seal(run_dir, metrics_path, metrics):
    """r38 seal-mutation audit. metrics.json's checkers-evidence block
    is sealed when the run gates; evidence is stale when artifacts
    were rewritten afterwards:

      * formal seal present (sealed_at + content_hash): recompute the
        hash over ledger.json + test files -> mismatch is FAIL; any
        artifact (or metrics.json itself) newer than sealed_at is
        FAIL — the evidence was resealed or the tree mutated after.
      * checkers/checker_evidence block but no formal seal: the block
        WAS sealed at metrics-write time; artifacts postdating
        metrics.json's mtime => stale sealed outputs => FAIL. If
        nothing postdates it, the absent formal seal is a WARN.
      * no seal at all (legacy runs): WARN only.

    Returns (findings, warnings) as (category, message) tuples."""
    findings, warnings = [], []
    sealed_at = _seal_field(metrics, "sealed_at")
    sealed_hash = _seal_field(metrics, "content_hash")
    artifacts = _seal_artifacts(run_dir)
    if sealed_at is not None or sealed_hash is not None:
        if sealed_at is not None:
            try:
                ts = datetime.fromisoformat(
                    str(sealed_at).replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
                warnings.append(("seal-format",
                                 f"sealed_at '{sealed_at}' is not an "
                                 f"ISO timestamp"))
            if ts is not None:
                newer = [p for p in artifacts + [metrics_path]
                         if os.path.getmtime(p) > ts + SEAL_MTIME_SLOP]
                if newer:
                    findings.append((
                        "seal-mutation",
                        f"{len(newer)} artifact(s) postdate the "
                        f"sealed_at timestamp (e.g. "
                        f"{os.path.relpath(newer[0], run_dir)}) — "
                        f"ledger/tests/metrics rewritten after the "
                        f"checker evidence was sealed"))
        if sealed_hash is not None:
            if content_hash(run_dir) != sealed_hash:
                findings.append((
                    "seal-mutation",
                    "sealed content_hash does not match ledger.json + "
                    "test files on disk — the sealed evidence no "
                    "longer describes this run"))
        return findings, warnings

    has_evidence = isinstance(metrics.get("checkers"), dict) or \
        metrics.get("checker_evidence") is not None
    warnings.append(("seal-missing",
                     "metrics.json carries no sealed_at/content_hash "
                     "evidence seal"))
    if not has_evidence:
        return findings, warnings
    # The embedded checker evidence was sealed at metrics-write time;
    # artifacts newer than metrics.json itself postdate it.
    try:
        seal_time = os.path.getmtime(metrics_path)
    except OSError:
        return findings, warnings
    newer = [p for p in artifacts
             if os.path.getmtime(p) > seal_time + SEAL_MTIME_SLOP]
    if newer:
        findings.append((
            "seal-mutation",
            f"{len(newer)} artifact(s) postdate metrics.json's "
            f"checker evidence (e.g. "
            f"{os.path.relpath(newer[0], run_dir)}) — ledger/tests "
            f"mutated after the checkers were sealed; every sealed "
            f"checker output is stale"))
    return findings, warnings


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
    seal_findings = []
    if args.metrics:
        met, met_err = metrics_truth(args.metrics)
        if met_err:
            errors.append(met_err)
        try:
            metrics_obj = json.load(open(args.metrics, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metrics_obj = None
        if isinstance(metrics_obj, dict):
            sf, sw = audit_seal(
                os.path.dirname(os.path.abspath(args.metrics)),
                args.metrics, metrics_obj)
            seal_findings = sf
            errors.extend(f"{c}: {m}" for c, m in sw)
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
    elif not claims:
        print("  no numeric claims found")
    if not claims:
        findings = [{"source": "seal", "line": 0, "kind": c,
                     "claimed": None, "expected": None, "raw": m}
                    for c, m in seal_findings]
        for f in findings:
            print(f"  seal: {f['kind']}: {f['raw']}  MISMATCH")
        if args.json:
            json.dump({"design": args.design, "truth": truth,
                       "claims_checked": 0, "findings": findings},
                      open(args.json, "w"), indent=1)
        if findings:
            print(f"  FAIL — {len(findings)} seal finding(s)")
            return 1
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

    for cat, msg in seal_findings:
        findings.append({"source": "seal", "line": 0, "kind": cat,
                         "claimed": None, "expected": None, "raw": msg})
        print(f"  seal: {cat}: {msg}  MISMATCH")

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
