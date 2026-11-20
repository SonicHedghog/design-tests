#!/usr/bin/env python3
"""Obligation-ledger reconciler for TEST_DESIGN.md. Stdlib only
(uses PyYAML when importable, else a minimal parser for the
restricted ledger shape).

Usage: ledger_reconcile.py TEST_DESIGN.md [--tests DIR] [--json out.json]

The skill requires TEST_DESIGN.md to embed a fenced ```ledger block:

    ```ledger
    obligations: [{id, kind, members: [...]}]
    witnesses:   [{test, covers: [{obligation, members: [...]}]}]
    folds:       [{obligation, member, fold_into, reason}]
    budget: N
    ```

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
  * budget == #witness entries == #collected items (when measured) ==
    sum of the TEST_DESIGN budget-table rows (when a table is found)

Exit: 0 clean (incl. clean "no ledger block" diagnostic), 1 findings,
2 usage/fatal error (input file unreadable).
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys

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
    lines = []
    for raw in text.split("\n"):
        t = _strip_comment(raw)
        if not t.strip():
            continue
        indent = len(t) - len(t.lstrip())
        lines.append((indent, t.lstrip()))
    if not lines:
        return None
    obj, _ = _parse_block(lines, 0)
    return obj


def load_ledger(block_text):
    if yaml is not None:
        return yaml.safe_load(block_text)
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


# ---------------------------------------------------------------------- main

def reconcile(md_text, tests_dir=None):
    findings = []   # (category, message)
    blocks = extract_fenced(md_text, "ledger")
    if not blocks:
        return None, findings
    if len(blocks) > 1:
        findings.append(("format", f"{len(blocks)} ```ledger blocks found; "
                                   f"reconciling the first"))
    try:
        raw = load_ledger(blocks[0])
    except Exception as e:
        findings.append(("format", f"ledger block failed to parse: {e}"))
        return {}, findings
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

    return {"ledger": ledger, "sums": sums, "collected": collected}, findings


def main():
    ap = argparse.ArgumentParser(
        description="Reconcile the ```ledger block of a TEST_DESIGN.md "
                    "against itself and (optionally) the collected suite.")
    ap.add_argument("design", help="path to TEST_DESIGN.md")
    ap.add_argument("--tests", help="tests dir for pytest --collect-only")
    ap.add_argument("--json", help="write machine-readable findings JSON")
    args = ap.parse_args()
    try:
        md_text = open(args.design, encoding="utf-8").read()
    except OSError as e:
        print(f"error: cannot read {args.design}: {e}")
        return 2

    result, findings = reconcile(md_text, args.tests)
    print(f"ledger_reconcile: {args.design}")
    if result is None:
        print("  no ```ledger block found — nothing to reconcile "
              "(skill requires this block; absence is a doc gap, "
              "not a checker finding)")
        return 0

    ledger, sums, collected = (result["ledger"], result["sums"],
                               result["collected"])
    n_members = sum(len(o["members"]) for o in ledger["obligations"])
    print(f"  obligations={len(ledger['obligations'])} "
          f"members={n_members} witnesses={len(ledger['witnesses'])} "
          f"folds={len(ledger['folds'])} budget={sums['budget']}")
    if collected is not None:
        print(f"  collected={len(set(collected))} items")
    if "budget-table-rows" in sums:
        print(f"  budget-table: rows sum={sums['budget-table-rows']}"
              + (f" stated-total={sums['stated-total']}"
                 if sums.get("stated-total") is not None else ""))

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
        json.dump({"design": args.design, "sums": sums, "findings":
                   [{"category": c, "msg": m} for c, m in findings]},
                  open(args.json, "w"), indent=1)
        print(f"\n  json -> {args.json}")
    print(f"\n  FAIL — {len(findings)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
