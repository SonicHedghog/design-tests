#!/usr/bin/env python3
"""Validate the `pins:` manifest in a run's ledger YAML. Stdlib + pyyaml.

Usage: pin_manifest.py TEST_DESIGN.md|RUN_DIR [TESTS_DIR] [--src SRC_DIR ...]
                       [--json out.json]

The ledger's `pins:` list is the machine-auditable inventory of
spec-silent / observed-behavior pins. Each entry MUST carry:

  id                  unique identifier
  unit                function/class under test
  input               the discriminating member literal
  observed            the pinned outcome
  clause_quote        verbatim doc text proving the contract is silent
  conforming_attempt  the flag assertion tried + its actual outcome

Findings:

  missing-field        FAIL  a pins entry lacks or empties a required field
  quote-not-found      FAIL  clause_quote does not appear verbatim in the
                             design doc (the silence proof is fabricated or
                             paraphrased)
  no-attempt           FAIL  conforming_attempt is empty or 'none' — an
                             unproven pin
  unmanifested-java-pin FAIL a `// pin-observed:` / `pin:` marker in a
                             Java test file whose id is not in the
                             manifest (r30 language-aware seal)
  unmanifested-pin     FAIL  (with --src + tests) a green assert pins a
                             literal return value on an outcome
                             expression calling NO documented unit —
                             an impl-observed spec-silent outcome with
                             no manifest entry covering that
                             unit+input (r35: cli_r35 shipped an empty
                             manifest while green asserts pinned
                             message formats and defect outcomes).
                             Type/shape checks, passthroughs and
                             documented-contract asserts are
                             conforming, never flagged
  dup-pin              FAIL  two pins entries cover the same unit+input
  attempt-unrelated    FAIL  tried does not reference the pin's unit/input
  exec-mismatch        FAIL  executed attempt outcome != recorded result
  exec-error           FAIL  attempt could not be executed (syntax/name/
                             timeout/non-assertion probe failure)
  exec-skipped-java    WARN  Java attempt not executed (no JVM in checker)
  attempt-asserts-observed FAIL tried's expected literal equals the pin's
                             observed outcome — it cannot distinguish the
                             conforming outcome from the defective one
  attempt-observed-similar WARN tried's expected literal is structurally
                             similar to observed (manual adjudication)
  attempt-tautological FAIL  tried is true regardless of the outcome
                             (self-comparison, return-union isinstance,
                             `or True`, bare pass, constant-true assert)
  pass-pin-no-justification FAIL result:pass pin lacks a verbatim
                             clause_absent quote from the docs region
  clause-absent-code   FAIL  clause_absent quotes a code line
                             (def/class/import/assignment/signature),
                             not the prose region a clause would live in
  clause-absent-wrong-unit FAIL clause_absent quotes prose from a
                             DIFFERENT unit's docstring/Javadoc (r30:
                             sci-negzero quoted clamp's identical Args
                             line) or prose attributable to no unit
                             at all — quote inside the pinned unit's
                             docstring span, or declare the region
                             explicitly (clause_absent {quote, unit}
                             or pin docs_unit:) matching pin.unit
  pin-defect-outcome FAIL    a result:pass pin's `observed` outcome is
                             defect-shaped (r36 seal): crash-named
                             outcomes (NPE/AssertionError/NameError/
                             traceback/segfault markers), malformed
                             quoted output (doubled minus, '1
                             milliseconds' number-unit disagreement,
                             negative fraction parts), or a
                             contract-shape violation — the observed
                             outcome is a non-str value where a clause
                             the pin itself cites declares a string
                             return. Spec-silent on the INPUT class
                             does not certify the outcome non-defective:
                             defect-shaped outcomes must be
                             dispositions flag|qfm, never pass-pins.
"""
import ast, json, os, re, subprocess, sys, tempfile

try:
    import yaml
except ImportError:
    sys.exit("pin_manifest: pyyaml required")

REQUIRED = ("id", "unit", "input", "observed",
            "clause_quote", "conforming_attempt")

JAVA_RE = re.compile(
    r"\b(assertEquals|assertTrue|assertFalse|assertSame|assertNotSame|"
    r"assertDoesNotThrow|assertThrows|assertIterableEquals|assertArrayEquals)\b"
    r"|->|\.java\b|;\s*$", re.S)
PLACEHOLDER_ALIASES = {
    "<empty>": ("''", '""'),
    "<blank>": ("''", '""'),
    "<null>": ("null", "None"),
    "<none>": ("null", "None"),
}
JAVA_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
# `// pin-observed:` / `pin:` markers, word-anchored so TLD-style
# comments (`"lupin", // lupin LUPIN`, `// pin Amazon`) cannot
# false-positive — the colon is mandatory and `pin` must start a word.
JAVA_PIN_MARK_RE = re.compile(
    r"\bpin(?:-observed)?\s*:\s*([A-Za-z0-9_.-]+)", re.I)
JAVA_BUILD_DIRS = {"target", "build", "out", "dist", ".git", ".gradle",
                   ".idea", "node_modules", "__pycache__"}
OBSERVED_LEAD_RE = re.compile(
    r"^\s*(?:returns?|raises?|throws?|yields?|is|are|was|were)\s+"
    r"(.+?)\s*$", re.I)
OUTCOME_TOKEN_RE = re.compile(
    r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
    r"|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"
    r"|\b(?:True|False|None)\b"
    r"|\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")

PROBE_BODY = r'''
NS = {'__name__': '__pin_attempt__'}
for _src in SRC_DIRS:
    _src = os.path.abspath(_src)
    if _src not in sys.path:
        sys.path.insert(0, _src)
    for _root, _dirs, _files in os.walk(_src):
        _dirs[:] = [d for d in _dirs if d != '__pycache__']
        for _fn in _files:
            if not _fn.endswith('.py'):
                continue
            _path = os.path.join(_root, _fn)
            _rel = os.path.relpath(_path, _src)
            _mod = _rel[:-3].replace(os.sep, '.')
            if _mod.endswith('.__init__'):
                _mod = _mod[:-9]
            if _mod in ('', '__init__'):
                continue
            try:
                _module = importlib.import_module(_mod)
            except Exception:
                continue
            if '.' not in _mod:
                NS[_mod] = _module
            for _name in dir(_module):
                if _name.startswith('_'):
                    continue
                try:
                    NS[_name] = getattr(_module, _name)
                except Exception:
                    pass
if INPUT_BOUND:
    NS['INPUT'] = INPUT_VALUE
try:
    _code = compile(TRIED, '<conforming_attempt>', 'exec')
except SyntaxError:
    print('PIN_OUTCOME=error:syntax')
    traceback.print_exc()
    raise SystemExit(2)
try:
    exec(_code, NS)
except AssertionError:
    print('PIN_OUTCOME=fail')
    raise SystemExit(1)
except NameError:
    print('PIN_OUTCOME=error:name')
    traceback.print_exc()
    raise SystemExit(2)
except BaseException:
    print('PIN_OUTCOME=fail')
    traceback.print_exc()
    raise SystemExit(1)
print('PIN_OUTCOME=pass')
'''


def ledger_block(doc):
    m = re.search(r"```ledger\n(.*?)```", doc, re.S)
    return m.group(1) if m else None


def norm_text(s):
    return re.sub(r"\s+", "", str(s))


def word_re(term):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(str(term)) +
                      r"(?![A-Za-z0-9_])")


def unit_candidates(unit):
    u = str(unit or "").strip()
    if not u:
        return []
    parts = [p for p in u.split(".") if p]
    out = []
    for cand in (u,) + tuple(reversed(parts)):
        if cand and cand not in out:
            out.append(cand)
    return out


