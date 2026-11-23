# Checker scripts (Phase 5 mechanical audits)

Eight stdlib-only checkers that verify the joins the skill mandates —
they exist because the failure mode they address is *claims written,
joins never executed* (budget columns that don't sum, grid cells with
no witness, tests anchored to no obligation, guard sites never
enumerated, prose counts that drift from the ledger) — plus
`ledger_entry.py`, the machine-ledger authoring tool runners use to
build `ledger.json`.

Convention: every script takes argparse args, prints a human-readable
report to stdout, and exits **0** when clean, **1** on findings, **2**
on usage/fatal errors. `--json out.json` writes machine-readable
findings where supported. `test_checkers.sh` runs all eight against a
run dir.

## ledger_reconcile.py — obligation⇄test join (highest leverage)

```
ledger_reconcile.py TEST_DESIGN.md [--tests DIR] [--src DIR ...]
                    [--metrics FILE] [--json out.json]
```

Ledger source: when `ledger.json` exists beside TEST_DESIGN.md it is
**authoritative** (runners build it with `ledger_entry.py`; the fenced
block in the doc is just its rendered snapshot). Otherwise the fenced
```` ```ledger ```` YAML block is read as the backcompat fallback
(PyYAML if importable, else a built-in minimal parser for the
restricted shape).

Schema-completeness FAILs (the hum_r34 corruption class — a truncated
hand-written block that silently lost `pins:`/`doors:` and a fresh
budget):

- `ledger-corrupt` — `ledger.json` is unparseable/not a mapping
  (fatal — a corrupt machine file is never skipped back to the
  rendered snapshot); on the YAML fallback, the fenced block fails to
  parse or contains stray non-YAML fragments the restricted parser
  could not consume (an orphan ` pass}}` continuation line — the
  minimal parser used to drop it and everything after it silently).
- `ledger-missing-section` — `ledger.json` lacks a required top-level
  key: `obligations`/`members`/`witnesses`/`pins`/`doors`/`folds`/
  `budget` (`members` is the flat append list; obligation-nested
  members also satisfy it for pre-migration ledgers). Machine path
  only — backcompat ledgers legitimately lack `pins:`/`doors:`.
- `entry-schema` — an entry lacks the fields the join needs: witness
  requires a `test` path; pin requires `unit`, `input`,
  `clause_absent`, `conforming_attempt`; fold requires `obligation`,
  `member`, `fold_into`, `reason`; door requires `unit`, `member`;
  a flat member requires `obligation`+`member` citing an existing
  obligation. Applied on both paths.

The ledger mapping (either source) has the shape:

```yaml
obligations: [{id, kind, members: [...]}]
witnesses:   [{test, covers: [{obligation, members: [...]}]}]
folds:       [{obligation, member, fold_into, reason}]
pins:        [{id, unit, input, clause_absent, conforming_attempt}]
doors:       [{unit, member, clause_id, disposition}]
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
- without `--tests` (or when the collection fails): the same
  `phantom-witness` join runs against STATICALLY discovered tests —
  `junit/`/`tests/`/`test/` dirs beside TEST_DESIGN.md are censused
  (.java `@Test`-family annotated + `public void test*` methods;
  `def test*` by AST) and every witness `test` ref must resolve to a
  discovered (file, method). `path.py::test_x[p]`, `Cls::m`,
  `pkg.Class#m`, and `pkg.Class.m` spellings all resolve; param
  brackets are stripped for the lookup but synthetic suffixes are
  NOT — cv_r37 minted 52 `~covN` pseudo-witnesses (real base name +
  fake tag) plus 5 `flagdN` witnesses naming methods that never
  existed to pass the witness floor
- `budget` vs #witnesses vs #collected vs the §3 budget-table row sum
  (rows like `8+3+1 = 12` are evaluated; a `total` row is the stated
  total) → `sum-mismatch` / `budget-table`
