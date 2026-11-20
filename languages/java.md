# Java — language-specific test obligations

Load when the target is Java. Additional obligation sources beyond
the generic method: language-level contracts and domain classes.
Fold each relevant one into the class registry and ledger.

## Object / value contracts (axiom obligations)

- **equals contract (all five laws)**: reflexive `x.equals(x)`,
  symmetric `x.equals(y) iff y.equals(x)`, transitive,
  consistent across repeated calls while state is unchanged,
  `x.equals(null) == false`. Each law is a separate probe;
  equals on a foreign type must return FALSE, not throw —
  the instanceof/getClass guard is the contract's edge.
- **equals→hashCode**: `a.equals(b)` MUST imply
  `a.hashCode() == b.hashCode()`; hashCode must be consistent
  while state is unchanged; unequal objects MAY collide (do
  not assert distinctness). Probe equal-but-differently-
  constructed objects — normalization in equals vs raw-field
  hashing is THE classic violation.
- **equals symmetry across hierarchy**: subclass-vs-base probes
  both directions — `sub.equals(base)` vs `base.equals(sub)`
  disagree when one side uses getClass and the other
  instanceof. A subclass that adds a field cannot extend a
  non-final equals and stay symmetric.
- **Comparable total order**: `sgn(c(x,y)) == -sgn(c(y,x))`
  antisymmetry, transitivity, and `c(x,y)==0` ⇒
  `sgn(c(x,z)) == sgn(c(y,z))` for all z. `compareTo` is
  "strongly recommended (but not required)" consistent with
  equals — sorted containers (TreeSet/TreeMap) use compareTo
  AS identity: an inconsistent ordering silently drops
  "equal" members (`BigDecimal("1.0")` vs `"1.00"`).
  `c.compareTo(null)` should throw NPE per Comparator doc,
  even though `e.equals(null)` returns false.
- **toString/parse round-trip**: if a parse/factory exists that
  reads toString output, `parse(x.toString()).equals(x)` —
  or flag the documented gap.
- **clone()/Cloneable**: Cloneable is a MARKER interface (no
  methods); `Object.clone` is protected and throws
  CloneNotSupportedException without it. Documented
  conventions — `x.clone() != x`, same class, typically
  equals — hold "by convention", not as requirements.
  Default clone is SHALLOW: probe shared mutable subobjects
  for aliasing. Arrays are Cloneable with a public covariant
  clone.
- **Serializable**: absent `private static final long
  serialVersionUID`, it is computed from class shape —
  mismatch on deserialize → InvalidClassException. `transient`
  fields skip the stream and return as type defaults
  (0/null/false) — post-deserialize invariants are a required
  member. Deserialization bypasses constructors — EXCEPT
  records, which DO run the canonical constructor. Enum
  constants serialize by name — singleton `==` survives.
- **records (16+)**: generated equals/hashCode cover ALL
  components; the canonical/compact constructor is THE
  validation hook — every construction path funnels through
  it. Records are final and shallowly immutable — mutable
  component refs still alias. Accessors may be overridden;
  equality is value-based, not identity.

## Numeric domain edges

- **All integral overflow wraps silently** (no exception):
  byte/short/int/long at MIN/MAX; `MAX_VALUE + 1` → MIN_VALUE;
  `i++` at MAX wraps to MIN. Both sides of every bound are
  REQUIRED members.
- **MIN_VALUE asymmetry**: `-Integer.MIN_VALUE ==
  Integer.MIN_VALUE`; `Math.abs(MIN_VALUE)` returns MIN_VALUE
  — abs does NOT guarantee non-negative; `MIN_VALUE / -1`
  overflows to MIN_VALUE (the one int division overflow) while
  `MIN_VALUE % -1 == 0` — no exception on either.
- **Compound assignment silently narrows** (JLS 15.26.2):
  `byte b = 100; b += 200;` COMPILES — b = -56 via hidden
  cast; `b = b + 200` would NOT compile. Same hidden cast on
  `char c += 1` — a defect shape invisible to reviewers.
- **`Math.*Exact` family** (addExact/subtractExact/
  multiplyExact/negateExact/incrementExact/decrementExact/
  toIntExact) throws ArithmeticException on overflow — code
  using them has an EXCEPTION member, not a wrap member.
