#!/usr/bin/env python3
"""Guard-site census — join implementation guard shapes against the
ledger member corpus. Stdlib only (uses PyYAML / ledger_reconcile.py
for ledger parsing when available).

Usage: guard_census.py TEST_DESIGN.md --case-dir SRC_DIR [--json out]

The skill's guard-site-census rule: each implementation guard shape
mints its own member classes, per door. This checker extracts the
shapes mechanically from Python source (AST) and asks whether the
```ledger corpus plausibly enumerated each required class:

  * `except (A, B, ...)` multi-class tuple — one member class per
    named exception class (the impl may route each differently)
  * `x.is*()` predicate calls — the satisfied class and the rejected
    class; the isdecimal ⊂ isdigit ⊂ isnumeric ladder additionally
    mints an "exclusive" class (satisfies this predicate but not the
    next-narrower — superscripts for isdigit, fractions/CJK for
    isnumeric)
  * `int()`/`float()`/`Decimal()`/`Fraction()` conversion sites —
    the conversion-grammar member set: a string-spelling class, an
    adjacent-type class (bool/float/index for int(), etc.), and a
    rejection class. Calls whose inputs are already regex-bounded
    (`int(m.group(...))`) are counted but mint nothing — their
    grammar is owned by the regex site.
  * `re.fullmatch`/`re.match`/`re.search`/`pattern.fullmatch(x)`
    validation calls — a conforming class and a rejecting class
  * protocol/dunder dispatch — `SupportsX` names in annotations
    (each protocol = an accepted-type member class; concrete siblings
    in the same Union mint classes too), `operator.index()` calls,
    '__index__'-style dunder string probes (hasattr/getattr), and
    multi-class isinstance/issubclass tuples — a member class per
    dispatched type
  * single-type `isinstance(x, cls)`/`issubclass` guards — the
    accepted type, a subclass-of-cls instance member, and a non-cls
    adjacent-type member
  * ambient-state reads in guard predicates (`if`/`elif`/`while`,
    ternary, `assert`) — each module-attribute read (`sys.argv`,
    `pkg.CONST`), module-level global, or unbound/dunder name
    (`__package__`) a guard consults mints an ambient member class

Coverage is PLAUSIBLE, not proven: a required class counts as covered
when some ledger spelling — an obligation id, a member key, a witness
test name, a fold member/target — hits one of the class's signal
tokens (whole-word match, >=4-char prefix stems, or squashed
substring for long class names like 'valueerror'). A finding means
"no spelling plausibly enumerates this class" — resolve by adding
the member or confirming a mechanism-spelled member already covers
it.

Exit: 0 clean (incl. "no ```ledger block" / "no guard sites"
diagnostics), 1 findings, 2 usage/fatal error. Unparseable source
files are warnings, never fatal.
"""
import argparse
import ast
import builtins
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger_reconcile import extract_fenced, load_ledger, tail_name
except Exception:
    extract_fenced = load_ledger = None

    def tail_name(t):
        return t.rsplit("::", 1)[-1].strip().strip('`"\'')


# ------------------------------------------------------------- token matching

def _words(text):
    """Word set of a spelling: lowercase alnum runs."""
    return {w for w in re.split(r"[^a-z0-9]+", str(text).lower()) if w}


