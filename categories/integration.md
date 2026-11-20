# Integration / Seam Testing

Exercise the units TOGETHER at their natural seams: public package
API, CLI entry points, workflows spanning modules.

## Method
1. Entry points: `__main__`, console_scripts, top-level package
   functions that orchestrate internals.
2. One test per documented workflow or CLI command class (not per
   permutation — permutations belong to unit categories).
3. Real objects only — no mocks unless a boundary is external
   (network/fs/time). Prefer tmp_path/fixtures over mocks.
4. Cross-module data flow: value produced by module A consumed by
   module B (e.g. validate -> store).

## Budget
~1-3 per entry point. Keep thin — unit categories carry the weight.

## Checklist
- [ ] every public entry point exercised once
- [ ] no mocks of the system under test itself
- [ ] at least one multi-module workflow
