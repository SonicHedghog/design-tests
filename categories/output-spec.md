# Output & Naming Spec

- Test file per unit under test: `tests/test_<module>.py` (py),
  `<Unit>Test.java` (java).
- Test ids traceable to TEST_DESIGN inventory: name tests
  `test_<unit>_<intent>`; group parametrized tables by category with a
  comment header naming the category and table.
- Use parametrized tests (`pytest.mark.parametrize`,
  `@ParameterizedTest`) whenever >=2 cases share a shape — one
  function, N rows.
- Self-contained: generated tests must not import or depend on the
  repo's existing test helpers/conftest unless the task is explicitly
  "extend the current suite".
- Expected values come from the REQUIREMENTS MODEL. Never derive
  expected output by running the implementation — that produces
  characterization tests that bless bugs.
- When the implementation contradicts the requirements model: keep
  the spec-true assertion and record the divergence in TEST_DESIGN
  under "Suspected defects" — a failing test that is right about the
  spec is a deliverable, not a mistake.
