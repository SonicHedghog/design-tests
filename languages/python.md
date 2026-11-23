# Python — language-specific test obligations

Load when the target is Python. These are ADDITIONAL obligation
sources beyond the generic method: language-level contracts and
domain classes that specs rarely state but implementations must
honor. Fold each relevant one into the class registry and ledger.
Items tagged (3.N+) exist only on newer interpreters — match the
target's floor version before minting members.

## Dunder / value-object contracts (axiom obligations)

When a type defines `__eq__`, `__hash__`, ordering, or repr:

- **eq→hash**: `a == b` MUST imply `hash(a) == hash(b)`. Probe with
  every pair of objects that compare equal but were built from
  different surface spellings — that is where this axiom breaks.
  Also hash invariance: same value hashed twice, hash stable across
  immutable-copy operations.
- **eq laws**: reflexive (`a == a`), symmetric, transitive,
  non-equal to `NotImplemented`/`None`/unrelated types. For
  cross-type eq, probe both operand orders — asymmetry bugs hide
  in which side's `__eq__`/`__ne__`/`__ge__` fires.
- **eq fallback is identity**: when both `__eq__`s return
  `NotImplemented`, `a == b` falls back to `a is b` — eq NEVER
  raises TypeError (`1 == "a"` → False). Ordering ops DO raise —
  `1 < "a"` → TypeError. eq-vs-ordering is a divergence class:
  every type pair has (eq-false, ordering-raise) members.
- **`__eq__` may return non-bool**: `a == b` yields whatever
  `__eq__` returns (vectorized types return elementwise results) —
  the caller's truthiness check then decides and may itself raise.
- **`!=` is derived**: `__ne__` defaults to inverting `__eq__`
  (py3) — a stale hand-written `__ne__` can diverge; probe both
  `==` and `!=` spellings on every eq class.
- **Ordering**: total-order implications (`a < b` iff `b > a`;
  `<` and `==` mutually exclusive); each ordering dunder is
  independent — `__lt__` alone gives no `__le__`;
  `total_ordering`-generated dunders must agree with hand-written
  ones.
- **repr/parse round-trip**: where a repr or str exists that a
  parser/constructor can re-read, `parse(str(x)) == x` — or flag
  the documented gap.
- **`__len__`/truthiness**: `len(x) == 0` iff `not x` unless the
  type deliberately breaks it; `__bool__`/`__len__` divergence
  between the two is a defect class. The contract has typed
  failure surfaces: `__bool__` returning non-bool → TypeError;
  `__len__` returning non-int → TypeError, negative → ValueError,
  > `sys.maxsize` → OverflowError.
- **`__hash__` mutability**: defining `__eq__` without `__hash__`
  sets `__hash__ = None` — the type is unhashable; test both
  intended and unintended hashability. Setting `__hash__ = None`
  deliberately is the other door.
- **`__init__` return**: must return None — returning a value →
  TypeError.
- **`__slots__`**: if declared, attribute assignment outside the
  slots must reject — a distinct probe from ordinary attr tests.
  Slots also drop `__dict__` (no `vars()`) and `__weakref__`
  unless listed; a subclass declared WITHOUT `__slots__` regains
  `__dict__` — the slot contract is not inherited.
- **Subclass contract**: methods documented "to allow subclasses"
  (classmethod constructors, factory methods) must preserve the
  subclass through the operation — `type(result) is type(sub)`
  not the base. Builtin types do NOT honor this: `str`/`int`
  subclass methods (`lower`, `+`, `[1:]`) return the BASE type —
  subclass preservation must be implemented, not assumed.
- **hash sentinels**: `hash(-1) == -2` (-1 is the C-level error
  sentinel) — code inspecting raw `hash()` output sees -2 for -1.
  The numeric tower hashes equal values equal:
  `hash(1) == hash(1.0) == hash(True) == hash(Fraction(1)) ==
  hash(Decimal(1)) == hash(1+0j)` — a custom numeric that
  eq-compares to builtins must hash-match or dict/set membership
  diverges from `==`.
- **Immutable-base construction**: an immutable subclass's value
  (`int`/`str`/`tuple`/`frozenset`) is fixed in `__new__`, not
  `__init__` — a subclass computing its value in `__init__`
  silently keeps the base's. `bool` accepts NO subclasses:
  `class X(bool)` → TypeError.

## Attribute & object-protocol contracts

- **Lookup order**: `__getattribute__` fires on EVERY access and
  must not self-recurse (route through `object.__getattribute__`
  or `super()`); `__getattr__` fires only AFTER normal lookup
  fails — an existing class/instance attr never reaches it.
- **Implicit dunder dispatch bypasses the instance**: `len(obj)`,
  `a + b`, `for x in obj`, `x in obj` look the dunder up on
  `type(obj)` — instance attributes named `__len__`/`__add__` are
  ignored AND `__getattr__`/`__getattribute__` are not consulted.
  Explicit `obj.__len__()` DOES see them — explicit-vs-implicit
  is a distinct member pair.
- **Descriptor precedence**: a data descriptor (`__get__` +
  `__set__`/`__delete__`, e.g. `property`) beats the instance
  dict — a setter-less `property` rejects `obj.x = v` with
  AttributeError, not silent shadowing; a non-data descriptor
  (plain functions → methods) loses — `obj.method = f` shadows
  the class method. `__set_name__` fires at class creation with
  (owner, name) — lazily-computed keys break under
  renaming/inheritance.
- **`__contains__` fallback chain**: `x in obj` tries
  `__contains__`, then `__iter__`, then the `__getitem__`
  sequence protocol — a `__getitem__`-only class IS iterable via
  `iter()` but `isinstance(x, collections.abc.Iterable)` is False
  (the ABC checks `__iter__` only). Reachable-via-protocol vs
  registered-via-ABC are different doors.
- **Iterator contract**: `__iter__` must return an ITERATOR
  (else TypeError); `__next__` raises `StopIteration` to end;
  once exhausted an iterator stays exhausted (builtin iterators
  do) — a self-rewinding `__next__` breaks `for`/`zip`/`dict`
  consumers' assumptions.
- **`iter` two doors**: `iter(obj)` needs `__iter__` or the
  `__getitem__` sequence protocol; `iter(callable, sentinel)`
  calls until the sentinel returns — different domains, different
  stop conditions.
- **Context-manager contract**: `with X() as t` binds `t` to
  `__enter__`'s RETURN, not `X()`. `__exit__(exc_type, exc, tb)`
  receives `(None, None, None)` on clean exit; returning truthy
  SUPPRESSES the in-flight exception — suppress-vs-propagate is
  THE boundary to pin; an exception raised inside `__exit__`
  replaces the original.
- **`@contextlib.contextmanager`**: the generator must yield
  EXACTLY once; the `as` target binds the yielded value; an
  exception in the body is thrown INTO the generator at the
  yield — suppressing means catching without re-raising.