- with `--src` on a Java tree (`.java` outnumbers `.py`): Java
  member-census floor — public methods are counted by regex over the
  non-test source and the ledger member total must reach ≥1 member per
  4 public methods, else `java-census-floor` FAIL (r30: a 61-member
  suite over a ~350-method API is implausibly thin and ship-blocks).
- with `--src` on a Python tree (`.py` outnumbers `.java`): Python
  member-census floor — public functions/classes/methods are counted
  by AST over non-test sources (`__all__` honored, public/dunder
  methods per public class) and the member total must reach ≥1 member
  per 4 public units, else `python-census-floor` FAIL (r31:
  surface_closure alone was not enough — a 110-member ledger over a
  ~140-unit surface still shipped only 23 grab-bag tests).
- `member-packing` FAIL (r34 member-granularity seal, needs `--src`):
  a ledger member must name ONE unit + discriminating input. A member
  string spelling ≥3 distinct public unit names is a bundle; aggregate
  tokenized unit-name coverage >~2x the discrete-member count is
  bundled enumeration. Census floors count DISCRETE (unit,
  input-class) members — a bundle mints no pair, so packed strings
  earn no member-census credit (validators_r34 bundled ~70 units into
  ~10 space-joined members like `between wrong-type int None bytes`,
  hitting the floor on 34 member STRINGS while shipping 12 tests).
  Unit names are matched at whole-subtoken granularity (snake/camel/
  kebab spellings, subsumed hits deduped, signature citations like
  `Cls.m0:public Builder argName(...)` count as one unit).
- min-witness floor: #witnesses must reach ≥1 per 3 obligation
  members, and ≥60% of enumerated members must appear in witness
  covers (the rest may not live only in folds), else
  `witness-starvation` FAIL — a member-rich ledger on a handful of
  tests is capacity-collapse, not minimalism.
- seal-gaming audits:
  - `bridge-artifact` FAIL — any `.py` file or `__pycache__` dir
    inside a Java `--src` tree (r31: `coverage_anchor.py` was planted
    in `src/main/java` to feed the Python checkers a fake module).
  - `coverage-exclusion` FAIL — `exclude_lines`/`exclude_also`
    patterns in coverage configs beside TEST_DESIGN.md
    (`.coveragerc`, `coverage.cfg`, `setup.cfg`, `tox.ini`,
    `pyproject.toml`) whose unescaped identifiers hit the ledger
    member/door token corpus (whole-token ≥4 chars, whole-squash ≥5,
    or ≥6-char containment). Excluded lines must be non-
    discriminating tails, not door mechanisms (r31: the `]`-strip /
    `is_private` / `_keccak_flag` sites were excluded while the doc
    claimed door outcomes asserted).
  - `metrics-divergence` FAIL — a `metrics.json` beside
    TEST_DESIGN.md (or `--metrics`) whose `collected`/`tests_run`
    count diverges from the ledger witness count by >10x without a
    quantified disclosure of the non-artifact portion (an
    upstream/external/vendored/pre-existing numeric key or
    keyword+count prose in metrics/design/journal) (r31: 3486
    executions reported vs 12 witnesses, ~3195 undisclosed upstream
    repo tests).
  - `covers-false` FAIL (r38, needs `--src` + resolvable witness
    `test` refs) — a witness's `covers` member list must actually be
    exercised by the test body it names. For each witness resolving
    to a discovered (file, method) the checker derives the covered
    unit set: public units spelled in covered member strings
    (word/camel-hump boundaries — `_` always blocks, so a unit
    embedded in a snake_case test id is prose, not a claim;
    `test_X` citations spell X when X is a public unit) plus units
    named by the cover's obligation id (whole id, `obl-` remainder,
    `:`-segments). The test's exercised call graph is its callee/
    attribute refs — comments/docstrings don't count; Java refs
    include file-scope imports, extends/implements clauses, field
    declarations (JUnit rebuilds fixtures per test) and a one-hop
    step into same-file probe helpers. Conservative: fires only
    when ZERO covered units appear in the named test's call graph —
    a param-row test may legitimately cover a member class without
    touching every member; covers resolving to no unit claim stay
    with the member-existence seals (val_r38 minted
    one-witness-per-item `case:` bookkeeping where covers cited
    members/units the test never touched — 0/502 real coverage).
  - `metrics-untruth` FAIL (r37) — metrics.json numbers are claims
    to re-verify, not truth: every internal consistency check can
    pass while every layer lies the same way. Fresh measurements:
    a `tests/` dir is re-collected with `pytest --collect-only`
    (±5% tolerance); a `junit/` dir gets a static `@Test`-method
    census (exact — a method census is deterministic).
    `collected`/`tests_run`/`methods_total`/`tests_emitted`/
    `witnesses`/`budget`-family leaves must equal the measurement;
    pass/fail-family leaves may not exceed the real count. With
    `junit/` + `pom.xml`, `mvn -o -q test-compile` (120s, mvn from
    PATH or the absolute path the metrics' own gate string
    discloses, JAVA_HOME likewise) is attempted — a failing compile
    while metrics/design/journal claim compile-clean or green tests
    is a FAIL — and `**/surefire-reports/TEST-*.xml` totals are
    diffed against pass/fail claims when reports exist. Absent
    toolchains (no mvn/javac/pytest on PATH, none disclosed) degrade
    to `[WARN]`, never a finding (cv_r37 shipped a non-compiling
    suite + fabricated 111-green/116-total claims over 112 real
    methods).

