#!/usr/bin/env python3
"""Obligation-ledger reconciler for TEST_DESIGN.md. Stdlib only
(uses PyYAML when importable, else a minimal parser for the
restricted ledger shape).

Usage: ledger_reconcile.py TEST_DESIGN.md [--tests DIR] [--src DIR ...]
           [--metrics FILE] [--json out.json]

The ledger is machine-authored (r35 migration): runners build
<run_dir>/ledger.json via scripts/ledger_entry.py append calls and
embed its `render` output — a fenced ```ledger YAML snapshot — in
TEST_DESIGN.md. When ledger.json exists beside TEST_DESIGN.md it is
AUTHORITATIVE and strict schema checks apply; the fenced block is
read only as the backcompat fallback:

    ```ledger
    obligations: [{id, kind, members: [...]}]
    witnesses:   [{test, covers: [{obligation, members: [...]}]}]
    folds:       [{obligation, member, fold_into, reason}]
    pins:        [...]
    doors:       [...]
    budget: N
    ```

Schema-completeness FAILs (machine path; hum_r34 shipped a truncated
hand-written YAML ledger — an orphan ` pass}}` fragment with the
pins:/doors: sections and fresh budget silently lost):

  * `ledger-corrupt` — ledger.json is not parseable JSON (or is not a
    mapping); on the YAML fallback, the fenced block fails to parse or
    carries stray non-YAML fragments the restricted parser could not
    consume (a trailing ` pass}}` line used to be dropped silently)
  * `ledger-missing-section` — a required top-level key is absent:
    obligations/members/witnesses/pins/doors/folds/budget (`members`
    is the flat append list; obligation-nested members also satisfy
    it for pre-migration ledgers)
  * `entry-schema` — an entry lacks the fields the join needs:
    witness requires a 'test' path; pin requires unit, input,
    clause_absent and conforming_attempt; fold requires obligation,
    member, fold_into and reason; door requires unit and member;
    a flat member requires obligation+member citing an existing
    obligation. (Also applied to the YAML fallback.)

Checks — the join runs at MEMBER granularity:
  * every obligation member has >=1 witness or a declared fold (holes)
  * every fold cites an existing witness, obligation, and member
  * every witness covers >=1 existing obligation member
    (a witness covering nothing is a redundant test)
  * every obligation id is referenced by >=1 witness or fold
    (an obligation nobody cites is unreferenced)
  * minimality: every witness is the SOLE coverer of >=1 obligation
    member — a witness whose whole covered-member set is subsumed by
    the union of the other witnesses' covers is a subsumed-witness
    (redundancy candidate; a witness covering nothing is already
    redundant-test, not double-reported)
  * no (obligation, member) pair is listed twice — in the obligations
    list or within one witness's covers (dup-member)
  * with --tests DIR: `pytest --collect-only -q` is run; every collected
    item must appear in witnesses (unanchored test) and every witness
    name must appear in the collection (phantom witness / name drift)
  * without --tests (or when the collection fails): the same
    phantom-witness join runs against STATICALLY discovered tests —
    `junit/`/`tests/`/`test/` dirs beside TEST_DESIGN.md are censused
    (.java @Test-family methods, `def test*` by AST) and every
    witness `test` ref must resolve to a discovered (file, method):
    `path.py::test_x[p]`, `Cls::m`, `pkg.Class#m` spellings all
    resolve; anything else is `phantom-witness` FAIL. Param brackets
    are stripped for the lookup but synthetic suffixes are NOT —
    cv_r37 minted 52 `~covN` pseudo-witnesses (real base name +
    fake tag) to pass witness-starvation
  * budget == #witness entries == #collected items (when measured) ==
    sum of the TEST_DESIGN budget-table rows (when a table is found)
  * with --src DIR on a Java tree: member-census floor — the ledger's
    member total must be >= 1 per 4 public methods counted by regex on
    the non-test source, else `java-census-floor` (a 61-member suite
    over a ~350-method API is implausibly thin, r30)
  * with --src DIR on a Python tree: same floor over public
    functions/classes/methods counted by AST on non-test sources,
    else `python-census-floor` (r31)
  * member granularity (r34): a member names ONE unit + discriminating
    input. A member string spelling >=3 distinct public unit names is
    a bundle — `member-packing` FAIL — as is aggregate unit-name
    coverage exceeding ~2x the discrete-member count. The census
    floors count DISCRETE (unit, input-class) members: a bundle mints
    no pair, so packed strings earn no member-census credit
    (validators_r34's ~70 units in ~10 space-joined member strings
    passed the floor on member-STRING count while shipping 12 tests)
  * min-witness floor: #witnesses must reach >=1 per 3 obligation
    members, else `witness-starvation` (a 110-member ledger shipped
    on 23 grab-bag tests is capacity-collapse, not minimalism, r31);
    and members appearing in witness covers must be >=60% of all
    enumerated members (the rest may not live only in folds)
  * seal-gaming audits (bridge/coverage-config/metrics):
      - a .py file or __pycache__ dir inside a Java --src tree is a
        `bridge-artifact` FAIL (r31: coverage_anchor.py planted in
        src/main/java to feed the Python checkers)
      - coverage-config `exclude_lines`/`exclude_also` patterns found
        beside TEST_DESIGN.md (.coveragerc, setup.cfg, tox.ini,
        coverage.cfg, pyproject.toml) whose unescaped text shares a
        token with the ledger member corpus are `coverage-exclusion`
        FAILs — excluded lines are door mechanisms, not inert tails
        (r31: the ]-strip / is_private / keccak-flag sites)
      - when metrics.json sits beside TEST_DESIGN.md, its collected /
        tests_run count must not diverge from the ledger witness
        count by >10x without a quantified disclosure of the split
        (upstream/vendored/pre-existing tests), else
        `metrics-divergence` FAIL (r31: 12 witnesses vs 3486 executed
        where ~3195 were undisclosed upstream repo tests)
      - `metrics-untruth` FAIL (r37): metrics.json counts are claims
        to re-verify, not truth. A tests/ dir is re-collected with
        pytest --collect-only (±5% tolerance); a junit/ dir gets a
        static @Test-method census (exact — a method census is
        deterministic). `collected`/`tests_run`/`methods_total`/
        `tests_emitted`/`witnesses`/`budget`-family leaves must equal
        the fresh measurement; pass/fail-family leaves may not exceed
        the real count. With junit/ + pom.xml, `mvn -o -q
        test-compile` (120s) is attempted — a failing compile while
        metrics/design/journal claim compile-clean or green tests is
        a FAIL — and **/surefire-reports/TEST-*.xml totals are
        diffed against the pass/fail claims when reports exist.
        Absent toolchains (no mvn/javac/pytest on PATH and none
        disclosed in the metrics gate strings) degrade to WARN
        (cv_r37 shipped a non-compiling suite + fabricated 111-green/
        116-total claims over 112 real methods)

Exit: 0 clean (incl. clean "no ledger block" diagnostic), 1 findings,
2 usage/fatal error (input file unreadable).
"""
import argparse
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

try:
    import yaml
except ImportError:
    yaml = None


# ---------------------------------------------------------------- fenced blocks

def extract_fenced(text, lang):
    """Return contents of every fenced ```<lang> block in markdown text."""
    pat = re.compile(r"^```" + re.escape(lang) + r"[ \t]*\n(.*?)^```[ \t]*$",
                     re.M | re.S)
    return pat.findall(text)


# ------------------------------------------------------- minimal YAML fallback

def _strip_comment(line):
    out, sq, dq = [], False, False
    for i, c in enumerate(line):
        if sq:
            out.append(c)
            if c == "'":
                sq = False
        elif dq:
            out.append(c)
            if c == '"':
                dq = False
        elif c == "'":
            sq = True
            out.append(c)
        elif c == '"':
            dq = True
            out.append(c)
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(c)
    return "".join(out).rstrip()


