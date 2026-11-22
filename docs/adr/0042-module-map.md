---
id: ADR-0042
status: accepted
date: 2026-11-05
superseded_by: null
---
# ADR-0042: The module map: topic folders in core, a lab package, and the frame of stages

Supersedes ADR-0007 in part: the layer table gains the `lab` layer, `stages` is described as
the frame, the stages and the orchestration of the commands, and a rule says where a protocol
lives. Supersedes ADR-0004 in part: the coverage minimums gain `lab` at 95 %. Everything else of
both stays as it is.

## Context and problem

The four layers of ADR-0007 hold, and the gates enforce them. Inside the layers the map has
grown uneven. `core` has 44 flat modules beside five folders, and topics are split between the
two: the CD+G folder has four loose siblings for the analysis of classic discs, the profile
modules are four loose files under two naming styles, the alignment maths sits in `align/` next
to a flat `alignment.py` with its stage file. Stage files follow three patterns (`lyrics/file.py`,
a flat `stems.py`, a `TempoFile` inside the rules module). About 3,000 lines of `core` serve
only the tools and the tests (the disc analysis, the separation evaluation, the listening test),
and nothing tells them apart from the code a `vocatron` command runs. `stages` is described as
"one module per pipeline stage" while 11 of its 20 modules are the frame and the orchestration
behind the commands. The text measurer protocols live in `core.measure`, which is right because
the layout calls them, but the docs say every protocol lives in `engines.protocols`. The fast
core tests are one flat folder of 83 files. A reader who knows the pipeline cannot find the code
of a topic from its folder and name.

## Considered options

1. **Document the map** as it is, on a developer page, and change nothing.
2. **Topic folders, one stage-file rule, a `lab` package, one naming rule, tests that mirror
   the source**, with the rules written here and enforced where a tool can.
3. **Rename the `stages` layer** to `pipeline` and split it into `frame/` and the stages.

## Decision

Option 2. Option 3 renames a layer that every contract and doc names for a
gain the package docstring gives as well. Option 1 leaves the map uneven.

### Topic folders in `core`

- A topic with more than one module has a folder named like its stage: `lyrics`, `separation`,
  `alignment`, `layout`, `cdg`; the looks have `profiles`, the languages `languages`. A topic of
  one module stays a flat module (`song`, `tempo`, `syllables`, `render`, `scene`, `ass`, …).
- **Stage files:** a topic with a folder holds its stage file in `<topic>/file.py`; the messages
  between a stage and its GPU worker in `<topic>/job.py`; a one-module topic keeps its stage
  file in that module. The committed schemas freeze the docstrings of the stage-file models
  (ADR-0006), so a model may move but its docstring does not change without a version bump.
- **Research code** that no `vocatron` command runs is the package `vocatron.lab`: pure like
  `core` (the same forbidden imports), may import `core` only; `engines` may import it (the
  evaluation worker); `stages` and `cli` never. The scripts in `tools/` drive it. Layer order
  for import-linter: `cli` > `stages` > `engines` > `lab` > `core`. Coverage minimum 95 % on
  the fast stage, mutation testing on demand like `core`.
- **Module names:** one word where possible; where two are needed, `snake_case`. A fast test
  checks every part of a module name against the project's word list, so a name that runs two
  words together fails `make check`.

### The `stages` layer

`stages` holds three kinds of module, told apart in its package docstring: the frame (`stage`,
`batch`, `registry`, `config`, `progress`, `report`), one module per pipeline stage, and the
orchestration behind the commands (`songs`, `models`, `profiles`, `doctor`, `bench`). The layer
table of ADR-0007 reads so from now on.

### Where a protocol lives

A protocol lives in the lowest layer that calls it. The engine protocols the stages call are in
`engines.protocols`; the text measurer and rasteriser, which the layout in `core` calls, are in
`core.measure`. Both come with fakes.

### Tests mirror the source

The fast tests of `vocatron/core/<path>/<module>.py` and `vocatron/lab/<path>/<module>.py` are
`tests/fast/core/<path>/test_<module>*.py` and `tests/fast/lab/<path>/test_<module>*.py`; their
snapshots move with them. The other layers have few folders and keep their flat test folders.

## Consequences

- A reader finds the code of a topic by its folder, the stage file in `file.py`, and knows that
  nothing in `lab` runs in a `vocatron` command.
- Every move is a `git mv`; a moved module changes only its imports, so the history follows it.
- The import-linter contracts, the coverage tool, the mutmut paths, the vulture whitelist and
  the developer docs follow the moves in the same change; no threshold drops.
- The naming test is one more gate: a new module with a run-together name fails `make check`
  until its words are in the list or it is written in `snake_case`.
