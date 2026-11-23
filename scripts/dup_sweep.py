#!/usr/bin/env python3
"""Duplicate-case sweep over pytest files (AST pass). Stdlib only.

Usage: dup_sweep.py TESTS_DIR [TESTS_DIR ...] [--json out.json]

Each parametrized case — and each non-parametrized test, as a single
case — is normalized to a signature:

  input set       every normalized call the case's executed body
                  invokes (SUT + fixtures), parametrize names resolved
                  to their row literals and `x = <expr>` assignments
                  resolved to the expr — `parse(s)` on row "a.b.c" and
                  `parse("a.b.c")` normalize identically, and
                  `s.add(n)` where s = Widget(10, 0) matches
                  `w.add(n)` under the same ctor args
  assertion shape the body's oracle predicates:
                    raises(E[, match=lit]) on normalized call C
                    == / is    with the expected literal on one side
                    != / is-not, < <= > >= ordering comparisons
                    in / not-in membership, len(...) shapes,
                    bare truthy / falsy / is-None checks

Branching: `if` / `elif` tests that constant-fold after parametrize
substitution (`if ok:` on row ok=True, `if code == 2:` on row 2)
resolve to the taken branch only — an `if ok:` success-row and a
failure-row exercise disjoint predicates and are never twins.
Unresolvable conditions walk both branches.

Findings (file:line pairs):

  dup       FAIL  identical input set AND identical assertion-shape
                  set — the same case emitted under different test
                  names or in different files
  near-dup  WARN  identical input set where one case's oracle is
                  strictly weaker: predicate set is a strict subset,
                  or every predicate is matched by an equal-or-stronger
                  predicate on the same subject with at least one
                  strict weakening —
                    truthy(x)      < x == <truthy literal>, x is not
                                   None, x > 0-style cmp, member in x
                    x is not None  < x == <lit>, truthy(x), cmp, in
                    falsy(x)       < x == <falsy lit>, x is None
                    x != a         < x == b        (a != b literals)
                    x <op> a       < x == b        (b satisfies <op> a)
                    x <op> a       < x <op> b      (same-direction
                                   thresholds: x > 0 < x > 5)
                    m in x / not   < x == <lit>    (membership
                    in                               evaluable)
                    x == approx()  < x == <exact lit>
                    raises(E)      < raises(E, match=...)
                    raises(A, B..) < raises(<strict subset>)
                    raises(Exception/BaseException) < raises(<other>)

Flag files: files named test_suspected_defects* are excluded from the
dup/near-dup index but scanned for CROSS-VERDICT overlap — a flag case
sharing a normalized input set with any green case is a
`contradiction` finding: a divergent outcome is never a green expected
value, so flag x green same-input pairs mean one encodes the wrong
verdict (the only legal overlap is a green assert on a DIFFERENT
clause's conforming outcome). Old flag whitelist
assertion shape => not a dup anyway; this just keeps them from
pairing with the suite they deliberately re-run).

flag-green-collision (r36 pin-OUTCOME seal): a green assert and a flag/
red test asserting on the SAME input literal — the same call args,
modulo trivial normalization — contradict: one must be wrong. Python
call arg tuples (callee + all-literal args, parametrize envs resolved)
and Java argv literals (`new T[]{...}` / `asList`/`of` factories) are indexed per file;
an exact-arg signature shared by a green file and a
*SuspectedDefects*/flag file => FAIL. Java files under junit/ (or any
dir passed here) are scanned — .java basenames containing 'suspected'
are flag files, the rest green (r36: cli_r36 shipped a green
innerQuoteKept assert on {"-f","\"a\"b\""} for all four parsers AND a
flag on the identical DefaultParser input — the green assert
laundered the defect).

Exit: 1 on any dup finding; 0 when only near-dups or clean; 2 usage.
"""
import argparse
import ast
import copy
import itertools
import json
import os
import re
import sys

WARN, FAIL = "WARN", "FAIL"

DEFECT_GLOB = "test_suspected_defects"


def _call_name(n):
    """Dotted name of a Call's func, else None."""
    f = n.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


