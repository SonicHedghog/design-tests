# Checker scripts (Phase 5 mechanical audits)

Seven stdlib-only checkers that verify the joins the skill mandates —
they exist because the failure mode they address is *claims written,
joins never executed* (budget columns that don't sum, grid cells with
no witness, tests anchored to no obligation, guard sites never
enumerated, prose counts that drift from the ledger).

Convention: every script takes argparse args, prints a human-readable
report to stdout, and exits **0** when clean, **1** on findings, **2**
on usage/fatal errors. `--json out.json` writes machine-readable
findings where supported. `test_checkers.sh` runs all seven against a
run dir.

## ledger_reconcile.py — obligation⇄test join (highest leverage)

```
ledger_reconcile.py TEST_DESIGN.md [--tests DIR] [--json out.json]
```

Parses the fenced ```` ```ledger ```` YAML block (PyYAML if importable,
else a built-in minimal parser for the restricted shape):

```yaml
obligations: [{id, kind, members: [...]}]
witnesses:   [{test, covers: [{obligation, members: [...]}]}]
folds:       [{obligation, member, fold_into, reason}]
budget: N
```

Checks, all at **member** granularity:

- member with no witness and no declared fold → `hole`
- fold citing a nonexistent witness/obligation/member → `dangling-fold`
- cover entry citing an unknown obligation/member → `dangling-cover`
- witness covering no obligation member → `redundant-test`
- obligation with zero witnessed/folded members → `unreferenced-obligation`
- with `--tests`: `pytest --collect-only -q` items missing from
  witnesses → `unanchored-test`; witness names absent from the
  collection → `phantom-witness` (name drift)
- `budget` vs #witnesses vs #collected vs the §3 budget-table row sum
  (rows like `8+3+1 = 12` are evaluated; a `total` row is the stated
  total) → `sum-mismatch` / `budget-table`

No ```` ```ledger ```` block → prints a clean "no ledger block"
diagnostic and exits 0 (the block is mandated; its absence is a doc
gap, not a checker crash).

## surface_closure.py — public surface × test/coverage join

```
surface_closure.py SRC_DIR TESTS_DIR [--justify FILE] [--no-cov] [--json out]
```

- Import surface: `__all__` members (else public module-level
  functions/classes) + public/dunder methods per class.
- Evidence: AST over TESTS_DIR — Name/Attribute leaves, call targets,
  operators. Dunders need operator evidence: `__ge__` ← a `>=`
  comparison, `__getitem__` ← a subscript, `__init__` ← a `ClassName(`
  call, `__contains__` ← `in`.
- Coverage: `pytest --cov` (pytest-cov) or `coverage run -m pytest`
  fallback. Uncovered lines are excused by an inline
  `pragma: no cover`/`nocover` comment or a `--justify` file
  (`relpath` or `relpath:lineno` lines).
- Output: per-module table (names / referenced / unreferenced /
  uncovered). Exit 1 on any unreferenced public name or unjustified
  uncovered line; coverage-tool absence warns, coverage failure fails.

## oracle_lint.py — oracle-shape AST lint

```
oracle_lint.py TESTS_DIR [TESTS_DIR ...] [--json out.json]
```

FAIL shapes (exit 1): `dup-body` (verbatim-identical test bodies),
`dup-literal` (same param-names + literal row repeated within one
parametrize table), `self-compare` (`assert x == x` / `is` /
`f(x)==f(x)`), `impl-mirror` (`r = f(a)` then `assert r == f(a)`),
`assert-const` (`assert True`), `lit-lit` (`assert 5 == 5`).

