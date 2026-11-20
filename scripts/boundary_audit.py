#!/usr/bin/env python3
"""Boundary-witness audit — verify mode for boundaries.py semantics.
Stdlib only (PyYAML / ledger_reconcile.py used for ledger parsing when
available).

Usage: boundary_audit.py --design TEST_DESIGN.md [--tests DIR]
                         [--spec boundaries.json] [--verify] [--dump]

Boundary entries (name, bound, operator, unit) are gathered from:
  * ```ledger obligations with kind: boundary
    ({id, kind: boundary, name, bound, operator, unit, members})
  * a fenced ```boundaries block in the design doc (boundaries.py spec
    shape — YAML or JSON list of domain specs)
  * a markdown table whose header names name/bound/operator columns
  * --spec JSON file in the boundaries.py domain-spec shape
    (min/max/min_exclusive/max_exclusive/len_min/len_max map to
    >=,<= / >,< operator-bound pairs)

Required witness sides per operator (robust BVA on the domain's
smallest unit):
    >=, <=, == : below + at + above
    >          : at(invalid) + above
    <          : below + at(invalid)
    !=         : at(invalid) + one of below|above

A side counts as witnessed when a ledger witness's covers list names
the boundary obligation with a member spelling that side ('below',
'at', 'above', 'under', 'over', 'edge', 'min', 'max', ...), or a test
function name cites the boundary name/id plus a side keyword.

TRANSFORM-COLLAPSE: when a boundary obligation involves a
validate-then-transform bound (a `transform: round|clamp|coerce|...`
key on the ledger obligation, or the obligation id/name/text mentions
rounding, clamping, coercion, normalization, truncation), the entry
additionally requires a member strictly INSIDE the collapse interval —
a value that passes the guard pre-transform but lands on or past the
rejected bound post-transform. A member witnesses this by spelling it
('collapse', 'straddle', 'rounds-to-bound', 'pre-transform', ...) or,
for the computable transforms round/floor/ceil/trunc/int, by being a
numeric member value that evaluates inside the interval. Test names
citing the boundary plus a collapse word also count.

Exit: 0 clean (incl. "no boundary entries" diagnostic), 1 findings,
2 usage error.
"""
import argparse
import ast
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger_reconcile import extract_fenced, load_ledger
except Exception:
    extract_fenced = load_ledger = None

try:
    import yaml
except ImportError:
    yaml = None

SIDE_WORDS = {
    "below": re.compile(r"(?<![a-z])(below|under|lower|less|lt|min-1|"
                        r"minus|underflow|beneath|just-under)(?![a-z])", re.I),
    "above": re.compile(r"(?<![a-z])(above|over|greater|gt|plus|exceed|"
                        r"overflow|beyond|upper|just-over)(?![a-z])", re.I),
    "at": re.compile(r"(?<![a-z])(at|on|edge|exact|equal|bound(?:ary)?|"
                     r"limit|min|max)(?![a-z])", re.I),
}

# operator -> list of acceptable-side groups (group satisfied by ANY member)
REQUIRED = {
    ">=": [["below"], ["at"], ["above"]],
    "<=": [["below"], ["at"], ["above"]],
    "==": [["below"], ["at"], ["above"]],
    "=":  [["below"], ["at"], ["above"]],
    ">":  [["at"], ["above"]],
    "<":  [["below"], ["at"]],
    "!=": [["at"], ["below", "above"]],
}


def side_of(text):
    """Classify a member/test-name spelling to a side, or None.
    Explicit direction words win over positional words ('at'/'min')."""
    if not isinstance(text, str):
        text = str(text)
    if SIDE_WORDS["below"].search(text):
        return "below"
    if SIDE_WORDS["above"].search(text):
        return "above"
    if SIDE_WORDS["at"].search(text):
        return "at"
    return None


# ------------------------------------------------------- transform-collapse

TRANSFORM_HINT = re.compile(
    r"round|clamp|coerc|normaliz|transform|trunc|floor|ceil|collapse|"
    r"cast", re.I)

# member/test-name spellings that mean "inside the collapse interval":
# passes the guard pre-transform, lands on/over the bound post-transform
COLLAPSE_RE = re.compile(
    r"collapse|straddle|pre-?transform|post-?transform|"
    r"inside-?(?:the-)?(?:collapse-?)?interval|between-?(?:the-)?domains?|"
    r"(?:round|clamp|coerce|normaliz|trunc|transform|cast)\w*-?"
    r"(?:to|into|onto|at|past|over|toward|across)-?"
    r"(?:the-)?(?:bound|edge|limit|reject|cut|boundary)",
    re.I)