class _Norm:
    """Expression normalizer bound to one case's env (parametrize name
    -> row-value node) plus the body's simple x = <expr> assignments."""

    def __init__(self, env, assigns):
        self.env = env
        self.assigns = assigns

    def n(self, node):
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.n(self.env[node.id])
            if node.id in self.assigns:
                return self.n(self.assigns[node.id])
            return "v" + node.id
        try:
            return "L" + repr(ast.literal_eval(node))
        except Exception:
            pass
        if isinstance(node, ast.Call):
            parts = []
            for a in node.args:
                if isinstance(a, ast.Starred):
                    inner = self.n(a.value)
                    ok, v = _litval(inner)
                    if ok and isinstance(v, (tuple, list)):
                        parts += ["L" + repr(x) for x in v]
                    else:
                        parts.append("*" + inner)
                else:
                    parts.append(self.n(a))
            kws = ",".join(f"{k.arg or '**'}={self.n(k.value)}"
                           for k in node.keywords)
            return (f"C{self.n(node.func)}({','.join(parts)}"
                    f"{';' if kws else ''}{kws})")
        if isinstance(node, ast.Attribute):
            return f"{self.n(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{self.n(node.value)}[{self.n(node.slice)}]"
        if isinstance(node, ast.Tuple):
            return "(" + ",".join(self.n(e) for e in node.elts) + ")"
        if isinstance(node, ast.List):
            return "[" + ",".join(self.n(e) for e in node.elts) + "]"
        if isinstance(node, ast.Set):
            return "{" + ",".join(sorted(self.n(e) for e in node.elts)) + "}"
        if isinstance(node, ast.Dict):
            return "{" + ",".join(f"{self.n(k)}:{self.n(v)}"
                                  for k, v in zip(node.keys, node.values)
                                  if k is not None) + "}"
        if isinstance(node, ast.UnaryOp):
            return f"{type(node.op).__name__}({self.n(node.operand)})"
        if isinstance(node, ast.BinOp):
            return (f"({self.n(node.left)}{type(node.op).__name__}"
                    f"{self.n(node.right)})")
        if isinstance(node, ast.BoolOp):
            return (f"{type(node.op).__name__}("
                    + ",".join(self.n(v) for v in node.values) + ")")
        if isinstance(node, ast.NamedExpr):
            return self.n(node.value)
        if isinstance(node, ast.IfExp):
            return (f"if({self.n(node.body)}|{self.n(node.test)}|"
                    f"{self.n(node.orelse)})")
        if isinstance(node, ast.Compare):
            sides = [node.left] + node.comparators
            return "cmp(" + ",".join(
                self.n(s) for s in sides) + "|" + ",".join(
                    type(o).__name__ for o in node.ops) + ")"
        return "E" + ast.dump(node)

    def exc_name(self, node):
        """Exception-class spelling for raises(E): raw dotted name,
        tuple -> sorted '+'-joined names."""
        if isinstance(node, (ast.Tuple, ast.List)):
            return "+".join(sorted(filter(None, (
                self.exc_name(e) for e in node.elts))))
        f = node
        parts = []
        while isinstance(f, ast.Attribute):
            parts.append(f.attr)
            f = f.value
        if isinstance(f, ast.Name):
            parts.append(f.id)
        return ".".join(reversed(parts)) if parts else "?"

    def const_eval(self, node):
        """(ok, value) — constant-fold an expr after env substitution.
        Used to resolve `if` tests to their taken branch."""
        subbed = _Sub(self.env).visit(copy.deepcopy(node))
        return _const_eval(subbed)


class _Sub(ast.NodeTransformer):
    def __init__(self, env):
        self.env = env

    def visit_Name(self, node):
        if node.id in self.env:
            return copy.deepcopy(self.env[node.id])
        return node


_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
           ast.Mod: lambda a, b: a % b, ast.FloorDiv: lambda a, b: a // b}
_CMPOPS = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
           ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
           ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
           ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b,
           ast.In: lambda a, b: a in b,
           ast.NotIn: lambda a, b: a not in b}


def _const_eval(node):
    """(ok, value) for exprs built of literals: constants/containers,
    BoolOp, unary not, comparisons, arithmetic."""
    try:
        return True, ast.literal_eval(node)
    except Exception:
        pass
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        ok, v = _const_eval(node.operand)
        return (True, not v) if ok else (False, None)
    if isinstance(node, ast.BoolOp):
        vals = []
        for x in node.values:
            ok, v = _const_eval(x)
            if not ok:
                return False, None
            vals.append(v)
        return True, all(vals) if isinstance(node.op, ast.And) \
            else any(vals)
    if isinstance(node, ast.Compare):
        sides = [node.left] + node.comparators
        vals = []
        for s in sides:
            ok, v = _const_eval(s)
            if not ok:
                return False, None
            vals.append(v)
        try:
            return True, all(type(node.ops[i]) in _CMPOPS and _CMPOPS[
                type(node.ops[i])](vals[i], vals[i + 1])
                for i in range(len(node.ops)))
        except Exception:
            return False, None
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        okl, lv = _const_eval(node.left)
        okr, rv = _const_eval(node.right)
        if not (okl and okr):
            return False, None
        try:
            return True, _BINOPS[type(node.op)](lv, rv)
        except Exception:
            return False, None
    if isinstance(node, ast.IfExp):
        ok, t = _const_eval(node.test)
        return _const_eval(node.body if ok and t else node.orelse) \
            if ok else (False, None)
    return False, None


