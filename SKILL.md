---
name: design-tests
description: Generate a complete-but-minimal test suite for a repo, requirements doc, or state/decision model. Formalizes inputs into a requirements model (decision tables, state diagrams, domain specs), computes per-category test budgets formulaically (BVA by bounds, MC/DC by conditions, state-transition by grid, branch coverage by cyclomatic complexity), then emits runnable tests in the project's framework. Language-agnostic; Python/pytest and Java/JUnit get first-class treatment. Per-category methodology in categories/*.md — invoke a single file to generate just one category.
argument-hint: "<path to repo | requirements | diagrams> [categories to generate] [--review]"
allowed-tools:
  - read
  - edit
  - grep
  - glob
  - exec
  - run_subagent
---

You design test suites the way a software-testing engineer does:
formalize the inputs into a requirements model, pick the minimal test
set that formulaic coverage criteria demand, then write those tests.
Your deliverable is a complete BUT MINIMAL suite — every test must be
defended by a rule in these files; a test with no rule behind it is
bloat, and a rule with no test is a coverage hole.

# Inputs

One of:
- **A repository** (default): recover requirements from type
  annotations, docstrings, README/spec docs, and — last resort —
  reading the implementation. The implementation defines *mechanism*,
  not *intent*; where they disagree, the spec wins.
- **A requirements document**: treat as the spec. Still scan any
  provided source for signature names and error types.
- **A state diagram / decision table**: skip re-derivation, validate
  completeness, go to Phase 3.

# Pipeline

## Phase 1 — Inventory
- Python: run `scripts/analyze_repo.py <src_dir> --json analysis.json`.
  It lists every public unit with params+annotations, cyclomatic
  complexity, raised exceptions, mutation hints, enums, and docstrings.
- Other languages: produce the same inventory by hand or grep:
  public units, signatures, throws/raises, mutators, enums.
- **Untyped Python warning**: if annotations are absent/sparse, warn
  the user that the recovered requirements are softer (domains are
  inferred, not declared), and suggest `mypy`/adding annotations.
  Proceed anyway — inference beats skipping.

## Phase 2 — Requirements model
For every public unit, write down:
- signature + each parameter's DOMAIN (type, range/length bounds,
  enum, format, optionality, classes that differ in behavior)
- the output rule per input class (this IS the spec for assertions)
- documented error classes (raises, error returns) and their triggers
- for stateful classes: the state machine (states, operations, guards,
  side effects, terminal states) — make the full state x operation grid
- for multi-condition decisions: the decision table / predicate terms

**Review gate**: if the user asked for review, present this model and
WAIT for approval before Phase 3. Default: no pause — proceed
straight to generation.

## Phase 3 — Category plan & budget
Default: all applicable categories from `categories/*.md`. If the
target's language matches a `languages/<lang>.md` file, LOAD it —
its contracts and domain-edge classes are additional registry
members (language-level obligations the spec rarely states). If
the user
names a subset, generate only those (read only those files — a user
can also invoke a single category file directly).

Every suite needs BOTH lenses:
- **Black-box** (spec-driven, no code reading): EP, BVA, decision
  table, state-transition, pairwise, contract-invariants,
  exception-negative, fuzzing, property-based, regression.
- **White-box** (structure-driven): control-flow/basis-path, MC/DC,
  mutation-testing audit, integration seams.
Black-box tests prove the spec is implemented; white-box tests prove
the implementation is exercised. Skipping a lens needs a written
justification in TEST_DESIGN.

For each unit x applicable category, compute the budget per that
file's formula (boundaries.py / mcdc.py / decision_table.py do the
arithmetic — use them). Record the budget table in TEST_DESIGN.md.

## Phase 4 — Generate tests
Follow `categories/output-spec.md` plus each category file.
Framework: pytest+parametrize (Python), JUnit5 parameterized (Java),
nearest equivalent elsewhere. Match the repo's existing test
conventions when extending a suite.
Every test maps to (a) a requirement row and (b) a budget line. Name
tests `test_<unit>_<intent>`; group parametrize tables under a comment
naming the category.

## Phase 5 — Verify
- Run the suite against the real source (install editable or set
  PYTHONPATH/import path; Java: mvn/gradle test if available).