WARN shapes (reported, don't fail): `dup-shape` (bodies identical
only after literal normalization — deselect-audit candidate),
`dup-literal-shared` (identical row in another function's table),
`raises-bypass` (calls inside/after a `pytest.raises` block with no
assertion anywhere — the guard-vs-bypass shape), `raises-conditional`
(`if` inside a raises body — a row can swallow the expected raise).

## dup_sweep.py — duplicate-case sweep (AST)

```
dup_sweep.py TESTS_DIR [TESTS_DIR ...] [--json out.json]
```

Normalizes every parametrized case (and each non-parametrized test) to
an **(input set, assertion-shape)** signature. The input set is every
normalized operation the case's executed body invokes — calls,
subscripts, operators — with parametrize names resolved to their row
literals and simple `x = <expr>` assignments resolved (`parse(s)` on
row `"1.2.3"` ≡ `parse("1.2.3")`; `f(*a)` with `a=(1,2,3)` ≡
`f(1,2,3)`). The assertion shape is the body's oracle predicates:
`raises(E[, match])`, `==`/`is` with the expected literal, `!=`,
ordering comparisons, `in`/`not in`, `len()`/attribute chains, bare
truthy/falsy/None checks. `if` tests that constant-fold on a row
literal resolve to the taken branch.

Findings: `dup` (FAIL — identical input set *and* identical predicate
set, even under different test names/files) and `near-dup` (WARN —
identical input set where one oracle is strictly weaker: a predicate-
set subset, or every predicate matched by an equal-or-stronger one on
the same subject — truthy `<` is-not-None `<` `!=`/cmp/in `<`
`==`-literal; `raises(E)` `<` `raises(E, match)`; `raises(Exception)`
`<` `raises(<specific>)`; same-direction threshold comparisons).
Files named `test_suspected_defects*` are whitelisted — defect flags
deliberately replay inputs under different oracles.

## boundary_audit.py — boundary × witness join (verify mode)

```
boundary_audit.py --design TEST_DESIGN.md [--tests DIR] [--spec spec.json]
                  [--verify] [--dump]
```

Boundary entries (name, bound, operator, unit) come from ```` ```ledger````
obligations with `kind: boundary`, a fenced ```` ```boundaries````
block, a markdown table with name/bound/operator columns, or a
`--spec` JSON in boundaries.py domain-spec shape (`min`→`>=`/`>`,
`max`→`<=`/`<`, `len_*` similarly on the length domain).

Required sides per operator: `>=` `<=` `==` need below+at+above;
`>` needs at(invalid)+above; `<` needs below+at(invalid); `!=` needs
at+one side. A side is witnessed by a ledger cover member spelling
the side (`below`/`under`, `at`/`edge`/`min`/`max`, `above`/`over`…)
or a test function name citing the boundary name/id plus a side word.
`--dump` prints parsed entries only.

**Transform-collapse (validate-then-transform bounds):** an entry
whose ledger obligation carries a `transform:` key (`transform:
round`, `clamp`, `coerce`, …) or whose id/name/text mentions
rounding/clamping/coercion/normalization/truncation additionally
requires a member strictly INSIDE the collapse interval — passing the
guard pre-transform, landing on or past the rejected bound
post-transform. Witnessed by a cover member spelling it (`collapse`,
`straddle`, `pre-transform`, `rounds-to-bound`…), by a numeric member
value that evaluates inside the interval (computable for
round/floor/ceil/trunc/int), or by a citing test name with a collapse
word. Missing → `collapse-interior` added to the missing-sides list.

## guard_census.py — guard-site × member-class join

```
guard_census.py TEST_DESIGN.md --case-dir SRC_DIR [--json out]
```

AST pass over the implementation source (--case-dir). Each guard
shape mints required member classes per door:

- `except (A, B, …)` tuples — one class per exception class
- `str.is*` predicates — satisfied + rejected classes; the
  `isdecimal ⊂ isdigit ⊂ isnumeric` ladder adds an "exclusive" class
  (isdigit-not-isdecimal superscripts, isnumeric-not-isdigit
  fractions/CJK)
- `int()`/`float()`/`Decimal()`/`Fraction()` sites — conversion-
  grammar set: string-spelling, adjacent-type, rejection. Calls fed
  only by `re.Match.group()` are counted but mint nothing (the regex
  site owns that grammar).
- `.fullmatch()`/`.match()`/`.search()` calls — conforming +
  rejecting classes
- `SupportsX` annotations (Union siblings mint accepted-type classes
  too), `operator.index()`, `'__index__'`-style hasattr/getattr
  probes, multi-class `isinstance` tuples — one class per accepted
  type

A class is "plausibly covered" when any ledger spelling — obligation
id, member key, witness test tail, fold member/target — hits a signal
token (whole word, ≥4-char prefix stem, or squashed substring like
`valueerror`). Uncovered → `file:line [door] no ledger member
plausibly covers <label>`. Unparseable source files are warnings.

## claim_reconcile.py — prose-claim × truth join

```
claim_reconcile.py TEST_DESIGN.md [--journal journal.txt]
                  [--metrics metrics.json] [--tests DIR] [--json out]
```

Parses the design doc's Self-review section (stops at next heading or
fence) plus the whole journal for `N <count-noun>` claims ("402
collected items", "399 pass", "3 plain failing assertions", "126
obligations, 403 members") and `noun: N`/`budget N` spellings.
Each claim diffs against ground truth: metrics.json `main.*` counts,
then `pytest --collect-only` (with `--tests`), then the ledger
(`budget:`, #witnesses, #members, #obligations). Uncheckable claims
are reported, never findings; disagreements are `claim-mismatch`
findings. A cross-check flags `passed + failed ≠ collected`.

## test_checkers.sh — run all seven

```
test_checkers.sh <run_dir> [--src SRC_DIR] [--tests TESTS_DIR] [--spec s.json]
```

`<run_dir>` should contain `TEST_DESIGN.md` and usually `tests/`;
`journal.txt` and `metrics.json` inside it are fed to claim_reconcile
automatically. Each checker is skipped (with a note) when its inputs
are missing. Exit 0 iff every checker that ran was clean.