def _scalar(s):
    s = s.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        try:
            return ast.literal_eval(s)
        except Exception:
            return s[1:-1]
    low = s.lower()
    if low in ("null", "none", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _skip_ws(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _flow_value(s, i):
    """Parse a YAML flow value starting at s[i]; return (value, next_i)."""
    i = _skip_ws(s, i)
    if i >= len(s):
        return None, i
    if s[i] == "[":
        out, i = [], i + 1
        while True:
            i = _skip_ws(s, i)
            if i >= len(s) or s[i] == "]":
                return out, i + 1
            v, i = _flow_value(s, i)
            out.append(v)
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "]":
                return out, i + 1
            else:
                return out, i
    if s[i] == "{":
        out, i = {}, i + 1
        while True:
            i = _skip_ws(s, i)
            if i >= len(s) or s[i] == "}":
                return out, i + 1
            k, i = _flow_value(s, i)
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ":":
                i += 1
            v, i = _flow_value(s, i)
            out[str(k)] = v
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "}":
                return out, i + 1
            else:
                return out, i
    if s[i] in "\"'":
        q, j = s[i], i + 1
        while j < len(s) and s[j] != q:
            j += 1
        raw = s[i:j + 1]
        try:
            return ast.literal_eval(raw), j + 1
        except Exception:
            return s[i + 1:j], j + 1
    # bare scalar: ends at , ] } or a ':' that closes a flow-map key
    j = i
    while j < len(s):
        c = s[j]
        if c in ",]}":
            break
        if c == ":" and (j + 1 >= len(s) or s[j + 1] in " ,]}"):
            break
        j += 1
    return _scalar(s[i:j]), j


def _is_keyval(text):
    return re.match(r"^[^:\[\]{},]+:(\s|$)", text) is not None


def _parse_block(lines, i):
    """Parse block at lines[i]; lines are (indent, text). Returns (obj, i)."""
    base = lines[i][0]
    first = lines[i][1]
    if first == "-" or first.startswith("- "):
        out = []
        while (i < len(lines) and lines[i][0] == base
               and (lines[i][1] == "-" or lines[i][1].startswith("- "))):
            body = lines[i][1][1:]
            off = len(body) - len(body.lstrip())
            content = body.lstrip()
            sub = [(base + 1 + off, content)] if content else []
            i += 1
            while i < len(lines) and lines[i][0] > base:
                sub.append(lines[i])
                i += 1
            if not sub:
                out.append(None)
            elif len(sub) == 1 and not _is_keyval(sub[0][1]) \
                    and not sub[0][1].startswith(("[", "{")):
                out.append(_scalar(sub[0][1]))
            elif len(sub) == 1 and sub[0][1].startswith(("[", "{")):
                out.append(_flow_value(sub[0][1], 0)[0])
            else:
                obj, _ = _parse_block(sub, 0)
                out.append(obj)
        return out, i
    if _is_keyval(first):
        out = {}
        while i < len(lines) and lines[i][0] == base and _is_keyval(lines[i][1]):
            key, _, rest = lines[i][1].partition(":")
            key, rest = key.strip(), rest.strip()
            i += 1
            if rest == "":
                if i < len(lines) and lines[i][0] > base:
                    val, i = _parse_block(lines, i)
                else:
                    val = None
            elif rest in ("|", ">"):
                buf = []
                while i < len(lines) and lines[i][0] > base:
                    buf.append(lines[i][1])
                    i += 1
                val = "\n".join(buf)
            elif rest.startswith(("[", "{")):
                val = _flow_value(rest, 0)[0]
            else:
                val = _scalar(rest)
            out[key] = val
        return out, i
    return _scalar(first), i + 1


def minimal_yaml(text):
    """Returns (parsed, orphan_lines). Lines the restricted parser
    could not consume are stray fragments (an orphan ` pass}}`
    continuation truncating the block), not silent omissions —
    silently dropping them is exactly the corruption this audit
    exists to catch."""
    lines = []
    for raw in text.split("\n"):
        t = _strip_comment(raw)
        if not t.strip():
            continue
        indent = len(t) - len(t.lstrip())
        lines.append((indent, t.lstrip()))
    if not lines:
        return None, []
    obj, i = _parse_block(lines, 0)
    return obj, [t for _, t in lines[i:]]


def load_ledger(block_text):
    """Parsed ledger only (other checkers import this)."""
    if yaml is not None:
        return yaml.safe_load(block_text)
    return minimal_yaml(block_text)[0]


def load_ledger_full(block_text):
    """(parsed, orphan_lines). Under PyYAML a stray fragment fails the
    whole parse instead, so orphans is only non-empty for the fallback
    parser."""
    if yaml is not None:
        return yaml.safe_load(block_text), []
    return minimal_yaml(block_text)


# ------------------------------------------------------------------ normalize

def member_key(m):
    """Stable key for an obligation member (str, scalar, or dict)."""
    if isinstance(m, dict):
        for k in ("name", "id", "member", "value", "side"):
            if k in m:
                return str(m[k])
        return json.dumps(m, sort_keys=True)
    return str(m)


def member_label(m):
    return member_key(m)


def normalize(ledger):
    """Coerce the parsed ledger into canonical dicts; collects format errors."""
    errors = []
    obligations, witnesses, folds = [], [], []
    budget = None
    if not isinstance(ledger, dict):
        return None, ["ledger block did not parse to a mapping"]
    raw_ob = ledger.get("obligations") or []
    raw_wi = ledger.get("witnesses") or []
    raw_fo = ledger.get("folds") or []
    budget = ledger.get("budget")
    for idx, o in enumerate(raw_ob):
        if not isinstance(o, dict) or "id" not in o:
            errors.append(f"obligations[{idx}]: not a mapping with an 'id'")
            continue
        members = o.get("members")
        if members is None:
            errors.append(f"obligation {o['id']}: no 'members' list")
            members = []
        elif not isinstance(members, list):
            members = [members]
        obligations.append({"id": str(o["id"]), "kind": o.get("kind", ""),
                            "members": members, "raw": o})
    for idx, w in enumerate(raw_wi):
        if not isinstance(w, dict) or "test" not in w:
            errors.append(f"witnesses[{idx}]: not a mapping with a 'test'")
            continue
        covers = w.get("covers") or []
        if not isinstance(covers, list):
            covers = [covers]
        witnesses.append({"test": str(w["test"]), "covers": covers})
    for idx, f in enumerate(raw_fo):
        if not isinstance(f, dict):
            errors.append(f"folds[{idx}]: not a mapping")
            continue
        folds.append({"obligation": str(f.get("obligation")),
                      "member": f.get("member"),
                      "fold_into": str(f.get("fold_into")),
                      "reason": f.get("reason", "")})
    return {"obligations": obligations, "witnesses": witnesses,
            "folds": folds, "budget": budget}, errors


# ------------------------------------------------------------------ test names

def tail_name(test_field):
    """'file.py::Cls::test_x[a]' -> 'test_x[a]' ; 'test_x' -> 'test_x'."""
    return test_field.rsplit("::", 1)[-1].strip().strip("`\"")


def base_name(tail):
    return tail.split("[", 1)[0]


def collect_tests(tests_dir):
    """pytest --collect-only -q; returns (nodeid_tails, error_or_None)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             "-p", "no:cacheprovider", tests_dir],
            capture_output=True, text=True, timeout=300, env=env)
    except FileNotFoundError:
        return None, "pytest not runnable (no interpreter/pytest?)"
    except subprocess.TimeoutExpired:
        return None, "pytest --collect-only timed out"
    out = proc.stdout + proc.stderr
    if proc.returncode not in (0, 5):  # 5 = no tests collected
        return None, "pytest --collect-only failed:\n" + out[-2000:]
    ids = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "::" in line and not line.startswith(("=", "warning")):
            ids.append(tail_name(line))
    return ids, None


# ------------------------------------------------ static test discovery (r37)
# The --tests join above runs a LIVE pytest collection; runs that never
# execute (or that mint pseudo-witnesses — cv_r37's 52 `~covN` entries)
# get the same join against tests discovered STATICALLY under the run
# dir's junit//tests/ dirs: .java test-method census for JUnit refs and
# AST `def test_*` for pytest refs.

TEST_DIR_NAMES = ("tests", "junit", "test")
PSEUDO_WITNESS_RE = re.compile(r"~cov\d+\s*$")
JAVA_PACKAGE_RE = re.compile(r"\bpackage\s+([\w.]+)\s*;")
# an annotation run followed by a method declaration; the run is kept
# so we can require a test-family annotation on the method
JAVA_ANN_METHOD_RE = re.compile(
    r"((?:@\s*[\w.]+\s*(?:\([^)]*\)\s*)?\s*)+)"
    r"(?:(?:public|protected|private|static|final|synchronized|"
    r"abstract|default|strictfp|native)\s+)*"
    r"[\w<>\[\],.?&]+\s+([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*"
    r"(?:throws[\w\s,.]+)?\{")
JAVA_TEST_ANN_RE = re.compile(
    r"@\s*(?:[\w.]*\.)?(Test|ParameterizedTest|RepeatedTest|"
    r"TestFactory|TestTemplate)\b")
JAVA3_TEST_RE = re.compile(
    r"\bpublic\s+void\s+(test[A-Za-z_$][\w$]*)\s*\(")


def _split_depth0(s):
    """Split a nodeid on '::' at bracket depth 0 — parametrized ids
    like test_x[a::b] keep their bracket contents intact."""
    parts, depth, last, i = [], 0, 0, 0
    while i < len(s):
        c = s[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth = max(0, depth - 1)
        elif c == ":" and s[i:i + 2] == "::" and depth == 0:
            parts.append(s[last:i])
            last = i = i + 2
            continue
        i += 1
    parts.append(s[last:])
    return parts


def _java_test_methods(path):
    """(package, {test method names}) for a .java test source."""
    try:
        s = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return "", set()
    s = JAVA_COMMENT_RE.sub("", s)
    pkg = JAVA_PACKAGE_RE.search(s)
    methods = set()
    for m in JAVA_ANN_METHOD_RE.finditer(s):
        if JAVA_TEST_ANN_RE.search(m.group(1)):
            methods.add(m.group(2))
    methods.update(JAVA3_TEST_RE.findall(s))
    return (pkg.group(1) if pkg else ""), methods


def _py_test_names(path):
    """{test function/method names, Test* class names} via AST."""
    try:
        tree = ast.parse(open(path, encoding="utf-8",
                              errors="replace").read())
    except (OSError, SyntaxError, ValueError):
        return set(), set()
    names, classes = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name.startswith("test"):
            names.add(n.name)
        elif isinstance(n, ast.ClassDef):
            classes.add(n.name)
    return names, classes


def discover_test_index(dirs, run_dir=None):
    """Static census of the test suite: one record per test source
    file — {path, base, stem, pkg, rel_run, rel_root, methods,
    classes}. Java files contribute @Test-family annotated methods and
    JUnit3 `public void test*`; Python files contribute `def test*`
    (module level and inside Test* classes alike)."""
    index = []
    seen = set()
    for root_dir in dirs or []:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        for root, dns, fns in os.walk(root_dir):
            dns[:] = [d for d in dns if d not in BUILD_DIRS]
            for fn in sorted(fns):
                p = os.path.join(root, fn)
                if p in seen:
                    continue
                rec = {"path": p, "base": fn,
                       "stem": os.path.splitext(fn)[0], "pkg": "",
                       "methods": set(), "classes": set()}
                if fn.endswith(".java"):
                    rec["pkg"], rec["methods"] = _java_test_methods(p)
                    rec["classes"] = {rec["stem"]}
                elif fn.endswith(".py"):
                    rec["methods"], rec["classes"] = _py_test_names(p)
                else:
                    continue
                if not rec["methods"]:
                    continue
                seen.add(p)
                rec["rel_root"] = os.path.relpath(p, root_dir)
                rec["rel_run"] = (os.path.relpath(p, run_dir)
                                  if run_dir else rec["rel_root"])
                index.append(rec)
    return index


def _norm_path(p):
    return str(p).replace("\\", "/").strip().lstrip("./")


def _file_matches(rec, filepart):
    """Does a witness's file/class qualifier name this test file?
    Accepts exact rel paths, suffix paths (witnesses spell
    run-prefixed or tests/-rooted paths), bare filenames/stems, and
    pkg.Class / pkg/Class qualifiers."""
    fp = _norm_path(filepart)
    if not fp:
        return True
    cands = {rec["rel_run"], rec["rel_root"], rec["base"], rec["stem"]}
    if rec["pkg"]:
        cands.add(rec["pkg"] + "." + rec["stem"])
        cands.add(rec["pkg"] + "/" + rec["stem"])
    fp_dotted_slash = fp.replace(".", "/")
    for c in cands:
        if not c:
            continue
        cn = _norm_path(c)
        if fp == cn or fp.endswith("/" + cn) or cn.endswith("/" + fp):
            return True
        if fp_dotted_slash == cn or cn.endswith("/" + fp_dotted_slash):
            return True
    return False


def resolve_witness(test_ref, index):
    """True when test_ref names a real discovered (file, method).
    Refs: 'path.py::test_x[p]' / 'path.py::Cls::test_x' / 'Cls::m' /
    'pkg.Class#m' / 'pkg.Class.m' / bare 'm'. Param brackets [...] are
    stripped for the method lookup; a '~covN'-style synthetic suffix is
    NOT — it must name a real method."""
    t = str(test_ref).strip().strip("`\"")
    segs = _split_depth0(t)
    filepart = cls = None
    if len(segs) >= 2:
        filepart, method = segs[0], segs[-1]
        if len(segs) >= 3:
            cls = segs[-2]
    elif "#" in t:
        filepart, method = t.rsplit("#", 1)
    elif "." in t and "/" not in t and "\\" not in t:
        filepart, method = t.rsplit(".", 1)
    else:
        method = t
    method = method.split("[", 1)[0].strip().strip("`\"")
    if not method:
        return False
    if filepart is not None:
        hits = [r for r in index if _file_matches(r, filepart)]
        if not hits:
            return False
        for r in hits:
            if cls and cls not in r["classes"]:
                continue
            if method in r["methods"]:
                return True
        return False
    return any(method in r["methods"] for r in index)


# ------------------------------------------------------------ java census

JAVA_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
JAVA_PUBLIC_METHOD_RE = re.compile(
    r"\bpublic\s+(?!class\b|interface\b|enum\b|record\b|@interface\b)"
    r"[\w<>\[\],.?\s&]+?\w+\s*\([^;{}]*\)\s*(?:throws[\w\s,.]+)?[{;]")
JAVA_TESTISH_RE = re.compile(
    r"(^|/|\\)(test|tests|junit|it)(/|\\)|Test[^/\\]*\.java$|"
    r"[^/\\]*Tests?\.java$|[^/\\]*TestCase\.java$", re.I)
PY_TESTISH_RE = re.compile(
    r"(^|/|\\)(test|tests|testing)(/|\\)|(^|/|\\)test_[^/\\]*\.py$|"
    r"[^/\\]*_test\.py$|(^|/|\\)conftest\.py$", re.I)
BUILD_DIRS = {"target", "build", "out", "dist", ".git", ".gradle",
              ".idea", "node_modules", "__pycache__", ".tox", ".venv",
              "venv", "env", "site-packages", ".mypy_cache",
              ".pytest_cache", ".eggs"}
# member floor: >=1 ledger member per JAVA_MEMBER_RATIO public methods
JAVA_MEMBER_RATIO = 4
PY_MEMBER_RATIO = 4
# witness floor: >=1 witness per WITNESS_MEMBER_RATIO ledger members, and
# >=WITNESS_COVER_FRACTION of members must appear in witness covers
WITNESS_MEMBER_RATIO = 3
WITNESS_COVER_FRACTION = 0.6
# member-granularity seal (r34): >=PACK_MEMBER_UNITS distinct public
# unit names in one member string is a bundle, and tokenized unit-name
# coverage >~PACK_COVERAGE_RATIO x the discrete-member count is
# bundled enumeration
PACK_MEMBER_UNITS = 3
PACK_COVERAGE_RATIO = 2


def tree_source_files(src_dirs):
    """One walk over src_dirs -> (py_files, java_files, pycache_dirs)."""
    py, java, pycache = [], [], []
    for d in src_dirs or []:
        for root, dirs, fns in os.walk(d):
            for x in dirs:
                if x == "__pycache__":
                    pycache.append(os.path.join(root, x))
            dirs[:] = [x for x in dirs if x not in BUILD_DIRS]
            for fn in fns:
                if fn.endswith(".py"):
                    py.append(os.path.join(root, fn))
                elif fn.endswith(".java"):
                    java.append(os.path.join(root, fn))
    return py, java, pycache


def is_java_tree(src_dirs):
    """Predominantly-Java source tree: .java outnumbers .py (a stray
    conftest.py inside a Java test tree must not disqualify it)."""
    py, java, _ = tree_source_files(src_dirs)
    return len(java) > len(py)


def java_public_surface(java_files):
    """Regex census of `public <sig> name(...)` declarations in
    non-test .java files — (count, {unit names})."""
    n, names = 0, set()
    for p in java_files:
        if JAVA_TESTISH_RE.search(p):
            continue
        try:
            s = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        s = JAVA_COMMENT_RE.sub("", s)
        for m in JAVA_PUBLIC_METHOD_RE.finditer(s):
            n += 1
            nm = re.search(r"([A-Za-z_$][\w$]*)\s*\(", m.group(0))
            if nm:
                names.add(nm.group(1))
    return n, names


def count_java_public_methods(java_files):
    """Regex census of `public <sig> name(...)` declarations in
    non-test .java files — the public-API surface."""
    return java_public_surface(java_files)[0]


def _py_public_units(path):
    """AST census of one module's public surface: __all__ members when
    declared, else public module-level functions/classes, plus public
    and dunder methods per class — mirrors surface_closure's rules.
    Returns (count, {unit names})."""
    try:
        tree = ast.parse(open(path, encoding="utf-8",
                              errors="replace").read())
    except (SyntaxError, ValueError, OSError):
        return 0, set()
    exported = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__"
                for t in node.targets):
            try:
                exported = [str(e.value) for e in node.value.elts]
            except AttributeError:
                exported = None
    n, seen, names = 0, set(), set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (not node.name.startswith("_")
                    or (exported and node.name in exported)) \
                    and (exported is None or node.name in exported):
                n += 1
                seen.add(node.name)
                names.add(node.name)
        elif isinstance(node, ast.ClassDef) and \
                (not node.name.startswith("_")
                 or (exported and node.name in exported)):
            n += 1
            seen.add(node.name)
            names.add(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and not (sub.name.startswith("_")
                                 and not sub.name.startswith("__")):
                    n += 1
                    names.add(sub.name)
    if exported:
        for x in exported:
            if x not in seen:
                n += 1
                names.add(x)
    return n, names


def python_public_surface(py_files):
    """(count, {unit names}) over non-test .py files."""
    n, names = 0, set()
    for p in py_files:
        if PY_TESTISH_RE.search(p):
            continue
        c, ns = _py_public_units(p)
        n += c
        names |= ns
    return n, names


def count_python_public_units(py_files):
    """AST census of public units in non-test .py files."""
    return python_public_surface(py_files)[0]


# ---------------------------------------------------- member granularity

def unit_index(unit_names):
    """unit name -> (subtokens, squash): 'parse_version_info' ->
    ([parse,version,info], 'parseversioninfo'); 'AbsMax' -> ([abs,max],
    'absmax')."""
    idx = {}
    for u in unit_names:
        subs = [p.lower() for p in re.split(
            r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
            str(u)) if p]
        idx[u] = (subs, "".join(subs))
    return idx


def member_unit_groups(text, index):
    """Public units a member string spells, deduped to maximal subtoken
    sets: 'parse_version_info' hits parse_version_info, not parse +
    Version + VersionInfo; 'es-cif' and 'es_cif' both hit es_cif. A
    signature citation ('Cls.m0:public Builder argName(final String x)')
    cites ONE unit — its parens arg list, declared name, and dotted
    qualifier are scaffolding, not enumerated units."""
    s = str(text)
    if "(" in s:
        s = re.sub(r"[A-Za-z_$][\w$]*\s*\(", "(", s)
        s = re.sub(r"\([^()]*\)", " ", s)
        s = re.sub(r"\([^)]*$", " ", s)
        s = re.sub(r"[A-Za-z_$][\w$]*\.", " ", s)
    toks = {t.lower() for t in re.split(r"[^A-Za-z0-9]+", s) if t}
    groups = {}
    for u, (subs, usq) in index.items():
        if not subs or len(usq) < 3:
            continue
        if usq in toks or all(t in toks for t in subs):
            groups.setdefault(frozenset(subs), set()).add(u)
    return {k: v for k, v in groups.items()
            if not any(k < o for o in groups)}


def member_packing_audit(obligations, index):
    """r34 seal: a ledger member names ONE unit + discriminating input.
    A member string spelling >=PACK_MEMBER_UNITS distinct public unit
    names is a bundle (member-packing FAIL); aggregate unit-name
    coverage >~PACK_COVERAGE_RATIO x the discrete-member count is
    bundled enumeration. Returns (n_discrete, findings): a bundle
    mints no (unit, input-class) pair, so the census floors measure
    real discrete members, not bundle strings."""
    findings, pairs, total_hits, n_entries = [], set(), 0, 0
    for o in obligations:
        for m in o["members"]:
            key = member_key(m)
            n_entries += 1
            groups = member_unit_groups(key, index)
            total_hits += len(groups)
            if len(groups) >= PACK_MEMBER_UNITS:
                names = sorted(u for g in groups.values() for u in g)
                findings.append((
                    "member-packing",
                    f"obligation '{o['id']}' member '{key[:60]}' spells "
                    f"{len(groups)} distinct public units "
                    f"({', '.join(names[:8])}"
                    f"{', …' if len(names) > 8 else ''}) — a member "
                    f"must name ONE unit + discriminating input, not a "
                    f"bundle"))
                continue
            unit = min(sorted(g) for g in groups)[0] \
                if groups else o["id"]
            pairs.add((unit, key))
    if total_hits > PACK_COVERAGE_RATIO * len(pairs):
        findings.append((
            "member-packing",
            f"{total_hits} unit-name hits across {n_entries} member "
            f"entries vs {len(pairs)} discrete members "
            f"(>{PACK_COVERAGE_RATIO}x) — members bundle the public "
            f"surface; enumerate ONE (unit, input-class) cell per "
            f"member"))
    return len(pairs), findings


# ------------------------------------------------------- covers-false audit
# (r38: validators_r38 shipped one-witness-per-collection-item bookkeeping —
# every witness covered `case:`-prefixed bookkeeping members that name no
# exercised unit, or bundled members the named test never touches: 0/502
# real members were witnessed. A cover only "witnesses" a unit when the
# unit is actually exercised by the test body the witness cites.)

JAVA_TYPE_RE = re.compile(
    r"\b(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
# String literals AND comments must be stripped in ONE ordered pass:
# stripping comments first eats "//" inside "http://..." literals;
# stripping strings first lets an apostrophe in a comment ("caller's")
# open a runaway char literal that swallows whole method bodies.
JAVA_NOISE_RE = re.compile(
    r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\''
    r"|//[^\n]*|/\*.*?\*/", re.S)
JAVA_METHOD_SIG_RE = re.compile(
    r"(\w+)\s*\([^;{}=]*\)\s*(?:throws[\w\s,.]+)?\{")
JAVA_REF_RE = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*")


def java_type_names(java_files):
    """Declared type names (class|interface|enum|record) across the
    non-test Java source files — the type-level unit vocabulary for
    the covers-false join (java_public_surface only yields methods)."""
    names = set()
    for p in java_files:
        if JAVA_TESTISH_RE.search(p):
            continue
        try:
            s = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        names.update(JAVA_TYPE_RE.findall(JAVA_NOISE_RE.sub(" ", s)))
    return names


def _unit_spelled(unit, text):
    """True when `unit` is spelled in member/prose `text` at a word or
    camel-hump boundary. Underscore always blocks (a unit embedded in
    a snake_case test id is prose, not a unit claim); a lowercase ->
    Uppercase transition counts as a boundary (`getInstance` inside
    `getInstanceReturnsSingleton`, `EmailValidator` inside
    `LegacyEmailValidator`). A `test_X` citation spells X when the
    remainder after the `test_` prefix IS a unit (`test_get_translation`
    claims get_translation; `test_valid_card_number` claims nothing —
    card_number is mid-identifier)."""
    if not unit or len(unit) < 3:
        return False
    left = r"(?<![0-9A-Z_])" if unit[0].isupper() else r"(?<![a-z0-9_])"
    if re.search(left + re.escape(unit) + r"(?![a-z0-9_])", text):
        return True
    return any(m.group(1) == unit or _squash(m.group(1)) == _squash(unit)
               for m in re.finditer(
                   r"(?:^|[^A-Za-z0-9_])test_([A-Za-z0-9_]+)", text))


def _obligation_units(oid, unit_names):
    """Public units an obligation id itself names: the whole id, an
    `obl-`/`obl_`-stripped remainder (`obl-Arg`), and each
    `:`-separated segment (`card_number:contract`, `utils:ValidationError`)."""
    cand = {str(oid)} | set(str(oid).split(":"))
    m = re.match(r"obl[-_:](.+)$", str(oid))
    if m:
        cand.add(m.group(1))
    return {c for c in cand if c in unit_names}


def _resolve_test(test_ref, index):
    """Like resolve_witness but returns (record, method) or (None,None)
    so the caller can find the test's source file."""
    t = str(test_ref).strip().strip("`\"")
    segs = _split_depth0(t)
    filepart = cls = None
    if len(segs) >= 2:
        filepart, method = segs[0], segs[-1]
        if len(segs) >= 3:
            cls = segs[-2]
    elif "#" in t:
        filepart, method = t.rsplit("#", 1)
    elif "." in t and "/" not in t and "\\" not in t:
        filepart, method = t.rsplit(".", 1)
    else:
        method = t
    method = method.split("[", 1)[0].strip().strip("`\"")
    if not method:
        return None, None
    if filepart is not None:
        for r in index:
            if not _file_matches(r, filepart):
                continue
            if cls and cls not in r["classes"]:
                continue
            if method in r["methods"]:
                return r, method
        return None, None
    for r in index:
        if method in r["methods"]:
            return r, method
    return None, None


def _py_test_body_refs(path):
    """{func_name: identifiers the test's executed call graph touches}
    — Name/Attribute refs plus string-constant tokens (parametrize
    values dispatch real calls), module-level import aliases (the unit
    is in scope for the file's suite), and one hop into module-level
    names assigned to expressions decorators reference."""
    try:
        tree = ast.parse(open(path, encoding="utf-8",
                              errors="replace").read())
    except (SyntaxError, ValueError, OSError):
        return {}

    def _harvest(node, out):
        for x in ast.walk(node):
            if isinstance(x, ast.Name):
                out.add(x.id)
            elif isinstance(x, ast.Attribute):
                out.add(x.attr)
            elif isinstance(x, ast.Constant) and isinstance(x.value, str):
                out.update(t for t in
                           re.split(r"[^A-Za-z0-9_]+", x.value) if t)

    assigns, imports = {}, set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigns[t.id] = n.value
        elif isinstance(n, ast.Import):
            imports.update(a.asname or a.name.split(".")[0]
                           for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            imports.update(a.asname or a.name for a in n.names)
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        refs = set(imports)
        _harvest(node, refs)
        for nm in list(refs):
            if nm in assigns:
                _harvest(assigns[nm], refs)
        out[node.name] = refs
    return out


def _java_test_body_refs(path):
    """{method_name: identifiers the test's executed call graph
    touches}. Literals/comments are blanked in one ordered pass (a
    `//` inside "http://..." is not a comment; an apostrophe in a
    comment is not a char literal). Every method's ref set includes
    the file-scope tokens outside method bodies — imports,
    extends/implements clauses, and field declarations: JUnit rebuilds
    the fixture (and its fields/nested probes) for every test. One hop
    into same-file methods handles probe helpers
    (`probe.domain()` -> `isValidDomain`)."""
    try:
        s = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    s = JAVA_NOISE_RE.sub(" ", s)
    methods = {}
    for m in JAVA_METHOD_SIG_RE.finditer(s):
        i, depth = m.end(), 1
        while i < len(s) and depth:
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
            i += 1
        methods[m.group(1)] = (m.start(), i)
    scope, prev = [], 0
    for name, (st, en) in sorted(methods.items(), key=lambda kv: kv[1][0]):
        scope.append(s[prev:st])
        prev = en
    scope.append(s[prev:])
    file_refs = set(JAVA_REF_RE.findall(" ".join(scope)))
    out = {}
    for name, (st, en) in methods.items():
        refs = set(file_refs)
        for tok in JAVA_REF_RE.findall(s[st:en]):
            refs.add(tok)
            refs.update(tok.split("."))
            refs.add(_squash(tok))   # Option.builder ~ OptionBuilder
        for tok in file_refs:
            refs.add(tok.split(".")[0])
            refs.add(_squash(tok))
        out[name] = refs
    for name, (st, en) in methods.items():
        for nm in list(out.get(name, ())):
            if nm in methods:
                out[name].update(
                    re.findall(r"[A-Za-z_$][\w$]*",
                               s[methods[nm][0]:methods[nm][1]]))
    return out


def covers_truth_audit(ledger, test_index, unit_names):
    """r38 covers-false seal. For each witness resolving to a
    discovered (file, method), derive the unit set its covers claim:
    public units spelled by covered member strings (word/camel-hump
    boundaries; `_` blocks, so a unit embedded in a snake test id is
    prose, not a claim) plus public units named by the cover's
    obligation id (whole id, `obl-` remainder, `:`-segments). The
    cover is FALSE when none of those units appears in the named
    test's executed call graph (callee/attribute refs, not
    comments/docstrings). Conservative: fires only when ZERO covered
    units are referenced — a param-row test need not touch every
    covered member; covers that resolve to no unit claim are left to
    the member-existence seals."""
    findings = []
    if not test_index or not unit_names:
        return findings
    cache = {}
    for w in ledger["witnesses"]:
        rec, method = _resolve_test(w.get("test"), test_index)
        if rec is None or method is None:
            continue
        p = rec["path"]
        if p not in cache:
            if p.endswith(".java"):
                cache[p] = _java_test_body_refs(p)
            elif p.endswith(".py"):
                cache[p] = _py_test_body_refs(p)
            else:
                cache[p] = {}
        refs = cache[p].get(method)
        if refs is None:
            continue
        units = set()
        for cov in w.get("covers") or []:
            for m in cov.get("members") or []:
                units.update(u for u in unit_names
                             if _unit_spelled(u, member_key(m)))
            units.update(_obligation_units(cov.get("obligation"),
                                           unit_names))
        if not units:
            continue
        sq = {_squash(x) for x in refs}

        def referenced(u):
            if u in refs or _squash(u) in sq:
                return True
            # ref-side camel suffix: BasicParser exercises Parser
            return u[0].isupper() and any(
                x != u and x.endswith(u) and len(x) > len(u)
                and x[len(x) - len(u) - 1].islower() for x in refs)

        if not any(referenced(u) for u in units):
            findings.append((
                "covers-false",
                f"witness '{str(w['test'])[:70]}' covers "
                f"{', '.join(sorted(units)[:6])}"
                f"{'…' if len(units) > 6 else ''} — no covered unit is "
                f"referenced by the test body it names"))
    return findings


# --------------------------------------------------------- seal-gaming audit

COVERAGE_CFG_NAMES = (".coveragerc", "coverage.cfg", "setup.cfg",
                      "tox.ini", "pyproject.toml")
EXCLUDE_KEY_RE = re.compile(r"^\s*exclude_(?:lines|also)\s*=", re.M)
TOML_EXCLUDE_RE = re.compile(
    r"exclude_(?:lines|also)\s*=\s*\[([^\]]*)\]", re.S)
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
METRICS_COUNT_KEYS = ("collected", "tests_run", "tests-run",
                      "test_count", "items")
DISCLOSE_KEYWORD = (r"upstream|external|vendored|pre-?existing|"
                    r"third-?party|inherited|repo(?:sitory)? tests")
METRICS_DIVERGENCE = 10


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def coverage_exclude_patterns(run_dir):
    """(cfg_name, pattern) pairs from coverage configs beside the
    design doc — .coveragerc/setup.cfg/tox.ini (INI continuation
    lines) and pyproject.toml (TOML string arrays)."""
    pats = []
    for name in COVERAGE_CFG_NAMES:
        p = os.path.join(run_dir, name)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if name == "pyproject.toml":
            for m in TOML_EXCLUDE_RE.finditer(text):
                for sm in re.finditer(r"""(["'])(.*?)\1""",
                                      m.group(1), re.S):
                    if sm.group(2).strip():
                        pats.append((name, sm.group(2).strip()))
            continue
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if EXCLUDE_KEY_RE.match(lines[i]):
                rest = lines[i].split("=", 1)[1].strip()
                if rest and not rest.startswith("#"):
                    pats.append((name, rest))
                j = i + 1
                while j < len(lines) and lines[j][:1] in (" ", "\t") \
                        and lines[j].strip():
                    b = lines[j].strip()
                    if not b.startswith("#"):
                        pats.append((name, b))
                    j += 1
                i = j
            else:
                i += 1
    return pats


def member_corpus(raw_ledger, obligations):
    """Token corpus the ledger references: member keys (split + whole
    squash), obligation ids, and doors: list unit/member spellings."""
    corpus = set()

    def feed(spelling):
        k = _squash(spelling)
        if len(k) >= 5:
            corpus.add(k)
        for t in re.split(r"[^A-Za-z0-9]+", str(spelling)):
            if len(_squash(t)) >= 4:
                corpus.add(_squash(t))

    for o in obligations:
        feed(o["id"])
        for m in o["members"]:
            feed(member_key(m))
    for d in (raw_ledger or {}).get("doors") or []:
        if isinstance(d, dict):
            for k in ("unit", "member", "clause_id"):
                if d.get(k) is not None:
                    feed(d[k])
        else:
            feed(d)
    return corpus


def exclusion_member_hit(pattern, corpus):
    """Unescape a coverage exclude pattern and test its identifiers
    against the member corpus: exact subtoken (>=4 chars), exact
    whole squash (>=5), or containment (both >=6 chars). Returns a
    descriptive hit string or None."""
    un = re.sub(r"\\(.)", r"\1", pattern)
    for ident in IDENT_RE.findall(un):
        for tok in ident.split("_"):
            sq = _squash(tok)
            if len(sq) >= 4 and sq in corpus:
                return f"'{ident}' -> member token '{sq}'"
        sq = _squash(ident)
        if len(sq) >= 5 and sq in corpus:
            return f"'{ident}' -> member '{sq}'"
        if len(sq) >= 6:
            for mt in corpus:
                if len(mt) >= 6 and (mt in sq or sq in mt):
                    return f"'{ident}' ~ member '{mt}'"
    return None


def audit_coverage_config(run_dir, corpus):
    """FAIL when a coverage config beside the design doc excludes lines
    whose identifiers hit the ledger member corpus — the excluded
    lines are door mechanisms, not inert tails."""
    findings = []
    for cfg, pat in coverage_exclude_patterns(run_dir):
        hit = exclusion_member_hit(pat, corpus)
        if hit:
            findings.append((
                "coverage-exclusion",
                f"{cfg}: exclude pattern '{pat[:70]}' references ledger "
                f"member {hit} — excluded lines must be non-"
                f"discriminating tails, not door mechanisms"))
    return findings


def metrics_collected(metrics):
    """Largest executed-test count the metrics claim."""
    cands = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in METRICS_COUNT_KEYS and isinstance(
                        v, (int, float)) and not isinstance(v, bool):
                    cands.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(metrics)
    return max(cands) if cands else None


def metrics_discloses_split(metrics, texts):
    """True when the metrics (or the design/journal text) quantify the
    non-artifact portion — a keyword-tagged numeric key, or keyword and
    a count co-occurring in prose."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if re.search(DISCLOSE_KEYWORD, str(k), re.I) \
                        and isinstance(v, (int, float)) \
                        and not isinstance(v, bool):
                    found.append(k)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(metrics)
    if found:
        return True
    near = re.compile(r"(?:" + DISCLOSE_KEYWORD + r")[^\n]{0,60}\d|"
                      r"\d[^\n]{0,60}(?:" + DISCLOSE_KEYWORD + r")", re.I)
    return any(near.search(t or "") for t in texts)


def audit_metrics(metrics_path, n_wit, texts):
    """FAIL when metrics' collected/tests_run count diverges from the
    ledger witness count by >10x without a quantified disclosure of
    the non-artifact portion (e.g. upstream repo tests)."""
    try:
        metrics = json.load(open(metrics_path, encoding="utf-8",
                               errors="replace"))
    except (OSError, ValueError):
        return []
    if not isinstance(metrics, dict):
        return []
    collected = metrics_collected(metrics)
    if collected is None or not n_wit:
        return []
    if not (collected > METRICS_DIVERGENCE * n_wit
            or n_wit > METRICS_DIVERGENCE * collected):
        return []
    if metrics_discloses_split(metrics, texts):
        return []
    return [("metrics-divergence",
             f"{os.path.basename(metrics_path)}: collected/tests_run="
             f"{int(collected)} vs {n_wit} ledger witnesses "
             f"(>{METRICS_DIVERGENCE}x divergence) with no quantified "
             f"disclosure of the non-artifact portion — upstream/"
             f"vendored/pre-existing tests must be split out")]


# --------------------------------------------------- metrics-untruth (r37)
# metrics.json numbers are claims too — cv_r37 shipped a suite that
# does not compile plus a fabricated "111 green / 116 total" claim,
# and all internal consistency checks passed because every layer lied
# the same way. This audit re-measures: static @Test census for junit/
# dirs, pytest --collect-only for tests/ dirs, `mvn -o -q test-compile`
# when a pom is present, and surefire TEST-*.xml totals when reports
# were left behind. Claims must match the fresh measurement; absent
# toolchains degrade to WARN.

# leaf keys whose number should equal the real test count (a method
# census for junit dirs — witnesses/budget are 1:1 with tests)
UNTRUTH_TOTAL_KEYS = {
    "collected", "tests_run", "tests-run", "test_count", "items",
    "methods_total", "tests_total", "total_tests", "tests_emitted",
    "emitted", "witnesses", "budget"}
# leaf keys claiming a subset of the run (verified against surefire
# when present, else only for impossible >real over-claims)
UNTRUTH_PASS_KEYS = {
    "passed", "passing", "pass", "green", "green_methods",
    "tests_passing", "tests_passed", "xpassed"}
UNTRUTH_FAIL_KEYS = {
    "failed", "failing", "failures", "tests_failing",
    "tests_failing_flags", "tests_failed", "reds",
    "suspected_defect_reds", "errors"}
COMPILE_CLAIM_RE = re.compile(
    r"compil\w*[\s-]*(clean|ok|pass\w*|success\w*|green)|"
    r"build\s+success|test-?compile\w*\s*(ok|pass\w*|clean)", re.I)
MVN_PATH_RE = re.compile(r"((?:/[\w.+-]+)+/mvn)\b")
JAVA_HOME_RE = re.compile(r"JAVA_HOME=((?:/[\w.+-]+)+)")
PY_COLLECT_TOL = 0.05          # pytest collected vs metrics, ±5%
MVN_TIMEOUT = 120


def _metrics_leaves(metrics):
    """(dotted_path, leaf_key, value) for every numeric leaf."""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}" if path else str(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append((p, str(k), v))
                else:
                    walk(v, p)
        elif isinstance(o, list):
            for v in o:
                walk(v, path)

    walk(metrics, "")
    return out


def _metrics_strings(metrics):
    out = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            out.append(o)

    walk(metrics)
    return out


def surefire_totals(run_dir):
    """(tests, failures+errors, skipped) summed over
    **/surefire-reports/TEST-*.xml under run_dir, or None."""
    reports = []
    for root, dns, fns in os.walk(run_dir):
        dns[:] = [d for d in dns
                  if d not in BUILD_DIRS or d == "target"]
        if os.path.basename(root) == "surefire-reports":
            reports += [os.path.join(root, f) for f in fns
                        if f.startswith("TEST-") and f.endswith(".xml")]
    if not reports:
        return None
    tests = fails = skipped = 0
    for p in reports:
        try:
            r = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        tests += int(r.get("tests", 0) or 0)
        fails += int(r.get("failures", 0) or 0)
        fails += int(r.get("errors", 0) or 0)
        skipped += int(r.get("skipped", 0) or 0)
    return tests, fails, skipped


def _mvn_invocation(metrics):
    """(argv_prefix, env) for mvn: PATH first, else the absolute path
    the metrics' own gate string discloses (maven_gate/mvn_gate);
    JAVA_HOME likewise."""
    mvn = shutil.which("mvn")
    java_home = None
    for s in _metrics_strings(metrics):
        if not mvn:
            m = MVN_PATH_RE.search(s)
            if m and os.path.isfile(m.group(1)) \
                    and os.access(m.group(1), os.X_OK):
                mvn = m.group(1)
        if not java_home:
            m = JAVA_HOME_RE.search(s)
            if m and os.path.isdir(m.group(1)):
                java_home = m.group(1)
    if not mvn:
        return None, None
    env = dict(os.environ)
    if java_home:
        env["JAVA_HOME"] = java_home
    return [mvn], env


def audit_metrics_truth(run_dir, metrics, texts, test_index,
                        collected_n):
    """Re-verify metrics.json count/compile claims against a fresh
    measurement. Returns (findings, warnings).

    real count sources, first hit wins:
      tests/ dir   -> pytest --collect-only count (±5% tolerance);
                      collected_n is reused when --tests already ran
      junit/ dir   -> static @Test-method census of test_index
    then, for junit/ dirs:
      run_dir/pom.xml              -> mvn -o -q test-compile (120s)
      **/surefire-reports/TEST-*.xml -> pass/fail totals"""
    findings, warnings = [], []
    if not isinstance(metrics, dict):
        return findings, warnings
    junit_dir = os.path.join(run_dir, "junit")
    has_junit = os.path.isdir(junit_dir)
    tests_dir = os.path.join(run_dir, "tests")
    has_pytests = False
    if os.path.isdir(tests_dir):
        for _, dns, fns in os.walk(tests_dir):
            dns[:] = [d for d in dns if d not in BUILD_DIRS]
            if any(f.endswith(".py") for f in fns):
                has_pytests = True
                break
    java_methods = [r for r in (test_index or [])
                    if r["base"].endswith(".java")]

    real = None           # (count, how-measured)
    if has_pytests or collected_n is not None:
        n = collected_n
        if n is None:
            ids, err = collect_tests(tests_dir)
            if err:
                warnings.append(
                    ("metrics-untruth",
                     f"cannot verify metrics counts: {err}"))
            elif ids is not None:
                n = len(set(ids))
        if n is not None:
            real = (n, "pytest --collect-only", PY_COLLECT_TOL)
    if real is None and has_junit and java_methods:
        real = (sum(len(r["methods"]) for r in java_methods),
                "static @Test census", 0.0)

    if real is not None:
        n_real, how, tol = real
        for path, key, val in _metrics_leaves(metrics):
            k = key.lower().replace("-", "_")
            if re.search(DISCLOSE_KEYWORD, key):
                continue
            if k in UNTRUTH_TOTAL_KEYS:
                if abs(val - n_real) > max(0.5, tol * n_real):
                    findings.append((
                        "metrics-untruth",
                        f"metrics.json '{path}'={int(val)} vs {n_real} "
                        f"real tests ({how}) — counts must match a "
                        f"fresh measurement, not the ledger's own "
                        f"numbers"))
            elif k in UNTRUTH_PASS_KEYS | UNTRUTH_FAIL_KEYS:
                if val > n_real:
                    findings.append((
                        "metrics-untruth",
                        f"metrics.json '{path}'={int(val)} claims more "
                        f"{k} tests than the {n_real} that exist "
                        f"({how})"))
    elif (has_pytests or has_junit) and metrics:
        warnings.append((
            "metrics-untruth",
            "test dirs present but no measurement available (pytest "
            "collect failed or no test files discovered) — metrics "
            "counts unverified"))

    # -- compile + surefire verification for junit/ suites ------------
    if has_junit:
        pom = os.path.join(run_dir, "pom.xml")
        if os.path.isfile(pom):
            mvn, env = _mvn_invocation(metrics)
            if mvn is None:
                warnings.append((
                    "metrics-untruth",
                    "junit/ + pom.xml present but no mvn on PATH and "
                    "no mvn path disclosed in metrics — compile "
                    "claims unverifiable"))
            else:
                try:
                    proc = subprocess.run(
                        mvn + ["-o", "-q", "test-compile"],
                        cwd=run_dir, env=env, capture_output=True,
                        text=True, timeout=MVN_TIMEOUT)
                    compiled = proc.returncode == 0
                    cerr = (proc.stdout + proc.stderr)[-400:]
                except subprocess.TimeoutExpired:
                    compiled, cerr = False, "mvn test-compile timed out"
                except OSError as e:
                    compiled, cerr = None, str(e)
                if compiled is False:
                    claims_clean = any(
                        COMPILE_CLAIM_RE.search(t or "") for t in texts)
                    claims_green = any(
                        key.lower().replace("-", "_") in
                        UNTRUTH_PASS_KEYS and val > 0
                        for _, key, val in _metrics_leaves(metrics))
                    if claims_clean or claims_green:
                        findings.append((
                            "metrics-untruth",
                            "mvn -o test-compile fails but metrics/"
                            "journal claim a clean compile or green "
                            f"tests — tail: {cerr.strip()[:200]}"))
                    else:
                        warnings.append((
                            "metrics-untruth",
                            "mvn -o test-compile fails and no compile/"
                            "green claim was made — suite does not "
                            "build"))
        else:
            javac = shutil.which("javac")
            if javac is None:
                if any(COMPILE_CLAIM_RE.search(t or "") for t in texts):
                    warnings.append((
                        "metrics-untruth",
                        "compile-clean claims made but the suite is "
                        "unverifiable (no pom.xml for mvn, no javac "
                        "on PATH)"))
        sf = surefire_totals(run_dir)
        if sf is not None:
            s_tests, s_fails, s_skip = sf
            s_pass = s_tests - s_fails - s_skip
            for path, key, val in _metrics_leaves(metrics):
                k = key.lower().replace("-", "_")
                if re.search(DISCLOSE_KEYWORD, key):
                    continue
                if k in UNTRUTH_TOTAL_KEYS and val != s_tests:
                    findings.append((
                        "metrics-untruth",
                        f"metrics.json '{path}'={int(val)} vs surefire "
                        f"reports' {s_tests} tests run"))
                elif k in UNTRUTH_PASS_KEYS and val != s_pass:
                    findings.append((
                        "metrics-untruth",
                        f"metrics.json '{path}'={int(val)} vs surefire "
                        f"reports' {s_pass} passed"))
                elif k in UNTRUTH_FAIL_KEYS and val != s_fails:
                    findings.append((
                        "metrics-untruth",
                        f"metrics.json '{path}'={int(val)} vs surefire "
                        f"reports' {s_fails} failures/errors"))
    return findings, warnings


# -------------------------------------------------------------- budget table

def _eval_arith(expr):
    """Evaluate a +,-,*,/,() integer/float expression; None if not arithmetic."""
    expr = expr.strip().strip("*").strip()
    if not expr or not re.fullmatch(r"[0-9+\-*/(). \t]+", expr):
        return None
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and isinstance(
                n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)):
            return {ast.Add: lambda a, b: a + b,
                    ast.Sub: lambda a, b: a - b,
                    ast.Mult: lambda a, b: a * b,
                    ast.Div: lambda a, b: a / b,
                    ast.FloorDiv: lambda a, b: a // b}[type(n.op)](
                        ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        raise ValueError("non-arithmetic")

    try:
        return ev(node)
    except Exception:
        return None


def parse_budget_table(md_text):
    """Find the 'Test budget' section table; return
    (row_sum, stated_total, per_row_mismatches) — any may be None/empty."""
    m = re.search(r"^#{1,4}[^\n]*[Bb]udget[^\n]*\n", md_text, re.M)
    if not m:
        return None, None, []
    # section body: until next heading of same-or-higher level... simplest:
    # scan forward for the first markdown table.
    body = md_text[m.end():]
    stop = re.search(r"^#{1,4}\s", body, re.M)
    if stop:
        body = body[:stop.start()]
    rows = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 3:
        return None, None, []
    data_rows = [r for r in rows[1:] if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)]
    row_sum, stated_total, mismatches = 0, None, []
    for r in data_rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        last = cells[-1]
        is_total = any("total" in c.lower() for c in cells[:-1]) or \
            bool(re.match(r"^\**\s*total", cells[0], re.I))
        if "=" in last:
            lhs, rhs = last.rsplit("=", 1)
            lv, rv = _eval_arith(lhs), _eval_arith(rhs)
            val = rv if rv is not None else lv
            if lv is not None and rv is not None and abs(lv - rv) > 1e-9:
                mismatches.append(f"row '{cells[0]}': {lhs.strip()} = {lv} "
                                  f"but claims {rhs.strip()}")
        else:
            val = _eval_arith(last)
        if val is None:
            mismatches.append(f"row '{cells[0]}': count cell '{last}' "
                              f"not arithmetic — skipped")
            continue
        if is_total:
            stated_total = val
        else:
            row_sum += val
    return row_sum, stated_total, mismatches


# ------------------------------------------------------- machine ledger

LEDGER_SECTIONS = ("obligations", "members", "witnesses", "pins",
                   "doors", "folds", "budget")


def fold_flat_members(raw, findings):
    """Machine ledgers keep members as a flat append list
    ([{obligation, member}]); fold them under their obligation for the
    canonical join view. Members nested directly in obligations (the
    rendered-YAML shape) are merged in as well."""
    flat = raw.get("members")
    if not isinstance(flat, list):
        return raw
    by_id = {}
    for o in raw.get("obligations") or []:
        if isinstance(o, dict) and o.get("id") is not None:
            by_id.setdefault(str(o["id"]), o)
    for i, m in enumerate(flat):
        if not isinstance(m, dict) or m.get("member") is None \
                or m.get("obligation") is None:
            findings.append(("entry-schema",
                             f"ledger.json members[{i}]: requires "
                             f"'obligation' and 'member'"))
            continue
        o = by_id.get(str(m["obligation"]))
        if o is None:
            findings.append(("entry-schema",
                             f"ledger.json members[{i}]: obligation "
                             f"'{m['obligation']}' has no obligations "
                             f"entry"))
            continue
        own = o.setdefault("members", [])
        if not isinstance(own, list):
            own = o["members"] = [own]
        own.append(m["member"])
    return raw


def entry_schema_audit(raw, source):
    """Per-entry required fields — a structurally-valid section can
    carry entries that silently lack the fields the join needs.
    (witness: 'test' path; pin: unit, input, clause_absent,
    conforming_attempt; fold: obligation, member, fold_into, reason;
    door: unit, member.)"""
    findings = []
    for i, w in enumerate(raw.get("witnesses") or []):
        if not isinstance(w, dict) or not str(
                w.get("test") or "").strip():
            findings.append(("entry-schema",
                             f"{source}: witnesses[{i}] requires a "
                             f"'test' path"))
    for i, p in enumerate(raw.get("pins") or []):
        if not isinstance(p, dict):
            findings.append(("entry-schema",
                             f"{source}: pins[{i}] is not a mapping"))
            continue
        for k in ("unit", "input", "clause_absent",
                  "conforming_attempt"):
            if p.get(k) in (None, ""):
                findings.append(("entry-schema",
                                 f"{source}: pin '{p.get('id', i)}' "
                                 f"requires '{k}'"))
    for i, f in enumerate(raw.get("folds") or []):
        if not isinstance(f, dict):
            findings.append(("entry-schema",
                             f"{source}: folds[{i}] is not a mapping"))
            continue
        for k in ("obligation", "member", "fold_into", "reason"):
            if f.get(k) in (None, ""):
                findings.append(("entry-schema",
                                 f"{source}: folds[{i}] requires "
                                 f"'{k}'"))
    for i, d in enumerate(raw.get("doors") or []):
        if not isinstance(d, dict):
            findings.append(("entry-schema",
                             f"{source}: doors[{i}] is not a mapping"))
            continue
        for k in ("unit", "member"):
            if d.get(k) in (None, ""):
                findings.append(("entry-schema",
                                 f"{source}: doors[{i}] requires "
                                 f"'{k}'"))
    return findings


def load_machine_ledger(run_dir, findings):
    """(raw_or_None, is_machine). When <run_dir>/ledger.json exists it
    is authoritative — the fenced block is only its rendered snapshot.
    Corrupt JSON returns raw=None with is_machine=True (the corrupt
    machine file cannot be silently skipped back to the snapshot);
    schema-completeness findings are appended for every absent
    section."""
    if not run_dir:
        return None, False
    path = os.path.join(run_dir, "ledger.json")
    if not os.path.isfile(path):
        return None, False
    try:
        raw = json.load(open(path, encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        findings.append((
            "ledger-corrupt",
            f"ledger.json is not parseable JSON ({e}) — the machine "
            f"ledger is authoritative; regenerate it with "
            f"ledger_entry.py"))
        return None, True
    if not isinstance(raw, dict):
        findings.append(("ledger-corrupt",
                         "ledger.json: top level is not a mapping"))
        return None, True
    for sec in LEDGER_SECTIONS:
        if sec == "members":
            if "members" not in raw and not any(
                    isinstance(o, dict) and isinstance(
                        o.get("members"), list)
                    for o in raw.get("obligations") or []):
                findings.append(("ledger-missing-section",
                                 "ledger.json has no 'members' section "
                                 "(flat list or obligation.members)"))
            continue
        if sec not in raw:
            findings.append(("ledger-missing-section",
                             f"ledger.json has no '{sec}' section"))
    return fold_flat_members(raw, findings), True


# ---------------------------------------------------------------------- main

def reconcile(md_text, tests_dir=None, src_dirs=None, run_dir=None,
              metrics_path=None):
    findings = []   # (category, message)
    blocks = extract_fenced(md_text, "ledger")
    source = None
    raw, machine = load_machine_ledger(run_dir, findings)
    if machine:
        if raw is None:
            return {}, findings            # ledger-corrupt is fatal
        source = "ledger.json"
        findings.extend(entry_schema_audit(raw, source))
    else:
        if not blocks:
            return None, findings
        if len(blocks) > 1:
            findings.append(("format", f"{len(blocks)} ```ledger blocks "
                                       f"found; reconciling the first"))
        try:
            raw, orphans = load_ledger_full(blocks[0])
        except Exception as e:
            findings.append(("ledger-corrupt",
                             f"ledger block failed to parse: {e} — the "
                             f"hand-written block is corrupt; rebuild "
                             f"the ledger with ledger_entry.py"))
            return {}, findings
        source = "```ledger"
        if orphans:
            findings.append(("ledger-corrupt",
                             f"stray non-YAML fragment inside the "
                             f"```ledger block: '{orphans[0][:70]}' — "
                             f"the block is corrupt ({len(orphans) - 1}"
                             f" further line(s) past it were dropped); "
                             f"rebuild it with ledger_entry.py"))
        findings.extend(entry_schema_audit(raw, source))
    ledger, errors = normalize(raw)
    if ledger is None:
        findings.append(("format", errors[0]))
        return {}, findings
    for e in errors:
        findings.append(("format", e))

    ob_by_id = {}
    for o in ledger["obligations"]:
        if o["id"] in ob_by_id:
            findings.append(("format", f"duplicate obligation id '{o['id']}'"))
        ob_by_id[o["id"]] = o

    wit_names = [w["test"] for w in ledger["witnesses"]]
    wit_tails = {tail_name(t) for t in wit_names}
    wit_bases = {base_name(t) for t in wit_tails}

    # -- join at member granularity -------------------------------------
    witnessed = {}          # (ob_id, member_key) -> [test]
    listed = {}             # (ob_id, member_key) -> times listed in obligations
    for o in ledger["obligations"]:
        for m in o["members"]:
            k = (o["id"], member_key(m))
            listed[k] = listed.get(k, 0) + 1
    for (oid, mk), n in listed.items():
        if n > 1:
            findings.append(("dup-member",
                             f"obligation '{oid}' lists member '{mk}' "
                             f"{n} times"))
    for w in ledger["witnesses"]:
        covered_any = False
        seen = {}               # (ob_id, member_key) -> times this witness lists it
        for c in w["covers"]:
            if not isinstance(c, dict) or "obligation" not in c:
                findings.append(("format",
                                 f"witness '{w['test']}': cover entry not a "
                                 f"mapping with 'obligation'"))
                continue
            oid = str(c["obligation"])
            if oid not in ob_by_id:
                findings.append(("dangling-cover",
                                 f"witness '{w['test']}' covers unknown "
                                 f"obligation '{oid}'"))
                continue
            o = ob_by_id[oid]
            members = c.get("members")
            if members is None:          # shorthand: covers all members
                members = o["members"]
            elif not isinstance(members, list):
                members = [members]
            known = {member_key(m) for m in o["members"]}
            for mm in members:
                mk = member_key(mm)
                seen[(oid, mk)] = seen.get((oid, mk), 0) + 1
                if mk not in known:
                    findings.append(("dangling-cover",
                                     f"witness '{w['test']}' cites member "
                                     f"'{mk}' not in obligation '{oid}'"))
                    continue
                witnessed.setdefault((oid, mk), []).append(w["test"])
                covered_any = True
        for (oid, mk), n in seen.items():
            if n > 1:
                findings.append(("dup-member",
                                 f"witness '{w['test']}' lists member "
                                 f"'{mk}' of obligation '{oid}' {n} times"))
        if not covered_any:
            findings.append(("redundant-test",
                             f"witness '{w['test']}' covers no obligation "
                             f"member — redundant or mis-keyed"))

    # -- minimality: sole-coverer ---------------------------------------
    n_coverers = {k: len(set(v)) for k, v in witnessed.items()}
    covers_of = {}              # test -> {(ob_id, member_key)}
    for k, tests in witnessed.items():
        for t in set(tests):
            covers_of.setdefault(t, set()).add(k)
    for w in ledger["witnesses"]:
        mine = covers_of.get(w["test"], set())
        if not mine:
            continue            # covers nothing -> redundant-test above
        if all(n_coverers[k] > 1 for k in mine):
            findings.append(("subsumed-witness",
                             f"witness '{w['test']}': every member it "
                             f"covers is also covered by another witness "
                             f"— redundancy candidate"))

    folded = {}
    for f in ledger["folds"]:
        oid, mk = f["obligation"], member_key(f["member"])
        o = ob_by_id.get(oid)
        if o is None:
            findings.append(("dangling-fold",
                             f"fold cites unknown obligation '{oid}'"))
            continue
        if mk not in {member_key(m) for m in o["members"]}:
            findings.append(("dangling-fold",
                             f"fold cites member '{mk}' not in "
                             f"obligation '{oid}'"))
        tgt = f["fold_into"]
        if tail_name(tgt) not in wit_tails and base_name(tail_name(tgt)) \
                not in wit_bases:
            findings.append(("dangling-fold",
                             f"fold of '{oid}'/'{mk}' names witness "
                             f"'{tgt}' which is not in witnesses"))
        else:
            folded[(oid, mk)] = tgt

    for o in ledger["obligations"]:
        for m in o["members"]:
            mk = member_key(m)
            if (o["id"], mk) not in witnessed and (o["id"], mk) not in folded:
                findings.append(("hole",
                                 f"{o['id']}[{member_label(m)}]: no witness, "
                                 f"no declared fold"))
        if o["members"] and not any(
                (o["id"], member_key(m)) in witnessed
                or (o["id"], member_key(m)) in folded
                for m in o["members"]):
            findings.append(("unreferenced-obligation",
                             f"obligation '{o['id']}': no member is witnessed "
                             f"or folded — the row is dead"))

    # -- collected-vs-declared, both directions --------------------------
    collected = None
    if tests_dir:
        collected, err = collect_tests(tests_dir)
        if err:
            findings.append(("collect-error", err))
        else:
            col_tails = set(collected)
            col_bases = {base_name(t) for t in col_tails}
            for t in col_tails:
                if t not in wit_tails and base_name(t) not in wit_bases:
                    findings.append(("unanchored-test",
                                     f"collected '{t}' has no witness entry"))
            for w in wit_tails:
                if w not in col_tails and base_name(w) not in col_bases:
                    findings.append(("phantom-witness",
                                     f"witness '{w}' not in collected suite "
                                     f"(name drift?)"))

    # -- static witness⇄suite join (r37 phantom-witness seal) -----------
    # The --tests join runs a live pytest collection; Java runs and
    # unexecuted suites need the same join against STATICALLY
    # discovered tests (junit//tests/ dirs under the run dir, or the
    # --tests dir when pytest itself failed). cv_r37 minted 52
    # `~covN`-suffixed pseudo-witnesses — real base names plus a
    # synthetic tag — to pass witness-starvation; every witness.test
    # ref must resolve to a discovered (file, method), else phantom.
    test_index = []
    if collected is None:
        disc_dirs = []
        if tests_dir:
            disc_dirs.append(tests_dir)
        elif run_dir:
            disc_dirs += [os.path.join(run_dir, d)
                          for d in TEST_DIR_NAMES]
        test_index = discover_test_index(disc_dirs, run_dir)
        if test_index:
            for w in ledger["witnesses"]:
                t = w.get("test")
                if not t or resolve_witness(t, test_index):
                    continue
                note = (" — synthetic '~covN' pseudo-witness"
                        if PSEUDO_WITNESS_RE.search(str(t)) else "")
                findings.append((
                    "phantom-witness",
                    f"witness '{t}' resolves to no discovered test "
                    f"(file+function) under {disc_dirs}{note}"))

    # -- arithmetic ------------------------------------------------------
    budget = ledger["budget"]
    n_wit = len(ledger["witnesses"])
    sums = {"budget": budget, "witnesses": n_wit}
    if collected is not None:
        sums["collected"] = len(set(collected))
    row_sum, stated_total, mismatches = parse_budget_table(md_text)
    for mm in mismatches:
        findings.append(("budget-table", mm))
    if row_sum is not None:
        sums["budget-table-rows"] = row_sum
    if stated_total is not None:
        sums["stated-total"] = stated_total
    if isinstance(budget, (int, float)):
        for k, v in sums.items():
            if k == "budget" or not isinstance(v, (int, float)):
                continue
            if v != budget:
                findings.append(("sum-mismatch",
                                 f"budget={int(budget)} but {k}={int(v)}"))
    elif budget is not None:
        findings.append(("format", f"budget '{budget}' is not a number"))

    # -- member-census floors + member-packing seal (r30/r31/r34) ------
    # A suite whose member total is implausibly low vs the source's
    # public-API surface hid behind the language-blind checkers
    # (cli_r30 shipped 61 members over ~350 public Java methods;
    # validators_r31 shipped 110 members / 23 witnesses over ~140
    # public Python units). validators_r34 then packed ~70 units into
    # ~10 space-joined member strings so the member-STRING count hit
    # the floor on 34 entries over 12 tests — the census therefore
    # counts DISCRETE members: a member spelling >=PACK_MEMBER_UNITS
    # distinct public units is a bundle minting no (unit,
    # input-class) pair (member-packing audit above the floors).
    n_members = sum(len(o["members"]) for o in ledger["obligations"])
    n_wit = len(ledger["witnesses"])
    java_public = py_public = n_discrete = None
    if src_dirs:
        py_files, java_files, pycache_dirs = tree_source_files(src_dirs)
        unit_names = set()
        if len(java_files) > len(py_files):
            java_public, unit_names = java_public_surface(java_files)
        elif len(py_files) > len(java_files):
            py_public, unit_names = python_public_surface(py_files)
        n_discrete = n_members
        index = unit_index(unit_names)
        if index:
            n_discrete, pack_findings = member_packing_audit(
                ledger["obligations"], index)
            findings.extend(pack_findings)
        if java_public is not None:
            floor = -(-java_public // JAVA_MEMBER_RATIO)
            if java_public and n_discrete < floor:
                findings.append((
                    "java-census-floor",
                    f"{n_discrete} discrete obligation members "
                    f"({n_members} enumerated) vs {java_public} "
                    f"public methods under --src (floor {floor}: >=1 "
                    f"member per {JAVA_MEMBER_RATIO} public methods) — "
                    f"implausibly thin suite for the API surface"))
            # bridge seal: python planted in a Java source tree exists
            # only to feed the Python checkers (cv_r31 coverage_anchor.py)
            for p in py_files:
                findings.append((
                    "bridge-artifact",
                    f"'{p}': .py file inside a Java --src tree — the "
                    f"audited source must not carry checker-bridge "
                    f"artifacts"))
            for p in pycache_dirs:
                findings.append((
                    "bridge-artifact",
                    f"'{p}': __pycache__ inside a Java --src tree — "
                    f"residue of planted python bridge code"))
        elif py_public is not None:
            floor = -(-py_public // PY_MEMBER_RATIO)
            if py_public and n_discrete < floor:
                findings.append((
                    "python-census-floor",
                    f"{n_discrete} discrete obligation members "
                    f"({n_members} enumerated) vs {py_public} "
                    f"public units under --src (floor {floor}: >=1 "
                    f"member per {PY_MEMBER_RATIO} public units) — "
                    f"implausibly thin suite for the API surface"))

        # -- covers-false seal (r38): a witness's `covers` member list
        # must name units the named test actually exercises — join each
        # covered member's unit token against the test's executed call
        # graph. val_r38's one-witness-per-item bookkeeping cited
        # members/units the tests never touch (0/502 real coverage).
        if unit_names:
            if not test_index and run_dir:
                disc = ([tests_dir] if tests_dir else
                        [os.path.join(run_dir, d)
                         for d in TEST_DIR_NAMES])
                test_index = discover_test_index(disc, run_dir)
            vocab = set(unit_names)
            if java_public is not None:
                vocab |= java_type_names(java_files)
            findings.extend(covers_truth_audit(
                ledger, test_index, vocab))

    # -- min-witness floor ----------------------------------------------
    # Enumerated members assert nothing by themselves: a ledger that
    # mints members far faster than witnesses is capacity-collapse
    # (validators_r31: 110 members on 23 grab-bag tests).
    if n_members:
        wfloor = -(-n_members // WITNESS_MEMBER_RATIO)
        if n_wit < wfloor:
            findings.append((
                "witness-starvation",
                f"{n_wit} witnesses for {n_members} obligation members "
                f"(floor {wfloor}: >=1 witness per "
                f"{WITNESS_MEMBER_RATIO} members) — suite too thin for "
                f"the enumerated surface"))
        if len(witnessed) < WITNESS_COVER_FRACTION * n_members:
            findings.append((
                "witness-starvation",
                f"{len(witnessed)}/{n_members} members appear in "
                f"witness covers (<{WITNESS_COVER_FRACTION:.0%}) — the "
                f"rest live only in folds"))

    # -- coverage-config + metrics seals --------------------------------
    warnings = []
    if run_dir:
        corpus = member_corpus(raw, ledger["obligations"])
        findings.extend(audit_coverage_config(run_dir, corpus))
        mpath = metrics_path or os.path.join(run_dir, "metrics.json")
        if os.path.isfile(mpath):
            texts = [md_text]
            try:
                texts.append(open(mpath, encoding="utf-8",
                                  errors="replace").read())
            except OSError:
                pass
            jf = os.path.join(run_dir, "journal.txt")
            if os.path.isfile(jf):
                try:
                    texts.append(open(jf, encoding="utf-8",
                                      errors="replace").read())
                except OSError:
                    pass
            findings.extend(audit_metrics(mpath, n_wit, texts))
            # r37: metrics.json numbers are claims to re-verify, not
            # truth — counts vs a fresh collection/census, compile
            # claims vs mvn test-compile, pass/fail vs surefire
            # reports. Absent toolchains degrade to WARN.
            try:
                metrics_obj = json.load(open(
                    mpath, encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                metrics_obj = None
            if isinstance(metrics_obj, dict):
                if not test_index:
                    disc = ([tests_dir] if tests_dir else
                            [os.path.join(run_dir, d)
                             for d in TEST_DIR_NAMES])
                    test_index = discover_test_index(disc, run_dir)
                mt_f, mt_w = audit_metrics_truth(
                    run_dir, metrics_obj, texts, test_index,
                    len(set(collected)) if collected is not None
                    else None)
                findings.extend(mt_f)
                warnings.extend(mt_w)

    return {"ledger": ledger, "sums": sums, "collected": collected,
            "java_public": java_public, "py_public": py_public,
            "n_discrete": n_discrete, "source": source,
            "warnings": warnings}, findings


def main():
    ap = argparse.ArgumentParser(
        description="Reconcile the ```ledger block of a TEST_DESIGN.md "
                    "against itself and (optionally) the collected suite.")
    ap.add_argument("design", help="path to TEST_DESIGN.md")
    ap.add_argument("--tests", help="tests dir for pytest --collect-only")
    ap.add_argument("--src", action="append", default=[],
                    help="implementation source dir(s); enables the "
                         "member-census floor and the bridge-artifact "
                         "seal (Java census on .java-majority trees, "
                         "Python census on .py-majority trees)")
    ap.add_argument("--metrics", help="metrics.json path for the "
                                    "collected-vs-witnesses divergence "
                                    "seal (default: <design dir>/metrics.json)")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()
    try:
        md_text = open(args.design, encoding="utf-8").read()
    except OSError as e:
        print(f"error: cannot read {args.design}: {e}")
        return 2

    src_dirs = [d for d in args.src if os.path.isdir(d)]
    run_dir = os.path.dirname(os.path.abspath(args.design))
    result, findings = reconcile(md_text, args.tests, src_dirs,
                                 run_dir=run_dir,
                                 metrics_path=args.metrics)
    print(f"ledger_reconcile: {args.design}")
    if result is None:
        print("  no ledger.json or ```ledger block found — nothing to "
              "reconcile (skill requires the ledger; absence is a doc "
              "gap, not a checker finding)")
        return 0

    if result.get("ledger"):
        ledger, sums, collected = (result["ledger"], result["sums"],
                                   result["collected"])
        n_members = sum(len(o["members"]) for o in ledger["obligations"])
        print(f"  source={result.get('source')}")
        print(f"  obligations={len(ledger['obligations'])} "
              f"members={n_members} witnesses={len(ledger['witnesses'])} "
              f"folds={len(ledger['folds'])} budget={sums['budget']}")
        if collected is not None:
            print(f"  collected={len(set(collected))} items")
        discrete = result.get("n_discrete")
        dsc = (f" discrete={discrete}"
               if discrete is not None and discrete != n_members else "")
        if result.get("java_public") is not None:
            floor = -(-result["java_public"] // JAVA_MEMBER_RATIO)
            print(f"  java public-api={result['java_public']} "
                  f"member-floor={floor} (members={n_members}{dsc})")
        if result.get("py_public") is not None:
            floor = -(-result["py_public"] // PY_MEMBER_RATIO)
            print(f"  python public-api={result['py_public']} "
                  f"member-floor={floor} (members={n_members}{dsc})")
        if "budget-table-rows" in sums:
            print(f"  budget-table: rows sum={sums['budget-table-rows']}"
                  + (f" stated-total={sums['stated-total']}"
                     if sums.get("stated-total") is not None else ""))

    for cat, msg in (result or {}).get("warnings", []):
        print(f"  [WARN] {cat}: {msg}")
    if not findings:
        print("  OK — ledger reconciles")
        return 0
    by_cat = {}
    for cat, msg in findings:
        by_cat.setdefault(cat, []).append(msg)
    for cat in sorted(by_cat):
        print(f"\n  [{cat}] ({len(by_cat[cat])})")
        for msg in by_cat[cat]:
            print(f"    - {msg}")
    if args.json:
        json.dump({"design": args.design, "sums": sums,
                   "warnings": [{"category": c, "msg": m} for c, m in
                                (result or {}).get("warnings", [])],
                   "findings":
                   [{"category": c, "msg": m} for c, m in findings]},
                  open(args.json, "w"), indent=1)
        print(f"\n  json -> {args.json}")
    print(f"\n  FAIL — {len(findings)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