- **Division/modulo doors**: `1/2 == 0` (int); `1/0` →
  ArithmeticException; `1.0/0` → Infinity; `0.0/0.0` → NaN.
  `%` sign follows the dividend: `-7 % 2 == -1` vs
  `Math.floorMod(-7,2) == 1`; `/` truncates toward zero vs
  `Math.floorDiv` toward -inf — negative operands split.
- **Numeric promotion**: byte/short/char arithmetic promotes
  to int — `'a' + 'b'` is int 195, not char; assigning back
  needs a cast. `char` is unsigned 16-bit (0..65535) —
  ordering and `Character.compare` are unsigned.
- **Boxed identity**: `Integer.valueOf(127) ==
  Integer.valueOf(127)` TRUE — the cache is MANDATED for
  -128..127 (JLS 5.1.7; a JVM may cache beyond); `128` is not
  guaranteed. `new Integer(n)` is deprecated-for-removal and
  ALWAYS a distinct object — `==` on boxes is a latent bug
  either way. Cross-box: `1 == 1L` unboxes numerically TRUE
  while `Integer.valueOf(1).equals(1L)` is FALSE — equals is
  class-strict, `==` is numeric.
- **NaN three doors**: `Double.NaN != Double.NaN` (primitive
  ==); `Double.compare(NaN, NaN) == 0` (NaN orders as
  greatest); `Double.valueOf(NaN).equals(...)` is TRUE —
  boxed equals canonicalizes via doubleToLongBits. Same for
  float. `Float.floatToIntBits` collapses all NaN payloads;
  `floatToRawIntBits` preserves them.
- **Signed zero**: `0.0 == -0.0` is TRUE but
  `Double.compare(0.0, -0.0) != 0` (-0.0 orders lower) and
  boxed equals treats them distinct — sorted containers and
  HashSets see the difference; `Math.min(0.0,-0.0)` returns
  -0.0; `1.0/-0.0` → -Infinity.
- **`Double.MIN_VALUE` is the smallest POSITIVE** nonzero
  double (4.9e-324), not most-negative — the classic literal
  misread; the most-negative member is `-Double.MAX_VALUE`.
- **strictfp**: Java 17+ (JEP 306) makes ALL floating point
  strict — the modifier is ignored; pre-17 code could vary
  precision across platforms. On a 17+ target strictfp is not
  a member.
- **Unsigned doors**: `Integer.divideUnsigned`/
  `remainderUnsigned`/`compareUnsigned`/`toUnsignedLong`/
  `parseUnsignedInt`, `Byte.toUnsignedInt`,
  `Short.toUnsignedInt` — `(byte)0xFF` is -1 signed vs 255
  unsigned; signed/unsigned comparison are distinct members.
- **Literal syntax**: `010` IS legal octal (== 8); `08`/`09`
  FAIL to compile. `0x` hex, `0b` binary (7+); `2147483648`
  needs the `L` suffix (`-2147483648` is special-cased legal
  as unary minus); underscores legal only BETWEEN digits —
  `1_000` ok; `0x_52`, `_5`, `5_`, `1_.5`, `100_L` all
  illegal; lowercase `l` legal but doc-discouraged.
- **BigDecimal**: `compareTo` ignores scale, `equals` doesn't
  — `new BigDecimal("1.0")` vs `("1.00")`. `new
  BigDecimal(0.1)` embeds the exact binary expansion — the
  doc prescribes the String ctor or `valueOf`. `divide`
  without a RoundingMode → ArithmeticException on
  non-terminating results.
- **Parse surfaces**: `Integer.parseInt` accepts a leading
  ASCII `+`/`-`, accepts Unicode decimal digits via
  Character.digit (NOT ASCII-only — "٣" parses to 3), but
  rejects whitespace, underscores, and empty →
  NumberFormatException. `Long.parseLong` overflow → NFE vs
  `parseUnsignedLong` (to 2^64-1) vs BigInteger (unbounded).
  `Integer.decode` additionally accepts `0x`, `#`, and
  `0`-octal forms.
- **`Math.round`** is half-up (`floor(x+0.5)`):
  `round(-2.5)` → -2; returns int for float, long for double.