No ```` ```ledger ```` block → prints a clean "no ledger block"
diagnostic and exits 0 (the block is mandated; its absence is a doc
gap, not a checker crash). Neither `ledger.json` nor a fenced block
→ same clean diagnostic, same exit 0.

## ledger_entry.py — machine-ledger authoring (r35 migration)

```
ledger_entry.py RUN_DIR add-obligation|add-member|add-witness|
                 add-fold|add-pin|add-door --json '{...}'
ledger_entry.py RUN_DIR render|show
```

The ledger is **never hand-written**: runners append entries to
`RUN_DIR/ledger.json` one call at a time. Each `add-*` validates its
entry against the per-entry schema (obligation needs `id`; member
needs `obligation`+`member` citing an existing obligation; witness
needs `test`; fold needs `obligation`/`member`/`fold_into`/`reason`;
pin needs `id`/`unit`/`input`/`clause_absent`/`conforming_attempt`;
door needs `unit`/`member`) and rewrites the file **atomically**
(tempfile + `os.replace`) — truncation at the JSON layer is
impossible. Rejected entries write nothing (exit 1). `budget` is
derived from the witness count on every write, so it can never go
stale.

`ledger.json` shape: `obligations`, `members` (flat
`[{obligation, member}]` append list), `witnesses`, `pins`, `doors`,
`folds`, `budget`. `render` folds the flat members under their
obligations and prints the fenced ```` ```ledger ```` YAML snapshot —
TEST_DESIGN.md embeds that output verbatim (human-readable, but
generated; never hand-edit it). `show` dumps the raw JSON.

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
row `"a.b.c"` ≡ `parse("a.b.c")`; `f(*a)` with `a=(1,2,3)` ≡
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

`flag-green-collision` FAIL (r36 pin-OUTCOME seal): a green assert and
a flag/red test asserting on the SAME input literal — the same call
args modulo trivial normalization — contradict; one must be wrong.
Python cases contribute (callee, all-literal-arg-tuple) signatures
(parametrize envs resolved) plus `('#argv', elts)` argv tuples for
literal list args; `*.java` files under the scanned dirs (e.g. junit/)
contribute argv literals (`new T[]{...}` and `asList`/`of`-family
collection factories). Basenames containing `suspected` are flag
files, all others green; an exact-arg signature present on both sides
is a FAIL (r36: cli_r36 green-asserted `{"-f","\"a\"b\""}` → the
impl-observed value for all four parsers while SuspectedDefectsParsers
flagged the identical DefaultParser input).

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

