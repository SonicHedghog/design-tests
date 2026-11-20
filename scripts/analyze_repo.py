#!/usr/bin/env python3
"""Inventory a Python package for test design. Stdlib only.

Usage: analyze_repo.py <src_dir> [--json out.json]

Emits, per public function/method:
  name, file, params (name, annotation, default), cyclomatic complexity,
  decision points (if/for/while/boolop/except/comprehension/match),
  raised exceptions, returns, docstring head, mutates-self hint.

Cyclomatic complexity per function = 1 + #decision points in that
function's AST (standard McCabe approximation).
"""
import ast
import json
import os
import sys


def ann(node):
    return ast.unparse(node) if node is not None else None


def complexity(fn):
    """McCabe CC: 1 + decision points."""
    cc = 1
    decisions = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            cc += 1; decisions.append(f"if@{node.lineno}")
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            cc += 1; decisions.append(f"for@{node.lineno}")
        elif isinstance(node, ast.While):
            cc += 1; decisions.append(f"while@{node.lineno}")
        elif isinstance(node, ast.BoolOp):
            n = len(node.values) - 1
            cc += n
            decisions.append(f"{'and' if isinstance(node.op, ast.And) else 'or'}x{n}@{node.lineno}")
        elif isinstance(node, ast.ExceptHandler):
            cc += 1; decisions.append(f"except@{node.lineno}")
        elif isinstance(node, ast.IfExp):
            cc += 1; decisions.append(f"ternary@{node.lineno}")
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for _ in node.generators:
                cc += 1; decisions.append(f"comp@{node.lineno}")
            for iff in [i for g in node.generators for i in g.ifs]:
                cc += 1; decisions.append(f"compif@{node.lineno}")
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):
            cc += len(node.cases); decisions.append(f"matchx{len(node.cases)}@{node.lineno}")
        elif isinstance(node, ast.Assert):
            decisions.append(f"assert@{node.lineno}")  # not a branch
    return cc, decisions


def raises(fn):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            try:
                out.append(ast.unparse(node.exc).split("(")[0])
            except Exception:
                pass
    return sorted(set(out))


def params(fn):
    args = fn.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    anns = {a.arg: ann(a.annotation) for a in
            args.posonlyargs + args.args + args.kwonlyargs}
    if args.vararg:
        names.append("*" + args.vararg.arg)
        anns[args.vararg.arg] = ann(args.vararg.annotation)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
        anns[args.kwarg.arg] = ann(args.kwarg.annotation)
    defaults = {}
    dflts = args.defaults
    pos = args.posonlyargs + args.args
    for a, d in zip(pos[len(pos) - len(dflts):], dflts):
        defaults[a.arg] = ast.unparse(d)
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        if d is not None:
            defaults[a.arg] = ast.unparse(d)
    return [{"name": n, "type": anns.get(n), "default": defaults.get(n.lstrip("*"))}
            for n in names if n not in ("self", "cls")]


def mutates_self(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id == "self"):
                    return True
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
            if isinstance(node.target.value, ast.Name) and node.target.value.id == "self":
                return True
    return False


def is_public(name):
    return not name.startswith("_")


def analyze_file(path):
    src = open(path).read()
    tree = ast.parse(src)
    mod_doc = ast.get_docstring(tree) or ""
    units = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_public(node.name):
            cc, dec = complexity(node)
            units.append({
                "unit": node.name, "kind": "function",
                "params": params(node), "cc": cc, "decisions": dec,
                "raises": raises(node),
                "returns": ann(node.returns),
                "doc": (ast.get_docstring(node) or "")[:200],
                "mutates": False, "lineno": node.lineno,
            })
        elif isinstance(node, ast.ClassDef) and is_public(node.name):
            if any(isinstance(b, ast.Name) and b.id == "Enum" for b in node.bases):
                units.append({"unit": node.name, "kind": "enum",
                              "members": [n.targets[0].id for n in node.body
                                          if isinstance(n, ast.Assign)],
                              "doc": (ast.get_docstring(node) or "")[:200],
                              "lineno": node.lineno})
                continue
            methods = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    vis = ("dunder" if sub.name.startswith("__")
                           else "private" if sub.name.startswith("_")
                           else "public")
                    if vis == "private":
                        continue
                    cc, dec = complexity(sub)
                    methods.append({
                        "unit": f"{node.name}.{sub.name}", "kind": "method",
                        "visibility": vis,
                        "params": params(sub), "cc": cc, "decisions": dec,
                        "raises": raises(sub), "returns": ann(sub.returns),
                        "doc": (ast.get_docstring(sub) or "")[:200],
                        "mutates": mutates_self(sub), "lineno": sub.lineno,
                    })
            units.append({"unit": node.name, "kind": "class",
                          "doc": (ast.get_docstring(node) or "")[:200],
                          "methods": methods, "lineno": node.lineno})
    return {"file": path, "module_doc": mod_doc[:300], "units": units}


def main():
    src_dir, out = sys.argv[1], None
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
    mods = []
    for root, _, files in os.walk(src_dir):
        for fn in sorted(files):
            if fn.endswith(".py"):
                mods.append(analyze_file(os.path.join(root, fn)))
    report = {"src": src_dir, "modules": mods}
    txt = json.dumps(report, indent=1)
    if out:
        open(out, "w").write(txt)
    # console summary
    for m in mods:
        rel = os.path.relpath(m["file"], src_dir)
        print(f"\n# {rel}")
        for u in m["units"]:
            if u["kind"] in ("class",):
                print(f"  class {u['unit']}  ({len(u['methods'])} methods)")
                for mm in u["methods"]:
                    sig = ", ".join(
                        f"{p['name']}:{p['type']}" if p["type"] else p["name"]
                        for p in mm["params"])
                    mut = " MUT" if mm["mutates"] else ""
                    print(f"    {mm['unit']}({sig}) cc={mm['cc']}"
                          f" raises={mm['raises']}{mut} [{mm['visibility']}]")
            elif u["kind"] == "enum":
                print(f"  enum {u['unit']} {u['members']}")
            else:
                sig = ", ".join(
                    f"{p['name']}:{p['type']}" if p["type"] else p["name"]
                    for p in u["params"])
                print(f"  {u['unit']}({sig}) cc={u['cc']} raises={u['raises']}")
    if out:
        print(f"\njson -> {out}")


if __name__ == "__main__":
    main()