- **copy/deepcopy protocol**: `__copy__()` /
  `__deepcopy__(memo)` customize; a shallow copy shares nested
  objects; `deepcopy` keys `memo` on `id()` so shared refs stay
  shared and cycles survive — a hand-rolled deepcopy that drops
  `memo` re-clones shared subgraphs and recurses forever on
  cycles. `copy.copy` preserves the runtime class; slicing
  (`x[:]`) on a list/str subclass returns the BASE type.
- **pickle protocol**: instances pickle by value (default state
  is `__dict__`); classes/functions pickle by qualified NAME —
  renamed/moved/lambda/closure targets fail to dump
  ("Can't pickle ... attribute lookup failed"). Customization
  order: `__reduce_ex__` → `__reduce__` →
  `__getstate__`/`__setstate__` (+ `__getnewargs_ex__` for ctor
  args). `pickle.loads` executes arbitrary code — untrusted
  payloads are a security surface, not a round-trip class.
- **`__format__`**: `format(x, spec)` / `f"{x:spec}"` /
  `"{:spec}".format(x)` all dispatch to `type(x).__format__`;
  must return `str` else TypeError. `object.__format__` accepts
  ONLY the empty spec (`format(obj, "x")` → TypeError) — a type
  documenting "formats like str" must delegate itself.
- **`__missing__`**: the dict-subclass hook fires on `d[k]` ONLY —
  `.get`, `in`, `setdefault` never consult it; each accessor is
  a separate door.
- **`__del__`**: no timing guarantee (refcount vs cyclic GC vs
  interpreter shutdown); at shutdown module globals may already
  be torn down — `__del__` reading module-level names can see
  None. Exceptions in `__del__` are printed, not raised.
- **`hasattr`/`getattr` semantics**: `hasattr` returns False ONLY
  on AttributeError — `__getattr__` raising anything else
  propagates; `getattr(o, n, d)` substitutes only for the
  missing-attr door — a stored falsy value is returned, not
  replaced. `getattr` does NOT traverse dots (that is
  `operator.attrgetter`).

## Operator dispatch & expression semantics

- **Binary-op dance**: `a + b` calls `type(a).__add__(a, b)`; on
  `NotImplemented` it tries `type(b).__radd__(b, a)`; both
  `NotImplemented` → TypeError. If `type(b)` is a SUBCLASS of
  `type(a)` and overrides the reflected op, `__radd__` goes
  FIRST — subclass-priority inversions hide in mixed-type
  arithmetic.
- **`NotImplemented` vs `NotImplementedError`**: dunders RETURN
  the singleton to decline dispatch; raising the exception type
  is a different, louder behavior — don't conflate.
- **In-place ops**: `x += y` uses `__iadd__` if defined, else
  `__add__` + rebind — for immutables it rebinds, for lists it
  mutates IN PLACE (aliases see it) and accepts ANY iterable:
  `[1] + (2,)` → TypeError but `l += (2,)` works. `+` is
  type-strict, `+=` is iterable-lenient — asymmetric members.
- **Mutate-then-raise**: `t[0] += x` on a tuple-of-lists RAISES
  TypeError AFTER `__iadd__` already mutated the list — state
  left changed under a raise surface.
- **Comparison chaining**: `a < b() < c` evaluates `b()` ONCE
  (middle operand cached) — side-effecting middles discriminate.
  `in`/`is` chain too: `x in seq == True` parses as
  `(x in seq) and (seq == True)` → False — NOT "membership is
  True".
- **`and`/`or` return operands**: `a or b` yields `a` if truthy
  else `b` — never a bool unless the operand is. `x or default`
  collapses EVERY falsy member (0, "", [], None, False) to
  default — spec-meaning-None vs spec-admits-falsy is a required
  class. `not x` is the only guaranteed bool-coercer.
- **Unary `+` is a contract**: `+x` calls `__pos__` — for Decimal
  it APPLIES context rounding (can change the value); a
  pass-through spec still gets a door.
- **Precedence traps**: `**` binds tighter than unary minus —
  `-2**2 == -4`; `**` is right-associative — `2**3**2 == 512`;
  `not a == b` is `not (a == b)`; `a is not b`/`a not in b` are
  single operators.
- **`match` (3.10+)**: a BARE name `case x:` binds anything — a
  capture, not a value check; value matching needs a literal or
  dotted name (`case Color.RED:`). Sequence patterns
  (`case [a, *rest]`), class patterns (`case P(x=0)`), and
  guards (`case p if cond`) are each distinct surfaces.
- **Walrus `:=`**: inside a comprehension it binds the ENCLOSING
  scope (`[y for x in it if (y := f(x))]` leaks `y`) while the
  comp's own loop var does not leak — scope asymmetry is
  testable.

## Numeric domain edges (registry members)

- **Non-finite**: `float("nan")` compares False with EVERYTHING
  including itself — `nan != nan` is True. Any guard written as
  `x <= bound` / `x >= bound` / `x == bound` silently admits NaN:
  it walks past the guard unguarded — and `bool(nan)` is True,
  so truthiness guards admit it too. NaN, `inf`, `-inf` are
  required members of every float-admitting domain.
- **NaN order-dependence**: `max(nan, 1)` → nan but
  `max(1, nan)` → 1 (first arg wins when comparisons fail);
  `sorted` places nan arbitrarily — no error, no ordering.
  `math.isnan`/`isinf`/`isfinite` are the only reliable guards.
- **`bool` IS `int`**: `True == 1`, `isinstance(True, int)` is
  True, `True + True == 2`, `hash(True) == hash(1)`,
  `"x" * True` works. Where the spec means "integer", bool is a
  smuggled member of both the valid and invalid classes — probe
  it. Mixed-key dicts merge: `{1: "a", 1.0: "b", True: "c"}` is
  ONE key.
- **int is unbounded**: no overflow — but check code that assumes
  fixed-width semantics: `float(10**400)` → OverflowError while
  `float("1e309")` → inf (the int→float door RAISES where the
  str→float door saturates); `to_bytes` too-small →
  OverflowError; `~x == -x-1`; `x << -1`/`x >> -1` → ValueError.
- **2^53 precision cliff**: ints beyond float precision lose
  bits silently — `float(2**53 + 1) == 2**53` is True;
  int→float→int round-trips degrade above 2^53 — required
  members wherever ints route through float (JSON numbers!).
- **`int()` conversion leniency**: accepts leading/trailing
  whitespace (incl. Unicode), `+`/`-`, single underscores BETWEEN
  digits (`"1_000"` — `"_1"`, `"1_"`, `"1__0"` all fail), and
  Unicode decimal digits (`int("١٢٣")` → 123). It REJECTS float
  syntax — `int("1e20")`, `int("1.5")` → ValueError: str→int and
  str→float are different grammars. "Int-declared" params admit
  far more than ASCII digits.
- **`int()`/`round()` on non-finite**: `int(3.9)` TRUNCATES
  toward zero (`int(-3.9)` → -3 vs `-3.9 // 1` → -4.0 floor —
  trunc-vs-floor diverges on negatives). `int(nan)` →
  ValueError but `int(inf)` → OverflowError; `round(nan)` →
  ValueError, `round(inf)` → OverflowError — divergent surfaces
  per non-finite member.
