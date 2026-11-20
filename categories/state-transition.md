# State Transition Testing

For objects/systems with a lifecycle: build the state diagram, then
test every legal arc once and every specified-illegal arc.

## Method
1. States = distinguishable configurations; transitions = operations
   that change state (mutating methods, events).
2. Legal arcs: one test each, asserting resulting state AND
   transition side effects (fields changed/cleared).
3. Illegal arcs: for each (state, operation) pair NOT in the legal
   table, test that it raises the specified error AND state is
   unchanged. The state x operation grid is the enumeration —
   don't sample it, cover it.
4. Guards: transitions conditioned on data (e.g. size < limit)
   get the guard boundary tested (just below / exactly at / above).
5. Terminal states: every operation attempted on a terminal state
   must be tested.
6. Setup: reach each non-initial state via the shortest legal path;
   keep a helper.

## Budget
|legal arcs| + |illegal cells| + |guard boundaries|. A full n-state
x m-operation table is n*m cells; legal + illegal should sum to it.

## Checklist
- [ ] state x operation grid fully accounted: every cell is tested or
      documented impossible
- [ ] side effects asserted, not just end state
- [ ] illegal attempts verified non-mutating
- [ ] guard boundaries tested on both sides