## String / Unicode domain edges

- **Immutability**: every "mutating" helper (concat, replace,
  trim, toUpperCase) returns a NEW string — an unconsumed
  return value is a no-op defect shape.
- **`intern()`/`==`**: literals and compile-time-constant
  concatenations are interned (same-content literals ARE the
  same object); runtime-built equal strings are NOT unless
  `intern()`ed — identity-vs-equality probes must be
  deliberate.
- **`String` is UTF-16**: `length()` counts code UNITS;
  `codePointCount` counts code points; `charAt`/`substring`
  operate on units and can sever a surrogate pair —
  supplementary chars (emoji, CJK ext) are required members.
- **null-door matrix**: `"x" + null` → `"xnull"` (JLS null→
  "null"); `"x".concat(null)` → NPE; `String.join(d, list)`
  renders null ELEMENTS as "null" but NPEs on a null
  delimiter or iterable. Three doors for the same null.
- **trim vs strip**: `trim()` removes only chars ≤ U+0020;
  `strip()` (11+) removes Unicode whitespace — U+00A0 nbsp
  distinguishes them. `isEmpty()` = length 0; `isBlank()` =
  all-Unicode-whitespace — whitespace-only is a required
  member alongside `""` and null.
- **indexOf negative fromIndex** is clamped to 0 — no
  exception; not-found → -1. `substring`/`charAt` OOB →
  StringIndexOutOfBoundsException (an IndexOutOfBounds).
- **matches is FULL-match**: `"abc123".matches("\\d+")` is
  FALSE — Pattern.matches anchors the entire input; contains
  needs `Matcher.find()`. `matches`, `replaceAll`,
  `replaceFirst`, `split` take REGEX; `replace`, `indexOf`
  take literals — `"a.b".split(".")` returns EMPTY (every
  char matched). Regex metachar injection is a class.
- **split quirks**: trailing empty fields dropped at default
  limit 0 — `":a:".split(":")` → `["", "a"]`; `limit < 0`
  keeps trailing empties; `"".split(":")` returns `[""]`,
  not `[]`.
- **Locale sensitivity**: `toUpperCase()`/`toLowerCase()` use
  the DEFAULT locale — Turkish `"i"` → `"İ"` is the canonical
  divergence; `toUpperCase(Locale)` is deterministic. Case
  ops can CHANGE LENGTH: `"ß".toUpperCase()` → `"SS"`.
  `equalsIgnoreCase`/`String.CASE_INSENSITIVE_ORDER` fold via
  Character methods — Unicode-broad but locale-INDEPENDENT.
- **Classification breadth**: `Character.isLetterOrDigit`/
  `isDigit` span Unicode; regex `\w` is ASCII `[a-zA-Z_0-9]`
  unless `UNICODE_CHARACTER_CLASS`/`(?U)`; `[0-9]` is ASCII —
  three different gates on "is this a word/digit character".
- **format/formatted**: `String.format` uses the default
  locale — `%f` renders `,` in de; `%n` is the platform
  newline vs `\n`; bad conversions → IllegalFormatException
  family (an unchecked surface on a checked-looking call).
- **Text blocks (15+)**: the opening `"""` must end its line;
  incidental indentation is stripped to the least-indented
  content line or the closing delimiter's column; `\`
  suppresses a newline; `\s` preserves a trailing space; a
  closing `"""` on its own line includes a trailing newline.
- **StringBuilder vs StringBuffer**: identical API — only
  StringBuffer synchronizes; a shared-across-threads context
  flips which member is correct.

## Null / Optional / generics