- **`float()` grammar**: accepts "inf"/"infinity"/"nan" (any
  case, signed), surrounding whitespace, underscores between
  digits, and Unicode digits (`float("١.٥")` → 1.5).
- **Base-0 literal grammar**: `int(s, 0)` follows literal syntax
  — `int("0x10", 0)` → 16 but `int("010", 0)` → ValueError
  (leading zeros rejected); `int(x, base)` accepts only str.
- **Float equality**: `0.1 + 0.2 != 0.3`. `repr` gives the
  SHORTEST round-trip string since 3.1 (`float(repr(x)) == x`
  guaranteed); the stored value is `x.as_integer_ratio()`
  (0.1 is 3602879701896397/36028797018963968). `float.hex()`/
  `float.fromhex()` is the exact-lossless door; `math.isclose`,
  `nextafter`, `ulp` are the comparison doors.
- **Rounding is half-even everywhere**: `round(2.5) == 2`,
  `round(3.5) == 4`, `round(25, -1) == 20`, `f"{2.5:.0f}"` →
  '2' — and `round(2.675, 2)` → 2.67 because the stored value is
  below .675, not because the rule broke. `round(x)` → int,
  `round(x, n)` → the input's type. Never pin naive decimal
  expectations.
- **Division taxonomy**: `/` ALWAYS returns float (`4/2` → 2.0);
  `//` floors the quotient but the RESULT TYPE follows operands
  (`7 // 2` → 3, `7.0 // 2` → 3.0, `inf // 2` → nan);
  `x / 0`, `x // 0`, `x % 0` ALL → ZeroDivisionError — pure-
  Python floats do NOT yield inf on divide-by-zero (numpy does;
  Decimal only when the context trap is cleared).
- **`%` vs `fmod` sign rules**: `a % b` takes the DIVISOR's sign
  (`-7 % 2` → 1, `7 % -2` → -1); `math.fmod` takes the
  DIVIDEND's (`fmod(-7, 2)` → -1.0). The invariant to assert:
  `divmod(a, b) == (a//b, a%b)` and `a == b*(a//b) + a%b` — on
  both signs of both operands.
- **`pow` forms**: `pow(2, 3, 5)` is int-only (floats →
  TypeError); `pow(2, -1, 5)` → 3 (modular inverse, 3.8+);
  `pow(0, -1)` → ZeroDivisionError; `0 ** 0` → 1. `**` on a
  negative base with fractional exponent returns COMPLEX —
  `(-1) ** 0.5` → ~1j — while `math.sqrt(-1)` → ValueError and
  `cmath.sqrt(-1)` → 1j: three doors for the same input.
- **Overflow/underflow**: float arithmetic saturates silently —
  `1e308 * 10` → inf, `inf + 1 == inf`, `inf - inf` → nan;
  underflow → 0.0 silently (`1e-320 * 1e-10` → 0.0). But
  `math.exp(1000)` RAISES OverflowError — per-function trap
  surfaces differ. `sys.float_info`: `.max` = largest FINITE,
  `.min` = smallest NORMALIZED (denormals reach ~5e-324),
  `.epsilon` = ulp of 1.0.
- **Signed zero**: `0.0 == -0.0` is True and hashes equal, but
  `repr(-0.0)` → '-0.0' and `math.copysign` distinguishes —
  sign-of-zero is a hidden member wherever sign reaches output.