# --------------------------------------------------------------- predicates

# pred tuples: (kind, subject, payload...)
#   eq       (eq, subj, expected)
#   neq      (neq, subj, expected)
#   cmp      (cmp, subj, opstr, other)
#   in/notin (in, container_norm, member_norm)
#   truthy/falsy/none/notnone (kind, subj)
#   raises   (raises, call_norm, exc_names, match_norm)

_CMP_DIR = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}


def _is_lit(s):
    return s.startswith("L")


def _litval(s):
    """(ok, value) for an 'L<repr>' norm string."""
    if not _is_lit(s):
        return False, None
    try:
        return True, ast.literal_eval(s[1:])
    except Exception:
        return False, None


def _cmp_pred(n, l_node, op, r_node):
    """(cmp, subj, op, other) normalized so the literal side — if
    exactly one — sits in `other` with the op flipped to the subject's
    perspective."""
    nl, nr = n.n(l_node), n.n(r_node)
    opstr = _CMP_DIR[type(op)]
    if _is_lit(nr) and not _is_lit(nl):
        return ("cmp", nl, opstr, nr)
    if _is_lit(nl) and not _is_lit(nr):
        return ("cmp", nr, _FLIP[opstr], nl)
    return ("cmp", nl, opstr, nr)


def _assert_preds(n, test):
    """Predicate tuples for one `assert <test>`."""
    preds = []
    if isinstance(test, ast.Compare):
        sides = [test.left] + test.comparators
        for i, op in enumerate(test.ops):
            l, r = sides[i], sides[i + 1]
            nl, nr = n.n(l), n.n(r)
            if isinstance(op, (ast.Eq, ast.Is)):
                if nl == "LNone" and nr != "LNone":
                    preds.append(("none", nr))
                elif nr == "LNone" and nl != "LNone":
                    preds.append(("none", nl))
                elif _is_lit(nl) and not _is_lit(nr):
                    preds.append(("eq", nr, nl))
                else:
                    preds.append(("eq", nl, nr))
            elif isinstance(op, (ast.NotEq, ast.IsNot)):
                if nl == "LNone" and nr != "LNone":
                    preds.append(("notnone", nr))
                elif nr == "LNone" and nl != "LNone":
                    preds.append(("notnone", nl))
                elif _is_lit(nl) and not _is_lit(nr):
                    preds.append(("neq", nr, nl))
                else:
                    preds.append(("neq", nl, nr))
            elif isinstance(op, (ast.In, ast.NotIn)):
                preds.append(("in" if isinstance(op, ast.In) else "notin",
                              nr, nl))
            elif type(op) in _CMP_DIR:
                preds.append(_cmp_pred(n, l, op, r))
        return preds
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return [("falsy", n.n(test.operand))]
    return [("truthy", n.n(test))]


def _raises_pred(n, with_node, ctx_expr):
    """Predicate tuple for `with pytest.raises(...)`: subject = the
    operation statement(s) in the with body."""
    exc = n.exc_name(ctx_expr.args[0]) if ctx_expr.args else "?"
    match = ""
    for kw in ctx_expr.keywords:
        if kw.arg == "match":
            match = n.n(kw.value)
    ops = [n.n(st.value) for st in with_node.body
           if isinstance(st, (ast.Expr, ast.Assign))
           and isinstance(st.value, _OP_EXPR)]
    subj = "|".join(ops) if ops else "<body>"
    return ("raises", subj, exc, match)


def _is_raises_ctx(ctx_expr):
    return isinstance(ctx_expr, ast.Call) \
        and _call_name(ctx_expr) == "raises"


_SKIP_STMT = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# expression shapes that count as exercised operations when they stand
# as a statement / assigned value: v[3], a < b, f(x), x.attr, -v, ...
_OP_EXPR = (ast.Call, ast.Subscript, ast.BinOp, ast.UnaryOp, ast.BoolOp,
            ast.Compare, ast.IfExp, ast.Attribute, ast.Await)