**Wrong-type-gap join (r32 probe-matrix seal):** each public unit
with ≥1 parameter whose ledger members carry NO type-class member at
all (int/str/list/tuple/dict/set/None/bool/bytes signal words, or a
collection/None literal in a param slot) is a `wrong-type-gap` FAIL —
validators_r32 claimed full enumeration while shipping zero non-str
probes. Units with no ledger presence are skipped (absence is the
ledger checkers' finding, not this one's).

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

r38 `seal-mutation` audit: metrics.json's checkers-evidence is
sealed when the run gates; artifacts rewritten afterwards make
every sealed checker output stale (val_r38 resealed metrics twice
mid-grading while the journal drifted). With a formal seal —
`sealed_at` (ISO timestamp) + `content_hash` anywhere at metrics
top level or inside a `seal`/`evidence`/`checker_evidence`/
`checkers` object — the hash is recomputed over ledger.json +
all test files (sha256 of sorted `relpath\0sha256(bytes)` lines)
and compared (mismatch => FAIL), and no artifact or metrics.json
itself may postdate `sealed_at` (=> FAIL). A `checkers`/
`checker_evidence` block without a formal seal falls back to
metrics.json's own mtime as seal time: ledger/test files newer
than it => `seal-mutation` FAIL; otherwise the absent seal is a
`seal-missing` WARN. No seal and no evidence block => WARN only
(legacy runs).

## pin_manifest.py — pins: manifest audit + attempt execution

```
pin_manifest.py TEST_DESIGN.md|RUN_DIR [TESTS_DIR] [--src SRC_DIR ...]
                [--json out.json]
```