- **Decimal**: `Decimal("0.1")` ≠ `Decimal(0.1)` (decimal string
  vs the float's full binary expansion — two members);
  `Decimal + float` → TypeError but `Decimal < float` COMPARES
  (asymmetric coercion); `Decimal("NaN") < 1` →
  `decimal.InvalidOperation` while `==` → False; arithmetic runs
  under a thread-local context (prec 28, ROUND_HALF_EVEN default)
  with per-signal traps — `/0` raises `decimal.DivisionByZero`
  by default but yields Infinity when the trap is cleared.
- **Fraction**: auto-reduces (`Fraction(2,4)` → 1/2);
  `Fraction(0.1)` takes the float's exact binary value but
  `Fraction("0.1")` the decimal; `Fraction("1/2")` parses;
  `Fraction(1,0)` → ZeroDivisionError; `limit_denominator` is a
  normalization door.
- **complex**: equality works (`1+0j == 1`), ordering →
  TypeError; `abs` → magnitude float; `//`, `%`, `divmod` →
  TypeError; `bool(0j)` is False.
- **`numbers` ABC**: `Integral`/`Rational`/`Real`/`Complex` are
  isinstance-doors (`isinstance(True, numbers.Integral)` →
  True); `Decimal` registers as `Number` only — NOT `Real`:
  arithmetic acceptance and ABC membership do not line up.
- **`sum`**: starts at int 0 — `sum([])` → 0 (int, not float);
  float drift accumulates (`sum` vs `math.fsum` is a precision
  class); `sum` on strings → TypeError pointing at `join`.

## String / Unicode domain edges

- **Classification breadth differs**: `isdecimal` ⊂ `isdigit` ⊂
  `isnumeric`. Superscripts (`"²"`), fractions (`"½"`), CJK
  numerals (`"四"`), and non-ASCII digits (`"٢"`, full-width)
  classify True under some predicates and not others — and
  `int()` accepts only the decimal subset (`int("²")` →
  ValueError while `"²".isdigit()` is True). If code gates on
  `isdigit()` intending "ASCII 0-9", non-ASCII digits are a
  bypass class; `string.digits` IS ASCII-only — pairing a
  Unicode predicate with an ASCII constant is the mismatch shape.
- **Normalization is not eq**: `"é"` (NFC) vs `"e\u0301"` (NFD)
  compare UNEQUAL with different `len` — `unicodedata.normalize`
  is the canonicalization door; NFKC folds compatibility chars
  (`"ﬁ"` → "fi", `"²"` → "2"). Inputs differing only in
  normalization are required spelling-variant members.
- **Empty vs None**: `""` is falsy but is NOT `None` — APIs that
  treat missing-vs-empty differently are a classic divergence
  point. Empty string is a required member of every string
  domain, alongside whitespace-only, NUL (`"\x00"`), and
  Unicode-whitespace (`"\xa0"`, `"\u2028"`).
- **Membership dual nature**: `"a" in "abc"` is a SUBSTRING test
  vs `"a" in ["abc"]` element; `"" in s` is ALWAYS True;
  `1 in "abc"` → TypeError — the left operand must be str.
  Functions accepting "a string or a list" conflate them.
- **`str` vs `bytes` — no implicit conversion**: `"a" + b"b"` →
  TypeError; `"a" in b"abc"` → TypeError; but `b"a" == "a"` →
  False SILENTLY — cross-type eq never errors and never matches.
  Index asymmetry: `"a"[0]` → "a" (str) but `b"a"[0]` → 97 (int);
  bytes membership accepts int OR bytes (`97 in b"abc"` → True).
- **Encoding doors**: `str.encode`/`bytes.decode` default UTF-8;
  `bytes("x")` → TypeError (encoding arg required) while
  `bytes(3)` → `b'\x00\x00\x00'` (zero-fill, not error). `open()`'s
  default encoding is LOCALE-dependent (PEP 686 makes UTF-8 the
  default in 3.15) — text I/O without `encoding=` is
  platform-flaky. `errors="strict|ignore|replace|
  backslashreplace|surrogateescape"` are distinct failure
  surfaces (`b"\xff".decode()` → UnicodeDecodeError).
- **casefold vs lower vs upper**: `casefold()` is the aggressive
  Unicode-aware fold for caseless comparison (`"ß".casefold()` →
  "ss"); `lower()` leaves `ß`; `upper()` gives "SS". Which one
  the impl uses determines which spellings normalize.
- **`strip`/`lstrip`/`rstrip` take a CHARSET**: `s.strip("ac")`
  removes any a/c from both ends — not a substring strip; the
  no-arg form strips the Unicode whitespace class (incl `\xa0`),
  not "spaces". `removeprefix`/`removesuffix` (3.9+) remove a
  literal affix and return an UNCHANGED copy when absent.
- **`split` family**: `s.split()` no-arg splits on whitespace
  RUNS and trims — `" a  b ".split()` → ['a','b'] vs
  `.split(" ")` → ['', 'a', '', 'b', '']; `s.split("")` →
  ValueError; `rsplit(..., maxsplit)` counts from the RIGHT;
  `splitlines()` splits on ~20 boundary types (`\r`, `\v`, `\f`,
  `\x1c-\x1e`, `\x85`, `\u2028/\u2029`) — far broader than
  `split("\n")`; `partition`/`rpartition` always return a
  3-tuple.
- **Search duality**: `find`/`rfind` → -1 on miss vs
  `index`/`rindex` → ValueError; `count` is NON-overlapping
  (`"aaa".count("aa")` → 1); `startswith`/`endswith` accept a
  TUPLE of candidates.
- **`replace` replaces all** by default (the count arg bounds
  it); an absent needle returns an equal copy — no error.
- **`join` requires str elements**: `",".join([1])` → TypeError
  naming the bad index; consumes an iterator in ONE pass.
- **String ordering is code-point order**: `"Z" < "a"` (uppercase
  sorts before lowercase), `"10" < "2"` (lexicographic, not
  numeric) — sorted output on mixed-case/zero-padded data is a
  pin-worthy surface.
- **Casing edges**: `"they're".title()` → "They'Re" (apostrophes
  split words); `"hELLO".capitalize()` → "Hello" (lowercases the
  rest); `zfill` keeps the sign (`"-42".zfill(6)` → "-00042").
- **Implicit literal concatenation**: `"a" "b"` → "ab" at compile
  time — a missing comma in a literal list silently merges two
  members; parametrize tables of strings are the classic victim.
- **`chr`/`ord` bounds**: `chr(0x10FFFF)` is the max —
  `chr(0x110000)` → ValueError; `ord("")`/`ord("ab")` →
  TypeError.
- **str methods return base `str`**: on a `str` subclass,
  `.lower()`/`[1:]`/`+` return plain `str` — subclass behavior
  and state are dropped through the operation.
- **Interning is impl detail**: `"a b" is "a b"` may be True
  (compile-time folding) or False (runtime-built); `sys.intern`
  forces it. `==`-vs-`is` probes must not lean on interning.
- **Formatting coercion diverges per door**: `"%d" % 3.7` → '3'
  (truncates!) where `"{:d}".format(3.7)` → ValueError and
  `f"{3.7:d}"` → ValueError; `"%s" % x` → `str(x)` vs `"%r"` →
  `repr(x)`; `"%(k)s" % dict` is a third grammar; `"%s" %
  ("a","b")` → TypeError (a tuple means multiple args — wrap a
  tuple-valued arg in a 1-tuple); `"{0} {}".format` mixing
  manual+auto numbering → ValueError.
- **f-strings evaluate eagerly in enclosing scope** — the
  expression part runs NOW (side effects execute even when the
  result is later dropped, e.g. a lazy log line); `f"{x=}"`
  debug-expands using repr; nested specs `f"{x:{w}}"` evaluate
  `w`; conversions are `!s`/`!r`/`!a` only. (3.12+: same-quote
  nesting and backslashes in expressions — earlier versions
  SyntaxError.)
- **`str.format` mini-language reaches in**: `{0.x}` / `{0[k]}`
  do attribute/item access on the argument — a user-controlled
  format string is an attribute-traversal door.
- **`re` is Unicode by default** on str patterns: `\d` matches
  `"٢"`, `\w` matches Unicode word chars — `re.ASCII` narrows it.
  A `\d`-gated validator is not an ASCII gate.

## Containers & iteration

- **Slices don't raise**: `seq[2:100]` returns what's available;
  `seq[100]` raises IndexError; `seq[::0]` → ValueError. If a
  docstring promises raise-on-out-of-range, slicing vs indexing
  is a divergence class. Slice assignment RESIZES
  (`a[1:2] = "xyz"` splices); extended-slice assignment
  (`a[::2] = it`) demands EXACT length → ValueError; `del a[i:j]`
  and `del a[::2]` remove by slice.
- **Negative indices**: `seq[-1]` is valid when nonempty — a
  member many domain models miss; `insert` CLAMPS out-of-range
  positions rather than raising.
- **Generators exhaust**: iterating twice yields empty the second
  time; `len()` on a generator raises; and `bool(iter([]))` is
  True — ITERATORS ARE ALWAYS TRUTHY, so `if it:` cannot detect
  exhaustion. `x in it` CONSUMES through `x` — membership on a
  one-shot iterable is destructive. If an API returns an
  iterator vs a sequence, reuse/truthiness/membership are
  obligations.
- **Lazy builtins**: `map`/`filter`/`zip`/`reversed`/`enumerate`
  are single-pass iterators — `sorted`/`list`/`sum`/`"".join`/
  `all`/`any` consume. `zip` silently stops at the SHORTEST
  input — `zip(a, b, strict=True)` (3.10+) → ValueError on
  mismatch; `itertools.zip_longest` pads with `fillvalue`.
- **Mutating during iteration**: list iterators are index-based —
  appends during `for` ARE iterated (`for x in l: l.append(...)`
  can run forever); dict/set raise RuntimeError on size change,
  but reassigning an existing key's VALUE mid-iter is fine —
  only insert/delete keys trip it. Three surfaces for
  "mutate while iterating".
- **Ordering guarantees differ per container**: dict is
  insertion-ordered (guaranteed 3.7+); SET ordering is arbitrary —
  int members may LOOK sorted (impl artifact of small-int
  hashing) while str members are hash-randomized per process —
  a test reading set iteration order is flaky by construction.
- **`==` semantics differ per container**: dict eq ignores order;
  `OrderedDict == OrderedDict` is ORDER-SENSITIVE but
  `OrderedDict == dict` is not; list/tuple eq is positional;
  set/frozenset eq ignores order; `d1.keys() == d2.keys()` is
  set-eq but `d.values() == d.values()` is IDENTITY-eq — always
  False between distinct view objects.
- **dict views are live**: `keys()`/`items()`/`values()` reflect
  later mutation (and `types.MappingProxyType(d)` is a VIEW, not
  a snapshot); materialize with `list()` where a pin is
  intended. `keys()`/`items()` support set algebra; `values()`
  does not; `set(d.items())` needs hashable VALUES.
- **dict accessors have different miss surfaces**: `d[k]` →
  KeyError (and `__missing__` on subclasses — `.get`/`in`/
  `setdefault` never consult it); `d.get(k)` → None —
  indistinguishable from a stored None without a sentinel;
  `setdefault` evaluates its default arg EAGERLY and returns the
  STORED value; `dict.fromkeys(iterable, v)` shares ONE `v`
  across keys — a mutable default aliases every key.
- **Merge/pop semantics**: `d1 | d2` (3.9+)/`update`/
  `{**d1, **d2}` are last-wins; `update` returns None; `|` makes
  a new dict where `|=` mutates. Pop-family empty surfaces
  differ: `d.popitem()` → KeyError, `set.pop()` → KeyError,
  `list.pop()` → IndexError, `deque.popleft()` → IndexError;
  `set.pop()` returns an ARBITRARY element.
- **Hashability gates keys, not membership**: `(1, [2])` is
  unhashable → TypeError as dict key/set member, but
  `[2] in (1, [2])` → True — `in` uses `==`, never hash. A
  tuple/frozenset is hashable only when every leaf is.
- **`in`/`index`/`count` use `==`** (with an `is` shortcut):
  `nan in [nan]` → True for the SAME object, False for a
  different NaN. `list.index`/`tuple.index` raise ValueError —
  NOT IndexError (LookupError is KeyError/IndexError's shared
  parent; `.index` lives under ValueError).
- **set-algebra asymmetry**: `{1} | [2]` → TypeError — the
  operators require set/frozenset on both sides — but
  `.union([2])`/`.intersection`/`.difference`/`.issubset`/
  `.issuperset` accept ANY iterable. Result type follows the
  LEFT operand (`frozenset([1]) | {2}` → frozenset). `{}` is an
  empty DICT — `set()` is the empty set.
- **Mutators return None**: `append`/`extend`/`insert`/`remove`/
  `sort`/`reverse`/`clear`/`update`/`add`/`discard` all return
  None — `l.append(x).sort()` → AttributeError on None. The
  str-side asymmetry (methods return NEW objects) makes
  mutator-vs-transformer expectation swaps a defect class.
- **`clear()` vs rebind**: `l.clear()`/`d.clear()` mutate (all
  aliases see it); `l = []` rebinds (aliases keep the old);
  `a = b = []` binds ONE object to two names.
- **`l.remove(x)`** deletes the FIRST `==` element — with
  equal-but-distinct members, which one dies is a member class.
- **`sorted`/`sort` contract**: stable — equal elements keep
  input order, INCLUDING under `reverse=True` (reverse applies
  after sorting, not by flipping comparisons); `key` is called
  ONCE per element; `list.sort()` → None; `sorted` ALWAYS
  returns a list (`sorted("cab")` → ['a','b','c'], not a str);
  mixed-type input → TypeError mid-sort; sorting needs `__lt__`
  only. If the key/comparison raises, the list may be left
  partially mutated (documented impl detail).
- **Aggregates on empty/type**: `min`/`max` return the FIRST
  extremum on ties and ValueError on empty without `default=`;
  `any([])` → False, `all([])` → True (vacuous members of every
  empty domain); `reduce` on empty without initializer →
  TypeError; `min`/`max`/`sorted`/`for`/`in` on a dict see KEYS.
- **`deque`**: indexable by int but NOT sliceable;
  `extendleft` inserts in REVERSE order; `maxlen` silently
  discards from the opposite end.
- **namedtuple is a tuple**: unpacks, indexes, `==`s against
  plain tuples — two semantic doors for one value; `_replace`
  returns a new object and ValueErrors on unknown field names.
- **Builtin containers bypass subclass methods**: iteration,
  `sort`, `index`, `in` on `list`/`dict` subclasses do NOT call
  overridden `__getitem__`/`__iter__` — `UserList`/`UserDict`/
  `UserString` exist for interceptable behavior; an override
  that "protects" a method is bypassable.
- **`collections` contracts**: `Counter` `-` drops non-positive
  counts while `.subtract` keeps negatives; `most_common` ties
  resolve by first-encounter order; `defaultdict` INSERTS the
  factory product on a `d[k]` miss — a lookup that mutates —
  while `.get(k)` does not; `ChainMap` reads first-match but
  WRITES to maps[0]; `SimpleNamespace` eq compares `__dict__`.
- **`heapq` is min-heap only**: `heap[0]` is smallest; elements
  compare pairwise — equal priorities fall through to the NEXT
  tuple element, which must be comparable or TypeError (store a
  counter tiebreaker). `bisect`/`insort` assume sorted input and
  do NOT check — unsorted input gets a silently wrong position;
  `bisect_left` vs `bisect_right` differ only on equal elements.
- **Unpacking arity**: `a, b = seq` requires exactly two →
  ValueError ("too many"/"not enough"); `a, *rest = seq` always
  collects a list (possibly empty); `a, b = b, a` evaluates the
  whole RHS tuple BEFORE any assignment.
- **Call-site packing**: `f(**kw)` keys must be str
  (`f(**{1: 2})` → TypeError); duplicate keys → TypeError;
  positional-only (`/`, 3.8+) and keyword-only (`*`) params
  reject the wrong door at call time.
- **`for`/`while` `else`**: the `else` runs when the loop ends
  WITHOUT `break` — including on an empty iterable.
- **Comprehension scoping**: comp variables do NOT leak (loop
  vars in ordinary `for` DO); the OUTERMOST `for` iterable is
  evaluated in the enclosing scope.
- **Recursion on self-similar structures**: `repr` handles cycles
  (`l` containing `l` → `'[[...]]'`), `deepcopy` preserves them
  via memo — but `==` on cyclic structures → RecursionError.
  Three surfaces for self-referential input.

## Exception surface

- **Hierarchy**: `BaseException` → `SystemExit`,
  `KeyboardInterrupt`, `GeneratorExit`, `asyncio.CancelledError`
  (3.8+), `BaseExceptionGroup` (3.11+) — `except Exception`
  catches NONE of them. Under `Exception`: `ArithmeticError`
  (ZeroDivisionError/OverflowError/FloatingPointError),
  `LookupError` (KeyError/IndexError — the shared parent),
  `OSError` (FileNotFoundError/PermissionError/TimeoutError/
  IsADirectoryError/NotADirectoryError/FileExistsError),
  `ValueError` (UnicodeDecodeError ⊂ it; `.index`/`.remove`/
  `split("")` land HERE — not under LookupError), `TypeError`,
  `RuntimeError` (RecursionError, NotImplementedError),
  `NameError` (UnboundLocalError), `AssertionError`,
  `StopIteration`/`StopAsyncIteration` — which ARE `Exception`
  members, so `except Exception` swallows them.
- **`except` semantics**: first matching clause wins — subclass
  ordering matters (`except OSError` catches
  `FileNotFoundError`); `except (A, B)` tuple form; bare
  `except:` catches BaseException — three distinct surfaces.
  `except E as e` DELETES `e` after the block — a later
  reference → NameError.
- **`try/else`**: `else` runs only when NO exception fired —
  distinct from `finally`.
- **`finally` always runs** — including under `return`, `break`,
  `continue`, `SystemExit`, `KeyboardInterrupt`; a `return` or
  `break`/`continue` INSIDE `finally` DISCARDS the in-flight
  exception silently — the "cleanup that swallows" shape.
- **Chaining**: an exception raised inside `except` gets the
  original as `__context__` ("During handling..."); `raise X
  from Y` sets `__cause__` ("direct cause"); `raise X from None`
  sets `__suppress_context__`. Re-raise-with-wrap has three
  spellings and three traceback shapes.
- **ExceptionGroup / `except*` (3.11+)**: `except* E` matches E
  LEAVES inside a group and re-raises the unmatched remainder;
  plain `except ValueError` never sees a ValueError leaf inside
  a group; plain `except Exception` catches the whole
  ExceptionGroup (it IS an Exception). `ExceptionGroup(...)`
  containing a non-Exception leaf constructs a
  `BaseExceptionGroup`. `.exceptions`/`.subgroup`/`.split`/
  `.derive` are the introspection doors.
- **SystemExit**: `sys.exit()` raises it — `.code`: None→0,
  int→status, anything else→status 1 with the object printed to
  stderr. Not caught by `except Exception` — APIs promising
  "returns instead of raises" may still propagate it (argparse
  errors → exit 2 + usage; `--help` → 0). `os._exit` bypasses
  `finally`/`atexit`/flushing entirely.
- **`GeneratorExit`/`StopIteration`**: `gen.close()` throws
  GeneratorExit at the yield point — the generator must re-raise
  or return; yielding again → RuntimeError. Raising
  `StopIteration` INSIDE a generator → RuntimeError (PEP 479);
  `return v` in a generator surfaces as `StopIteration.value`.
- **`assert`**: raises AssertionError — and is STRIPPED under
  `-O`/`-OO`: validation written as assert disappears in
  optimized runs. `assert (cond, msg)` (a tuple) is always true
  + SyntaxWarning — a classic spec-vs-impl gap.
- **Warnings are not exceptions**: `DeprecationWarning`/
  `PendingDeprecationWarning`/`ResourceWarning` are filtered
  INVISIBLE by default (DeprecationWarning shows only for code
  in `__main__`); `-W error`/`simplefilter("error")` promote
  them to raised exceptions — the same defect, two surfaces. An
  unawaited coroutine fires `RuntimeWarning` at GC, not at the
  call site.
- **`KeyError` str**: `str(KeyError("k"))` → `"'k'"` — the repr
  of the key, quotes included; message-shape assertions are an
  edge.
- **TypeError vs ValueError**: wrong-TYPE vs wrong-VALUE are
  distinct documented surfaces — don't accept one for the other
  (`"a" + 1` TypeError vs `int("a")` ValueError; `d[k]` KeyError
  vs `.index` ValueError vs `seq[i]` IndexError — three
  "missing" surfaces under two parents).
- **`raise` bare** re-raises the ACTIVE exception — valid only
  inside a handler.
- **Exception attrs**: `e.args` is the ctor tuple; `OSError`
  carries `.errno`/`.strerror`/`.filename`; `UnicodeError`
  carries `.encoding`/`.start`/`.end`/`.reason`; `ImportError`
  carries `.name`/`.path` — attribute assertions are more stable
  than `str(e)` assertions.
- **`match=` semantics**: `pytest.raises(..., match=)` is
  re.search, not re.fullmatch — loose patterns pass on wrong
  reasons. Anchor guard-order-critical assertions.

## Concurrency, identity & lifetime

- **The GIL makes nothing atomic**: interleaving can occur
  between ANY bytecodes — `n += 1` is load-add-store and races;
  check-then-act (`if k in d: d[k]`) races. Single-step builtins
  (`list.append`, `d[k] = v`) are effectively atomic under the
  CPython GIL — an IMPL detail, not a spec: atomicity claims
  need locks, not faith.
- **threading**: `Lock` is NON-reentrant (second acquire on the
  same thread deadlocks) vs `RLock`; `threading.local` for
  per-thread state; daemon threads are killed silently at
  interpreter exit — no cleanup, no join.
- **`queue.Queue`**: thread-safe; nonblocking `get` raises
  `queue.Empty` — an `Exception` member, so broad handlers
  swallow it.
- **`concurrent.futures`**: `submit` never raises the worker's
  exception — it is STORED in the `Future` and surfaces only on
  `.result()`/`.exception()`; an un-retrieved future's failure
  is dropped silently. `Executor.map` preserves input order but
  raises on iteration; `as_completed` is unordered.
- **`multiprocessing`**: targets/args must PICKLE — top-level
  functions only, no lambdas/closures; `spawn` (default on
  macOS/Windows) re-imports the module — the
  `if __name__ == "__main__"` guard is load-bearing or the child
  re-runs the parent's top level; `fork` (POSIX default) copies
  memory INCLUDING held locks. `Value`/`Array`/`Manager` are the
  shared-state doors — plain globals are per-process.
- **asyncio**: calling `coro()` creates a coroutine and runs
  NOTHING — an unawaited coroutine is a RuntimeWarning at GC;
  `await coro()` runs it INLINE — overlap needs `create_task`/
  `gather`; `asyncio.run` inside a running loop → RuntimeError;
  `asyncio.CancelledError` is `BaseException` — `except
  Exception` lets it through (as it must); `asyncio.TimeoutError`
  IS builtin `TimeoutError` (3.11+); a finished Task's
  un-retrieved exception warns at GC. `async for`/`async with`
  need `__aiter__`/`__anext__`/`StopAsyncIteration`/
  `__aenter__`/`__aexit__`.
- **`id`/`is` lifetime rules**: `id` may be REUSED once the
  object is collected — `id(a) == id(b)` across non-overlapping
  lifetimes is not identity; `is` on literals is impl-defined
  (constant folding can make `1000 is 1000` True inside one
  compilation unit); `None`/`True`/`False`/`()`/`""`/`...`/
  `NotImplemented` are the singletons where `is` IS the contract.
- **weakref**: most builtins can't be weak-referenced —
  `weakref.ref([])`/`ref("s")`/`ref(1)` → TypeError; `__slots__`
  classes need `__weakref__` listed; `ref()()` → None after
  death while `weakref.proxy` raises ReferenceError on access;
  `WeakKeyDictionary` still requires hashable keys.
- **GC/`__del__`**: refcounting collects acyclic garbage
  immediately (impl detail); cycles need `gc.collect`; at
  interpreter shutdown module globals are torn down — `__del__`
  bodies may observe None where module attrs were.
- **`is` vs `==`**: small-int interning (-5..256) and string
  interning are impl details — `==` tests must not rely on `is`
  behavior and vice versa.

## Types & annotations

- **Annotations are not enforced**: `def f(x: int) -> str`
  admits and returns anything — they are metadata; an
  "annotation says X" domain is inferred, never guaranteed.
- **Annotations evaluate at def time**: `def f(x: Undefined)` →
  NameError at DEFINITION (import time) unless quoted or
  `from __future__ import annotations` (stores strings; 3.14's
  PEP 649 evaluates lazily instead). `typing.get_type_hints`
  re-evaluates — unresolvable names → NameError at introspection.
- **`isinstance`/`issubclass` reject parameterized generics**:
  `isinstance(x, list[int])` → TypeError — use the bare origin
  or `get_origin`/`get_args`; the `(A, B)` tuple form is fine.
- **`isinstance` vs `type()`**: `isinstance` includes subclasses
  (`isinstance(True, int)`!) and ABC registrations; `type(x) is
  T` is exact — "subclass-admitting" vs "exact-type" are
  different domains and specs rarely say which.
- **ABCs are structural in places**: `register()` makes
  isinstance true with NO inheritance; `__subclasshook__` checks
  method PRESENCE — `Sized` needs `__len__`, `Hashable` needs
  `__hash__ is not None`, `Iterable` needs `__iter__` (a
  `__getitem__`-only iterable FAILS `isinstance(..., Iterable)`
  while remaining iterable), `Callable` needs `__call__` — not a
  signature.
- **`@runtime_checkable` Protocol**: `isinstance` checks method
  NAMES exist — signatures, return types, and semantics are not
  checked; a non-checkable Protocol under `isinstance` →
  TypeError.
- **`@typing.overload` has no dispatch**: only the LAST,
  non-decorated definition runs — overload signatures are
  invisible at runtime (calling a decorated stub →
  NotImplementedError).
- **`TypeVar`/`Generic`/`Final`/`ClassVar`/`NewType`/`cast`/**
  `Annotated`/`TypedDict` are runtime-inert — no constraint is
  enforced; a `TypedDict` is a plain dict. `X | None` syntax
  works at runtime only 3.10+.
- **dataclass semantics**: fields with defaults cannot precede
  default-less fields — TypeError at CLASS CREATION, including
  across an inheritance join; a mutable default → ValueError,
  `field(default_factory=)` is the door; `eq=True` (default)
  generates `__eq__` and sets `__hash__ = None` — UNHASHABLE —
  unless `frozen=True` (which generates `__hash__` and makes
  mutation → `FrozenInstanceError`, an AttributeError) or
  `unsafe_hash=True`; `field(compare=False)` drops a field from
  eq/order only; `__post_init__` runs after the generated
  `__init__`; `replace()` routes THROUGH `__init__`/
  `__post_init__` but cannot touch `init=False` fields;
  `asdict` deep-copies; `slots=True` returns a DIFFERENT class
  object than the one decorated.
- **enum**: members are singletons — `E.X is E["X"] is
  E(value)` — so `is` is valid for members; THREE lookup doors
  with three errors: `E.X` → AttributeError, `E["X"]` →
  KeyError, `E(value)` → ValueError. Iteration yields members
  only; `__members__` includes aliases (equal values alias
  unless `@unique` — which makes duplicates a ValueError at
  class creation). `IntEnum` members `==` ints and ARE ints;
  `StrEnum` (3.11+) members ARE strs; `str(IntEnum.X)` is
  version-divergent (≤3.10 → 'E.X', 3.11+ → the int's str). A
  concrete Enum cannot be subclassed → TypeError.
- **ABC instantiation**: `ABC`/`abstractmethod` block
  instantiation ONLY while abstractmethods remain — an ABC with
  none instantiates fine; an `abstractmethod` body is still
  callable via `super()`.
- **`super()`/`__mro__`**: C3 linearization — a diamond calls
  each ancestor ONCE; bare `super()` relies on the `__class__`
  cell (methods only). Cooperative chains need every link to
  forward `**kwargs` — a non-cooperative base silently drops
  downstream initializers.
- **Metaclass hooks**: `isinstance`/`issubclass` are themselves
  customizable via `__instancecheck__`/`__subclasscheck__` on
  the metaclass — type checks are dispatch, not fact.
- **`__init_subclass__`/`__set_name__`/`__class_getitem__`**:
  class-CREATION hooks — they fire on subclassing/subscription,
  not on instantiation; instance-level probes miss the contract
  entirely.

## Standard-library surfaces

- **`re`**: `match` anchors at start only; `fullmatch` requires
  end-to-end; `search` anywhere. `findall`'s return SHAPE depends
  on group count (none → str list, one → group strings, many →
  tuples); `split` keeps captured separators; `$` matches before
  a trailing newline where `\Z` does not; user input needs
  `re.escape`.
- **`json`**: `dumps` emits `NaN`/`Infinity`/`-Infinity` by
  default (`allow_nan=True`) — INVALID strict JSON that
  `json.loads` accepts back: a silent non-standard round-trip;
  non-str keys coerce — `{1: x}` dumps `{"1": x}` and loads a
  str key (lossy); tuples become lists; `sort_keys` on mixed
  int/str keys → TypeError; unknown types → TypeError unless
  `default=`; duplicate keys last-win unless `object_pairs_hook`
  watches.
- **`random`**: `randint(a, b)` is INCLUSIVE both ends (unlike
  `range`/`randrange`); `random()` is [0.0, 1.0) half-open;
  `choice([])` → IndexError; `shuffle` mutates and returns None;
  `sample` is without-replacement vs `choices` with-replacement;
  `secrets`/`SystemRandom` is the security door, not `random`.
- **`math`/`statistics`**: `math.log(0)`/`sqrt(-1)` → ValueError
  (NOT -inf/nan — `cmath` is the complex door); `floor`/`ceil`/
  `trunc` return int (inf → OverflowError); `isclose` defaults
  rel_tol=1e-9 and abs_tol=0 — near-ZERO comparisons always fail
  without an explicit abs_tol; `stdev`/`variance` need ≥2 points
  (StatisticsError), `pstdev`/`pvariance` divide by n not n−1;
  `mean`/`median`/`mode` on empty → StatisticsError.
- **`itertools`**: `groupby` groups CONSECUTIVE runs only —
  unsorted input yields repeated groups; `dropwhile`/`takewhile`
  switch PERMANENTLY on first failure — not a filter;
  `count`/`cycle`/`repeat` are infinite — consumers must bound;
  `tee` splits but the original drains; `pairwise` (3.10+)/
  `batched` (3.12+) are version-gated.
- **`functools`**: `lru_cache` requires hashable args and returns
  the SAME cached object per key — a mutable return value is a
  shared-alias door; `cached_property` needs `__dict__` (fails
  on bare-`__slots__` classes); `singledispatch` dispatches on
  the FIRST arg only; `partial` binds leading args + keywords;
  `cmp_to_key` bridges cmp-style comparators.
- **`datetime`/`time`**: naive vs aware `datetime` comparisons →
  TypeError; `datetime` IS a `date` subclass but
  `datetime < date` → TypeError (both directions — isinstance
  passes, ordering fails); `timedelta` normalizes negatives
  (`timedelta(milliseconds=-1)` → days=-1, seconds=86399,
  microseconds=999000); `replace(tzinfo=tz)` RELABELS without
  converting — `astimezone()` converts; `strptime` `%y` pivots
  at 69; `fromisoformat` accepts 'Z' only 3.11+; `weekday()`
  (0=Mon) vs `isoweekday()` (1=Mon) vs `strftime` `%w` (0=Sun)
  are three conventions for one fact; `monotonic`/`perf_counter`
  for durations; `sleep(-1)` → ValueError.
- **`os.path`/`pathlib`**: `os.path.join("/a", "/b")` → "/b" —
  an absolute segment DISCARDS prior parts (same for
  `Path(a) / "/b"`); `splitext(".bashrc")` → ('.bashrc', '') —
  leading dots are not extensions, and only the LAST suffix
  splits (`"a.tar.gz"` → ".gz"); `Path.resolve` follows
  symlinks, `absolute` does not.
- **`glob`/`fnmatch`**: `glob`'s `*` skips dotfiles (`**` needs
  `recursive=True`); `fnmatch` normalizes case per OS normcase
  (`fnmatchcase` does not) — pattern tests are platform-gated.
- **`open`/`io`**: modes `r w a x b t +` — `'x'` →
  FileExistsError on existing; text mode translates newlines on
  read AND write (`newline=` controls); `tell`/`seek` offsets in
  text files are opaque cookies; default encoding is locale-
  dependent until 3.15 — pin `encoding=`; `errors=` selects the
  decode-failure surface.
- **`subprocess`**: `check=True` → `CalledProcessError` (carries
  returncode/stdout/stderr); `timeout=` → `TimeoutExpired`
  (carries partial output); `shell=True` is a different parsing
  and injection surface than list-form; pipe deadlock needs
  `communicate()`.
- **`argparse`**: parse errors raise `SystemExit` (status 2 +
  stderr usage; `--help` → 0) — "the CLI returns" vs "the CLI
  exits" is a surface fork; `exit_on_error=False` (3.9+) reroutes
  to ArgumentError; `type=` callables and `choices=` are
  validation doors.
- **`logging`**: root default level WARNING — `info`/`debug`
  drop silently; `basicConfig` is a NO-OP if a handler already
  exists; `%`-args format lazily; `logging.exception` attaches
  the traceback.
- **`unittest.mock`**: `patch` string-resolves the target —
  patch where the name is LOOKED UP (the consumer module), not
  where defined: `from m import f` snapshots the binding and
  `patch("m.f")` misses it. `Mock` silently creates any
  attribute (typos pass); `spec=`/`autospec` constrain;
  `MagicMock` adds magic methods (`__len__`, `__iter__`) that
  `Mock` lacks; `assert_called_once` vs
  `assert_called_once_with` are different surfaces.
- **`csv`/`configparser`/`sqlite3`**: csv wants `newline=""` on
  the file; `DictReader` extras go to `restkey`, missing fields
  to `restval`. configparser interpolates `%(name)s` — a literal
  `%` must be `%%`. sqlite3 `?`-params vs f-strings (injection);
  `check_same_thread` blocks cross-thread use by default.
- **`urllib.parse`/`base64`**: `urljoin("http://a/b", "c")` →
  "http://a/c" — the base's last segment is a resource, not a
  directory; `quote` leaves "/" safe by default; `parse_qs`
  DROPS blank values (`keep_blank_values` keeps);
  `b64encode` is bytes-in-bytes-out — a str door needs
  encode/decode on both sides.
- **`pprint` sorts dict keys** by default (`sort_dicts=True`) —
  output order is not insertion order.
- **pytest doors**: `approx` for float comparison;
  `raises(..., match=)` is `re.search` (anchor it); a leaf type
  in `pytest.raises` does not reach INSIDE an ExceptionGroup —
  `except*` does; `monkeypatch` cannot fix `from m import f`
  bindings — patch the consumer's name.

## Import & name-binding edges

- **`from m import f` snapshots**: the name binds the CURRENT
  object at import — later `m.f = new` (monkeypatch, reload,
  reassignment) is invisible to the importer; `import m` +
  `m.f(...)` re-resolves every call. Two doors, two binding
  times — THE mocking divergence.
- **`import a.b` binds `a`** in the namespace;
  `__import__("a.b")` returns the TOP package —
  `importlib.import_module` is the nested-name door.
- **`sys.modules` is the cache**: a repeat `import` returns the
  cached module; `importlib.reload` mutates it in place —
  existing `from`-imports keep the OLD objects.
- **Circular imports**: `import` succeeds but the
  partially-initialized module fails at USE — `from`-import →
  ImportError, attribute read → AttributeError.
- **Module top-level runs once at first import** — import-time
  side effects (including `multiprocessing` spawn re-import)
  are a domain member; `__name__ == "__main__"` is the guard.
- **`__all__` gates `from m import *`** only; module-level
  `__getattr__`/`__dir__` (3.7+) hook missing attribute reads —
  `hasattr` probes can be answered dynamically.
- **Scoping is compile-time**: ANY assignment/`del`/binding in
  a function makes the name local EVERYWHERE in it —
  read-before-assign → UnboundLocalError (a NameError member).
  `global`/`nonlocal` change the binding; mutating a captured
  object needs neither.
- **Loop-var closures bind late**: `[lambda: i for i in
  range(3)]` all return 2 — the default-arg trick
  (`lambda i=i:`) captures per-iteration.
- **Mutable default args**: `def f(x=[])` evaluates defaults
  ONCE at def — the list accumulates across calls; an
  impure default expression also runs at def time, not call
  time.
- **Shadowing builtins**: assigning `list`/`id`/`open` in scope
  breaks later lookups in that scope — module-level shadowing
  is module-wide.
- **`del` unbinds** — a later read raises NameError
  (UnboundLocalError in function scope).

## Spec-silent defaults worth pinning

- `dict.get(k, default)` vs `dict[k]`; `sorted` stability;
  `%`/`//` sign behavior on negatives (`-7 // 2 == -4` floor);
  `min()`/`max()` on empty with `default=`; `bool("0")` is True
  (and `bool(" ")`, `bool(nan)`); `x or default` collapses ALL
  falsy members to `default`; `None` participation in
  comparisons (TypeError in py3, not ordering); `int(-3.9)`
  truncates vs `-3.9 // 1` floors; `"" in s` is always True;
  `if it:` cannot detect an empty iterator; `next(it, sentinel)`
  returns the sentinel forever once exhausted; `{}` is a dict,
  not a set.