def _squash(text):
    """Whole spelling squashed to one alnum run: 'value-Error' -> 'valueerror'."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _word_hit(words, tok):
    """tok hits a word set: exact, or >=4-char prefix-stem in either
    direction ('digit'~'digits', 'index'~'indexed')."""
    if tok in words:
        return True
    if len(tok) >= 4:
        for w in words:
            if w.startswith(tok) or (len(w) >= 4 and tok.startswith(w)):
                return True
    return False


def _camel_words(name):
    """'ZeroDivisionError' -> {'zero','division','error'}."""
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name))
    return _words(parts)


# ------------------------------------------------------------- class registry
#
# Each guard site emits required member classes:
#   {site, door, cls, label, words, subs}
# A class is plausibly covered when some corpus spelling has a `words`
# token as a word/stem OR a `subs` token as a squashed substring.

LADDER = {"isdecimal": ("decimal", 0), "isdigit": ("digit", 1),
          "isnumeric": ("numeric", 2)}
OTHER_IS = {"isalpha", "isalnum", "isascii", "isidentifier", "islower",
            "isupper", "istitle", "isspace", "isprintable"}
IS_PREDS = set(LADDER) | OTHER_IS

CONVERSIONS = {
    # name: (string-grammar words, adjacent-type words, reject words)
    "int": ({"str", "string", "digits", "padded", "sign", "signed",
             "underscore", "underscored", "whitespace", "unicode",
             "literal", "prefixed", "base"},
            {"bool", "boolean", "float", "index", "enum", "integral",
             "decimal", "fraction", "truncates", "number"},
            {"none", "list", "dict", "tuple", "set", "object", "range",
             "typeerror", "valueerror", "invalid", "reject", "rejected",
             "alpha", "letters", "empty", "nan", "inf", "infinity",
             "floatstr", "nonnumeric", "bytes"}),
    "float": ({"str", "string", "digits", "padded", "sign", "signed",
               "underscore", "underscored", "whitespace", "unicode",
               "literal", "exponent", "scientific", "inf", "infinity",
               "nan"},
              {"int", "ints", "bool", "boolean", "index", "integral",
               "decimal", "fraction", "number"},
              {"none", "list", "dict", "tuple", "set", "object", "range",
               "typeerror", "valueerror", "invalid", "reject", "rejected",
               "alpha", "letters", "empty", "nonnumeric", "bytes"}),
    "Decimal": ({"str", "string", "digits", "padded", "sign", "signed",
                 "whitespace", "unicode", "literal", "exponent",
                 "scientific", "inf", "infinity", "nan", "tuple"},
                {"int", "ints", "bool", "boolean", "float", "index",
                 "integral", "fraction", "number"},
                {"none", "list", "dict", "set", "object", "range",
                 "typeerror", "valueerror", "invalid", "reject",
                 "rejected", "alpha", "letters", "empty", "nonnumeric",
                 "bytes"}),
    "Fraction": ({"str", "string", "digits", "ratio", "slash",
                  "whitespace", "literal", "sign", "signed"},
                 {"int", "ints", "bool", "boolean", "float", "decimal",
                  "number", "rational"},
                 {"none", "list", "dict", "tuple", "set", "object",
                  "typeerror", "valueerror", "zerodivisionerror",
                  "invalid", "reject", "rejected", "alpha", "letters",
                  "empty", "nonnumeric", "bytes"}),
}

REGEX_FUNCS = {"fullmatch", "match", "search"}
PROTO_RE = re.compile(r"Supports[A-Z]\w*")
DUNDER_PROBES = {"__index__", "__int__", "__float__", "__complex__",
                 "__bytes__", "__trunc__", "__floor__", "__ceil__",
                 "__round__"}
BUILTINS = frozenset(dir(builtins))


def _dotted(node):
    """'a.b.c' for Name/Attribute chains, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _exc_class(name):
    """Required member-class descriptor for an exception class name."""
    words = _camel_words(name) - {"error", "exception"}
    if not words:
        words = {str(name).lower()}
    subs = {_squash(name)} if len(_squash(name)) >= 5 else set()
    return {"cls": f"except:{name}",
            "label": f"exception class '{name}'",
            "words": words, "subs": subs}


def _type_class(tag, name):
    """Required member class for a dispatched/accepted type name."""
    words = _camel_words(name) - {"error", "exception"}
    words.add(str(name).split(".")[-1].lower())
    subs = {_squash(name)} if len(_squash(name)) >= 5 else set()
    return {"cls": f"{tag}:{name}", "label": f"accepted type '{name}'",
            "words": words, "subs": subs}