- **null everywhere**: every reference-typed parameter gets a
  null member — documented NonNull contracts aside, the
  rejection path (NPE vs IllegalArgumentException vs silent
  tolerate vs `Objects.requireNonNull`'s message-bearing NPE)
  is itself a domain class.
- **Optional**: `Optional.of` NPEs on null vs `ofNullable`
  tolerates; `orElse` evaluates EAGERLY vs `orElseGet` lazily
  (visible via side-effecting suppliers); no-arg
  `orElseThrow()` → NoSuchElementException. The doc intends
  Optional as a method RETURN type — field/parameter members
  are a discouraged-use class.
- **Autoboxing NPE**: unboxing a null box → NPE at the use
  site, not the declaration. `int r = cond ? 0 : null`
  compiles via the mixed ternary (JLS 15.25) and NPEs when
  false.
- **Generics erasure**: runtime type not checked —
  `List<String>` accepts raw `List`; ClassCastException at
  retrieval sites, not insert. `instanceof List<String>`
  doesn't compile (only `List<?>`); `new T()`, `new T[]`,
  `new List<String>[n]` are all illegal.

## Type system & resolution rules

- **Overload picks the STATIC type**: resolution happens at
  COMPILE time — `Object o = "s"; m(o)` calls `m(Object)`
  even when `m(String)` exists. Override dispatch is the
  runtime door — same call shape, different chosen member.
- **`m(null)` resolution**: picks the MOST SPECIFIC
  applicable overload; unrelated siblings (`m(String)` vs
  `m(Integer)`) → compile-time ambiguous — a no-call member.
- **Resolution order**: widening > boxing > varargs (strict
  → loose → varargs phases). `m(long)` beats `m(Integer)`
  for an int arg; widen-then-box is ILLEGAL — an int can
  never reach `Long`.
- **Wildcards / PECS**: `? extends T` reads T, writes nothing
  but null; `? super T` writes T, reads Object — producer
  and consumer sides of the same member set are asymmetric
  doors.
- **Heap pollution**: non-reifiable varargs (`m(T...)`)
  warns at declaration unless @SafeVarargs; call sites warn
  unchecked; storing a wrong-typed element into the varargs
  array defers the failure to a later cast site.
- **instanceof patterns (16+)**: `o instanceof String s` —
  null NEVER matches (`null instanceof X` is always false),
  so null silently takes the negative branch; the binding's
  scope is flow-sensitive.
- **switch patterns/sealed (21+)**: a null selector → NPE
  unless `case null` (or `case null, default`) is written;
  sealed-type switches require all permitted subclasses or a
  default — adding a permitted subclass is a documented
  compile break, i.e. exhaustiveness is a checkable member.
- **enum**: `==` is guaranteed even across serialization
  (`Enum.equals` is final); `compareTo` is ordinal-based and
  final — ordinal-dependent logic breaks on constant
  reordering; `valueOf` → IllegalArgumentException on an
  unknown name, NPE on a null type or name.

## Exceptions & mutability

- **Hierarchy**: Throwable → Error | Exception →
  RuntimeException. `catch (Exception)` misses ALL Errors —
  AssertionError (asserts, test frameworks),
  StackOverflowError, ExceptionInInitializerError. "Catches
  everything" is a member, not an impl detail. Declared
  `throws` vs runtime surface differ — test the declared one.
- **Initializer failures**: a throwing static initializer →
  ExceptionInInitializerError wrapping the cause; every
  SUBSEQUENT access to that class → NoClassDefFoundError —
  first-failure vs repeat-failure are different surfaces.
- **NoClassDefFoundError vs ClassNotFoundException**: an
  Error for a class present at compile but missing at
  runtime vs a checked exception for a reflective-load miss
  (`Class.forName`) — distinct doors.
- **try-with-resources**: resources close in REVERSE
  declaration order; body-throw + close-throw → the close
  exception is SUPPRESSED onto the primary (`getSuppressed`),
  not lost — catch sees only the primary.
  `AutoCloseable.close` is only "strongly encouraged"
  idempotent; `Closeable.close` is REQUIRED no-op-if-closed —
  close-twice probes differ per interface.
- **finally hazards**: `return`/`throw` inside finally
  swallows the in-flight exception AND any prior return
  value — a documented silent-loss class.
- **multi-catch**: alternatives must be disjoint (no
  super/sub relation); the parameter is implicitly final —
  per-alternative members share one handler surface.
- **InterruptedException clears the interrupt flag** —
  documented: a catch-and-continue must restore via
  `Thread.currentThread().interrupt()` or propagate; a
  swallowed interrupt is a distinct defect class.
- **Immutability surface**: `Collections.unmodifiable*` and
  `List.of`/`Map.of` throw UnsupportedOperationException on
  mutation — a distinct class from IllegalArgumentException;
  `List.of` also rejects null members — two separate classes.
- **Inheritance reach**: subclass reach into protected
  members; final classes/methods can't extend/override —
  probe only where the doc invites extension; `Object`'s
  wait/notify/getClass are final and cannot be overridden.

## Collections & iteration

- **`Collection.add`'s five doors**: the doc enumerates
  UnsupportedOperationException, ClassCastException,
  NullPointerException, IllegalArgumentException, and
  IllegalStateException (capacity-bound full) — the impl's
  chosen door is a member; do not collapse them.
- **`List.of`/`Set.of`/`Map.of`**: unmodifiable AND null-
  rejecting (NPE) — two classes; `Set.of(1,1)` or a duplicate
  Map key → IllegalArgumentException AT CONSTRUCTION;
  iteration order is unspecified — do not pin it.
- **View vs snapshot**: `Collections.unmodifiableList(src)`
  is a VIEW — backing mutation shows through;
  `List.copyOf(src)` is a null-rejecting SNAPSHOT;
  `Arrays.asList` is fixed-size — `set()` writes through to
  the backing array while add/remove →
  UnsupportedOperationException.
- **Null doors per impl**: HashMap/LinkedHashMap/ArrayList/
  LinkedList accept nulls; Hashtable, ConcurrentHashMap (key
  AND value), PriorityQueue, ArrayDeque, EnumSet → NPE;
  TreeMap/TreeSet NPE under natural ordering but may accept
  null under a null-tolerant comparator.
- **Map.get ambiguity**: a null return means absent OR
  null-valued — `containsKey` distinguishes; `getOrDefault`
  returns the mapped value EVEN when it is null (the default
  applies only when absent). `merge`/`compute` returning null
  REMOVES the mapping — differs from `put(k, null)` which
  stores one.
- **computeIfAbsent**: the mapping function must not modify
  the map — recursive update on ConcurrentHashMap →
  IllegalStateException per doc.
- **Paired empty/capacity doors**: `poll`/`peek` → null vs
  `remove`/`element` → NoSuchElementException; `offer` →
  false vs `add` → IllegalStateException on a full bounded
  queue; `first()`/`last()` throw on empty vs
  `pollFirst()`/`pollLast()` return null;
  `lower`/`floor`/`ceiling`/`higher` return null when the
  bound is absent (exclusive vs inclusive pairs).
- **PriorityQueue**: the iterator does NOT traverse in
  priority order — "does not guarantee"; only `peek`/`poll`
  honor order; non-Comparable members under natural ordering
  → ClassCastException; null members → NPE.
- **`List.subList` view**: structural modification of the
  backing list NOT via the view leaves the view's semantics
  "undefined" — typically CME on next access; view ops write
  through; `subList.clear()` removes the range.
- **Iterator.remove contract**: removes the last `next()`
  element; IllegalStateException if called before `next()` or
  twice in a row; the default impl throws
  UnsupportedOperationException.
- **fail-fast vs fail-safe**: ConcurrentModificationException
  is "best effort" per doc — a bug-detector, not a guarantee;
  CopyOnWriteArrayList and ConcurrentHashMap iterators are
  snapshot/weakly-consistent — they tolerate concurrent
  mutation but their mutator methods throw
  UnsupportedOperationException.
- **Content equality**: List equals is ordered element-wise,
  Set unordered, Map entrySet-wise — a List is NEVER equal to
  a Set even with the same members. Mutating a member
  post-insert changes its hash → HashSet/HashMap ghost
  entries: `contains` false while iteration still shows it.
- **Comparator-defined identity**: TreeSet/TreeMap treat
  `compareTo == 0` as the SAME element regardless of equals —
  `new BigDecimal("1.0")` and `("1.00")` collapse to one
  entry.
- **Sort stability**: `Collections.sort`, `List.sort`, and
  `Arrays.sort(Object[])` are guaranteed stable;
  `Arrays.sort` on PRIMITIVES is dual-pivot and not
  guaranteed; `parallelSort` follows the same contract —
  where a doc claims stability, probe it.
- **`Arrays.equals`/`deepEquals`/`==`**: `==` identity;
  `Arrays.equals` element-wise shallow; `Arrays.deepEquals`
  recurses nested arrays — three distinct members.
- **`toArray` runtime type**: `toArray()` returns `Object[]` —
  casting to `String[]` → ClassCastException; `toArray(new
  T[0])` is idiomatic; an OVERSIZED array gets a null
  sentinel one past the end — a subtle observable member.
- **Order dependence**: HashMap iteration order is
  unspecified and shifts on resize; LinkedHashMap documents
  insertion order; TreeMap sorted — pin order only where the
  impl documents it.
- **Nulls in sorting**: natural-order sort over a null-
  containing collection → NPE/ClassCastException mid-sort;
  `Comparator.nullsFirst`/`nullsLast` are the documented
  tolerance doors.

## Concurrency & memory model

- **happens-before edges** (JLS 17.4.5) — shared-state tests
  must thread through one edge or visibility is OPTIONAL:
  program order; monitor unlock → subsequent lock on the SAME
  monitor; volatile write → subsequent read of the SAME
  variable; caller's actions → `Thread.start`; a thread's
  actions → `join()` return; `interrupt()` → detection of the
  interrupt; default write → every thread's first action.
- **Final-field publication**: a correctly constructed
  object's final fields (plus state reachable from them at
  freeze time) are visible WITHOUT sync — `this`-escape
  during construction forfeits the guarantee.
