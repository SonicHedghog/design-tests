#!/usr/bin/env python3
"""Public-surface closure audit. Stdlib only.

Usage: surface_closure.py SRC_DIR TESTS_DIR [--justify FILE] [--no-cov]
                              [--json out.json]

Joins the source import surface against what the test suite actually
touches:

  * Import surface per module: __all__ members (else public module-level
    functions/classes), plus public and dunder methods of each class.
  * Test-side evidence (AST over TESTS_DIR): every Name/Attribute leaf,
    every call target, every comparison/arithmetic operator, subscripts,
    with-blocks. A dunder is evidenced by operator use, not by the name —
    e.g. __ge__ needs a '>=' in a test, __getitem__ a subscript,
    __init__ a 'ClassName(' call.
  * Coverage: runs pytest under coverage (pytest-cov if installed, else
    coverage.py) and lists source lines never executed AND not justified
    (inline 'pragma: no cover'/nocover comment, or a --justify file with
    'relpath' or 'relpath:lineno' lines).

Exit: 0 clean, 1 findings (unreferenced public names, unjustified
uncovered lines, coverage run failure), 2 usage error.
"""
import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

CMP_DUNDER = {"__eq__": ast.Eq, "__ne__": ast.NotEq, "__lt__": ast.Lt,
              "__le__": ast.LtE, "__gt__": ast.Gt, "__ge__": ast.GtE}
BIN_DUNDER = {"__add__": ast.Add, "__sub__": ast.Sub, "__mul__": ast.Mult,
              "__truediv__": ast.Div, "__floordiv__": ast.FloorDiv,
              "__mod__": ast.Mod, "__pow__": ast.Pow, "__and__": ast.BitAnd,
              "__or__": ast.BitOr, "__xor__": ast.BitXor,
              "__lshift__": ast.LShift, "__rshift__": ast.RShift}
BUILTIN_DUNDER = {"__hash__": "hash", "__len__": "len", "__str__": "str",
                  "__repr__": "repr", "__int__": "int", "__float__": "float",
                  "__complex__": "complex", "__bool__": "bool",
                  "__iter__": "iter", "__next__": "next",
                  "__abs__": "abs", "__round__": "round",
                  "__index__": "operator.index"}
CTOR_DUNDER = {"__init__", "__new__"}
SUBSCRIPT_DUNDER = {"__getitem__", "__setitem__", "__delitem__"}
WITH_DUNDER = {"__enter__", "__exit__", "__aenter__", "__aexit__"}
JUSTIFY_RE = re.compile(r"pragma:\s*no\s*cover|nocover|no-cover", re.I)


# ------------------------------------------------------------- import surface

def _public(name):
    return not name.startswith("_")


def module_surface(path, src_root):
    """Public names for one module file: exported names + class methods."""
    rel = os.path.relpath(path, src_root)
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):
        return rel, [], "unparseable"
    entries, exported = [], None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__"
                for t in node.targets):
            try:
                exported = [str(e.value) for e in node.value.elts]
            except AttributeError:
                exported = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and (_public(node.name) or exported):
            if exported is None or node.name in exported:
                entries.append({"qual": node.name, "leaf": node.name,
                                "kind": "function"})
        elif isinstance(node, ast.ClassDef) and \
                (_public(node.name) or (exported and node.name in exported)):
            entries.append({"qual": node.name, "leaf": node.name,
                            "kind": "class"})
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and not (sub.name.startswith("_")
                                 and not sub.name.startswith("__")):
                    entries.append({"qual": f"{node.name}.{sub.name}",
                                    "leaf": sub.name, "kind": "method",
                                    "cls": node.name})
    if exported is not None:
        have = {e["leaf"] for e in entries}
        for name in exported:
            if name not in have:
                entries.append({"qual": name, "leaf": name,
                                "kind": "__all__"})
    return rel, entries, None


# ------------------------------------------------------------- test evidence

