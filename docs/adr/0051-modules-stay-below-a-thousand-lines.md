---
id: ADR-0051
status: accepted
date: 2026-11-10
superseded_by: null
---

# ADR-0051: Modules stay below a thousand lines

Adds to ADR-0007 (layers and quality gates): a new gate on the size of a module.

## Context and problem

Ruff caps the complexity of a function (ADR-0007), but nothing caps the size of a module. A few
modules have grown to well over a thousand lines, so a reader scrolls for minutes to find a rule,
and a module grows a little with every change without anyone deciding it.

## Considered options

1. **A stage 1 test that fails for every Python file in `src` and `tests` above 1000 lines**, with
   no exceptions at the start.
2. **The same test with a cap of 800 lines**, which forces more splits without a clear seam.
3. **No cap**; splits only when a review asks for them.

## Decision

Option 1.

- The test walks `src` and `tests` and names every file above the cap with its line count. It runs
  in `make check`; Ruff has no rule for module length.
- An exception needs an entry in one named list next to the test, with a reason per file. A raised
  limit is a review finding.
- Modules above the cap are split along their natural seams, keeping public names; the layout
  rules keep their numbers.

## Consequences

- The size of a module is a decision, not an accident.
- A module near the cap is split before it can grow; the split costs a move, not a rewrite.