def _walk_body(stmts, n, calls, preds, sigs=None):
    """Collect normalized call norms + oracle predicates over a
    statement list, resolving constant-foldable `if` branches."""
    for st in stmts:
        if isinstance(st, ast.If):
            for c in ast.walk(st.test):
                if isinstance(c, ast.Call):
                    calls.add(n.n(c))
                    _add_call_sig(n, c, sigs)
            ok, v = n.const_eval(st.test)
            if ok and v:
                _walk_body(st.body, n, calls, preds, sigs)
            elif ok:
                _walk_body(st.orelse, n, calls, preds, sigs)
            else:
                _walk_body(st.body, n, calls, preds, sigs)
                _walk_body(st.orelse, n, calls, preds, sigs)
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                if _is_raises_ctx(item.context_expr):
                    preds.append(_raises_pred(n, st, item.context_expr))
                else:
                    for c in ast.walk(item.context_expr):
                        if isinstance(c, ast.Call):
                            calls.add(n.n(c))
                            _add_call_sig(n, c, sigs)
            _walk_body(st.body, n, calls, preds, sigs)
        elif isinstance(st, (ast.For, ast.AsyncFor)):
            for c in ast.walk(st.iter):
                if isinstance(c, ast.Call):
                    calls.add(n.n(c))
                    _add_call_sig(n, c, sigs)
            _walk_body(st.body, n, calls, preds, sigs)
            _walk_body(st.orelse, n, calls, preds, sigs)
        elif isinstance(st, ast.While):
            for c in ast.walk(st.test):
                if isinstance(c, ast.Call):
                    calls.add(n.n(c))
                    _add_call_sig(n, c, sigs)
            _walk_body(st.body, n, calls, preds, sigs)
            _walk_body(st.orelse, n, calls, preds, sigs)
        elif isinstance(st, ast.Try):
            _walk_body(st.body, n, calls, preds, sigs)
            for h in st.handlers:
                _walk_body(h.body, n, calls, preds, sigs)
            _walk_body(st.orelse, n, calls, preds, sigs)
            _walk_body(st.finalbody, n, calls, preds, sigs)
        elif not isinstance(st, _SKIP_STMT):
            if isinstance(st, (ast.Expr, ast.Assign, ast.AugAssign,
                               ast.Return)) and st.value is not None \
                    and isinstance(st.value, _OP_EXPR):
                calls.add(n.n(st.value))
            for c in ast.walk(st):
                if isinstance(c, ast.Call):
                    calls.add(n.n(c))
                    _add_call_sig(n, c, sigs)
            if isinstance(st, ast.Assert):
                preds += _assert_preds(n, st.test)


def _add_call_sig(n, c, sigs):
    """Record the flag-green-collision signature of one call: its
    callee basename plus the normalized tuple of arg literals when
    EVERY arg resolves to a literal. Literal list/tuple/set args also
    mint an argv-tuple signature ('#argv', elts) — the
    `parse(["-f","x"])` shape a Java `new String[]{...}` row mirrors.
    """
    if sigs is None:
        return
    name = _call_name(c)
    if not name:
        return
    args, arrs = [], []
    for a in c.args:
        if isinstance(a, ast.Starred):
            return
        norm = n.n(a)
        if not _is_lit(norm):
            return
        args.append(norm)
        ok, v = _litval(norm)
        if ok and isinstance(v, (tuple, list)) and v and \
                all(isinstance(x, (str, int, float, bool)) for x in v):
            arrs.append(tuple(v))
    for k in c.keywords:
        if k.arg is None:
            return
        norm = n.n(k.value)
        if not _is_lit(norm):
            return
        args.append(f"{k.arg}={norm}")
    if args:
        sigs.add((name, tuple(args)))
    for t in arrs:
        sigs.add(("#argv", t))


def function_signature(fn, env):
    """(input_set, preds, sigs) for one case's env: every normalized
    call in the executed body, its oracle predicates, and the
    all-literal call-arg signatures for the flag-green-collision join."""
    assigns = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            assigns.setdefault(node.targets[0].id, node.value)
    n = _Norm(env, assigns)
    calls, preds, sigs = set(), [], set()
    _walk_body(fn.body, n, calls, preds, sigs)
    return tuple(sorted(calls)), frozenset(preds), sigs