Parses the fenced ```` ```ledger ```` YAML block's `pins:` list and keeps
the original joins: required fields, verbatim `clause_quote` in the design
doc and (with `--src`) in library source, non-tautological
`conforming_attempt`, duplicate unit+input pins, unmanifested pin-shaped
markers under TESTS_DIR, and census `verdict: pin` refs resolving to a
manifest id.

New r24 attempt checks: `tried` must textually reference the pin's `unit`
and `input` (or a resolvable alias such as `INPUT`/`<empty>`/`<null>`),
else `attempt-unrelated` FAIL. With `--src` on Python source, each
`{tried,input}` is materialized into a temp probe that imports the source
tree, binds `INPUT` when `input` is a Python literal, executes the
attempt, and compares the measured pass/fail to the recorded `result` —
mismatch is `exec-mismatch` FAIL; syntax/name/timeout probe failures are
`exec-error` FAIL. Java sources are not compiled in the checker: their
attempts are marked `exec-skipped-java` WARN. No `--src` → one
`exec-skipped` WARN.

New r26 attempt-independence checks: `tried` must not be satisfied by the
pin's own `observed` outcome. Expected literals are extracted from Python
asserts (`==`/`is`/`in`, `isinstance` unions) and common Java assert
shapes; an expected literal textually equal to `observed` is
`attempt-asserts-observed` FAIL, while structural similarity is
`attempt-observed-similar` WARN. Self-evidently true attempts —
`F(x)==F(x)`, `isinstance(F(x),(str,type(None)))`, `F(x) or True`, bare
`pass`, constant-true asserts — are `attempt-tautological` FAIL. Every
`result: pass` pin must also carry `clause_absent:` quoting verbatim the
docs/source region where a covering clause would live;
`pass-pin-no-justification` FAILs when it is missing or not verbatim.

New r32 unit join on `clause_absent`: with `--src`, the quote must be
PROSE inside the pinned unit's own docstring span (Python:
`ast.get_docstring` over every def/class; Java: the Javadoc block
preceding the method). A `def`/`class`/`import`/assignment/signature
line is `clause-absent-code` FAIL (r29 laundered `def foo(...)` lines
as silence proofs); prose verbatim in a DIFFERENT unit's docstring is
`clause-absent-wrong-unit` FAIL (r30's sci-negzero quoted clamp's
identical Args line — tree-wide verbatim match is unit-blind without
this join). Prose inside no unit's docstring (module docstring,
comments) passes only as an explicit `unspecified|not documented|
undocumented` statement or with a declared `unit:` on the
clause_absent mapping / `docs_unit:` on the pin matching pin.unit.

New r35 assert-body seal (observed-outcome pins): with `--src` + a
tests dir, green (non-suspected) test asserts are scanned for the
observed-outcome shape — `assertEquals(lit, expr)` / `assert expr ==
lit` whose expected side carries a concrete str/num literal and whose
outcome expression calls a spec-silent unit (project-DEFINED but
undocumented, or an impl-format accessor like `getMessage`/`toString`).
When no `pins:` entry covers the assert's unit+input →
`unmanifested-pin` FAIL (r35: cli_r35 shipped an EMPTY manifest while
>=6 green asserts pinned impl-observed outcomes — message formats,
hyphen asymmetry, 2 catalog defects — and passed because only markers
and manifest entries were counted). Conservative exclusions: boolean/
null/name/`.class` expecteds are not literal outcomes; `.size()`/
`.length`/`len()`/`isEmpty`/`contains`/instanceof-style oracles are
type/shape checks; an expected literal equal to a call-argument
literal is a passthrough; asserts on documented units (a doc clause
may cover the input class) and on purely foreign calls (test helpers,
JDK/stdlib that are neither project-defined nor format accessors)
are conforming, never flagged.

New r30 language-aware seal (Java): the unmanifested-pin scan is no
longer Python-only. When a RUN_DIR is passed, the checker looks for
`junit/` and any staged `*.java` under the run dir (or `--tests`) and
scans their `//` and `/* */` comments for `pin-observed:` / `pin:`
markers; each captured marker id must appear in the manifest, else
`unmanifested-java-pin` FAIL. `--src` is scanned only when the run has
no Java of its own — and the marker match is word-anchored +
colon-mandatory inside comments, so TLD-table comments like
`"lupin", // lupin LUPIN` and `// pin Amazon` cannot false-positive
(the bug that produced them was `--src` being scanned as the tests
root; `test_checkers.sh` now passes `--tests`/`--src` as flags so a
missing `tests/` dir can no longer shift `--src` into the tests slot).
Files named `*suspected*` are whitelisted like `test_suspected_*`.

New r36 defect-outcome seal: a `result: pass` pin's `observed` outcome
must be non-defective — spec-silent on the INPUT class does not
certify the outcome. `pin-defect-outcome` FAIL fires only on
unambiguous shapes: crash-named outcomes (`NullPointerException`/NPE,
`AssertionError` family, JVM Error classes, `NameError`/
`AttributeError`/`RecursionError`, traceback/panic/segfault markers),
malformed quoted output (doubled minus signs / negative fraction
parts like `'-1 -3/10'`, `'1 milliseconds'` number-unit
disagreement), and contract-shape violations — the observed outcome
is a non-str passthrough/bare literal where a clause the pin itself
cites (`clause_quote`/`clause_absent`) declares a string return (r36:
hum's `pin-sci-prec-*` pinned `scientific(500, precision=-1) == 500`
under a clause_absent that IS the Returns-str clause — invalid pins;
the door was clause-covered defective). Defect-shaped observed
outcomes must be dispositions flag|qfm, never pass-pins.

## test_checkers.sh — run all eight

```
test_checkers.sh <run_dir> [--src SRC_DIR] [--tests TESTS_DIR] [--spec s.json]
```

`<run_dir>` should contain `TEST_DESIGN.md` and usually `tests/`;
`journal.txt` and `metrics.json` inside it are fed to claim_reconcile
automatically. Each checker is skipped (with a note) when its inputs
are missing. Exit 0 iff every checker that ran was clean.
