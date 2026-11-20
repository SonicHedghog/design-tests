# Exception & Negative Testing

Every documented raise/errno/error-return is a requirement: one test
per distinct error condition, asserting the specified type AND that
state is unchanged.

## Method
1. analyze_repo lists `raises` per function; docstrings list more.
   Union = the error contract.
2. One test per distinct failure CLASS (not per value): "below range"
   is one class even if the range is [1,1000].
3. Assert: exception type (the documented one, not a superclass like
   Exception), and non-mutation for stateful objects.
4. Wrong-type inputs (None, wrong class): reachable inputs are
   testable inputs — where the spec is silent on them, pin observed
   behavior rather than asserting a raise the spec never promised.
5. Message content: assert key substrings only if the spec pins the
   message format.

## Budget
one per documented error class per function (analyze's `raises` list
x distinct trigger conditions).

## Checklist
- [ ] every documented error class has a test
- [ ] exception TYPE asserted precisely
- [ ] post-error state verified unchanged for mutators

## Distinguish the guard (mandatory)
When a function has more than one raise path, each error test must
identify WHICH guard fired — `match=` on message text, a
distinguishing exception field, or observable state. This holds even
when the spec does not pin message text: assert a stable substring of
the actual message, or demonstrate the distinguishing input hits the
intended branch (e.g., pair a passing case that differs only in the
condition under test). "raises some error somewhere" is not an error
test.