def detect_transform(entry, raw=None):
    """Transform name for a boundary entry, or None. An explicit
    `transform:` key wins; else the entry's id/name (plus free-text
    obligation fields) are scanned for a transform verb."""
    if raw and isinstance(raw, dict):
        t = raw.get("transform")
        if t:
            return str(t) if not isinstance(t, bool) else "transform"
        for k in ("note", "notes", "description", "text", "guard",
                  "reason", "comment", "bound"):
            v = raw.get(k)
            if isinstance(v, str):
                m = TRANSFORM_HINT.search(v)
                if m:
                    return m.group(0).lower()
    for k in ("id", "name"):
        m = TRANSFORM_HINT.search(str(entry.get(k) or ""))
        if m:
            return m.group(0).lower()
    return None


def _apply_transform(name, x):
    """post-transform value for the computable transforms; None when
    the transform's semantics aren't mechanically evaluable."""
    n = str(name).lower()
    try:
        if "floor" in n:
            return math.floor(x)
        if "ceil" in n:
            return math.ceil(x)
        if "trunc" in n or "int(" in n or n == "int":
            return math.trunc(x)
        if "round" in n:
            return round(x)
    except (ValueError, OverflowError):
        return None
    return None                     # clamp/coerce/normalize: needs bounds


def _guard_holds(op, x, bound):
    try:
        b = float(bound)
    except (TypeError, ValueError):
        return None
    return {">=": x >= b, "<=": x <= b, ">": x > b, "<": x < b,
            "==": x == b, "=": x == b, "!=": x != b}.get(op)


def _numeric_member(m):
    """A member that IS a number (scalar, dict value, or a spelling
    that is exactly a numeric literal); None otherwise."""
    if isinstance(m, bool):
        return None
    if isinstance(m, (int, float)):
        return float(m)
    if isinstance(m, dict):
        for k in ("value", "x", "input", "at", "member"):
            v = m.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        for k in ("value", "member", "name", "id"):
            v = m.get(k)
            if isinstance(v, str):
                try:
                    return float(v.strip())
                except ValueError:
                    pass
        return None
    if isinstance(m, str):
        try:
            return float(m.strip())
        except ValueError:
            return None
    return None


def is_collapse_member(m, entry):
    """True when member m plausibly sits inside the collapse interval:
    spells it, or (for a computable transform) numerically passes the
    guard pre-transform while its post-transform image lands on the
    bound or fails the guard."""
    key = member_key(m)
    if COLLAPSE_RE.search(key):
        return True
    x = _numeric_member(m)
    if x is None:
        return False
    post = _apply_transform(entry.get("transform"), x)
    if post is None or post == x:
        return False
    pre = _guard_holds(entry.get("operator"), x, entry.get("bound"))
    if pre is not True:
        return False
    b = None
    try:
        b = float(entry.get("bound"))
    except (TypeError, ValueError):
        pass
    return (b is not None and post == b) or \
        _guard_holds(entry.get("operator"), post,
                     entry.get("bound")) is False


# ------------------------------------------------------------ entry parsing

def _entry(eid, name, bound, op, unit, members=None, src="?",
           transform=None):
    return {"id": str(eid), "name": str(name if name is not None else eid),
            "bound": bound, "operator": str(op) if op else None,
            "unit": unit, "members": members or [], "src": src,
            "transform": transform}


def entries_from_ledger(md_text, errors):
    if extract_fenced is None or load_ledger is None:
        return []
    blocks = extract_fenced(md_text, "ledger")
    if not blocks:
        return []
    try:
        led = load_ledger(blocks[0])
    except Exception as e:
        errors.append(f"ledger block unparseable for boundary scan: {e}")
        return []
    out = []
    for o in (led or {}).get("obligations") or []:
        if not isinstance(o, dict):
            continue
        if str(o.get("kind", "")).lower() not in ("boundary", "bound", "bva"):
            continue
        out.append(_entry(
            o.get("id"), o.get("name"), o.get("bound", o.get("value")),
            o.get("operator", o.get("op")), o.get("unit", o.get("type")),
            members=o.get("members") or [], src="ledger",
            transform=o.get("transform")))
        if out[-1]["transform"] is None:
            out[-1]["transform"] = detect_transform(out[-1], raw=o)
    return out, led


def entries_from_spec(spec, src):
    """boundaries.py domain-spec entries -> (bound, operator) pairs."""
    out = []
    for p in spec or []:
        if not isinstance(p, dict) or "name" not in p:
            continue
        name = p["name"]
        if p.get("min") is not None:
            out.append(_entry(f"{name}:min", name, p["min"],
                              ">" if p.get("min_exclusive") else ">=",
                              p.get("type"), src=src))
        if p.get("max") is not None:
            out.append(_entry(f"{name}:max", name, p["max"],
                              "<" if p.get("max_exclusive") else "<=",
                              p.get("type"), src=src))
        if p.get("len_min") is not None:
            out.append(_entry(f"{name}.len:min", f"{name} length",
                              p["len_min"], ">=", "len", src=src))
        if p.get("len_max") is not None:
            out.append(_entry(f"{name}.len:max", f"{name} length",
                              p["len_max"], "<=", "len", src=src))
    return out


