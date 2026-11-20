# Contract & Invariant Testing

Language/library contracts every type must honor, plus type-specific
invariants. Highest bug-finding yield per test written.

## Method
For each public type/value object, test the contract axioms with
concrete instances:

- Equality/hash: a==b implies hash(a)==hash(b); equal objects behave
  identically in set membership and dict lookup. Construct equal
  objects via DIFFERENT input spellings — alternate representations,
  canonical vs non-canonical forms, equivalent syntaxes — that is
  where these
  contracts break.
- Ordering consistency: a<b and b<c -> a<c; cmp==0 iff eq; compare
  agrees with eq/ne/lt/le/gt/ge.
- Roundtrips: parse(str(x))==x; serialize->deserialize==x;
  encode->decode==x — when both directions are public.
- Immutability: mutating-looking ops on "immutable" objects return new
  objects and leave the original unchanged.
- Algebraic: idempotence, commutativity, associativity, identity/
  absorbing elements where the spec claims them.
- Copy semantics: copy/deepcopy equality; independence after copy.

## Budget
~2-4 tests per applicable axiom per public type. Small count,
disproportionate value — never skip.

## Equivalence-axis table (mandatory artifact, matrix-driven)
The axis table is DERIVED from the field x consumer matrix (SKILL.md
Phase 2) — it is an ORCHESTRATOR artifact, never per-cluster. WRITE
the matrix AND the table into TEST_DESIGN: checklist claims about
either without the artifact are false claims.
Row sources, all mandatory:
1. Every field that is NORM under one consumer and RAW under another
   in the matrix — that mismatch IS the axis.
2. Construction-side spellings: alternate representations of equal
   inputs (value-equal spellings a normalizer might collapse,
   alternate orderings or encodings of the same meaning, redundant
   sub-expressions), distinct APIs reaching the same object with
   different acceptance criteria, subclass/base.
3. Model facts: EVERY "X == Y under normalization N" fact in the
   requirements model MUST appear as a row — do not file
   normalization behavior under compare-semantics only.
For EACH axis emit a row asserting: a==b, hash(a)==hash(b),
len({a,b})==1, and dict/set membership of b in {a}. Axes require
DIFFERENT input spellings — an axis whose two sides are the SAME
object/member is interpreter-guaranteed, not a contract test; skip
it. If an axis fails, that is a suspected defect — keep the test.

## Checklist
- [ ] equivalence-axis table lists every eq/hash divergence axis and
      each has eq+hash+set+dict rows (grep-checkable)
- [ ] eq->hash contract tested with alternate spellings of equal values
- [ ] container-membership consistency (set/dict) on equal objects
- [ ] every public roundtrip pair tested
- [ ] ordering total and consistent with equality
