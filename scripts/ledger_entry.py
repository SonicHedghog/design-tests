#!/usr/bin/env python3
"""Machine-ledger entry API for TEST_DESIGN runs. Stdlib only.

Usage: ledger_entry.py RUN_DIR <command> [--json '{...}']

The ledger is <RUN_DIR>/ledger.json — a machine-authored mapping with
seven top-level sections:

    obligations: [{id, kind}]
    members:     [{obligation, member}]   flat append list; render()
                                        folds them under their
                                        obligation for the YAML form
    witnesses:   [{test, covers: [{obligation, members: [...]}]}]
    pins:        [{id, unit, input, observed, clause_quote,
                   clause_absent, conforming_attempt: {tried, result}}]
    doors:       [{unit, clause_id|clause, member, disposition|verdict,
                   reason?}]
    folds:       [{obligation, member, fold_into, reason}]
    budget:      N                        derived — len(witnesses),
                                          never typed by hand

Commands:

    add-obligation --json '{"id": "...", "kind": "..."}'
    add-member     --json '{"obligation": "...", "member": "..."}'
    add-witness    --json '{"test": "tests/t.py::test_x",
                            "covers": [{"obligation": "...", "members":
                                        ["..."]}]}'
    add-fold       --json '{"obligation": "...", "member": "...",
                            "fold_into": "tests/t.py::test_x",
                            "reason": "..."}'
    add-pin        --json '{"id": "...", "unit": "...", "input": "...",
                            "observed": "...",
                            "clause_quote": "...",
                            "clause_absent": "...",
                            "conforming_attempt": {"tried": "...",
                                                   "result": "pass"}}'
    add-door       --json '{"unit": "...", "clause_id": "...",
                            "member": "...", "disposition": "..."}'
    render                            print the fenced ```ledger YAML
                                      snapshot for TEST_DESIGN.md
    show                              print the raw ledger.json

Every add-* call validates its entry against the per-entry schema
BEFORE writing, then rewrites ledger.json atomically (tempfile +
os.replace) — a hand-edited YAML block can truncate or drop a section
silently; a JSON file written this way cannot. `budget` is derived
from the witness count on every write, so it can never go stale.

TEST_DESIGN.md embeds the `render` output verbatim — human-readable,
but generated, never hand-edited.

Exit: 0 clean, 1 schema rejection (nothing written), 2 usage/fatal.
"""
import argparse
import json
import os
import sys
import tempfile

SECTIONS = ("obligations", "members", "witnesses", "pins", "doors",
            "folds", "budget")


def ledger_path(run_dir):
    return os.path.join(run_dir, "ledger.json")


def empty_ledger():
    return {"obligations": [], "members": [], "witnesses": [],
            "pins": [], "doors": [], "folds": [], "budget": 0}


def load_ledger(run_dir):
    """Return (ledger, error). Missing file -> fresh ledger."""
    path = ledger_path(run_dir)
    if not os.path.isfile(path):
        return empty_ledger(), None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{path}: unparseable JSON ({e}) — fix or remove " \
                     f"the file; ledger_entry never truncates, so this " \
                     f"was hand-edited"
    if not isinstance(data, dict):
        return None, f"{path}: top level is not a mapping"
    base = empty_ledger()
    base.update(data)
    for sec in ("obligations", "members", "witnesses", "pins", "doors",
                "folds"):
        if base[sec] is None:
            base[sec] = []
        if not isinstance(base[sec], list):
            return None, f"{path}: '{sec}' is not a list"
    return base, None


def atomic_write(path, text):
    """tempfile + os.replace — readers never see a partial write."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".ledger-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------- validation
# Each validator returns an error string or None. The ledger-entry
# schema is the SHIP-side half of ledger_reconcile's entry-schema
# audit: entries rejected here can never reach the file.

def _need(entry, *keys):
    for k in keys:
        if entry.get(k) is None or entry.get(k) == "":
            return k
    return None


def valid_obligation(e):
    k = _need(e, "id")
    if k:
        return "obligation entry requires 'id'"
    if "kind" in e and not isinstance(e["kind"], str):
        return "obligation 'kind' must be a string"
    if "members" in e and not isinstance(e["members"], list):
        return "obligation 'members' must be a list (add members with " \
               "add-member instead)"
    return None


def valid_member(e, ledger):
    k = _need(e, "obligation") or _need(e, "member")
    if k:
        return f"member entry requires '{k}'"
    known = {str(o.get("id")) for o in ledger["obligations"]
             if isinstance(o, dict)}
    if str(e["obligation"]) not in known:
        return (f"member references obligation '{e['obligation']}' "
                f"which has no add-obligation entry")
    return None


def valid_witness(e):
    if not isinstance(e.get("test"), str) or not e["test"].strip():
        return "witness entry requires a 'test' path (e.g. " \
               "tests/test_x.py::test_y)"
    covers = e.get("covers")
    if covers is not None:
        if not isinstance(covers, list):
            return "witness 'covers' must be a list"
        for i, c in enumerate(covers):
            if not isinstance(c, dict) or _need(c, "obligation"):
                return f"witness covers[{i}] requires 'obligation'"
    return None


def valid_fold(e):
    k = _need(e, "obligation", "member", "fold_into", "reason")
    if k:
        return f"fold entry requires '{k}'"
    return None


def valid_pin(e):
    k = _need(e, "id", "unit", "input", "clause_absent",
              "conforming_attempt")
    if k:
        return f"pin entry requires '{k}'"
    ca = e["conforming_attempt"]
    if not isinstance(ca, dict) or _need(ca, "tried", "result"):
        return "pin 'conforming_attempt' requires 'tried' and 'result'"
    return None


def valid_door(e):
    k = _need(e, "unit", "member")
    if k:
        return f"door entry requires '{k}'"
    return None


VALIDATORS = {"add-obligation": ("obligations", valid_obligation),
              "add-member": ("members", valid_member),
              "add-witness": ("witnesses", valid_witness),
              "add-fold": ("folds", valid_fold),
              "add-pin": ("pins", valid_pin),
              "add-door": ("doors", valid_door)}


# ----------------------------------------------------------------- render

def yaml_scalar(v):
    """Leaf scalar as a YAML-safe spelling. json.dumps produces valid
    YAML double-quoted scalars for strings and true/false/null for the
    rest, so quoting bugs are impossible."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if v is None:
        return "null"
    return json.dumps(str(v), ensure_ascii=False)