def entries_from_fenced(md_text, errors):
    out = []
    for blk in extract_fenced(md_text, "boundaries") if extract_fenced else []:
        spec = None
        try:
            spec = json.loads(blk)
        except Exception:
            if load_ledger is not None:
                try:
                    spec = load_ledger(blk)
                except Exception as e:
                    errors.append(f"```boundaries block unparseable: {e}")
        if isinstance(spec, dict):
            spec = spec.get("domains") or spec.get("boundaries") or [spec]
        if isinstance(spec, list):
            out += entries_from_spec(spec, "fenced-boundaries")
    return out


def entries_from_table(md_text):
    """Markdown table with name|bound|operator|unit-ish headers."""
    out = []
    rows = [ln for ln in md_text.splitlines() if ln.strip().startswith("|")]
    i = 0
    while i < len(rows):
        hdr = [c.strip().lower() for c in rows[i].strip().strip("|").split("|")]
        idx_name = next((j for j, h in enumerate(hdr) if "name" in h or
                         h in ("id", "param", "bound-id")), None)
        idx_bound = next((j for j, h in enumerate(hdr)
                          if h in ("bound", "value", "edge", "cut")), None)
        idx_op = next((j for j, h in enumerate(hdr)
                       if h in ("op", "operator", "relation")), None)
        idx_unit = next((j for j, h in enumerate(hdr)
                         if h in ("unit", "type", "domain")), None)
        idx_trf = next((j for j, h in enumerate(hdr)
                        if TRANSFORM_HINT.fullmatch(h)
                        or h == "transform"), None)
        if idx_name is None or (idx_bound is None and idx_op is None):
            i += 1
            continue
        j = i + 1
        if j < len(rows) and re.match(r"^\s*\|[\s:|-]+\|\s*$", rows[j]):
            j += 1
        while j < len(rows):
            cells = [c.strip().strip("`") for c in
                     rows[j].strip().strip("|").split("|")]
            if len(cells) <= max(x for x in (idx_name, idx_bound or 0,
                                             idx_op or 0, idx_unit or 0,
                                             idx_trf or 0)):
                break
            bound = cells[idx_bound] if idx_bound is not None else None
            try:
                bound = ast.literal_eval(bound) if bound else None
            except Exception:
                pass
            out.append(_entry(cells[idx_name], cells[idx_name], bound,
                              cells[idx_op] if idx_op is not None else None,
                              cells[idx_unit] if idx_unit is not None else None,
                              src="md-table",
                              transform=cells[idx_trf] or None
                              if idx_trf is not None else None))
            j += 1
        i = j
    return out


# ----------------------------------------------------------------- witnesses

def member_key(m):
    if isinstance(m, dict):
        for k in ("name", "id", "member", "value", "side"):
            if k in m:
                return str(m[k])
        return json.dumps(m, sort_keys=True)
    return str(m)


def ledger_citations(ledger):
    """(obligation-id -> set of sides cited by witness covers + folds,
    obligation-id -> raw member objects for collapse checks)."""
    cited, members_of = {}, {}
    for w in (ledger or {}).get("witnesses") or []:
        if not isinstance(w, dict):
            continue
        for c in w.get("covers") or []:
            if not isinstance(c, dict) or "obligation" not in c:
                continue
            oid = str(c["obligation"])
            members = c.get("members") or []
            if not isinstance(members, list):
                members = [members]
            for m in members:
                members_of.setdefault(oid, []).append(m)
                s = side_of(member_key(m))
                if s:
                    cited.setdefault(oid, set()).add(s)
        # also let the witness's own test name carry a side
        s = side_of(str(w.get("test", "")))
        if s:
            for c in w.get("covers") or []:
                if isinstance(c, dict) and "obligation" in c:
                    cited.setdefault(str(c["obligation"]), set()).add(s)
    for f in (ledger or {}).get("folds") or []:
        if not isinstance(f, dict):
            continue
        oid = str(f.get("obligation"))
        members_of.setdefault(oid, []).append(f.get("member"))
        s = side_of(member_key(f.get("member")))
        if s:
            cited.setdefault(oid, set()).add(s)
    return cited, members_of


def test_function_names(tests_dir):
    names = []
    for root, _, fns in os.walk(tests_dir):
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(root, fn),
                                      encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.append(node.name)
    return names