def collect_evidence(tests_dir):
    ev = {"names": set(), "calls": set(), "cmpops": set(), "binops": set(),
          "unaryops": set(), "subscript": False, "with": False}
    files = []
    for root, _, fns in os.walk(tests_dir):
        for fn in sorted(fns):
            if fn.endswith(".py"):
                files.append(os.path.join(root, fn))
    parse_errors = []
    for path in files:
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError) as e:
            parse_errors.append(f"{path}: {e}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                ev["names"].add(node.id)
            elif isinstance(node, ast.Attribute):
                ev["names"].add(node.attr)
            elif isinstance(node, ast.Call):
                f = node.func
                leaf = f.id if isinstance(f, ast.Name) else \
                    f.attr if isinstance(f, ast.Attribute) else None
                if leaf:
                    ev["calls"].add(leaf)
                    ev["names"].add(leaf)
            elif isinstance(node, ast.Compare):
                ev["cmpops"].update(type(o) for o in node.ops)
            elif isinstance(node, ast.BinOp):
                ev["binops"].add(type(node.op))
            elif isinstance(node, ast.UnaryOp):
                ev["unaryops"].add(type(node.op))
            elif isinstance(node, ast.AugAssign):
                ev["binops"].add(type(node.op))
            elif isinstance(node, ast.Subscript):
                ev["subscript"] = True
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                ev["with"] = True
    return ev, parse_errors


def referenced(entry, ev):
    leaf = entry["leaf"]
    if leaf in ev["names"]:
        return True
    if not leaf.startswith("__"):
        return False
    if leaf in CTOR_DUNDER:
        return entry.get("cls") in ev["calls"]
    if leaf in CMP_DUNDER:
        return CMP_DUNDER[leaf] in ev["cmpops"]
    if leaf == "__contains__":
        return ast.In in ev["cmpops"] or ast.NotIn in ev["cmpops"]
    if leaf in BIN_DUNDER:
        return BIN_DUNDER[leaf] in ev["binops"]
    if len(leaf) > 4 and leaf[2] in "ri":      # __radd__ / __iadd__ -> __add__
        fwd = "__" + leaf[3:]
        if fwd in BIN_DUNDER:
            return BIN_DUNDER[fwd] in ev["binops"]
    if leaf in BUILTIN_DUNDER:
        return BUILTIN_DUNDER[leaf] in ev["calls"]
    if leaf in SUBSCRIPT_DUNDER:
        return ev["subscript"]
    if leaf in WITH_DUNDER:
        return ev["with"]
    return False


# ------------------------------------------------------------------ coverage

def _env():
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def run_coverage(src_dir, tests_dir):
    """Return (json_report_dict, error_or_None)."""
    tmp = tempfile.mkdtemp(prefix="surface_closure_")
    jpath = os.path.join(tmp, "cov.json")
    cwd = os.path.dirname(os.path.abspath(tests_dir))
    if importlib.util.find_spec("pytest_cov") is not None:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
             "--cov", os.path.abspath(src_dir),
             "--cov-report", f"json:{jpath}", "-q",
             os.path.abspath(tests_dir)],
            capture_output=True, text=True, timeout=600, cwd=cwd, env=_env())
        if os.path.exists(jpath):
            return json.load(open(jpath)), None
        return None, ("pytest --cov produced no report:\n"
                      + (proc.stdout + proc.stderr)[-2000:])
    if importlib.util.find_spec("coverage") is not None:
        data = os.path.join(tmp, ".coverage")
        proc = subprocess.run(
            [sys.executable, "-m", "coverage", "run",
             f"--source={os.path.abspath(src_dir)}",
             f"--data-file={data}", "-m", "pytest", "-q",
             "-p", "no:cacheprovider", os.path.abspath(tests_dir)],
            capture_output=True, text=True, timeout=600, cwd=cwd, env=_env())
        rj = subprocess.run(
            [sys.executable, "-m", "coverage", "json",
             f"--data-file={data}", "-o", jpath],
            capture_output=True, text=True, cwd=cwd, env=_env())
        if os.path.exists(jpath):
            return json.load(open(jpath)), None
        return None, ("coverage.py produced no report:\n"
                      + (proc.stdout + proc.stderr
                         + rj.stdout + rj.stderr)[-2000:])
    return None, "no coverage tool (pytest-cov / coverage.py) — skipped"


def load_justify(path):
    lines, files = set(), set()
    for ln in open(path, encoding="utf-8"):
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        if ":" in ln and ln.rsplit(":", 1)[1].isdigit():
            lines.add(ln)
        else:
            files.add(ln)
    return lines, files


