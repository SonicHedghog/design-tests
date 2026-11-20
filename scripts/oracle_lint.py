#!/usr/bin/env python3
"""Oracle-shape lint over test files (AST pass). Stdlib only.

Usage: oracle_lint.py TESTS_DIR [TESTS_DIR ...] [--json out.json]

Findings (file:line + shape name):

  raises-bypass    WARN  `with pytest.raises(...)` body contains statements
                         after the raising call (unreachable tail = mutating
                         work hidden in the raises context), or the function
                         performs calls after the raises block without any
                         assertion — the guard-vs-bypass shape the skill
                         warns about. Conservative: reported, not failed.
  raises-conditional WARN  `if` inside a raises body (row rescue: the
                         branch can swallow the expected raise).
  dup-body         FAIL  two test functions with byte-identical bodies
                         (verbatim dupe).
  dup-shape        WARN  bodies identical only after literal normalization
                         — different guards/inputs may be legit; deselect-
                         audit candidate.
  dup-literal      FAIL  the same (param-names, literal row) repeated
                         within one parametrize table.
  dup-literal-shared WARN  identical row in another function's table —
                         suspicious but may be independent EP members.
  self-compare     FAIL  assert X == X / X is X / X != X — both sides the
                         same expression (incl. f(x) == f(x), repr(v)==repr(v)).
  impl-mirror      FAIL  r = f(*a) ... assert r == f(*a) — expected value
                         recomputed by the implementation's own call.
  assert-const     FAIL  assert <constant> (assert True, assert 1, ...).
  lit-lit          FAIL  assert <literal> == <literal> — compares two
                         compile-time constants, exercises no code.

Exit: 1 on any FAIL finding; 0 when only WARN shapes or clean.
"""
import argparse
import ast
import copy
import json
import os
import sys

WARN, FAIL = "WARN", "FAIL"


def _is_const(n):
    return isinstance(n, ast.Constant)


def _same(a, b):
    return ast.dump(a) == ast.dump(b)


def _call_name(n):
    """Dotted name of a Call's func, else None."""
    f = n.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _is_raises_ctx(ctx_expr):
    """True for `with pytest.raises(...)` / `with raises(...)`."""
    if isinstance(ctx_expr, ast.Call):
        return _call_name(ctx_expr) == "raises"
    return False


def _norm_dump(stmts):
    """AST dump of a stmt list with every literal normalized."""
    class N(ast.NodeTransformer):
        def visit_Constant(self, node):
            return ast.Constant(value="<lit>")
    mod = N().visit(ast.Module(body=copy.deepcopy(stmts), type_ignores=[]))
    return ast.dump(mod)


def _id_kw(arg):
    """True for pytest.param id-ish kwargs: id, ids, *_id, id_*."""
    a = (arg or "").lower()
    return a in ("id", "ids") or a.endswith("_id") \
        or a.startswith("id_")


def _row_dump(elt):
    """AST dump of a parametrize row with id-ish kwargs stripped from
    the comparison key, so rows identical except for pytest.param
    id= still key alike."""
    if isinstance(elt, ast.Call) \
            and any(_id_kw(kw.arg) for kw in elt.keywords):
        elt = copy.deepcopy(elt)
        elt.keywords = [kw for kw in elt.keywords if not _id_kw(kw.arg)]
    return ast.dump(elt)


def _parametrize_rows(fn):
    """(param_names_key, row_dump) pairs from @parametrize decorators."""
    rows = []
    for d in fn.decorator_list:
        if not isinstance(d, ast.Call) or _call_name(d) != "parametrize" \
                or len(d.args) < 2:
            continue
        try:
            names_key = ast.dump(d.args[0])
        except Exception:
            names_key = ""
        vals = d.args[1]
        if isinstance(vals, (ast.List, ast.Tuple)):
            for elt in vals.elts:
                try:
                    rows.append((names_key, _row_dump(elt)))
                except Exception:
                    pass
    return rows


def lint_function(fn, path):
    finds = []
    # (c)/(d) tautology shapes -------------------------------------------------
    assigns = {}  # name -> ast.dump(value) for simple `x = call(...)`
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call):
            assigns.setdefault(node.targets[0].id, []).append(
                (ast.dump(node.value), node.lineno))
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assert):
            continue
        t = node.test
        if _is_const(t) and t.value:
            finds.append((t.lineno, FAIL, "assert-const",
                          f"assert {ast.unparse(t)} is always true"))
        if isinstance(t, ast.Compare):
            sides = [t.left] + t.comparators
            if all(_is_const(s) for s in sides):
                finds.append((t.lineno, FAIL, "lit-lit",
                              f"assert {ast.unparse(t)}: literal vs literal"))
            for op, comp in zip(t.ops, t.comparators):
                if _same(t.left, comp) and not all(
                        _is_const(s) for s in sides):
                    finds.append((comp.lineno, FAIL, "self-compare",
                                  f"assert {ast.unparse(t)}: same expression "
                                  f"both sides"))
                if isinstance(t.left, ast.Name) and isinstance(comp, ast.Call):
                    for d, al in assigns.get(t.left.id, []):
                        if al < node.lineno and d == ast.dump(comp):
                            finds.append((comp.lineno, FAIL, "impl-mirror",
                                          f"'{t.left.id}' compared to the "
                                          f"same call that produced it"))
                if isinstance(comp, ast.Name) and isinstance(t.left, ast.Call):
                    for d, al in assigns.get(comp.id, []):
                        if al < node.lineno and d == ast.dump(t.left):
                            finds.append((comp.lineno, FAIL, "impl-mirror",
                                          f"'{comp.id}' compared to the same "
                                          f"call that produced it"))
    # (a) raises-context shapes -------------------------------------------------
    body_asserts = sum(isinstance(n, ast.Assert) for n in ast.walk(fn))
    for node in ast.walk(fn):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            if not _is_raises_ctx(item.context_expr):
                continue
            inner_if = any(isinstance(n, ast.If) for n in
                           (x for st in node.body for x in ast.walk(st)))
            if inner_if:
                finds.append((node.lineno, WARN, "raises-conditional",
                              "`if` inside pytest.raises body — a row can "
                              "bypass the expected raise"))
            tail_calls = any(
                isinstance(st, ast.Expr) and isinstance(
                    st.value, (ast.Call, ast.Await))
                for st in node.body[1:])
            after = fn.body[fn.body.index(node) + 1:] if node in fn.body \
                else []
            after_calls = any(
                isinstance(st2, ast.Expr) and isinstance(
                    st2.value, (ast.Call, ast.Await))
                for st2 in after)
            after_assert = any(isinstance(n2, ast.Assert)
                               for st in after for n2 in ast.walk(st))
            if (tail_calls or after_calls) and not after_assert \
                    and body_asserts == 0:
                finds.append((node.lineno, WARN, "raises-bypass",
                              "calls inside/after pytest.raises with no "
                              "assertion — verify state or return elsewhere"))
    return finds