def emit_yaml(value, indent=0):
    """Minimal YAML emitter for the ledger's restricted shape
    (dicts/lists/scalars, block style)."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(emit_yaml(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {emit_yaml(v, 0)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, dict) and item:
                keys = list(item)
                first, rest = keys[0], keys[1:]
                fv = item[first]
                if isinstance(fv, (dict, list)) and fv:
                    lines.append(f"{pad}- {first}:")
                    lines.append(emit_yaml(fv, indent + 2))
                else:
                    lines.append(f"{pad}- {first}: {emit_yaml(fv, 0)}")
                for k in rest:
                    v = item[k]
                    if isinstance(v, (dict, list)) and v:
                        lines.append(f"{pad}  {k}:")
                        lines.append(emit_yaml(v, indent + 2))
                    else:
                        lines.append(f"{pad}  {k}: {emit_yaml(v, 0)}")
            elif isinstance(item, (dict, list)):
                lines.append(f"{pad}- {emit_yaml(item, 0)}")
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
        return "\n".join(lines)
    return yaml_scalar(value)


def yaml_form(ledger):
    """Canonical nested mapping: flat members folded under their
    obligation (the YAML/doc shape every checker consumes)."""
    by_ob = {}
    for m in ledger["members"]:
        if isinstance(m, dict) and "obligation" in m:
            by_ob.setdefault(str(m["obligation"]), []).append(
                m.get("member"))
    obligations = []
    for o in ledger["obligations"]:
        if not isinstance(o, dict):
            continue
        entry = dict(o)
        own = list(entry.get("members") or [])
        entry["members"] = own + by_ob.get(str(o.get("id")), [])
        obligations.append(entry)
    return {"obligations": obligations,
            "witnesses": ledger["witnesses"],
            "folds": ledger["folds"],
            "budget": ledger["budget"],
            "doors": ledger["doors"],
            "pins": ledger["pins"]}


def render(ledger):
    body = emit_yaml(yaml_form(ledger), 0)
    return f"```ledger\n{body}\n```"


def main():
    ap = argparse.ArgumentParser(
        description="Append entries to a run's machine ledger "
                    "(RUN_DIR/ledger.json) with atomic writes, or "
                    "render the fenced ```ledger YAML snapshot.")
    ap.add_argument("run_dir", help="run directory containing "
                                    "ledger.json (created on first add)")
    ap.add_argument("command", choices=sorted(VALIDATORS) +
                    ["render", "show"])
    ap.add_argument("--json", help="entry payload as a JSON object "
                                   "(required for add-* commands)")
    args = ap.parse_args()

    if not os.path.isdir(args.run_dir):
        print(f"error: run dir {args.run_dir} not found")
        return 2
    ledger, err = load_ledger(args.run_dir)
    if err:
        print(f"error: {err}")
        return 2

    if args.command in ("render", "show"):
        if args.command == "show":
            print(json.dumps(ledger, indent=1, ensure_ascii=False))
        else:
            print(render(ledger))
        return 0

    if not args.json:
        print(f"error: {args.command} requires --json '<entry>'")
        return 2
    try:
        entry = json.loads(args.json)
    except ValueError as e:
        print(f"error: --json is not valid JSON: {e}")
        return 2
    if not isinstance(entry, dict):
        print("error: --json must be a JSON object")
        return 1

    section, validator = VALIDATORS[args.command]
    err = validator(entry, ledger) if validator is valid_member \
        else validator(entry)
    if err:
        print(f"REJECTED — {err} (nothing written)")
        return 1

    ledger[section].append(entry)
    ledger["budget"] = len(ledger["witnesses"])   # derived, never stale
    atomic_write(ledger_path(args.run_dir),
                 json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    n = len(ledger[section])
    print(f"ledger.json: {section}[{n - 1}] appended "
          f"(obligations={len(ledger['obligations'])} "
          f"members={len(ledger['members'])} "
          f"witnesses={len(ledger['witnesses'])} "
          f"budget={ledger['budget']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