# ------------------------------------------------------------- parametrize

def _param_names(arg):
    """argnames list from a parametrize decorator's first arg."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [s.strip() for s in arg.value.split(",") if s.strip()]
    if isinstance(arg, (ast.List, ast.Tuple)):
        names = []
        for e in arg.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                names.append(e.value)
            else:
                return None
        return names
    return None


def _row_values(elt, n_names):
    """Positional value nodes for one argvalues element:
    pytest.param(...) -> .args; tuple matching arity -> .elts;
    single-name row -> the element itself."""
    if isinstance(elt, ast.Call) and _call_name(elt) == "param":
        return list(elt.args)
    if n_names and n_names > 1 and isinstance(elt, ast.Tuple) \
            and len(elt.elts) == n_names:
        return list(elt.elts)
    return [elt]


def _parametrize_axis(deco):
    """(names, [(value_nodes, lineno)]) for one parametrize decorator;
    None when not a parseable parametrize."""
    if not isinstance(deco, ast.Call) or _call_name(deco) != "parametrize" \
            or len(deco.args) < 2:
        return None
    names = _param_names(deco.args[0])
    vals = deco.args[1]
    rows = []
    if isinstance(vals, (ast.List, ast.Tuple)):
        n_names = len(names) if names else 1
        for elt in vals.elts:
            rows.append((_row_values(elt, n_names), elt.lineno))
    return names, rows


def fn_cases(fn):
    """Yield (env, lineno) per case: one per argvalues row, one for
    non-parametrized functions."""
    axes = []
    for deco in fn.decorator_list:
        ax = _parametrize_axis(deco)
        if ax:
            axes.append(ax)
    if not axes:
        yield {}, fn.lineno
        return
    products = []
    for names, rows in axes:
        if not rows:
            # unresolvable argvalues (name ref, call): one placeholder row
            rows = [([ast.Constant(value=None)], fn.lineno)]
        if names is None or len(names) != len(rows[0][0]):
            names = [None] * len(rows[0][0])
        products.append([(dict(zip(names, vals)), line)
                         for vals, line in rows])
    for combo in itertools.product(*products):
        env = {}
        line = fn.lineno
        for i, (e, l) in enumerate(combo):
            env.update({k: v for k, v in e.items() if k})
            if i == 0:
                line = l
        yield env, line


# --------------------------------------------------------------- sweeping

def collect_cases(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError) as e:
        return [], [(path, 0, WARN, "unparseable", str(e))]
    cases, finds = [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test"):
            for env, line in fn_cases(node):
                calls, preds, sigs = function_signature(node, env)
                cases.append({
                    "file": path, "line": line, "name": node.name,
                    "input": calls, "preds": preds, "sigs": sigs,
                })
    return cases, finds


# ----------------------------------------------- flag-green-collision join
#
# A green assert and a flag/red test asserting on the SAME input
# literal (same call args, modulo trivial normalization) contradict:
# one must be wrong. The join is signature-based: Python cases emit
# (callee, literal-arg-tuple) sigs from their executed bodies and
# ('#argv', elts) sigs for literal argv lists; Java files are scanned
# textually for `new T[]{...}` argv literals and `asList`/`of`-family
# collection factories — the input literal a suite feeds the SUT.
# A signature shared by a green file and a suspected-defect file
# => FAIL.

JAVA_ARGV_RE = re.compile(
    r"\bnew\s+[\w.$]*(?:<[^;{}()]*>)?\s*\[\s*\]\s*\{")
JAVA_FACTORY_WORDS = {"aslist", "of", "singleton", "singletonlist",
                      "singletonmap", "ncopies", "argumentsof"}
JAVA_CALL_RE = re.compile(r"\b([a-z][A-Za-z0-9_]*)\s*\(")
JAVA_STR_LIT_RE = re.compile(r'"(?:\\.|[^"\\])*"')
JAVA_CHAR_LIT_RE = re.compile(r"'(?:\\.|[^'\\])'")
JAVA_NUM_LIT_RE = re.compile(
    r"\b\d+(?:_\d+)*(?:\.\d+(?:_\d+)*)?(?:[eE][+-]?\d+)?[fFdDlL]?\b|"
    r"\b0[xX][0-9a-fA-F]+[lL]?\b")
JAVA_KW_LIT_RE = re.compile(r"\b(?:true|false|null)\b")


def _java_skip_ws(text, i):
    while i < len(text) and text[i] in " \t\n\r":
        i += 1
    return i


def _java_match_paren(text, start):
    """Index of the ')' matching text[start] == '(' (or '{'=='}'),
    quote/char/comment-aware; -1 when unbalanced."""
    close = ")" if text[start] == "(" else "}"
    open_ = text[start]
    depth, i, quote, esc = 0, start, None, False
    while i < len(text):
        ch = text[i]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "/" and text[i:i + 2] == "//":
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        elif ch == "/" and text[i:i + 2] == "/*":
            j = text.find("*/", i + 2)
            i = len(text) if j < 0 else j + 1
        elif ch == open_:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _java_split_args(argstr):
    """Split a Java arg list on top-level commas (quote/paren-safe)."""
    args, depth, quote, esc, cur = [], 0, None, False, []
    i = 0
    while i < len(argstr):
        ch = argstr[i]
        if quote:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "/" and argstr[i:i + 2] == "//":
            j = argstr.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        elif ch == "/" and argstr[i:i + 2] == "/*":
            j = argstr.find("*/", i + 2)
            if j < 0:
                break
            i = j + 1
            continue
        elif ch == "," and depth == 0:
            args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        args.append(tail)
    return args


def _java_decode_str(tok):
    """Decode a Java string/char literal body (no quotes)."""
    out, i = [], 0
    while i < len(tok):
        ch = tok[i]
        if ch == "\\" and i + 1 < len(tok):
            nxt = tok[i + 1]
            if nxt == "u" and i + 5 < len(tok):
                try:
                    out.append(chr(int(tok[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b",
                        "f": "\f", "0": "\0", "\\": "\\", '"': '"',
                        "'": "'"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _java_lit_value(arg):
    """(ok, value) — a Java literal arg normalized to a Python value."""
    a = arg.strip()
    m = JAVA_STR_LIT_RE.fullmatch(a)
    if m:
        return True, _java_decode_str(m.group(0)[1:-1])
    m = JAVA_CHAR_LIT_RE.fullmatch(a)
    if m:
        return True, _java_decode_str(m.group(0)[1:-1])
    m = JAVA_NUM_LIT_RE.fullmatch(a)
    if m:
        t = re.sub(r"[fFdDlL]$", "", m.group(0)).replace("_", "")
        try:
            return True, float(t) if re.search(r"[.eE]", t) else int(t)
        except ValueError:
            try:
                return True, int(t, 16)
            except ValueError:
                return False, None
    if JAVA_KW_LIT_RE.fullmatch(a):
        return True, {"true": True, "false": False, "null": None}[a]
    return False, None


def _java_lit_tuple(argstr):
    """tuple of decoded literals when EVERY comma-separated arg is a
    literal, else None."""
    if not argstr.strip():
        return None
    vals = []
    for a in _java_split_args(argstr):
        ok, v = _java_lit_value(a)
        if not ok:
            return None
        vals.append(v)
    return tuple(vals)


def java_arg_sigs(text):
    """Yield (lineno, sig) for argv-literal and all-literal call
    signatures in Java test source."""
    seen_at = set()
    for m in JAVA_ARGV_RE.finditer(text):
        open_i = text.index("{", m.start())
        close_i = _java_match_paren(text, open_i)
        if close_i < 0:
            continue
        t = _java_lit_tuple(text[open_i + 1:close_i])
        if t:
            ln = text.count("\n", 0, m.start()) + 1
            if (ln, "#argv") not in seen_at:
                seen_at.add((ln, "#argv"))
                yield ln, ("#argv", t)
    for m in JAVA_CALL_RE.finditer(text):
        name = m.group(1)
        if name.lower() not in JAVA_FACTORY_WORDS:
            continue
        open_i = text.index("(", m.end() - 1)
        close_i = _java_match_paren(text, open_i)
        if close_i < 0:
            continue
        t = _java_lit_tuple(text[open_i + 1:close_i])
        if t:
            yield text.count("\n", 0, m.start()) + 1, ("#argv", t)


# ------------------------------------------------------------- weakening

def _satisfies_cmp(val, op, bound):
    try:
        return {">": val > bound, ">=": val >= bound,
                "<": val < bound, "<=": val <= bound}[op]
    except TypeError:
        return None


def weaker(a, b):
    """True when predicate a is a strict superset (weaker oracle) of
    predicate b. Same subject required; raises compared on its own
    payload."""
    if a[0] == "raises" or b[0] == "raises":
        if a[0] != "raises" or b[0] != "raises" or a[1] != b[1]:
            return False
        a_exc, b_exc = set(a[2].split("+")), set(b[2].split("+"))
        if a_exc != b_exc:
            return (b_exc < a_exc) or bool(
                a_exc & {"Exception", "BaseException"})
        return not a[3] and bool(b[3])          # match= pins harder
    if a[1] != b[1]:
        return False
    ak, bk = a[0], b[0]
    if ak == bk:
        return False                            # equal kind handled by
                                                # subset / same-payload
    b_val = _litval(b[2]) if bk in ("eq", "neq") else (False, None)
    if ak == "truthy":
        if bk == "eq":
            ok, v = b_val
            return ok and bool(v)
        if bk in ("notnone", "in"):
            return True
        if bk == "cmp":
            ok, t = _litval(b[3])
            return ok and b[2] in (">", ">=") and t >= 0
        return False
    if ak == "falsy":
        if bk == "eq":
            ok, v = b_val
            return ok and not v
        return bk == "none"
    if ak == "notnone":
        if bk in ("truthy", "cmp", "in"):
            return True
        if bk == "eq":
            ok, v = b_val
            return ok and v is not None
        return False
    if ak == "neq":
        if bk == "eq":
            a_ok, av = _litval(a[2])
            b_ok, bv = b_val
            return a_ok and b_ok and av != bv
        if bk == "truthy":
            a_ok, av = _litval(a[2])
            return a_ok and not av
        return False
    if ak == "cmp":
        ok_t, t = _litval(a[3])
        if not ok_t:
            return False
        if bk == "eq":
            ok, v = b_val
            return ok and _satisfies_cmp(v, a[2], t) is True
        if bk == "cmp":
            ok2, t2 = _litval(b[3])
            inc = a[2] in (">", ">=") and b[2] in (">", ">=")
            dec = a[2] in ("<", "<=") and b[2] in ("<", "<=")
            return ok2 and (inc or dec) and \
                _satisfies_cmp(t2, a[2], t) is True
        return False
    if ak in ("in", "notin"):
        if bk == "eq":
            ok_m, m = _litval(a[2])
            ok_c, c = b_val
            if not (ok_m and ok_c):
                return False
            try:
                inside = m in c
            except TypeError:
                return False
            return inside if ak == "in" else not inside
        return False
    if ak == "eq":
        # approx(expected) admits a band around the literal an exact
        # == pins: same subject, loose expected -> strictly weaker
        return bk == "eq" and "approx(" in a[2] and a[2] != b[2]
    return False


def near_dup(a, b):
    """(weaker_case, stronger_case) when a's oracle is strictly
    covered by b's, else None. Requires identical input sets and
    non-identical predicate sets."""
    if a["input"] != b["input"] or a["preds"] == b["preds"]:
        return None
    if a["preds"] < b["preds"]:
        return a, b
    if b["preds"] < a["preds"]:
        return b, a
    if a["preds"] and all(
            any(p == q or weaker(p, q) for q in b["preds"])
            for p in a["preds"]):
        return a, b
    if b["preds"] and all(
            any(p == q or weaker(p, q) for q in a["preds"])
            for p in b["preds"]):
        return b, a
    return None


def main():
    ap = argparse.ArgumentParser(
        description="AST sweep for duplicate / near-duplicate "
                    "parametrized test cases.")
    ap.add_argument("tests", nargs="+", help="test dirs or files")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()

    files, jfiles = [], []
    for t in args.tests:
        if os.path.isfile(t):
            if t.endswith(".py"):
                files.append(t)
            elif t.endswith(".java"):
                jfiles.append(t)
        elif os.path.isdir(t):
            for root, _, fns in os.walk(t):
                for f in sorted(fns):
                    if f.endswith(".py"):
                        files.append(os.path.join(root, f))
                    elif f.endswith(".java"):
                        jfiles.append(os.path.join(root, f))
        else:
            print(f"error: not found: {t}")
            return 2
    files = sorted(set(files))
    jfiles = sorted(set(jfiles))
    flag_files = [f for f in files
                  if os.path.basename(f).startswith(DEFECT_GLOB)]
    files = [f for f in files if f not in flag_files]
    jflag = [f for f in jfiles
             if "suspected" in os.path.basename(f).lower()]
    jgreen = [f for f in jfiles if f not in jflag]

    cases, finds = [], []
    for path in files:
        c, f = collect_cases(path)
        cases += c
        finds += f
    flag_cases = []
    for path in flag_files:
        c, f = collect_cases(path)
        flag_cases += c
        finds += f

    # dup: identical (input set, predicate set)
    seen = {}
    for c in cases:
        sig = (c["input"], c["preds"])
        if sig in seen:
            o = seen[sig]
            if o["file"] != c["file"] or o["name"] != c["name"]:
                finds.append((c["file"], c["line"], FAIL, "dup",
                              f"identical input + oracle to "
                              f"'{o['name']}' at {o['file']}:{o['line']}"))
        else:
            seen[sig] = c

    # near-dup: identical input set, strictly weaker oracle
    by_input = {}
    for c in cases:
        by_input.setdefault(c["input"], []).append(c)
    for inp, group in by_input.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pair = near_dup(group[i], group[j])
                if pair is None:
                    continue
                w, s = pair
                if w["file"] == s["file"] and w["name"] == s["name"]:
                    continue
                kind = ("subset oracle" if w["preds"] < s["preds"]
                        else "strictly weaker oracle")
                finds.append((w["file"], w["line"], WARN, "near-dup",
                              f"{kind} than '{s['name']}' on the same "
                              f"input at {s['file']}:{s['line']}"))

    # cross-verdict: flag-case input appearing in any green case
    green_inputs = {c["input"]: c for c in cases}
    for fc in flag_cases:
        g = green_inputs.get(fc["input"])
        if g is not None:
            finds.append((g["file"], g["line"], FAIL,
                          "contradiction",
                          f"input also asserted as defect flag "
                          f"'{fc['name']}' at "
                          f"{fc['file']}:{fc['line']} — a divergent "
                          f"outcome is never a green expected value"))

    # flag-green-collision (r36): an exact-arg signature — callee +
    # all-literal args, or an argv literal — shared by a green file and
    # a *SuspectedDefects*/flag file. One side asserts the observed
    # outcome, the other the conforming one: they cannot both be right.
    green_sigs = {}
    for c in cases:
        for s in c["sigs"]:
            green_sigs.setdefault(s, c)
    for fp in jgreen:
        try:
            src = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for ln, s in java_arg_sigs(src):
            if s not in green_sigs:
                green_sigs[s] = {"file": fp, "line": ln,
                                 "name": "<java>"}
    seen_coll = set()
    for fc in flag_cases:
        for s in fc["sigs"]:
            g = green_sigs.get(s)
            if g is None or (s, g["file"], g["line"]) in seen_coll:
                continue
            seen_coll.add((s, g["file"], g["line"]))
            finds.append((g["file"], g["line"], FAIL,
                          "flag-green-collision",
                          f"call args {s[1]!r} on '{s[0]}' also "
                          f"asserted as defect flag '{fc['name']}' at "
                          f"{fc['file']}:{fc['line']} — same input, "
                          f"opposite verdicts: one is wrong"))
    for fp in jflag:
        try:
            src = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for ln, s in java_arg_sigs(src):
            g = green_sigs.get(s)
            if g is None or (s, g["file"], g["line"]) in seen_coll:
                continue
            seen_coll.add((s, g["file"], g["line"]))
            finds.append((g["file"], g["line"], FAIL,
                          "flag-green-collision",
                          f"input literal {s[1]!r} also asserted as "
                          f"defect flag at {fp}:{ln} — same input, "
                          f"opposite verdicts: one is wrong"))

    finds = sorted(set(finds), key=lambda x: (x[0], x[1]))
    n_fail = sum(1 for f in finds if f[2] == FAIL)
    n_warn = sum(1 for f in finds if f[2] == WARN)
    print(f"dup_sweep: {len(files)} file(s), {len(cases)} case(s)"
          + (f" [{len(flag_files) + len(jflag)} flag file(s) "
             f"cross-verdicted: {len(flag_cases)} flag case(s)]"
             if flag_files or jflag else "")
          + (f" [{len(jfiles)} java file(s) collision-scanned]"
             if jfiles else ""))
    for path, lineno, sev, shape, msg in finds:
        print(f"  {path}:{lineno}: [{sev}] {shape}: {msg}")
    if args.json:
        json.dump([{"file": p, "line": l, "severity": s, "shape": sh,
                    "msg": m} for p, l, s, sh, m in finds],
                  open(args.json, "w"), indent=1)
        print(f"  json -> {args.json}")
    if not finds:
        print("  OK — no duplicate-case findings")
    else:
        print(f"  {n_fail} dup(s), {n_warn} near-dup warning(s)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