def unit_referenced(unit, tried):
    return any(word_re(c).search(tried) for c in unit_candidates(unit)
               if len(c) >= 2)


def scalar_present(value, tried):
    if isinstance(value, str):
        spellings = set()
        if "'" not in value:
            spellings.add("'" + value + "'")
        if '"' not in value:
            spellings.add('"' + value + '"')
        spellings.update((repr(value), json.dumps(value, ensure_ascii=False)))
        return any(s and s in tried for s in spellings)
    pat = r"(?<![A-Za-z0-9_])" + re.escape(repr(value)) + \
          r"(?![A-Za-z0-9_])"
    return re.search(pat, tried) is not None


def input_atoms(text):
    s = str(text)
    atoms = []
    for mode in ("eval", "exec"):
        try:
            tree = ast.parse(s, mode=mode)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                atoms.append(("const", node.value))
            elif isinstance(node, ast.Name):
                atoms.append(("name", node.id))
            elif isinstance(node, ast.Attribute):
                atoms.append(("name", node.attr))
        if atoms:
            return _dedup_atoms(atoms)
    # Fallback: quoted literals + identifiers/numbers in the remaining text.
    masked = s
    for m in re.finditer(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", s):
        raw = m.group(0)
        try:
            atoms.append(("const", ast.literal_eval(raw)))
        except Exception:
            atoms.append(("name", raw.strip("'\"")))
        masked = masked.replace(raw, " ", 1)
    for m in re.finditer(r"\b\d+(?:\.\d+)?\b", masked):
        tok = m.group(0)
        atoms.append(("const", float(tok) if "." in tok else int(tok)))
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", masked):
        atoms.append(("name", m.group(0)))
    return _dedup_atoms(atoms)


def _dedup_atoms(atoms):
    out, seen = [], set()
    for kind, val in atoms:
        key = (kind, val)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def atom_present(atom, tried):
    kind, val = atom
    if kind == "const":
        return scalar_present(val, tried)
    return word_re(val).search(tried) is not None


def input_literal(text):
    try:
        return True, ast.literal_eval(str(text))
    except Exception:
        return False, None


def input_referenced(pin_input, tried):
    inp = str(pin_input)
    t_norm, i_norm = norm_text(tried), norm_text(inp)
    if i_norm and i_norm in t_norm:
        return True
    de_in = re.sub(r"['\"]", "", i_norm)
    de_tried = re.sub(r"['\"]", "", t_norm)
    if len(de_in) > 2 and de_in in de_tried:
        return True
    stripped = inp.strip()
    if stripped in PLACEHOLDER_ALIASES:
        return any(a in tried for a in PLACEHOLDER_ALIASES[stripped])
    if re.search(r"\bINPUT\b", tried):
        bound, _ = input_literal(inp)
        if bound:
            return True
    atoms = input_atoms(inp)
    return bool(atoms) and all(atom_present(a, tried) for a in atoms)


def attempt_related(pin, tried):
    return (unit_referenced(pin.get("unit"), tried) and
            input_referenced(pin.get("input"), tried))


def _const_key(value):
    if isinstance(value, bool):
        return ("bool", "True" if value else "False")
    if value is None:
        return ("none", "None")
    if isinstance(value, str):
        return ("str", value)
    return ("literal", repr(value))


def _canon_name(name):
    s = str(name).strip().strip("'\"")
    s = re.sub(r"\.class$", "", s)
    parts = [p for p in s.split(".") if p]
    return (parts[-1] if parts else s).lower()


def _cand_key(cand):
    kind, val = cand
    if kind == "const":
        return ("const", _const_key(val))
    return ("name", _canon_name(val))


def _dedup_candidates(cands):
    out, seen = [], set()
    for cand in cands:
        key = _cand_key(cand)
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def _add_text_atoms(text, out):
    s = str(text).strip()
    if not s:
        return
    try:
        out.append(("const", ast.literal_eval(s)))
    except Exception:
        pass
    for m in OUTCOME_TOKEN_RE.finditer(s):
        tok = m.group(0)
        if tok[:1] in ("'", '"'):
            try:
                out.append(("const", ast.literal_eval(tok)))
            except Exception:
                pass
        elif tok in ("True", "False", "None"):
            out.append(("const", {"True": True, "False": False,
                                  "None": None}[tok]))
        elif re.fullmatch(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", tok):
            try:
                out.append(("const", ast.literal_eval(tok)))
            except Exception:
                pass
        else:
            out.append(("name", tok))


def observed_candidates(observed):
    raw = str(observed).strip()
    m = OBSERVED_LEAD_RE.match(raw)
    text = m.group(1) if m else raw
    out = []
    for piece in text.split(";"):
        piece = piece.strip()
        if piece:
            _add_text_atoms(piece, out)
    return _dedup_candidates(out)


def _call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _is_none_type_call(node):
    return (isinstance(node, ast.Call) and _call_name(node.func) == "type"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value is None)


def _add_expected_node(node, out):
    if node is None:
        return
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for elt in node.elts:
            _add_expected_node(elt, out)
        return
    if isinstance(node, ast.Constant):
        out.append(("const", node.value))
        return
    if isinstance(node, ast.Name):
        if node.id in ("True", "False", "None"):
            out.append(("const", {"True": True, "False": False,
                                  "None": None}[node.id]))
        else:
            out.append(("name", node.id))
        return
    if isinstance(node, ast.Attribute):
        name = _dotted_name(node)
        if name:
            out.append(("name", name))
        return
    if (isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
            and not isinstance(node.operand.value, bool)):
        val = node.operand.value
        out.append(("const", val if isinstance(node.op, ast.UAdd)
                    else -val))
        return
    if _is_none_type_call(node):
        out.append(("const", None))


def _add_expected_operand(node, out):
    if isinstance(node, ast.Call) and _call_name(node.func) != "type":
        return
    _add_expected_node(node, out)


def _collect_expected(node, out, negated=False):
    if node is None:
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        _collect_expected(node.operand, out, not negated)
        return
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.Or):
            for value in node.values:
                _collect_expected(value, out, negated)
        return
    if isinstance(node, ast.Compare):
        if negated:
            return
        operands = [node.left] + list(node.comparators)
        for i, op in enumerate(node.ops):
            left, right = operands[i], operands[i + 1]
            if isinstance(op, (ast.Eq, ast.Is)):
                _add_expected_operand(left, out)
                _add_expected_operand(right, out)
            elif isinstance(op, ast.In):
                _add_expected_operand(right, out)
        return
    if (isinstance(node, ast.Call) and _call_name(node.func) == "isinstance"
            and not negated and len(node.args) >= 2):
        _add_expected_node(node.args[1], out)


def _collect_textual_expected(tried, out):
    s = str(tried)
    for m in re.finditer(r"\bassert(True|False)\s*\(", s):
        out.append(("const", m.group(1) == "True"))
    for m in re.finditer(r"\bassert(?:Equals|Same|ArrayEquals|"
                         r"IterableEquals)\s*\(\s*([^,;]+)\s*,", s):
        _add_text_atoms(m.group(1), out)
    for m in re.finditer(r"\bassertThrows\s*\(\s*([A-Za-z_][\w.]*)\.class",
                         s):
        out.append(("name", m.group(1)))
    for m in re.finditer(r"\bassert\s+([^;\n]+?)\s*(?:==|\bis\b)\s*"
                         r"([^;\n]+)", s):
        _add_text_atoms(m.group(2), out)


def expected_candidates(tried):
    out = []
    try:
        tree = ast.parse(str(tried), mode="exec")
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                _collect_expected(node.test, out)
        if out:
            return _dedup_candidates(out)
    _collect_textual_expected(tried, out)
    return _dedup_candidates(out)


def _candidate_text(cand):
    kind, val = cand
    if kind == "const":
        return val if isinstance(val, str) else repr(val)
    return str(val)


def _candidates_similar(expected, observed):
    a = re.sub(r"\s+", "", _candidate_text(expected)).lower()
    b = re.sub(r"\s+", "", _candidate_text(observed)).lower()
    if len(a) < 4 or len(b) < 4:
        return False
    return a in b or b in a


def attempt_observed_status(tried, observed):
    expected = expected_candidates(tried)
    observed_c = observed_candidates(observed)
    if not expected or not observed_c:
        return None
    obs_keys = {_cand_key(c) for c in observed_c}
    for cand in expected:
        if _cand_key(cand) in obs_keys:
            return ("fail",
                    f"expected {_candidate_text(cand)!r} equals observed "
                    f"{str(observed).strip()!r}")
    for cand in expected:
        for obs in observed_c:
            if _candidates_similar(cand, obs):
                return ("warn",
                        f"expected {_candidate_text(cand)!r} is structurally "
                        f"similar to observed {str(observed).strip()!r}")
    return None


def _contains_call(node):
    return any(isinstance(n, ast.Call) for n in ast.walk(node))


def _is_return_union_type(node):
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return False
    has_str = has_none = False
    for elt in node.elts:
        if isinstance(elt, ast.Name) and elt.id == "str":
            has_str = True
        elif _is_none_type_call(elt):
            has_none = True
    return has_str and has_none


def _taut_reason(node):
    if isinstance(node, ast.Constant):
        return "constant-true" if node.value else None
    if isinstance(node, ast.IfExp):
        if isinstance(node.test, ast.Constant):
            return _taut_reason(node.body if node.test.value
                                else node.orelse)
        body = _taut_reason(node.body)
        other = _taut_reason(node.orelse)
        return body if body and body == other else None
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.Or):
            for value in node.values:
                reason = _taut_reason(value)
                if reason:
                    return reason
            return None
        reasons = [_taut_reason(value) for value in node.values]
        return reasons[0] if reasons and all(reasons) else None
    if isinstance(node, ast.Compare):
        operands = [node.left] + list(node.comparators)
        for i, op in enumerate(node.ops):
            if (isinstance(op, (ast.Eq, ast.Is))
                    and ast.dump(operands[i]) == ast.dump(operands[i + 1])):
                return "self-comparison"
        return None
    if (isinstance(node, ast.Call)
            and _call_name(node.func) == "isinstance"
            and len(node.args) >= 2 and _contains_call(node.args[0])
            and _is_return_union_type(node.args[1])):
        return "isinstance-return-union"
    return None