def _bound_names(fn):
    """Names bound inside a function scope: params plus every assigned,
    imported, or def'd name. Nested scopes are over-approximated —
    treating a name as bound only ever suppresses an ambient mint."""
    bound = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.Name) \
                and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, ast.Import):
            bound.update(a.asname or a.name.split(".")[0]
                         for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            bound.update(a.asname or a.name for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
    return bound


def _ambient_class(name):
    """Required member class for an ambient-state read in a guard: a
    module-attribute read, a module-level global, or an unbound/dunder
    name the predicate consults."""
    words = _words(name) | {"ambient", "global", "globals", "module",
                            "environ", "env", "state", "monkeypatch",
                            "monkeypatched", "patched", "patch"}
    subs = {"ambient", "monkeypatch"}
    if len(_squash(name)) >= 4:
        subs.add(_squash(name))
    return {"cls": f"ambient:{name}",
            "label": f"ambient-state member for guard read '{name}'",
            "words": words, "subs": subs}


def _is_ladder_exclusive(attr):
    """Exclusive-class tokens for ladder predicates (satisfies this
    predicate but not the next narrower)."""
    if attr == "isdigit":
        return {"cls": "isdigit-exclusive",
                "label": "member satisfying isdigit but not isdecimal "
                         "(superscript/subscript/circled digits)",
                "words": {"superscript", "subscript", "circled",
                          "nondecimal", "exclusive", "ladder"},
                "subs": {"notdecimal", "nondecimal", "digitnotdec",
                         "digitonly"}}
    if attr == "isnumeric":
        return {"cls": "isnumeric-exclusive",
                "label": "member satisfying isnumeric but not isdigit "
                         "(fractions, CJK numerals)",
                "words": {"fraction", "fractions", "vulgar", "cjk",
                          "numeral", "numerals", "nondigit",
                          "exclusive", "ladder"},
                "subs": {"notdigit", "nondigit", "numericonly"}}
    return None


class GuardVisitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.classes = []          # required member classes
        self.skipped_internal = 0  # conversion calls owned by regex sites
        self._fn_stack = []
        self._scope_stack = []     # bound-name sets, innermost last

    def _emit(self, node, door, cls):
        cls = dict(cls)
        cls.update({"site": f"{self.path}:{getattr(node, 'lineno', 0)}",
                    "line": getattr(node, "lineno", 0), "door": door,
                    "func": self._fn_stack[-1] if self._fn_stack else ""})
        self.classes.append(cls)

    # -- structural visitors (track enclosing def for context) ---------
    def visit_FunctionDef(self, node):
        self._fn_stack.append(node.name)
        self._scope_stack.append(_bound_names(node))
        self._annotation(node.returns)
        self.generic_visit(node)
        self._scope_stack.pop()
        self._fn_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    # -- except (A, B, ...) tuples --------------------------------------
    def visit_ExceptHandler(self, node):
        if isinstance(node.type, (ast.Tuple, ast.List)) \
                and len(node.type.elts) >= 2:
            for elt in node.type.elts:
                name = _dotted(elt)
                if name:
                    self._emit(node, "except-tuple", _exc_class(name))
        self.generic_visit(node)

    # -- calls -----------------------------------------------------------
    def visit_Call(self, node):
        func = node.func
        leaf = func.attr if isinstance(func, ast.Attribute) else \
            func.id if isinstance(func, ast.Name) else None
        dotted = _dotted(func) or ""

        # str.is* predicates
        if isinstance(func, ast.Attribute) and leaf in IS_PREDS:
            stem = LADDER.get(leaf, (leaf[2:], None))[0]
            self._emit(node, "str-is", {
                "cls": f"{leaf}-member",
                "label": f"member satisfying .{leaf}()",
                "words": {stem} | ({"number", "numeral"}
                                   if leaf == "isnumeric" else set()),
                "subs": {leaf}})
            ex = _is_ladder_exclusive(leaf)
            if ex:
                self._emit(node, "str-is", ex)
            neg_words = {"non" + stem, "not" + stem, "reject",
                         "rejected", "invalid", "fails"}
            if leaf in LADDER or leaf in ("isalpha", "isalnum"):
                neg_words |= {"alpha", "letters", "alphabetic"}
            self._emit(node, "str-is", {
                "cls": f"{leaf}-rejects",
                "label": f"member failing .{leaf}()",
                "words": neg_words,
                "subs": {"non" + _squash(stem), "not" + _squash(stem)}})

        # int()/float()/Decimal()/Fraction() conversions
        conv = None
        if isinstance(func, ast.Name) and leaf in CONVERSIONS:
            conv = leaf
        elif isinstance(func, ast.Attribute) and leaf in ("Decimal",
                                                        "Fraction"):
            conv = leaf
        if conv:
            if not node.args or all(
                    isinstance(a, ast.Constant) for a in node.args):
                pass                      # literal fold, no input domain
            elif all(isinstance(a, ast.Call)
                     and isinstance(a.func, ast.Attribute)
                     and a.func.attr in ("group", "groupdict", "groups")
                     for a in node.args):
                self.skipped_internal += 1   # grammar owned by regex site
            else:
                sw, aw, rw = CONVERSIONS[conv]
                self._emit(node, "conversion", {
                    "cls": f"{conv}():str-grammar",
                    "label": f"string-spelling member for {conv}() "
                             f"conversion grammar",
                    "words": set(sw),
                    "subs": {"string", "digits", "numstr", "padded",
                             "unicode"}})
                self._emit(node, "conversion", {
                    "cls": f"{conv}():adjacent-type",
                    "label": f"accepted adjacent-type member for "
                             f"{conv}()",
                    "words": set(aw), "subs": {"truncat"}})
                self._emit(node, "conversion", {
                    "cls": f"{conv}():rejects",
                    "label": f"rejected member for {conv}()",
                    "words": set(rw),
                    "subs": {"typeerror", "valueerror", "nonnumeric"}})

        # regex validation calls: re.fullmatch / pattern.match / x.search
        if isinstance(func, ast.Attribute) and leaf in REGEX_FUNCS:
            self._emit(node, "regex", {
                "cls": f"{leaf}-conform",
                "label": f"conforming member for .{leaf}() validation",
                "words": {"match", "matches", "matched", "conform",
                          "conforms", "valid", "accepted", "accepts",
                          "conforming"},
                "subs": {"fullmatch", "conform", "grammarvalid"}})
            self._emit(node, "regex", {
                "cls": f"{leaf}-reject",
                "label": f"rejecting member for .{leaf}() validation",
                "words": {"nomatch", "mismatch", "reject", "rejected",
                          "invalid", "bad", "nonconforming",
                          "unparseable"},
                "subs": {"nomatch", "mismatch", "nonconform",
                         "unparseable"}})

        # operator.index() dispatch
        if dotted.endswith("operator.index") or (
                leaf == "index" and isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "operator"):
            self._emit(node, "protocol", {
                "cls": "dunder:__index__",
                "label": "member exercising the __index__ protocol",
                "words": {"index", "supportsindex", "intenum", "enum"},
                "subs": {"supportsindex", "__index__"}})

        # hasattr/getattr(x, '__index__'-style) dunder probes
        if leaf in ("hasattr", "getattr"):
            for a in node.args[1:]:
                if isinstance(a, ast.Constant) and isinstance(
                        a.value, str) and a.value in DUNDER_PROBES:
                    inner = a.value.strip("_")
                    self._emit(node, "protocol", {
                        "cls": f"dunder:{a.value}",
                        "label": f"member exercising the {a.value} "
                                 f"protocol",
                        "words": {inner, "supports" + inner},
                        "subs": {_squash(a.value)}})

        # isinstance/issubclass dispatch tuples + SupportsX singles
        if leaf in ("isinstance", "issubclass") and len(node.args) >= 2:
            tgt = node.args[1]
            elts = tgt.elts if isinstance(tgt, (ast.Tuple, ast.List)) \
                else [tgt]
            multi = isinstance(tgt, (ast.Tuple, ast.List)) \
                and len(tgt.elts) >= 2
            for elt in elts:
                name = _dotted(elt)
                if not name:
                    continue
                base = name.split(".")[-1]
                if PROTO_RE.fullmatch(base):
                    self._emit(node, "protocol",
                               _type_class("protocol", base))
                elif multi:
                    self._emit(node, "type-dispatch",
                               _type_class("isinstance", base))
                elif len(elts) == 1:
                    # single-type guard: accepted type, a subclass
                    # instance, and a non-cls adjacent type
                    self._emit(node, "type-guard",
                               _type_class("isinstance", base))
                    sq = _squash(base)
                    self._emit(node, "type-guard", {
                        "cls": f"isinstance:{base}-subclass",
                        "label": f"subclass instance of '{base}'",
                        "words": {"subclass", "subclasses", "derived",
                                  "child", "subtype", "subtyped",
                                  "inherits", "inheritance"},
                        "subs": {"subclass", "subtype"}})
                    self._emit(node, "type-guard", {
                        "cls": f"isinstance:{base}-other",
                        "label": f"member of a non-{base} adjacent type",
                        "words": {"adjacent", "foreign", "unrelated",
                                  "other", "wrongtype", "badtype",
                                  "incompatible", "reject", "rejected",
                                  "typeerror", "invalid"},
                        "subs": {"non" + sq, "not" + sq}})
        self.generic_visit(node)

    # -- guard predicates: ambient-state reads ----------------------------
    def _guard(self, test):
        """Each ambient read a guard predicate consults mints an
        ambient-state member class."""
        bound = set().union(*self._scope_stack) \
            if self._scope_stack else set()
        reads = set()
        self._ambient_node(test, bound, reads)
        for name in sorted(reads):
            self._emit(test, "ambient-state", _ambient_class(name))

    def _ambient(self, node, bound, out):
        for child in ast.iter_child_nodes(node):
            self._ambient_node(child, bound, out)

    def _ambient_node(self, node, bound, out):
        """Collect dotted spellings of ambient reads inside a guard
        expression into `out`: attribute chains rooted at a non-local
        name (sys.argv, pkg.CONST) and bare non-local, non-builtin
        names (module globals, __package__)."""
        if isinstance(node, ast.Call):
            func = node.func
            leaf = func.attr if isinstance(func, ast.Attribute) else \
                func.id if isinstance(func, ast.Name) else None
            # a callee's own name isn't ambient state; the object a
            # method is invoked on can be (sys.platform.startswith -> sys.platform)
            if isinstance(func, ast.Attribute):
                self._ambient_node(func.value, bound, out)
            elif not isinstance(func, ast.Name):
                self._ambient_node(func, bound, out)
            args = node.args[:1] if leaf in ("isinstance", "issubclass") \
                and len(node.args) >= 2 else node.args
            for a in args:
                self._ambient_node(a, bound, out)
            for kw in node.keywords:
                self._ambient_node(kw.value, bound, out)
        elif isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id not in bound:
                d = _dotted(node)
                if d:
                    out.add(d)      # whole chain is a single read
            else:
                self._ambient(node, bound, out)
        elif isinstance(node, ast.Name) \
                and isinstance(node.ctx, ast.Load):
            dunder = node.id.startswith("__") and node.id.endswith("__")
            if node.id not in bound \
                    and (node.id not in BUILTINS or dunder):
                out.add(node.id)
        else:
            self._ambient(node, bound, out)

    def visit_If(self, node):
        self._guard(node.test)
        self.generic_visit(node)

    def visit_While(self, node):
        self._guard(node.test)
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self._guard(node.test)
        self.generic_visit(node)

    def visit_Assert(self, node):
        self._guard(node.test)
        self.generic_visit(node)

    # -- SupportsX in annotations; Union siblings ------------------------
    def _annotation(self, node):
        if node is None:
            return
        supports = [n for n in ast.walk(node)
                    if isinstance(n, (ast.Name, ast.Attribute))
                    and PROTO_RE.fullmatch(
                        n.id if isinstance(n, ast.Name) else n.attr)]
        if not supports:
            return
        for n in supports:
            base = n.id if isinstance(n, ast.Name) else n.attr
            suffix = PROTO_RE.match(base).group(0)[len("Supports"):]
            self._emit(node, "protocol", {
                "cls": f"protocol:{base}",
                "label": f"accepted protocol type '{base}'",
                "words": {suffix.lower(), "supports" + suffix.lower()},
                "subs": {_squash(base)}})
        # concrete siblings of a Union containing a SupportsX are
        # accepted types of the same dispatch domain
        for n in ast.walk(node):
            if isinstance(n, ast.Subscript):
                head = _dotted(n.value) or ""
                if head.split(".")[-1] in ("Union", "Optional"):
                    for leaf in ast.walk(n.slice):
                        if isinstance(leaf, (ast.Name, ast.Attribute)):
                            nm = leaf.id if isinstance(
                                leaf, ast.Name) else leaf.attr
                            if nm and not PROTO_RE.fullmatch(nm) \
                                    and nm not in ("None", "NoneType"):
                                self._emit(node, "protocol",
                                           _type_class("union", nm))

    def visit_arg(self, node):
        self._annotation(node.annotation)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._annotation(node.annotation)
        self.generic_visit(node)


def scan_source(case_dir):
    """Return (classes, skipped_internal, warnings)."""
    classes, skipped, warnings = [], 0, []
    for root, _, fns in os.walk(case_dir):
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError, ValueError) as e:
                warnings.append(f"{path}: unparseable — skipped ({e})")
                continue
            v = GuardVisitor(path)
            v.visit(tree)
            classes += v.classes
            skipped += v.skipped_internal
    # dedupe identical (site, cls) pairs
    seen, out = set(), []
    for c in classes:
        k = (c["site"], c["cls"])
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out, skipped, warnings


# ------------------------------------------------------------- ledger corpus

def ledger_corpus(md_text, errors):
    """All ledger spellings that can plausibly enumerate a member
    class: obligation ids, member keys, witness test tails, fold
    members/targets. Returns a list of (words, squashed) pairs."""
    if extract_fenced is None or load_ledger is None:
        errors.append("ledger_reconcile.py not importable — cannot "
                      "parse ```ledger block")
        return []
    blocks = extract_fenced(md_text, "ledger")
    if not blocks:
        return None                     # sentinel: no block, clean exit
    try:
        led = load_ledger(blocks[0])
    except Exception as e:
        errors.append(f"ledger block unparseable: {e}")
        return []
    spellings = []

    def add(x):
        if x is None:
            return
        s = str(x)
        spellings.append((_words(s), _squash(s)))

    def member_key(m):
        if isinstance(m, dict):
            for k in ("name", "id", "member", "value", "side"):
                if k in m:
                    return str(m[k])
            return json.dumps(m, sort_keys=True)
        return str(m)

    for o in (led or {}).get("obligations") or []:
        if not isinstance(o, dict):
            continue
        add(o.get("id"))
        add(o.get("name"))
        for m in o.get("members") or []:
            add(member_key(m))
    for w in (led or {}).get("witnesses") or []:
        if not isinstance(w, dict):
            continue
        add(tail_name(w.get("test", "")))
        for c in w.get("covers") or []:
            if not isinstance(c, dict):
                continue
            ms = c.get("members")
            for m in (ms if isinstance(ms, list) else [ms]):
                add(member_key(m))
    for f in (led or {}).get("folds") or []:
        if isinstance(f, dict):
            add(member_key(f.get("member")))
            add(tail_name(f.get("fold_into", "")))
    return spellings


def covered(cls, corpus):
    for words, squashed in corpus:
        if any(t in squashed for t in cls["subs"] if len(t) >= 4):
            return True
        if any(_word_hit(words, t) for t in cls["words"]):
            return True
    return False


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Census implementation guard sites and check each "
                    "minted member class is plausibly enumerated in "
                    "the ```ledger.")
    ap.add_argument("design", help="path to TEST_DESIGN.md")
    ap.add_argument("--case-dir", required=True,
                    help="implementation source dir to scan (Python)")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()
    if not os.path.isdir(args.case_dir):
        print(f"error: not a directory: {args.case_dir}")
        return 2
    try:
        md_text = open(args.design, encoding="utf-8").read()
    except OSError as e:
        print(f"error: cannot read {args.design}: {e}")
        return 2

    errors = []
    corpus = ledger_corpus(md_text, errors)
    classes, skipped, warnings = scan_source(args.case_dir)

    print(f"guard_census: design={args.design} case-dir={args.case_dir}")
    for w in warnings + errors:
        print(f"  warning: {w}")
    if corpus is None:
        print("  no ```ledger block found — nothing to join against "
              "(absence is a doc gap, not a checker finding)")
        return 0
    if not classes:
        print("  no guard sites found — nothing to census")
        return 0

    n_sites = len({c["site"] for c in classes})
    print(f"  sites={n_sites} required-classes={len(classes)} "
          f"corpus-spellings={len(corpus)}"
          + (f" internal-conversions={skipped}" if skipped else ""))

    findings = []
    for c in sorted(classes, key=lambda c: (c["site"], c["cls"])):
        if not covered(c, corpus):
            findings.append(c)

    if args.json:
        json.dump({"design": args.design, "case_dir": args.case_dir,
                   "sites": n_sites, "required": len(classes),
                   "findings": [{"site": c["site"], "door": c["door"],
                                 "func": c["func"], "class": c["cls"],
                                 "label": c["label"]}
                                for c in findings]},
                  open(args.json, "w"), indent=1)
        print(f"  json -> {args.json}")
    if findings:
        for c in findings:
            ctx = f" in {c['func']}()" if c["func"] else ""
            print(f"  {c['site']}: [{c['door']}]{ctx} no ledger member "
                  f"plausibly covers {c['label']}")
        print(f"  FAIL — {len(findings)} uncovered guard class(es)")
        return 1
    print("  OK — every guard class plausibly enumerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