- **volatile is visibility, not atomicity**: `i++`,
  check-then-act, and lazy init are compound — each
  interleaving is a member; the Atomic* classes' CAS/
  incrementAndGet are the documented atomic doors.
- **Torn 64-bit reads**: non-volatile `long`/`double` writes
  may be observed as two 32-bit halves (JLS 17.7) — a
  torn-value member on shared mutable numerics.
- **Double-checked locking**: broken unless the field is
  volatile (the post-Java-5 memory model fixes it only WITH
  volatile); the static-holder idiom is the safe alternative.
- **Monitor choice**: synchronized instance methods lock
  `this`; static methods lock the Class object — the two do
  NOT mutually exclude.
- **`wait()` contract**: must own the monitor (else
  IllegalMonitorStateException); releases the monitor while
  waiting (`sleep` does NOT); may return SPURIOUSLY per doc —
  wait in a condition loop, never a bare `if`.
- **Lock/Condition vs synchronized**: `tryLock(timeout)`,
  `lockInterruptibly()`, multiple Conditions per Lock, and
  optional fairness (unfair barging is legal) are
  capabilities synchronized lacks; unlock belongs in
  `finally`.
- **CME is not a correctness proof**: fail-fast detection is
  best-effort — absence of ConcurrentModificationException
  does NOT prove safe publication.