def tautology_reason(tried):
    s = str(tried).strip()
    if not s:
        return None
    try:
        tree = ast.parse(s, mode="exec")
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        if (len(tree.body) == 1 and isinstance(tree.body[0], ast.Pass)):
            return "bare pass"
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                reason = _taut_reason(node.test)
                if reason:
                    return reason
        return None
    if re.fullmatch(r"pass\b.*", s, re.I):
        return "bare pass"
    if re.search(r"\bor\s+True\b", s) or re.search(r"\bassert\s+True\b", s):
        return "constant-true"
    if re.search(r"isinstance\s*\([^,]+,\s*\(\s*str\s*,\s*type\s*\(\s*None"
                 r"\s*\)\s*\)\s*\)", s):
        return "isinstance-return-union"
    return None


def clause_absent_quote(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("quote", "text", "clause_quote", "region", "docs"):
            if value.get(key):
                return str(value[key]).strip()
        return ""
    return str(value).strip()


# ------------------------------------------------ clause_absent unit join
#
# A result:pass pin's clause_absent must be PROSE from the pinned
# unit's own docstring/Javadoc (or an explicit 'unspecified' statement),
# never a code line and never prose laundered from a different unit.

CODE_LINE_RES = tuple(re.compile(p) for p in (
    r"^\s*(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(",      # def signature
    r"^\s*class\s+[A-Za-z_]\w*",                       # class decl
    r"^\s*(?:from\s+[\w.]+\s+)?import\s+[\w.]+",       # import
    r"^\s*@[A-Za-z_]",                                 # decorator
    r"^\s*[A-Za-z_][\w.]*\s*=[^=]",                    # assignment
    r"^\s*(?:public|protected|private|static|final|abstract|"
    r"synchronized|native|default|strictfp|transient|volatile)\b",
    r"^\s*[\w<>\[\],.?]+\s+[A-Za-z_]\w*\s*\([^;{}]*\)"
    r"\s*(?:throws\b[^{;]*)?[;{]?\s*$",                # Java method decl
))
SILENCE_RE = re.compile(
    r"unspecified|undocument|not\s+(?:documented|specified|defined)|"
    r"no\s+documentation|not\s+covered\s+by\s+(?:the\s+)?"
    r"(?:docs?|spec|documentation)", re.I)
JAVA_JAVADOC_RE = re.compile(
    r"/\*\*(.*?)\*/\s*(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:public|protected|private|static|final|abstract|synchronized|"
    r"native|default|strictfp|transient|volatile|\s)*"
    r"[\w<>\[\],.?]+\s+(\w+)\s*\(", re.S)


def is_code_line(text):
    """Any line of the quote parses as code (def/class/import/
    assignment/signature) rather than docstring prose."""
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        if any(rx.match(line) for rx in CODE_LINE_RES):
            return True
    return False


def _walk_py_defs(node, prefix, units):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            doc = ast.get_docstring(child)
            if doc:
                units.setdefault(child.name, []).append(doc)
                if prefix:
                    units.setdefault(prefix + "." + child.name,
                                     []).append(doc)
            _walk_py_defs(child,
                          (prefix + "." if prefix else "") + child.name,
                          units)
        else:
            _walk_py_defs(child, prefix, units)


def docstring_units(src_dirs):
    """Return ({unit-name: [docstring,...]}, [module-level docstrings])
    built from .py sources (ast.get_docstring) and .java sources
    (Javadoc block preceding each method)."""
    units, mod_docs = {}, []
    for d in src_dirs:
        for root, dirs, fns in os.walk(d):
            dirs[:] = [x for x in dirs if x not in JAVA_BUILD_DIRS]
            for fn in fns:
                path = os.path.join(root, fn)
                if fn.endswith(".py"):
                    try:
                        tree = ast.parse(
                            open(path, encoding="utf-8",
                                 errors="replace").read())
                    except (SyntaxError, UnicodeDecodeError, ValueError,
                            OSError):
                        continue
                    md = ast.get_docstring(tree)
                    if md:
                        mod_docs.append(md)
                    _walk_py_defs(tree, "", units)
                elif fn.endswith(".java"):
                    try:
                        text = open(path, encoding="utf-8",
                                    errors="replace").read()
                    except OSError:
                        continue
                    for m in JAVA_JAVADOC_RE.finditer(text):
                        body = re.sub(r"^\s*\* ?", "", m.group(1),
                                      flags=re.M).strip()
                        units.setdefault(m.group(2), []).append(body)
    return units, mod_docs


def _declared_unit(pin):
    """Explicit provenance attribution: clause_absent dict's `unit:`
    or a pin-level `docs_unit:` field. Returns '' when absent."""
    ca = pin.get("clause_absent")
    if isinstance(ca, dict) and ca.get("unit"):
        return str(ca["unit"]).strip()
    if pin.get("docs_unit"):
        return str(pin["docs_unit"]).strip()
    return ""


def clause_absent_unit_check(pin, ca, doc_units, mod_docs):
    """Unit-join a clause_absent quote to its docstring owner.
    Returns None when clean, else (shape, detail)."""
    nca = norm_text(ca)
    holders = set()
    if nca:
        for name, docs in doc_units.items():
            if any(nca in norm_text(d) for d in docs):
                holders.add(name.lower())
    pin_names = {c.lower() for c in unit_candidates(pin.get("unit"))
                 if len(c) >= 2}
    if holders:
        if holders & pin_names:
            return None
        others = sorted(holders - pin_names) or sorted(holders)
        return ("clause-absent-wrong-unit",
                f"quote lives in docstring(s) of {', '.join(others)}, "
                f"not the pinned unit's — laundered provenance")
    # quote sits inside no unit's docstring span (module docstring,
    # comment, doc file): allowed only as an explicit silence
    # statement or with an explicit unit: attribution matching pin.unit
    if SILENCE_RE.search(ca):
        return None
    declared = _declared_unit(pin)
    if declared and declared.lower() in pin_names:
        return None
    if any(nca in norm_text(d) for d in mod_docs):
        return ("clause-absent-wrong-unit",
                "quote is module-level docstring prose attributable "
                "to no unit — declare the unit explicitly "
                "(clause_absent {quote, unit} or docs_unit:)")
    return ("clause-absent-wrong-unit",
            "quote is not within the pinned unit's docstring span and "
            "no explicit unit: attribution is declared")


# --------------------------------------- r36 defect-outcome seal
#
# A pass-pin's `observed` outcome must be non-defective — spec-silent on
# the INPUT class does not certify the outcome non-defective. Fires only
# on unambiguous shapes; defect-shaped observed outcomes must be
# dispositions flag|qfm, never pass-pins.

CRASH_EXC_RE = re.compile(
    r"\b(?:NullPointerException|NPE|AssertionError|AssertionFailedError|"
    r"ComparisonFailure|StackOverflow(?:Error|Exception)?|"
    r"OutOfMemoryError|InternalError|UnknownError|VirtualMachineError|"
    r"ExceptionInInitializerError|NoClassDefFoundError|"
    r"UnsatisfiedLinkError|ClassCircularityError|"
    r"IncompatibleClassChangeError|BootstrapMethodError|VerifyError|"
    r"ArrayIndexOutOfBounds(?:Exception|Error)?|"
    r"StringIndexOutOfBounds(?:Exception|Error)?|"
    r"NegativeArraySizeException|AttributeError|NameError|"
    r"UnboundLocalError|RecursionError|MemoryError|SystemError|"
    r"ReferenceError|SegmentationFault|FatalError)\b")
CRASH_MARKER_RE = re.compile(
    r"Traceback \(most recent call last\)|Exception in thread|"
    r"panic:|Segmentation fault|core dumped", re.I)
QUOTED_LIT_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
UNIT_AGREE_RE = re.compile(
    r"\b1\s+(?:(?:milli|micro|nano)?seconds|minutes|hours|days|weeks|"
    r"months|years|bytes|bits)\b")
DBL_MINUS_RE = re.compile(r"[\u207b\u208b\u2212]{2,}")
MINUS_DIGIT_RE = re.compile(r"(?<![\w/])-\d")
RETURNS_STR_RE = re.compile(
    r"\breturns?\b[^.\n]{0,80}\bstring\b|\bstring\b[^.\n]{0,40}\b"
    r"return(?:s|ed)?\b|\breturns?\s*:\s*str\b", re.I)
UNCHANGED_RE = re.compile(
    r"\bunchanged\b|\bas-?is\b|\bpassthrough\b|\bpass(?:es|ed)?\s*"
    r"through\b|\breturns?\s+(?:the\s+|its\s+|a\s+|an\s+)?(?:null\s+|"
    r"same\s+|original\s+)?(?:input|argument|value|param(?:eter)?)\b",
    re.I)
BARE_NONSTR_RE = re.compile(
    r"\breturns?\s+(?:a\s+|an\s+|the\s+)?(-?\d[\d,]*(?:\.\d+)?|None|"
    r"True|False)\b")


def _first_input_literal(pin_input):
    """(ok, value) — first positional arg literal of a `f(a, ...)` input,
    or the input's own literal when not call-shaped."""
    s = str(pin_input).strip()
    if "(" in s and s.rfind(")") > s.index("("):
        inner = s[s.index("(") + 1:s.rfind(")")]
        parts = _split_args(inner)
        s = parts[0].strip() if parts else ""
    elif "," in s:
        s = s.split(",", 1)[0].strip()
    try:
        return True, ast.literal_eval(s)
    except Exception:
        pass
    if re.fullmatch(r"[\d\s*/+\-.()eExXa-fA-F]+", s):
        try:
            return True, eval(s, {"__builtins__": {}}, {})
        except Exception:
            pass
    return False, None


def defect_outcome_reason(pin):
    """Defect-shape reason for a pin's `observed` outcome, else None.
    Conservative: crash-named exceptions/markers, malformed quoted
    output, and observed outcomes contradicting a Returns-str clause
    the pin itself cites."""
    obs = str(pin.get("observed") or "")
    if not obs:
        return None
    m = CRASH_EXC_RE.search(obs) or CRASH_MARKER_RE.search(obs)
    if m:
        return (f"observed names a crash outcome {m.group(0)!r} — an "
                f"uncaught crash is a defect, not a spec-silent pin")
    for lm in QUOTED_LIT_RE.finditer(obs):
        lit = lm.group(0)[1:-1]
        if len(MINUS_DIGIT_RE.findall(lit)) >= 2 or \
                DBL_MINUS_RE.search(lit):
            return (f"observed output {lit[:40]!r} carries a doubled "
                    f"minus sign — malformed output is defect-shaped")
        if UNIT_AGREE_RE.search(lit):
            return (f"observed output {lit[:40]!r} writes '1 <plural "
                    f"unit>' — number-unit disagreement is defect-"
                    f"shaped")
    cites = clause_absent_quote(pin.get("clause_absent")) + " " + \
        str(pin.get("clause_quote") or "")
    if RETURNS_STR_RE.search(cites):
        if UNCHANGED_RE.search(obs):
            ok, v = _first_input_literal(pin.get("input"))
            if ok and not isinstance(v, str):
                return (f"observed passthrough returns the non-str "
                        f"{type(v).__name__} input where the pin's own "
                        f"cited clause declares a string return — a "
                        f"contract-shape violation")
        elif BARE_NONSTR_RE.search(obs):
            return (f"observed returns a non-str value where the "
                    f"pin's own cited clause declares a string "
                    f"return — a contract-shape violation")
    return None


def source_text(src_dirs):
    parts = []
    for d in src_dirs:
        for root, _, fns in os.walk(d):
            for fn in fns:
                try:
                    parts.append(open(os.path.join(root, fn),
                                      encoding="utf-8",
                                      errors="replace").read())
                except OSError:
                    pass
    return "\n".join(parts)


def looks_java(tried, pin):
    text = " ".join(str(x) for x in (tried, pin.get("unit"),
                                     pin.get("input")) if x is not None)
    return JAVA_RE.search(text) is not None


def detect_language(src_dirs):
    py = java = 0
    for d in src_dirs or []:
        for root, _, fns in os.walk(d):
            for fn in fns:
                if fn.endswith(".py"):
                    py += 1
                elif fn.endswith(".java"):
                    java += 1
    if java and not py:
        return "java"
    return "python"


def probe_source(src_dirs, tried, pin_input):
    bound, value = input_literal(pin_input)
    return ("import importlib, os, sys, traceback\n"
            f"SRC_DIRS = {list(src_dirs)!r}\n"
            f"TRIED = {tried!r}\n"
            f"INPUT_VALUE = {value!r}\n"
            f"INPUT_BOUND = {bound!r}\n" + PROBE_BODY)


def run_python_attempt(src_dirs, tried, pin_input, timeout=10):
    fd, path = tempfile.mkstemp(prefix="pin_attempt_", suffix=".py")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(probe_source(src_dirs, tried, pin_input))
        try:
            cp = subprocess.run([sys.executable, path], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout,
                                text=True, errors="replace")
        except subprocess.TimeoutExpired:
            return "timeout", f"probe exceeded {timeout}s"
        out = (cp.stdout or "") + (cp.stderr or "")
        m = re.search(r"PIN_OUTCOME=(\S+)", out)
        if m:
            outcome = m.group(1)
        elif cp.returncode == 0:
            outcome = "pass"
        else:
            outcome = f"error:exit{cp.returncode}"
        tail = "\n".join(out.strip().splitlines()[-4:])
        return outcome, tail[:500]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _java_files_under(root):
    out = []
    for r, dirs, fns in os.walk(root):
        dirs[:] = [d for d in dirs if d not in JAVA_BUILD_DIRS]
        for fn in fns:
            if fn.endswith(".java"):
                out.append(os.path.join(r, fn))
    return out


def java_test_files(run_dir, tests_dir, src_dirs):
    """Java test-file discovery for the unmanifested-pin join.

    Order (r30 seal): the run's junit/ dir, then every *.java staged
    under the run dir or tests dir; --src is scanned ONLY when the run
    has no java of its own — previously --src could be treated as the
    tests root, which is where the LUPIN/Amazon TLD-comment false
    positives came from."""
    files, seen = [], set()

    def add(root):
        for fp in _java_files_under(root):
            ap = os.path.abspath(fp)
            if ap not in seen:
                seen.add(ap)
                files.append(fp)

    if run_dir and os.path.isdir(run_dir):
        add(os.path.join(run_dir, "junit"))
        add(run_dir)
    if tests_dir and os.path.isdir(tests_dir):
        add(tests_dir)
    if not files:
        for d in src_dirs or []:
            if os.path.isdir(d):
                add(d)
    return files


def java_pin_markers(path):
    """Yield (lineno, marker_id) for // pin-observed: / pin: comments."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return
    for m in JAVA_COMMENT_RE.finditer(text):
        for pm in JAVA_PIN_MARK_RE.finditer(m.group(0)):
            yield text.count("\n", 0, m.start()) + 1, pm.group(1)


# ------------------------------------------- r35 observed-outcome seal
#
# A green assert that pins a literal return value the docs never
# promise is an unmanifested observed-behavior pin: the suite ran the
# impl and froze whatever came back (r35: commons-cli shipped an empty
# pins: manifest while its green tests pinned exception-message
# formats, hyphen-asymmetry and defect outcomes). The scan is kept
# CONSERVATIVE — it fires only when all of these hold:
#
#   * the expected side carries a concrete literal (str/char/num, also
#     inside array/collection constructors) — boolean/null expecteds,
#     names, constants and .class refs are not literal outcomes;
#   * the outcome side is a call chain, not a type/shape check
#     (size/len/isEmpty/contains/startsWith/isinstance/null/same/
#     raises are conforming oracles, not pins);
#   * the expected literal is not a passthrough of a literal among the
#     outcome call's own arguments (f("abc") == "abc" is identity, not
#     an observed pin);
#   * NO call in the outcome expression resolves to a documented unit
#     (a docstring/Javadoc exists in the --src doc map) — a documented
#     unit may have a clause for the input class, so the literal is
#     potentially contract-derived;
#   * at least one outcome call is spec-silent by construction —
#     project-defined but undocumented (no doc clause exists for ANY
#     input class) or an impl-format accessor (getMessage/toString
#     content is impl-specific). Purely foreign calls (test helpers,
#     JDK/stdlib) are not attributable evidence and are never flagged;
#   * no pins: manifest entry covers the assert's unit+input.
#
# Documented-contract asserts (f(x) == documented outcome on a unit
# whose doc clause covers that input class) are conforming — they are
# never flagged.

JAVA_ASSERT_EQ_RE = re.compile(
    r"\bassert(?:Equals|ArrayEquals|IterableEquals)\s*\(")
JAVA_CALL_NAME_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
JAVA_LIT_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    r"|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[fFdDlL]?\b")
JAVA_NONCALL_WORDS = {"if", "for", "while", "switch", "catch", "return",
                      "new", "assert", "synchronized", "throw", "do",
                      "else", "case", "instanceof", "typeof", "sizeof"}
JAVA_SHAPE_TAIL_RE = re.compile(
    r"(?:\.\s*(?:size|length|isEmpty|isBlank|contains|startsWith|"
    r"endsWith|hashCode|getClass|charAt|compareTo|indexOf)\s*"
    r"\([^()]*\)|\.(?:length|size))\s*$")
PY_SHAPE_CALLS = {"len", "size", "length", "is_empty", "isnull"}
PY_SHAPE_ATTRS = {"size", "length", "shape", "ndim", "nbytes", "ndim"}
ASSERT_EQ_NAMES = {"assertEqual", "assertEquals"}
# impl-format outcome accessors: their literal content is impl-specific
# formatting, the classic spec-silent pin target. A unit DEFINED in
# --src but carrying no docstring/Javadoc is also spec-silent by
# construction; foreign calls (test helpers, JDK/stdlib) that are
# neither defined nor format accessors are never flagged.
FOREIGN_OBSERVED_ACCESSORS = {
    "getMessage", "getLocalizedMessage", "toString"}
JAVA_DEF_NAME_RE = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public|protected|private|"
    r"static|final|abstract|synchronized|native|default|strictfp|"
    r"transient|volatile)\s+(?:[\w<>\[\],.?]+\s+)*([A-Za-z_]\w*)\s*\(")


def defined_units(src_dirs):
    """Names of units DEFINED in --src (documented or not): Python
    def/class names via AST; Java method/ctor names from modifier-led
    declaration lines (generic signatures included)."""
    units = set()
    for d in src_dirs:
        for root, dirs, fns in os.walk(d):
            dirs[:] = [x for x in dirs if x not in JAVA_BUILD_DIRS]
            for fn in fns:
                path = os.path.join(root, fn)
                if fn.endswith(".py"):
                    try:
                        tree = ast.parse(
                            open(path, encoding="utf-8",
                                 errors="replace").read())
                    except (SyntaxError, UnicodeDecodeError, ValueError,
                            OSError):
                        continue
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef,
                                             ast.AsyncFunctionDef,
                                             ast.ClassDef)):
                            units.add(node.name)
                elif fn.endswith(".java"):
                    try:
                        text = open(path, encoding="utf-8",
                                    errors="replace").read()
                    except OSError:
                        continue
                    for line in text.splitlines():
                        m = JAVA_DEF_NAME_RE.match(line)
                        if m:
                            units.add(m.group(1))
    return units


def _match_paren(text, start):
    """Index of the ')' matching text[start] == '(', or -1."""
    depth, quote, esc = 0, None, False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "'\"`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_args(argstr):
    """Split a Java argument list on top-level commas (quote/paren-safe)."""
    args, depth, quote, esc, cur = [], 0, None, False, []
    for ch in argstr:
        if quote:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "'\"`":
            quote = ch
            cur.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        args.append(tail)
    return args


def _java_lit_text(tok):
    """Normalize a Java literal token for passthrough comparison."""
    t = tok.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    return re.sub(r"[fFdDlL]$", "", t)


def _java_outcome_calls(expr):
    out = []
    for m in JAVA_CALL_NAME_RE.finditer(expr):
        name = m.group(1)
        if name not in JAVA_NONCALL_WORDS:
            out.append(name)
    return out


def java_literal_outcome_asserts(text):
    """Yield (lineno, stmt, expected_literals, outcome_calls) for
    assertEquals-family asserts whose expected side carries a concrete
    literal and whose outcome side is a non-shape call expression."""
    for m in JAVA_ASSERT_EQ_RE.finditer(text):
        open_i = text.index("(", m.start())
        close_i = _match_paren(text, open_i)
        if close_i < 0:
            continue
        stmt = text[m.start():close_i + 1]
        args = _split_args(text[open_i + 1:close_i])
        if len(args) < 2:
            continue
        lits = [_java_lit_text(t) for t in JAVA_LIT_TOKEN_RE.findall(
            args[0])]
        if not lits:
            continue
        outcome = args[1].strip()
        if JAVA_SHAPE_TAIL_RE.search(outcome):
            continue
        calls = _java_outcome_calls(outcome)
        if not calls:
            continue
        arg_lits = {_java_lit_text(t)
                    for t in JAVA_LIT_TOKEN_RE.findall(outcome)}
        if any(v in arg_lits for v in lits):
            continue    # passthrough: expected == an input literal
        ln = text.count("\n", 0, m.start()) + 1
        yield ln, stmt, lits, calls


def _py_pure_literal(node):
    """The node is composed only of constants and literal containers —
    no names, calls, attributes or operators."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return bool(node.elts) and all(
            _py_pure_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is None or _py_pure_literal(k) for k in node.keys) \
            and all(_py_pure_literal(v) for v in node.values)
    return (isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.UAdd, ast.USub))
            and _py_pure_literal(node.operand))