- Measure branch coverage (coverage.py --branch; jacoco).
- Failing tests: if the test is wrong, fix the test. If the
  implementation violates the requirements model, KEEP the test and
  log it under "Suspected defects" — that is a found bug, the point
  of the exercise.
- Any budget line with no test, or uncovered branch: resolve or
  justify in TEST_DESIGN.md.
- Run all seven checkers and fix every finding:
  scripts/ledger_reconcile.py (member-granularity join),
  oracle_lint.py (forbidden oracle shapes), dup_sweep.py
  (literal-identical input × assertion-shape duplicates and
  strictly-weaker near-dups across names/files), boundary_audit.py
  (declared-bound side coverage + transform-collapse interior),
  surface_closure.py (public-surface + source closure),
  guard_census.py (implementation guard sites × member classes),
  claim_reconcile.py (reported numeric claims vs
  ledger/metrics).
- **Oracle lint (mechanical):** grep the suite for forbidden oracle
  shapes: expected values computed with the implementation's own
  formula (`f(x) == f`'s-formula) or RESTATING an impl formula
  (asserting hash(x) equals a literal of the impl's hash expression —
  assert the CONTRACT: equal objects -> equal hash); `f(x) == f(x)`
  self-comparisons (including `is`-spelled); non-empty/exists
  assertions as the whole test; `eval`/`exec` strings building
  expected values; bare `pytest.raises` with no guard identification
  beyond the type when the unit has >1 raise path; WEAK-VALUE
  projections: sign-of-comparisons ((r>0)-(r<0)) where the exact
  value is pinned, substring membership ("x" in out) where the exact
  output is pinned, truthiness smoke checks (is not None) as the
  whole assertion, any self-comparison including across assignments
  (res is f(x), repr(v)==repr(v)). Each hit must be rewritten or
  justified in TEST_DESIGN.
- **Reachable inputs are testable inputs.** "Spec-invalid" or
  spec-silent is NOT a reason to skip: if the public API accepts an
  input class, test it — assert documented behavior, or where spec is
  silent, assert observed behavior and flag in Suspected defects.
- **Universal load-bearing audit (mechanical, BOTH directions):** the
  obligation→test direction is a join (every ledger cell has a witness)
  — it cannot discriminate rows. Run the TEST→OBLIGATION direction
  too: every emitted row must name the obligation or mutant-kill that
  UNIQUELY requires it — a discriminating input where the wrong-order,
  dropped-argument, or absent-check failure is observable. If another
  row already witnesses the same discrimination, the row is redundant:
  `pytest --deselect` it, recheck coverage, delete if nothing is lost
  AND it anchors to no model row. Existence of a test never justifies
  a member — a class's second+ member must discriminate a DIFFERENT
  path or be folded. Never delete a row named by a boundary/MC/DC/
  axis/fact-join entry — those are load-bearing. Emitted count must
  EQUAL the ledger total — a member minted late goes into the
  ledger (budget updated before freeze), never an unledgered test.
  ORDERING/DELEGATION clauses specifically require a discriminating
  witness — an input where passing args in wrong order, omitting a
  forwarded arg, or skipping the delegation produces an observably
  different result. A well-formed-input probe can't kill an
  ordering/delegation mutant.
- **Validate-then-transform boundary:** when a unit validates a
  value then transforms it (round, clamp, coerce, normalize),
  test the boundary BETWEEN domains — a value inside the
  validation domain on pre-transform magnitude but outside on
  post-transform (e.g. smallest positive that rounds/clamps to
  the rejected bound) is a mandatory registry member per door,
  with a defect flag if the guard checks the pre-transform value.
- **Guard-site census:** each implementation guard shape mints
  its own member class, per door: a multi-class `except` tuple
  gets a member per exception class (the impl may route
  differently); a `str.is*` predicate gets members from EACH
  is-class it names (isdecimal/isdigit/isnumeric admit different
  members — see the language ref's classification ladder); a
  `int()`/`float()` conversion site gets the full conversion-
  grammar member set (lenient + rejection classes); a validation
  regex gets conforming-adjacent and rejecting members per
  alternation; a protocol-dispatch site (`__index__`, SupportsX)
  gets members per accepted protocol type; a single-type
  isinstance guard mints accepted-type, subclass-instance, and
  adjacent non-type members. AMBIENT STATE reads in guards
  (module attrs, __package__, sys.*, env vars, module-level
  globals) mint a member per reachable state value — patch the
  state in-process; never disposition as unreachable. A justify-out
  line is invalid when a module-attr/monkeypatch could reach it —
  test the patch (e.g. __package__="" on a __main__ module) before
  claiming unreachability. VIOLATION-DOOR DISPOSITION: every docstring
  or contract clause whose observed behavior diverges must appear
  in a §5 disposition table — each door gets an explicit verdict
  (defect flag / spec-silent pin / questions-for-maintainer) and a
  citing reason. A door absent from the table counts as silently
  dropped and fails review; doc-level promises (raise conditions,
  return contracts, "equal → compatible" clauses, IndexError
  guarantees) that behavior contradicts are flags, not ambiguity
  pins. LANGUAGE-AXIOM violations (eq→hash, iter round-trip,
  documented return-type contracts, context-manager protocols)
  are NEVER design-gap pins — "the impl is internally consistent"
  or "any fix has the same shape" does not excuse a broken
  documented axiom. When observed behavior contradicts a
  language-level or documented contract, flag it. NEVER pin the
  violation itself as expected — an assertion encoding the
  divergence (e.g. hash-inequality for an eq pair) is an inverted
  oracle: it fails on the fixed impl. Pins assert CONFORMING
  behavior only; divergent behavior on a documented contract is
  a flag. When sibling members share a root cause but differ in
  fix-repaired vs still-open status, the flag sits on the
  VARIANT-DIVERGENT member — a member that fails on both buggy
  and fixed can never be the detector for a fixable defect.
  A spec-silent verdict requires QUOTING the relevant doc text in
  §5 and showing it does not entail the behavior — "seems
  undocumented" is not a verdict. Before pinning any divergent
  behavior green, run the MENTAL-FIX check: if the doc clause
  were implemented faithfully, would the pin still pass? A pin
  that would fail on the conforming implementation is a flag.
  Reason against the VERBATIM doc wording only — never upgrade
  a paraphrase ("whitespace" for "spaces", "numeric" for
  "digits") into a stronger clause and pin against the upgrade.
  Every divergent clause observed during member enumeration
  gets its own §5 row — an unverdicted door is a miss, not a
  fold. The flag BODY must exercise the member §5 names as the
  detector — never docstring-fold siblings whose mechanism
  differs (falsy-collapse vs normalization are different root
  causes → separate flags or separate pins). Siblings are only
  a fold when every member fails for the same code path; if
  any sibling would outlive the minimal fix it cannot share
  the flag. Requirements-clause completeness: EVERY
  behavioral clause in the docs/docstrings (guard promises,
  exception clauses, transform descriptions, deprecated
  wrappers) must appear as a requirement row, and every
  requirement row must resolve to a witness, a flag, or a
  §5 verdict — a clause that contradicts impl but never
  became a requirement row is the highest-loss miss class.
  TRANSFORM ops are
  matrix consumers too — bump/convert/format/normalize ops
  consume fields and must appear in the field×consumer matrix
  or their field-edge members go unenumerated.
- **Independent disposition audit (mandatory, after self-verification):**
  the author CANNOT audit their own judgments. Before delivery, re-verify
  every §5 disposition with fresh eyes — probe each spec-silent pin
  against the source (run it), re-run mental-fix on every green pin,
  check no flag asserts what a pin calls conforming, confirm every §5
  row carries a VERBATIM quote (any doc format), and RE-SUM the ledger
  budget arithmetic instead of claim-matching. Any pin whose stated
  mechanism is wrong, any row without a witness, and any sum that
  doesn't reconcile must be fixed before shipping. This pass is what
  graders deduct for — run it first, don't wait to be caught.
- **Clause inventory (mandatory, before designing tests):**
  list EVERY testable clause of EVERY in-scope public API's
  docs verbatim — each @param contract, @return shape,
  @throws clause, "must"/"always"/"never" statement, example,
  and boundary claim. One line per clause, tagged [clause].
  The requirements model must trace every clause → witness
  test OR defect flag OR an explicit `absent:` quote showing
  the clause isn't actually there. A clause dropped from the
  model is a guaranteed recall miss — you can't flag what
  you never wrote down.
- **Pin-proof (mandatory before shipping):** for EVERY
  spec-silent pin, fold, or observed-behavior witness on a
  divergence, you must first TRY to write the conforming
  flag (`assert documented_contract(input)`). If it fails,
  that IS the defect flag — ship it. A pin is only legal
  after a documented proof that no conforming assertion is
  possible: the clause is provably absent (quote where it
  would live), or the divergence is impl-consistent and
  doc-consistent on every reading. "Inverted oracle",
  "design gap", "can't assert a crash" and "the doc is
  ambiguous" are not proof — ambiguity means flag both
  readings, not pin the convenient one. A run that ships
  zero flags on code with known divergent behavior has
  laundered the defects, not characterized them.
- **Pin-vs-flag discipline:** a written clause the impl
  contradicts is ALWAYS a flag door, never a green pin.
  "Spec-silent" describes an absent contract, not a
  violated one — pinning a written-clause violation
  green is evasion, not characterization. You may ALSO
  pin the observed behavior alongside the flag (flag the
  dead clause AND pin what it does), but the flag is
  mandatory. Reserve spec-silent pins for inputs the
  docs truly don't cover.
- **Defect-family completeness (mandatory):** when a divergence
  mechanism is found on one input, enumerate EVERY input in scope
  that reaches the same mechanism — sibling sites (same defect in a
  different function/branch), sibling parameters (a flag that only
  crashes when combined with another arg), and sibling classes of
  the input (zero, empty, null, negative variants of the triggering
  type). A defect family witnessed on one input but silent on its
  siblings is a recall miss — each uncovered sibling is an
  unenumerated door, not a fold.
- **Unwitnessed-member sweep (mandatory):** every ledger member
  must resolve to a test witness OR carry an explicit `unwitnessed:`
  reason in the ledger (e.g. `dead-code`, `env-gated`, `defect-flag`).
  Rejected-defect candidates get a §5 row even when rejected — a
  disposition is a verdict, not silence. An enumerated member that is
  neither witnessed nor justified is a hole, not an omission.
- **Compile-and-run gate (mandatory before ANY claims):** the
  delivered suite must compile and run exactly as shipped, with the
  documented command, in a clean environment. If the journal reports
  pass/fail counts, they must be reproducible from a fresh checkout —
  no scratch fixes, no hand-patched intermediates, no "it worked in my
  earlier attempt." A suite that doesn't compile as shipped fails
  executability outright regardless of test quality.
- **Final self-verification pass (mandatory before reporting done):**
  re-run the suite and verify every claim against reality —
  (a) pytest result == reported/metrics counts;
  (b) every §5 flag reproduces its violation AND its siblings
  pinned green — run each flag's sibling members and confirm
  they behave as claimed (a "fold" that lists members not
  actually exercised is fictional);
  (c) every spec-silent pin quotes doc text that genuinely
  lacks entailment;
  (d) duplicate sweep on literals — same literal, same
  assertion shape, same obligation = fold or delete;
  (e) requirements rows re-checked against actual impl
  behavior, not assumed semantics;
  (f) budget == collected == ledger table sum.
  A claim you cannot reproduce does not ship — fix the test
  or fix the claim.
- **Cross-file literal-dup sweep:** after emission, diff each
  file's parametrized rows against every other file's — the same
  input + same assertion pair may not appear twice even under
  different test names (fold the second obligation into the first
  test's covers).
- **Cross-section fold (no duplicate witnesses):** when two
  artifacts name the same discriminating input — an axis row
  whose spelling is already a decision-table member, a boundary
  rep that is also an EP rep — the SAME test covers both
  obligations; list both in its `covers:` entries. Never mint a
  second test re-running an identical input to satisfy a second
  section's join — the join is member-granular, not section-
  granular.
- **Minimal cover (rep selection):** completeness is necessary,
  not sufficient — the ledger join must also verify MINIMALITY.
  Every witness must be the SOLE coverer of >=1 obligation member
  (a witness whose cover set is fully subsumed by another witness's
  is redundant: fold it). When one input value can serve several
  obligations — a boundary rep that also lands in a decision-table
  row, an EP rep that also witnesses a contract axiom — mint ONE
  witness covering all of them: prefer reps that sit ON declared
  bounds/edges over interior values. Interior reps are a smell:
  an interior value usually means a bound-adjacent value would
  have covered the same member AND an additional boundary
  obligation. Representative-selection is where over-provisioning
  hides; budgets formula-derived but reps interior = the delta
  is already minted.
- **Falsifiable-oracle rule:** every oracle must be able to FAIL
  on some implementation — an assertion that no conforming OR
  non-conforming impl could violate (re-asserting what the
  declared return type already guarantees, asserting only
  non-emptiness, re-stating the input as output) is a tautology:
  it witnesses nothing and inflates the budget. Before minting a
  witness ask "which impl shape makes this fail?" — if the answer
  is none, drop the witness or sharpen the oracle until some
  impl fails it.
- **Suspected defects: one per root cause, kept green-visible, and
  must DETECT — a flag failing identically on buggy and reference
  implementations witnesses nothing; disposition it as a documented
  ambiguity/design gap, not a shipped red test.**
  N failing tests for one defect = N-1 redundant. Collect them in a
  dedicated file (test_suspected_defects.*), hard assertions with an
  issue-style docstring — ONE flag per root cause: when the same
  defect mechanism manifests at several entry points, flag the most
  discriminating door and pin the sibling doors as green
  observed-behavior (with the fold recorded in the ledger). The
  ONLY split permitted inside a root cause is the differential
  boundary — when instances differ on whether a plausible fix
  would repair them.
  DIFFERENTIAL ISOLATION: keep pairs that a plausible fix would
  repair separate from sibling pairs the same root cause admits
  but the fix wouldn't — bundling them into one flag destroys the
  differential signal (the flag fails on both impls and detects
  nothing). Flag the differential instances as their own test;
  sibling residuals get separate flag entries. Flags MUST be
  plain failing assertions on the defective implementation: never
  xfail, skip, or expect-failure marks — packaging a violation as an
  expected outcome makes the suite report it as passing and
  destroys the flag's detection signal entirely (an xfail on a
  buggy impl reports green and would hard-fail only once FIXED —
  the inverse of a detector). If a red test breaks tooling
  (coverage reports etc), fix the tooling invocation, not the
  flag.
- **Defect-consistency gate:** a suspected defect must not contradict
  the suite's own pins. If any test asserts the same semantics as
  valid, the flag is a false positive — resolve the spec reading
  first (pick the consistent interpretation, or disposition as
  ambiguity). Also: only flag what the model's OWN requirements say, and every
  flag must CITE a behavioral clause that ENTAILS the flag — the
  clause must actually forbid the observed behavior, not merely
  exist nearby. A return contract constrains successful returns
  and says nothing about the raise surface; an observed raise type
  is not a documented closed enumeration. If no clause entails the
  flag, disposition it as an ambiguity/design-gap, not a defect.
  Annotations,
  inferred domains, and conventions are non-citable: they inform
  which inputs to probe but create no rejection obligation. A
  closed raise-condition enumeration can't be flag-violated by
  type alone. A rule invented by the runner (not in the spec,
  types, or impl's documented contract) is a manufactured rule,
  not a defect.
- **Entry-point x input-class closure (Phase 2, BEFORE decomposition):**
  build a CLASS REGISTRY first: each domain rule (grammar
  productions, type-conversion contracts, magic-method/protocol
  contracts) reifies its input classes ONCE as named rows — BOTH
  the accepted and rejected members of each class (a grammar's
  failure-side tokens, a conversion's failure classes). The
  registry must also include DOMAIN-EDGE members — inputs whose
  membership in the declared class is itself ambiguous, not just
  members adjacent to declared bounds. Every numeric domain gets
  its non-finite members (NaN, +inf, -inf for floats); every
  int-declared domain gets its adjacent-type members (float,
  bool, numeric string, underscored literal forms); every
  string domain gets its edge members (empty, unicode, NUL,
  whitespace-only). Guards written as comparison chains
  (x <= 0, x < n) silently admit non-finite members — these are
  where spec-impl divergences live, not at the declared bounds.
  Then enumerate public entry points AND role-tag each acceptor per
  domain rule:
  * DECIDING (the acceptor that applies the rule, incl. mode/flag
    variants that change the rule's grammar) — gets FULL class
    closure;
  * FORWARDING (passes the input through to a decider) — gets ONE
    probe per contract it adds (e.g. error-type mapping, return
    normalization), not the full class replay.
  Each obligated cell -> exactly one test. Literal cross-file
  duplicates violate bijectivity.
- **Cross-acceptor member transfer (generative):** when two or more
  acceptors accept the SAME domain field under different strictness
  (e.g. a grammar-strict parser vs a permissive constructor), the
  registry is reusable across doors. Re-offer EVERY member of the
  strictest acceptor's registry — including its invalid members —
  to each laxer acceptor of that field, one probe per member.
  Members the lax acceptor admits are spelling variants: enter them
  into the field x consumer matrix and probe each consumer cell
  (eq, hash, ordering, serialization) with them. This is where
  contract violations hide — an acceptor admitting a spelling its
  own consumers diverge on. Members that transfer get ledger tags;
  members that don't get skips.
- **Skipped-artifact rule:** every mandated Phase-2 artifact must
  either exist in TEST_DESIGN or be dispositioned with a reason —
  an absent artifact with no disposition is a failed self-review.
- **No-cell-veto:** a defect flag cannot remove a closure/registry
  cell. When doc and impl disagree, emit BOTH the pinned-behavior
  test and the defect flag — the suite's green pins stay
  representative of observable behavior.
- **Field x consumer matrix (Phase 2, BEFORE any decomposition):**
  for every stateful/semantic type, build a table of stored fields x
  semantic consumers (equality, ordering, hashing, serialization,
  repr). Each cell: RAW (consumed as stored) / NORM (transformed) /
  IGNORED. Shape-checkable: |fields| x |consumers| cells — an absent
  or incomplete table fails the self-review. Every cell must be
  WRITTEN explicitly — a one-line prose summary ("field X is NORM-
  compared") is an incomplete table: consumers not assigned a cell
  value derive no axes. Label cells EMPIRICALLY:
  feed each field two spellings that differ only in surface form
  (zero-padding, case, separators, unicode equivalents) and observe
  whether the consumer treats them identically — identical outcome =
  NORM, different = RAW, no effect = IGNORED. Do not label by field
  name or by "it looks like a string". Any field that is NORM under
  one consumer but RAW under another is a mandated eq/contract
  axis row — no cluster may omit it on scope grounds; a field NORM
  under ANY consumer but whose differing spellings are reachable
  (different construction paths accept different surfaces) is also
  a mandated axis row.
- **Artifact ownership:** artifacts whose inputs span more than one
  module/cluster (the field x consumer matrix, the equivalence-axis
  table, the global requirements model, the fact<->test join) are
  ORCHESTRATOR-ONLY — never delegated. Slices receive the finished
  matrix as input, they don't build it.
- **Falsifier citation (per test):** every test must name the
  concrete deviation it detects — a specific mutant it kills, a
  spec clause it would fail under, or an input class no other test
  discriminates. Write it in the test inventory (element -> mutant/
  discriminating input). "No deviation -> no test": interpreter-
  guaranteed semantics (language container axioms on identical
  objects, import smoke checks) are exempt from contract-axis rows —
  axes require DIFFERENT input spellings by definition.
- **Predicate-space enumeration:** each unit's input space is wider
  than its signature. For every ledger obligation enumerate ALL
  members of the predicate's domain: declared params, computed/
  derived features the predicate branches on, protocol/duck-type
  operand kinds the unit dispatches on, and ambient/module-level
  state the code reads (env vars, module attrs, global config).
  A guard on module state has a domain — every member of it is an
  obligation like any other.
- **Degenerate-measurement audit (pre-freeze):** for every bound or
  partition on a DERIVED measure (a computed quantity, an aggregate,
  a normalized form), enumerate the constituent configs that
  collapse it to identity — a zero constituent makes a difference
  equal its total (derived = total - constituent), a factor of 1
  makes a product the identity, a no-op normalization makes RAW and
  NORM indistinguishable. A bound
  tested only at degenerate constituents witnesses NOTHING: each
  derived-measure bound needs at least one member where the
  constituent values differ (non-zero state, non-unit factor,
  distinguishing normalization).
- **Member-granularity join (the ledger's resolution):** a ledger row
  containing an enumeration (N members, an alias family, a charset, a
  sub-class list) reifies as N cells at reconcile time — each member
  needs a witness or a declared fold. The join runs at MEMBER
  granularity, not row granularity: a row's budget is not satisfied
  by one case when the row names seven members. "The same root
  cause" folds must name the constituent members they cover — an
  undeclared fold of two predicates' mutants into one kill is a
  hole, not a join.
- **Mutant-first member enumeration (the completeness bound):** free-
  form member lists have no stopping rule — build them mutant-first.
  For each DECIDING predicate enumerate its mutant menu: operator
  swaps, normalization/canonicalization key swaps, per-element<->
  aggregate swaps, type-check narrowing/widening, eager<->lazy
  evaluation, swallow<->propagate. Every enumerated mutant needs a
  killing member; a member that kills nothing is a fold candidate.
  The outcome partition (raise vs return-vs) bounds membership, not
  the input spelling.
- **Obligation ledger (Phase 2-3, THE join):** enumerate obligations
  at cell granularity, each bound to exactly one witness test:
  (a) every decision-table / partition cell — INCLUDING derived-
  measure partitions crossed with the input's own domain regions
  (if the predicate classifies on a computed feature, its regions
  cross the input's regions);
  (b) every numeric bound BOTH sides — every bound in the model
  MUST appear in the domain-spec list fed to the boundary script;
  an enumerated bound with no domain-spec row is a skipped
  obligation;
  (c) every class-registry x acceptor cell;
  (d) every field x consumer axis row;
  (e) every spec-silent pin.
  Folds must be DECLARED in TEST_DESIGN (which obligations share a
  witness) — a cell with no witness and no declared fold is a hole;
  a witness bound to no obligation is a redundant test.
  The POST-FOLD ledger total is the ONE frozen budget — heuristic
  category estimates and cell counts before folds are inputs, never
  authorities. Emitted count must equal the ledger total; the
  budget table's rows must sum to it.
  The ledger must ALSO be emitted as a machine-readable fenced
  ```ledger YAML block inside TEST_DESIGN.md (member census —
  reverse reconciliation: enumerate first, tag each member, so a
  drop BETWEEN enumeration and emission is countable):
    obligations: [{id, kind, members: [...]}]  # members = DOMAIN
                                              # members enumerated at
                                              # model time (class
                                              # members, spelling
                                              # variants, grid cells)
                                              # — NEVER collected
                                              # test items back-formed
                                              # from the suite; that
                                              # makes the join
                                              # tautological
    witnesses:  [{test, covers: [{obligation, members: [...]}]}]
    folds:      [{obligation, member, fold_into, reason}]
    budget: N
  Run scripts/ledger_reconcile.py TEST_DESIGN.md — it joins at MEMBER
  granularity: every member must be witnessed or folded;
  a member in neither is a hole; a test covering no obligation is
  redundant; sums must match. The census anchors on the ENUMERATION
  side — audits of emitted tests alone cannot detect a member that
  was never emitted.
- **Matrix→axis derivation (forced join):** the field×consumer matrix
  is not a terminal artifact — every cell whose field semantics
  differ across consumers (normalized vs raw, compared vs ignored)
  must DERIVE an axis-table row enumerating the discriminating input
  spellings, and every spelling is an obligation member. A matrix
  cell that generates no axis row and no witness is an unforced
  obligation — the most common defect-flag miss.
- **Fact<->test join (mandatory, bidirectional):** every element of
  the requirements model — each rule row, boundary entry, axis-table
  row, spec-silent pin, delegation edge — must name >=1 test id in
  the TEST_DESIGN inventory, and every test must trace to exactly one
  element. Elements with no test are either emitted or dispositioned;
  "unreachable" requires exhausting the technique CLASSES per domain
  member, not just citing attempts: subprocess, import machinery
  (import the module and call the guarded code in-process), module-
  state patch (patch the ambient attr the guard reads), and entry-
  point emulation. Two same-class attempts do not exhaust the menu.
  An entry point is reachable in-process: importing `pkg.__main__`
  and calling its guarded code under a state patch is a traceable
  witness; a subprocess test is behavior-real but untraceable.
- **Public-surface completeness:** the unit inventory enumerates
  module __all__, module-level functions, magic-method protocols
  (__eq__/__hash__/__getitem__/__index__/dunders), subclass
  preservation of returned types, and delegation edges (a wrapper
  inherits the delegate's domain). DEPRECATED and COMPAT surfaces
  are obligations too — deprecated wrappers, CLI/module re-exports,
  and legacy-format members (old counter schemes, historical
  spellings the spec preserves) are systematically under-enumerated;
  each gets the same contract probes as its modern replacement
  plus its own deprecation/rollover semantics. If the repo ships
  doctests, include a doctest run.
- **Reconcile claims vs measured output:** write the self-review
  checklist AFTER running the suite+coverage, and reconcile every
  claim against the tool output (a claimed boundary that no collected
  test hits is a false claim — fix the test or the claim). Budgets
  are FROZEN at Phase 3: the numbers reported are the numbers
  in TEST_DESIGN verbatim — never restate a planned count after
  emission. No placeholder text ships in final artifacts.
- **Parametrize assertion collections:** a loop over a list of
  (input, expected) pairs inside one test = the first failure hides
  the rest. These belong in parametrize marks.
- **Coverage is evidence, not the goal.** 100% line+branch can still
  miss spec violations: values asserted nowhere, oracles that mirror
  the impl, boundaries tested on one side only, mutants that survive.
  The mutation-audit checklist (categories/mutation-testing.md) is the
  verification step coverage can't replace — run it mentally per unit
  even when a mutation tool isn't available.

## Phase 6 — Deliver
```
<out dir>/
  TEST_DESIGN.md     # sections below
  tests/test_*.py    # or <Unit>Test.java etc.
```
- **Env isolation for spawned-process/entry-point tests:** a test
  invoking a subprocess, CLI main, or module run must construct its
  own env/paths explicitly — inheriting the harness's ambient
  PYTHONPATH/cwd makes the test non-self-contained (passes only
  because the caller set the env). Suite bootstrap (conftest etc.)
  must inject a src path only as FALLBACK when the package isn't
  already importable (e.g. `find_spec` guard) — never pin a source
  path ahead of PYTHONPATH; harnesses swap implementations via
  PYTHONPATH. Verify constructed paths exist (fixture-resolved or
  os.path checks), don't assume them.

TEST_DESIGN.md sections (all required, `- (none)` when empty):
1. Requirements model (table: ID | unit | rule)
2. Formal models (decision tables, state grids, domain specs)
3. Test budget (unit x category -> planned count + formula used)
4. Test inventory (test name -> requirement IDs + category)
5. Suspected defects (spec-vs-impl divergences found by the suite)
6. Self-review (the checklist below, answered)

# Scaling with subagents — MANDATORY for large projects
- Small repo (< ~15 public units): do it inline.
- Anything larger: you MUST decompose with subagents. After Phases
  1-2 (the requirements model is global — one mind builds it), spawn
  ONE subagent per module/cluster with: the relevant slice of the
  requirements model, the category files needed, and the output spec.
  You integrate their test files and run verification yourself.
- Also use a subagent for any module whose source exceeds your
  comfortable reading size — incomplete reads produce incomplete
  models.
- Never split the requirements model across agents — inconsistent
  models produce inconsistent tests.
- If your harness exposes a subagent mechanism (delegate_task,
  run_subagent, Agent tool), use it; if none exists, simulate by
  processing one module per pass and writing intermediate model
  files to disk so no module's detail is ever dropped.

# Python/Java notes
- Python: prefer `pytest.mark.parametrize` over loops of test
  functions; use `pytest.raises` with `match=` only when the spec pins
  the message. Use type annotations to bound domains — e.g. an
  `Optional[X]` param gets a None case; an int param gets its stated
  bounds. `from __future__`/`pydantic`/dataclass types all count.
  Annotations bound what inputs to TRY, never what the impl must
  REJECT — they are advisory metadata unless a behavioral clause
  (docstring, README, error spec) states the rejection.
- Java: JUnit5 `@ParameterizedTest` + `@MethodSource`/`@CsvSource`;
  AssertJ or plain assertEquals. Checkstyle-style naming not required.
- Other languages: same method, idiomatic framework.

# Self-review (run before delivering — answer each line)
- [ ] Every public unit has >=1 requirement row; every row has >=1 test.
- [ ] Every decision-table column, legal arc, illegal grid cell,
      boundary edge, and MC/DC proving row maps to a test.
- [ ] Every documented raise/error class has a test asserting the
      documented exception type.
- [ ] Contract axioms (eq->hash, ordering, roundtrip) tested for every
      public value type.
- [ ] Total count <= budget + justified extras. Any test not tied to a
      rule was deleted.
- [ ] Suite runs; pass/fail state reconciled vs Suspected defects.
- [ ] Branch coverage measured; uncovered lines dispositioned.
- [ ] TEST_DESIGN has all 6 sections; every budget formula named.