def lint_file(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError) as e:
        return [(0, WARN, "unparseable", f"{path}: {e}")], [], []
    finds, fn_bodies, rows = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test"):
            finds += lint_function(node, path)
            deco = ast.dump(ast.Module(
                body=[ast.Expr(value=d) for d in node.decorator_list],
                type_ignores=[]))
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            has_param = any(isinstance(d, ast.Call)
                            and _call_name(d) == "parametrize"
                            for d in node.decorator_list)
            fn_bodies.append((node.name, node.lineno, deco + body,
                              _norm_dump(node.body), has_param))
            for names_key, r in _parametrize_rows(node):
                rows.append((node.name, node.lineno, names_key, r))
    return finds, fn_bodies, rows


def main():
    ap = argparse.ArgumentParser(
        description="AST lint for forbidden/weak oracle shapes in tests.")
    ap.add_argument("tests", nargs="+", help="test dirs or files")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()

    files = []
    for t in args.tests:
        if os.path.isfile(t):
            files.append(t)
        elif os.path.isdir(t):
            for root, _, fns in os.walk(t):
                files += [os.path.join(root, f) for f in sorted(fns)
                          if f.endswith(".py")]
        else:
            print(f"error: not found: {t}")
            return 2

    all_finds, all_bodies, all_rows = [], [], []
    for path in sorted(set(files)):
        f, b, r = lint_file(path)
        all_finds += [(path, *x) for x in f]
        all_bodies += [(path, *x) for x in b]
        all_rows += [(path, *x) for x in r]

    # (b) duplicate bodies across functions
    seen_exact, seen_norm = {}, {}
    for path, name, lineno, exact, norm, has_param in all_bodies:
        if exact in seen_exact and seen_exact[exact][0] != name:
            p2, n2, l2 = seen_exact[exact][1], seen_exact[exact][0], \
                seen_exact[exact][2]
            all_finds.append((path, lineno, FAIL, "dup-body",
                              f"verbatim-identical body to '{n2}' "
                              f"at {p2}:{l2}"))
        elif not has_param and norm in seen_norm \
                and seen_norm[norm][0] != name:
            p2, n2, l2 = seen_norm[norm][1], seen_norm[norm][0], \
                seen_norm[norm][2]
            all_finds.append((path, lineno, WARN, "dup-shape",
                              f"body identical mod literals to '{n2}' "
                              f"at {p2}:{l2}"))
        else:
            seen_exact.setdefault(exact, (name, path, lineno))
            if not has_param:
                seen_norm.setdefault(norm, (name, path, lineno))

    # duplicate literal parametrize rows
    seen_r = {}
    for path, name, lineno, names_key, dump in all_rows:
        key = (names_key, dump)
        if key in seen_r:
            p2, n2, l2 = seen_r[key]
            if p2 == path and n2 == name:
                all_finds.append((path, lineno, FAIL, "dup-literal",
                                  "row repeated in same parametrize table"))
            else:
                all_finds.append((path, lineno, WARN, "dup-literal-shared",
                                  f"row also parametrized by '{n2}' "
                                  f"at {p2}:{l2}"))
        else:
            seen_r[key] = (path, name, lineno)

    all_finds.sort(key=lambda x: (x[0], x[1]))
    n_fail = sum(1 for f in all_finds if f[2] == FAIL)
    n_warn = sum(1 for f in all_finds if f[2] == WARN)
    print(f"oracle_lint: {len(set(files))} file(s)")
    for path, lineno, sev, shape, msg in all_finds:
        print(f"  {path}:{lineno}: [{sev}] {shape}: {msg}")
    if args.json:
        json.dump([{"file": p, "line": l, "severity": s, "shape": sh,
                    "msg": m} for p, l, s, sh, m in all_finds],
                  open(args.json, "w"), indent=1)
        print(f"  json -> {args.json}")
    if not all_finds:
        print("  OK — no oracle-shape findings")
    else:
        print(f"  {n_fail} fail-shape(s), {n_warn} warning(s)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