def _py_outcome_literal(value):
    return (isinstance(value, (str, bytes, int, float, complex))
            and not isinstance(value, bool))


def _py_literal_values(node):
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant)
            and _py_outcome_literal(n.value)]


def _py_shape_outcome(node):
    if isinstance(node, ast.Call):
        return _call_name(node.func) in PY_SHAPE_CALLS
    if isinstance(node, ast.Attribute):
        return node.attr in PY_SHAPE_ATTRS
    return False


def _py_call_names(node):
    names = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            last = _call_name(n.func)
            dotted = _dotted_name(n.func)
            if last:
                names.append(last)
            if dotted:
                names.append(dotted)
    return names


def py_literal_outcome_asserts(text):
    """Yield (lineno, seg, expected_literals, outcome_calls) for
    `assert <expr> == <literal>` / assertEqual(lit, expr) where the
    literal side is a pure-literal expression with at least one
    str/num outcome literal and the outcome side is a non-shape call."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return

    def emit(lit_side, out_side, node):
        vals = _py_literal_values(lit_side)
        if not vals or _py_pure_literal(out_side):
            return
        if _py_shape_outcome(out_side):
            return
        calls = _py_call_names(out_side)
        if not calls:
            return
        arg_vals = {v for v in _py_literal_values(out_side)}
        if any(v in arg_vals for v in vals):
            return    # passthrough: expected == an input literal
        seg = ast.get_source_segment(text, node) or ""
        yield node.lineno, seg, vals, calls

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            t = node.test
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1
                    and isinstance(t.ops[0], ast.Eq)):
                continue
            left, right = t.left, t.comparators[0]
            if _py_pure_literal(right):
                yield from emit(right, left, node)
            elif _py_pure_literal(left):
                yield from emit(left, right, node)
        elif (isinstance(node, ast.Call)
                and _call_name(node.func) in ASSERT_EQ_NAMES
                and len(node.args) >= 2):
            lit, out = node.args[0], node.args[1]
            if _py_pure_literal(lit):
                yield from emit(lit, out, node)


def observed_pin_findings(asserts, pins, doc_units, def_units):
    """Filter literal-outcome asserts to the spec-silent ones: no call
    in the outcome expression resolves to a documented unit (a doc
    clause may cover the input class), at least one call is
    project-attributable but undocumented or an impl-format accessor,
    and no manifest pin covers the assert's unit+input.
    Yields (lineno, calls, lits, stmt)."""
    for ln, stmt, lits, calls in asserts:
        if any(c in doc_units for c in calls):
            continue
        callset = set(calls)
        if not (callset & def_units
                or callset & FOREIGN_OBSERVED_ACCESSORS):
            continue
        covered = any(
            isinstance(pin, dict)
            and unit_referenced(pin.get("unit"), stmt)
            and input_referenced(pin.get("input"), stmt)
            for pin in pins)
        if not covered:
            yield ln, calls, lits, stmt


def parse_args(argv):
    pos, opts = [], {"json": None, "src": [], "tests": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json" and i + 1 < len(argv):
            opts["json"] = argv[i + 1]; i += 2
        elif a.startswith("--json="):
            opts["json"] = a.split("=", 1)[1]; i += 1
        elif a == "--src" and i + 1 < len(argv):
            opts["src"].append(argv[i + 1]); i += 2
        elif a.startswith("--src="):
            opts["src"].append(a.split("=", 1)[1]); i += 1
        elif a == "--tests" and i + 1 < len(argv):
            opts["tests"] = argv[i + 1]; i += 2
        elif a.startswith("--tests="):
            opts["tests"] = a.split("=", 1)[1]; i += 1
        else:
            pos.append(a); i += 1
    return pos, opts


def resolve_paths(pos, opts):
    if not pos:
        sys.exit("pin_manifest: TEST_DESIGN.md or run dir required")
    target = pos[0]
    if os.path.isdir(target):
        run_dir = target
        design = os.path.join(target, "TEST_DESIGN.md")
        default_tests = os.path.join(target, "tests")
    else:
        design = target
        run_dir = os.path.dirname(os.path.abspath(target))
        default_tests = os.path.join(run_dir, "tests")
    tests_dir = opts["tests"]
    extra = list(pos[1:])
    if tests_dir is None and extra:
        tests_dir = extra.pop(0)
    src_dirs = list(opts["src"]) + extra
    if tests_dir is None:
        tests_dir = default_tests
    return design, run_dir, tests_dir, src_dirs


def main(path, json_out=None, tests_dir=None, src_dirs=None,
         run_dir=None):
    doc = open(path).read()
    block = ledger_block(doc)
    if block is None:
        print("pin_manifest: no ```ledger block found")
        return 2
    data = yaml.safe_load(block) or {}
    pins = data.get("pins") or []
    finds = []
    seen = set()
    sd = [d for d in (src_dirs or []) if os.path.isdir(d)]
    lang = detect_language(sd) if sd else None
    java_only = lang == "java"
    srctext = source_text(sd) if sd else ""
    doc_units, mod_docs = docstring_units(sd) if sd else ({}, [])
    flag_srcs = []
    if tests_dir and os.path.isdir(tests_dir):
        for root, _, fns in os.walk(tests_dir):
            for fn in fns:
                if fn.startswith("test_suspected") and \
                        fn.endswith(".py"):
                    try:
                        flag_srcs.append(
                            (fn, open(os.path.join(root, fn),
                                      encoding="utf-8",
                                      errors="replace").read()))
                    except OSError:
                        pass
    has_structured_attempts = any(
        isinstance(p, dict) and isinstance(p.get("conforming_attempt"), dict)
        for p in pins)
    if not sd and has_structured_attempts:
        finds.append(("WARN", "exec-skipped",
                      "no --src dir; conforming_attempts not executed"))
    for i, pin in enumerate(pins):
        if not isinstance(pin, dict):
            finds.append(("FAIL", "malformed",
                          f"pins[{i}] is not a mapping"))
            continue
        where = pin.get("id", f"pins[{i}]")
        for field in REQUIRED:
            if not pin.get(field):
                finds.append(("FAIL",
                              "no-attempt" if field == "conforming_attempt"
                              else "missing-field",
                              f"{where}: `{field}` empty or absent"))
        att = pin.get("conforming_attempt")
        if isinstance(att, dict):
            res = str(att.get("result", "")).lower()
            if res not in ("pass", "fail"):
                finds.append(("FAIL", "open-result",
                              f"{where}: conforming_attempt result "
                              f"'{att.get('result')}' not pass|fail — "
                              f"prose attempts are gamed (r20)"))
            elif res == "fail":
                finds.append(("FAIL", "binding-attempt",
                              f"{where}: conforming_attempt result=fail — "
                              f"pin must be re-verdicted flag-or-qfm"))
            if res == "pass":
                dod = defect_outcome_reason(pin)
                if dod:
                    finds.append(("FAIL", "pin-defect-outcome",
                                  f"{where}: {dod} — spec-silent on the "
                                  f"input class does not certify the "
                                  f"outcome non-defective; re-verdict "
                                  f"flag|qfm"))
            tried = str(att.get("tried", ""))
            obs = str(pin.get("observed", ""))
            nt = re.sub(r"\s+", "", tried)
            no = re.sub(r"\s+", "", obs)
            if tried and obs and (nt == no or (no and no in nt)):
                finds.append(("FAIL", "tautological-attempt",
                              f"{where}: tried asserts the observed "
                              f"(defective) outcome — a conforming "
                              f"attempt must assert a DIFFERENT "
                              f"outcome"))
            if tried and obs:
                status = attempt_observed_status(tried, obs)
                if status and status[0] == "fail":
                    finds.append(("FAIL", "attempt-asserts-observed",
                                  f"{where}: {status[1]} — the attempt "
                                  f"cannot distinguish conforming from "
                                  f"defective"))
                elif status and status[0] == "warn":
                    finds.append(("WARN", "attempt-observed-similar",
                                  f"{where}: {status[1]}"))
            taut = tautology_reason(tried)
            if taut:
                finds.append(("FAIL", "attempt-tautological",
                              f"{where}: tried is tautological "
                              f"({taut}) regardless of outcome"))
            if res == "pass" and re.search(
                    r"\braises?\b|\bthrows?\b|\bpropagates?\b|\buncaught\b",
                    obs, re.I) and \
                    re.search(r"\bis\s+(True|False|None)\b|==|assert\s+not",
                              tried):
                finds.append(("FAIL", "attempt-contradicts-observed",
                              f"{where}: observed claims an uncaught "
                              f"exception but the passing attempt asserts "
                              f"a return value"))
            if res == "pass":
                ca = clause_absent_quote(pin.get("clause_absent"))
                cq = str(pin.get("clause_quote") or "").strip()
                if not ca:
                    finds.append(("FAIL", "pass-pin-no-justification",
                                  f"{where}: result=pass without a "
                                  f"verbatim clause_absent quote"))
                elif "..." in ca or "\u2026" in ca:
                    finds.append(("FAIL", "clause-absent-interpolated",
                                  f"{where}: clause_absent interpolates "
                                  f"'...' — the docs region must be "
                                  f"quoted verbatim"))
                elif cq and norm_text(ca) == norm_text(cq):
                    finds.append(("FAIL", "clause-absent-equals-quote",
                                  f"{where}: clause_absent duplicates "
                                  f"clause_quote — quote the region "
                                  f"where the missing clause would live"))
                elif srctext and ca not in srctext:
                    finds.append(("FAIL", "quote-not-in-source",
                                  f"{where}: clause_absent quote is not "
                                  f"verbatim in the source tree "
                                  f"(self-certification in the design "
                                  f"doc is forbidden)"))
                elif not srctext and ca not in doc:
                    finds.append(("FAIL", "pass-pin-no-justification",
                                  f"{where}: clause_absent quote is not "
                                  f"verbatim in the design doc"))
                if ca and is_code_line(ca):
                    finds.append(("FAIL", "clause-absent-code",
                                  f"{where}: clause_absent quotes a "
                                  f"code line "
                                  f"({ca.splitlines()[0].strip()[:60]!r})"
                                  f" — the silence proof must be "
                                  f"docstring/Javadoc prose, not a "
                                  f"def/class/import/assignment/"
                                  f"signature line"))
                elif doc_units and srctext and ca and ca in srctext:
                    bad = clause_absent_unit_check(pin, ca, doc_units,
                                                   mod_docs)
                    if bad:
                        finds.append(("FAIL", bad[0],
                                      f"{where}: clause_absent "
                                      f"{bad[1]}"))
            if tried and pin.get("input") is not None:
                if not attempt_related(pin, tried):
                    finds.append(("FAIL", "attempt-unrelated",
                                  f"{where}: tried does not reference the "
                                  f"pin's unit/input (or a resolvable "
                                  f"alias)"))
                if sd:
                    if java_only or looks_java(tried, pin):
                        finds.append(("WARN", "exec-skipped-java",
                                      f"{where}: Java conforming_attempt "
                                      f"not executed (no JVM in checker)"))
                    else:
                        outcome, detail = run_python_attempt(
                            sd, tried, pin.get("input"))
                        base = outcome.split(":", 1)[0]
                        if base in ("error", "timeout") or \
                                outcome.startswith("error"):
                            finds.append(("FAIL", "exec-error",
                                          f"{where}: conforming_attempt "
                                          f"probe {outcome} — {detail}"))
                        elif base != res:
                            finds.append(("FAIL", "exec-mismatch",
                                          f"{where}: recorded result="
                                          f"{res} but probe measured="
                                          f"{base} ({outcome})"))
            # observed-probe: a pin claiming an uncaught exception is
            # verified by executing the pinned call — if it returns
            # normally or raises a different type, the pin lies
            if sd and not java_only and pin.get("input") is not None and \
                    re.search(r"\braises?\b|\bthrows?\b|\buncaught\b",
                              obs, re.I):
                exc_m = re.search(r"(?:raises?|throws?|uncaught)\s+`?"
                                  r"([A-Za-z_][\w.]*)", obs, re.I)
                exc = exc_m.group(1).rsplit(".", 1)[-1] if exc_m else ""
                unit_last = str(pin.get("unit") or "").rsplit(".", 1)[-1]
                raw_in = str(pin.get("input"))
                if unit_last and not raw_in.lstrip().startswith(
                        unit_last + "("):
                    if exc:
                        exc_line = (
                            f"assert type(__e).__name__ == {exc!r}, "
                            f"'raised ' + type(__e).__name__ + "
                            f"' not {exc}'")
                    else:
                        exc_line = "pass"
                    probe = ("try:\n"
                             f"    {unit_last}({raw_in})\n"
                             "except BaseException as __e:\n"
                             f"    {exc_line}\n"
                             "else:\n"
                             "    raise AssertionError('call returned "
                             "normally')\n")
                    o2, d2 = run_python_attempt(sd, probe, raw_in)
                    b2 = o2.split(":", 1)[0]
                    if b2 in ("error", "timeout") or \
                            o2.startswith("error"):
                        finds.append(("WARN", "observed-unverifiable",
                                      f"{where}: observed-claim probe "
                                      f"{o2} — {d2}"))
                    elif b2 != "pass":
                        finds.append(("FAIL", "observed-mismatch",
                                      f"{where}: claimed observed "
                                      f"'{obs[:80]}' contradicts the "
                                      f"measured outcome — probe: {d2}"))
        else:
            finds.append(("FAIL", "unstructured-attempt",
                          f"{where}: conforming_attempt not "
                          f"{{tried,result}} mapping"))
        q = pin.get("clause_quote")
        if q and str(q).strip() not in doc:
            finds.append(("FAIL", "quote-not-found",
                          f"{where}: clause_quote not verbatim in doc"))
        key = (pin.get("unit"), json.dumps(pin.get("input"),
                                           default=str, sort_keys=True))
        if key in seen:
            finds.append(("FAIL", "dup-pin",
                          f"{where}: duplicate pin for {key[0]} "
                          f"on {key[1]}"))
        else:
            seen.add(key)
        # pin x flag join: a spec-silent pin must not bless an outcome a
        # suspected-defect file asserts is broken for the same unit+input
        unit_last = str(pin.get("unit") or "").rsplit(".", 1)[-1]
        raw_in = str(pin.get("input") or "").strip()
        core = raw_in[1:-1] if len(raw_in) > 2 and \
            raw_in[0] in "'\"" and raw_in[-1] == raw_in[0] else raw_in
        if unit_last and len(core) >= 4:
            for fn, fsrc in flag_srcs:
                if unit_last in fsrc and \
                        (raw_in in fsrc or core in fsrc):
                    finds.append(("FAIL", "flag-pin-contradiction",
                                  f"{where}: pin on {unit_last} input "
                                  f"{raw_in[:60]!r} overlaps a "
                                  f"suspected-defect assertion in "
                                  f"{fn} — same-input flag and pin "
                                  f"cannot coexist"))
                    break
    # unmanifested-pin join: optional TESTS_DIR — scan green test files
    # for pin-shaped marker comments (# pin: / @pin ids); any pin-shaped
    # assert id not in the manifest = unmanifested pin
    if tests_dir and os.path.isdir(tests_dir):
        ids = {p.get("id") for p in pins if isinstance(p, dict)}
        for root, _, fns in os.walk(tests_dir):
            for fn in fns:
                if fn.startswith("test_suspected") or \
                        not (fn.startswith("test_") and
                             fn.endswith(".py")):
                    continue
                fp = os.path.join(root, fn)
                try:
                    src = open(fp, encoding="utf-8",
                               errors="replace").read()
                except OSError:
                    continue
                for m in re.finditer(r"\bpin[:_ -]([A-Za-z0-9_-]+)", src):
                    if m.group(1) not in ids:
                        finds.append(("FAIL", "unmanifested-pin",
                                      f"{fp}: pin-shaped marker "
                                      f"'{m.group(1)}' not in manifest — "
                                      f"undisclosed pins are evasion "
                                      f"channels (r21)"))
    # unmanifested-java-pin join (r30 language-aware seal): Java suites
    # could hide pins behind the Python-only scan — junit/ and staged
    # *.java tests are searched for `// pin-observed:` / `pin:` comment
    # markers; --src is scanned only when the run has no java of its own.
    jfiles = java_test_files(run_dir, tests_dir,
                             sd if sd else src_dirs)
    if jfiles:
        ids = {p.get("id") for p in pins if isinstance(p, dict)}
        for fp in jfiles:
            if "suspected" in os.path.basename(fp).lower():
                continue        # flag files: pins-as-flags are whitelisted
            seen_mark = set()
            for ln, mark_id in java_pin_markers(fp):
                if mark_id in seen_mark:
                    continue
                seen_mark.add(mark_id)
                if mark_id not in ids:
                    finds.append(("FAIL", "unmanifested-java-pin",
                                  f"{fp}:{ln}: pin marker '{mark_id}' "
                                  f"not in manifest — undisclosed pins "
                                  f"are evasion channels (r30)"))
    # unmanifested-observed-pin join (r35 assert-body seal): with --src
    # + green tests, scan assert BODIES for the observed-outcome shape —
    # a literal-return assert whose outcome expression calls no
    # documented unit. cli_r35 passed the marker join on an EMPTY
    # manifest while >=6 green asserts pinned impl-observed spec-silent
    # outcomes (2 of them catalog defects). Markers are opt-in; assert
    # bodies are not.
    if sd:
        def_units = defined_units(sd)
        for root, _, fns in os.walk(tests_dir or ""):
            for fn in fns:
                if "suspected" in fn.lower() or \
                        not (fn.startswith("test_")
                             and fn.endswith(".py")):
                    continue
                fp = os.path.join(root, fn)
                try:
                    src = open(fp, encoding="utf-8",
                               errors="replace").read()
                except OSError:
                    continue
                for ln, calls, lits, stmt in observed_pin_findings(
                        py_literal_outcome_asserts(src), pins,
                        doc_units, def_units):
                    finds.append(
                        ("FAIL", "unmanifested-pin",
                         f"{fp}:{ln}: literal-outcome assert on "
                         f"undocumented unit(s) "
                         f"{', '.join(sorted(set(calls))[:3])} pins "
                         f"{str(lits[0])[:40]!r} — no doc clause "
                         f"covers the input class and no pins: entry "
                         f"claims it (r35)"))
        for fp in jfiles:
            if "suspected" in os.path.basename(fp).lower():
                continue
            try:
                src = open(fp, encoding="utf-8",
                           errors="replace").read()
            except OSError:
                continue
            for ln, calls, lits, stmt in observed_pin_findings(
                    java_literal_outcome_asserts(src), pins,
                    doc_units, def_units):
                finds.append(
                    ("FAIL", "unmanifested-pin",
                     f"{fp}:{ln}: literal-outcome assert on "
                     f"undocumented unit(s) "
                     f"{', '.join(sorted(set(calls))[:3])} pins "
                     f"{str(lits[0])[:40]!r} — no doc clause "
                     f"covers the input class and no pins: entry "
                     f"claims it (r35)"))
    # census->manifest join: door rows marked 'pin' must resolve to
    # a manifest entry (id or ref), else the pin is undisclosed
    ids = {p.get("id") for p in pins if isinstance(p, dict)}
    dd = data.get("doors") or {}
    items = (dd.items() if isinstance(dd, dict)
             else enumerate(dd) if isinstance(dd, list) else [])
    for dk, dv in items:
        v = (dv if isinstance(dv, dict) else {})
        verdict = str(v.get("verdict", dv if isinstance(dv, str) else "")
                      ).lower().strip()
        if verdict != "pin":
            continue
        ref = str(v.get("pin") or v.get("pin_id")
                  or v.get("ref") or "")
        if ref not in ids:
            finds.append(("FAIL", "census-pin-unresolved",
                          f"doors[{dk}]: census 'pin' ref '{ref}' "
                          f"not in manifest"))
    # source-verified clause_quote: if src dirs are provided, the quote
    # must appear verbatim in the LIBRARY source, not just the design doc
    if sd and srctext:
        for pin in pins:
            if not isinstance(pin, dict):
                continue
            q = pin.get("clause_quote")
            if q and str(q).strip() not in srctext:
                finds.append(("FAIL", "quote-not-in-source",
                              f"{pin.get('id')}: clause_quote not "
                              f"verbatim in library source — "
                              f"fabricated or paraphrased"))
    if not pins:
        finds.append(("WARN", "empty-manifest",
                      "no pins: entries — if the suite has spec-silent "
                      "pins they are unmanifested"))
    print(f"pin_manifest: {len(pins)} pin(s) audited")
    for sev, shape, msg in finds:
        print(f"  [{sev}] {shape}: {msg}")
    if json_out:
        json.dump([{"severity": s, "shape": sh, "msg": m}
                   for s, sh, m in finds], open(json_out, "w"), indent=1)
    n_fail = sum(1 for f in finds if f[0] == "FAIL")
    if not finds:
        print("  OK — manifest clean")
    else:
        print(f"  {n_fail} failure(s), "
              f"{len(finds) - n_fail} warning(s)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    pos, opts = parse_args(sys.argv[1:])
    design, run_dir, tests_dir, src_dirs = resolve_paths(pos, opts)
    sys.exit(main(design, opts["json"], tests_dir, src_dirs, run_dir))