def name_citations(entries, test_names):
    """(boundary-id -> sides cited by test names mentioning name/id +
    side,  set of boundary-ids whose citing test names carry a
    collapse-interval word)."""
    cited, collapse = {}, set()
    for e in entries:
        tokens = set()
        for t in (e["name"], e["id"]):
            if t and len(str(t)) > 2:
                tokens.add(str(t).lower())
                tokens.add(re.sub(r"[:./]", "_", str(t)).lower())
        for tn in test_names:
            low = tn.lower()
            if not any(t in low for t in tokens):
                continue
            s = side_of(tn)
            if s:
                cited.setdefault(e["id"], set()).add(s)
            if COLLAPSE_RE.search(tn):
                collapse.add(e["id"])
    return cited, collapse


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Verify every enumerated boundary has below/at/above "
                    "witnesses per its operator.")
    ap.add_argument("--design", help="TEST_DESIGN.md to parse boundaries from")
    ap.add_argument("--tests", help="tests dir (test-name citations)")
    ap.add_argument("--spec", help="JSON domain-spec file (boundaries.py shape)")
    ap.add_argument("--verify", action="store_true",
                    help="explicit verify flag (this is the default mode)")
    ap.add_argument("--dump", action="store_true",
                    help="print parsed boundary entries and exit 0")
    args = ap.parse_args()
    if not args.design and not args.spec:
        ap.error("need --design and/or --spec")

    errors, entries, ledger = [], [], None
    if args.design:
        try:
            md_text = open(args.design, encoding="utf-8").read()
        except OSError as e:
            print(f"error: cannot read {args.design}: {e}")
            return 2
        got = entries_from_ledger(md_text, errors)
        if isinstance(got, tuple):
            entries += got[0]
            ledger = got[1]
        entries += entries_from_fenced(md_text, errors)
        entries += entries_from_table(md_text)
    if args.spec:
        try:
            spec = json.load(open(args.spec, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: cannot parse {args.spec}: {e}")
            return 2
        entries += entries_from_spec(spec, "spec-file")

    # dedupe by (id, bound, operator)
    seen, uniq = set(), []
    for e in entries:
        k = (e["id"], json.dumps(e["bound"]), e["operator"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    entries = uniq
    for e in entries:                    # hint from id/name when unset
        if e["transform"] is None:
            e["transform"] = detect_transform(e)

    print(f"boundary_audit: design={args.design} tests={args.tests} "
          f"spec={args.spec}")
    for e in errors:
        print(f"  warning: {e}")
    if not entries:
        print("  no boundary entries found — nothing to audit")
        return 0
    if args.dump:
        for e in entries:
            print(f"  {e['id']:24s} {e['operator'] or '?':3s} "
                  f"{e['bound']!r:10} unit={e['unit'] or '-'} "
                  f"transform={e['transform'] or '-'} "
                  f"members={e['members']} ({e['src']})")
        return 0

    led_cited, led_members = ledger_citations(ledger)
    test_names = test_function_names(args.tests) if args.tests else []
    tn_cited, tn_collapse = name_citations(entries, test_names)

    findings = []
    for e in entries:
        cited = set(led_cited.get(e["id"], ())) | set(
            tn_cited.get(e["id"], ()))
        # covers naming members verbatim (non-side spellings) also count:
        # member 'k' witnessed if it appears in covers — side resolved above
        req = REQUIRED.get(e["operator"] or "")
        if req is None:
            findings.append(f"{e['id']}: unknown operator "
                            f"'{e['operator']}' — cannot derive sides")
            continue
        missing = ["/".join(g) for g in req
                   if not any(s in cited for s in g)]
        if e["transform"] and not (
                e["id"] in tn_collapse or any(
                    is_collapse_member(m, e)
                    for m in led_members.get(e["id"], []))):
            missing.append("collapse-interior")
        tr = f" transform={e['transform']}" if e["transform"] else ""
        if not cited and not e["transform"]:
            findings.append(f"{e['id']} ({e['name']} {e['operator']} "
                            f"{e['bound']}): no witness at all "
                            f"(need {'+'.join('/'.join(g) for g in req)})")
        elif missing:
            findings.append(f"{e['id']} ({e['name']} {e['operator']} "
                            f"{e['bound']}{tr}): witnessed "
                            f"{sorted(cited)}, missing {missing}")
        else:
            print(f"  ok {e['id']} ({e['name']} {e['operator']} "
                  f"{e['bound']}{tr}): sides {sorted(cited)} [{e['src']}]")

    if findings:
        for f in findings:
            print(f"  HOLE: {f}")
        print(f"  FAIL — {len(findings)} finding(s)")
        return 1
    print("  OK — every boundary side witnessed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