def uncovered_lines(report, src_root, just_lines, just_files):
    """Map coverage 'files' entries to src-relpaths; return
    {rel: [unjustified missing linenos]} for files with any."""
    src_abs = os.path.abspath(src_root)
    out = {}
    for key, fdata in (report.get("files") or {}).items():
        path = key if os.path.isabs(key) else os.path.abspath(key)
        if not os.path.exists(path):
            # try resolving relative to src root's parent chain
            cand = os.path.join(src_abs, key)
            path = cand if os.path.exists(cand) else None
        if not path:
            continue
        rel = os.path.relpath(path, src_abs)
        if rel.startswith(".."):
            continue
        if rel in just_files:
            continue
        missing = fdata.get("missing_lines") or []
        try:
            srclines = open(path, encoding="utf-8").read().splitlines()
        except OSError:
            srclines = []
        bad = []
        for n in missing:
            if f"{rel}:{n}" in just_lines:
                continue
            text = srclines[n - 1] if 0 < n <= len(srclines) else ""
            if JUSTIFY_RE.search(text):
                continue
            bad.append(n)
        if bad:
            out[rel] = bad
    return out


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Audit that every public source name is referenced by "
                    "tests and every source line is covered-or-justified.")
    ap.add_argument("src", help="source dir (the import surface)")
    ap.add_argument("tests", help="tests dir")
    ap.add_argument("--justify", help="file of 'relpath' or 'relpath:line' "
                                      "justifications for uncovered lines")
    ap.add_argument("--no-cov", action="store_true",
                    help="skip the coverage pass (name closure only)")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()
    for d in (args.src, args.tests):
        if not os.path.isdir(d):
            print(f"error: not a directory: {d}")
            return 2

    modules = []          # (rel, entries)
    surface_errors = []
    for root, _, files in os.walk(args.src):
        for fn in sorted(files):
            if fn.endswith(".py"):
                rel, entries, err = module_surface(
                    os.path.join(root, fn), args.src)
                if err:
                    surface_errors.append(f"{rel}: {err}")
                modules.append((rel, entries))

    ev, parse_errors = collect_evidence(args.tests)
    for e in parse_errors:
        surface_errors.append(f"test file unparseable: {e}")

    just_lines, just_files = (load_justify(args.justify)
                              if args.justify else (set(), set()))

    cov_report, cov_err = (None, "disabled") if args.no_cov else \
        run_coverage(args.src, args.tests)
    uncov = {}
    if cov_report is not None:
        uncov = uncovered_lines(cov_report, args.src, just_lines, just_files)

    findings, rows = [], []
    for rel, entries in modules:
        unref = [e["qual"] for e in entries if not referenced(e, ev)]
        miss = uncov.get(rel, [])
        rows.append((rel, len(entries), len(entries) - len(unref),
                     unref, miss))
        for q in unref:
            findings.append(("unreferenced-name", f"{rel}: {q}"))
        for n in miss:
            findings.append(("uncovered-line", f"{rel}:{n}"))

    print(f"surface_closure: src={args.src} tests={args.tests}")
    print(f"  {'module':44s} {'names':>5s} {'refed':>5s} "
          f"{'unref':>5s} {'uncov':>5s}")
    for rel, n, r, unref, miss in rows:
        print(f"  {rel:44s} {n:5d} {r:5d} {len(unref):5d} {len(miss):5d}")
        for q in unref:
            print(f"      unreferenced: {q}")
        for n_ in miss:
            print(f"      uncovered line: {n_}")
    for e in surface_errors:
        print(f"  warning: {e}")
    if cov_err and not args.no_cov:
        print(f"  coverage: {cov_err}")
    if cov_err and cov_err != "no coverage tool (pytest-cov / coverage.py) — skipped":
        findings.append(("coverage-error", cov_err))

    if args.json:
        json.dump({"src": args.src, "tests": args.tests,
                   "modules": [{"file": r[0], "names": r[1],
                                "referenced": r[2], "unreferenced": r[3],
                                "uncovered": r[4]} for r in rows],
                   "findings": [{"category": c, "msg": m}
                                for c, m in findings]},
                  open(args.json, "w"), indent=1)
        print(f"  json -> {args.json}")
    if findings:
        print(f"  FAIL — {len(findings)} finding(s)")
        return 1
    print("  OK — surface closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