- **`InterruptedException` clears the flag** — see
  Exceptions; `Thread.sleep` retains all monitors;
  `Thread.stop`/`suspend`/`resume` are deprecated unsafe
  doors.

## Runtime & version gates

- **`assert` is OFF by default**: enabled only under `-ea`;
  AssertionError is an Error — `catch (Exception)` misses it;
  doc requires asserts be side-effect-free (skipped entirely
  when disabled).
- **`finalize()`**: deprecated-for-removal since 9 — whether,
  when, and in what order it runs is JVM-optional;
  Cleaner/try-with-resources are the documented replacements.
- **`System.exit` vs `Runtime.halt`**: exit runs shutdown
  hooks; halt bypasses them — two termination surfaces.
- **SecurityManager**: deprecated-for-removal 17 (JEP 411),
  disabled by default 18+, `setSecurityManager` throws on 24+
  (JEP 486) — policy-based behaviors are dead members on
  modern targets.
- **Time sources**: `currentTimeMillis` is wall-clock — can
  jump backward, coarse granularity; `nanoTime` is monotonic-
  relative with an arbitrary origin — values may be NEGATIVE;
  pin durations and ordering, never absolute values.
- **JDK-level gating**: pin probes to the spec's target —
  `List.of`/`Map.of` 9+, `strip`/`isBlank`/text-block-free
  String API 11+, `var` 10+, text blocks 15+, records and
  instanceof patterns 16+, always-strict FP and sealed
  classes 17+, pattern switch and `case null` 21+, `_`
  reserved as an identifier since 9 (unnamed patterns 22+),
  `new Integer(...)` deprecated-for-removal. A behavior
  documented on a NEWER level is not an obligation on an
  older target.
