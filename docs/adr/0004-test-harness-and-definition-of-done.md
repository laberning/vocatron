---
id: ADR-0004
status: accepted
date: 2026-10-28
superseded_by: "ADR-0042 (in part: the coverage minimum of the lab layer)"
---
# ADR-0004: Test harness and Definition of Done

## Context and problem

Every change to Vocatron must be judged quickly, precisely and reproducibly: is it right, and does it keep the architecture intact? Most of the logic (lyrics cleaning, alignment maths, syllables, layout, timing, status rules, format writers) can be tested without models, network or rendering, while a small part needs a GPU, real models and real songs. Songs are copyrighted and cannot be committed. The checks need one entry point, a short failure summary that a contributor can act on directly, and a shared definition of when a change is done.

## Considered options

1. **One test suite** run in full on every change.
2. **Staged harness**: static checks, fast tests without GPU or network, slow tests with real engines, a benchmark; each stage a `make` target.
3. **Tests mainly end-to-end** on real songs, few unit tests.

## Decision

Option 2.

### Stages

| Stage | What | Constraints | Make target |
|---|---|---|---|
| 0 Static | Ruff format check and lint, Pyrefly strict, import-linter contracts, deptry, vulture, `uv lock --check` | seconds | part of `make check` |
| 1 Fast | unit, property and golden-file tests, contract tests on recorded responses, every stage on fakes, one end-to-end run of the whole pipeline on fakes; coverage thresholds | no GPU, no network (blocked), no real models, no ffmpeg rendering; under one minute | part of `make check` |
| 2 Slow | real engines: the copied Roformer model against its checkpoint, alignment against torchaudio's `forced_align`, ffmpeg rendering and frame checks, one short local song end to end | GPU if present, local song corpus | `make check-all` (stages 0–2) |
| 3 Benchmark | sync quality against hand-made reference timings on the local corpus | GPU, local corpus | `make bench` |

### Make targets

`make setup` (environment, tools, ffmpeg and libass check), `make check` (stages 0 and 1), `make check-all` (stages 0 to 2), `make bench` (stage 3), `make summary` (only the failures of the last run: file, line, message), `make format` (fix what can be fixed), `make mutation` (mutmut on `core`, on demand), `make dup` (jscpd), `make docs`, `make help`. Every check writes machine-readable reports (JUnit XML, coverage) into `reports/`, which `make summary` reads.

### Test kinds

- **Property tests** (Hypothesis, `ci` profile derandomised) for algorithms: alignment, syllable timing, layout invariants, format round trips.
- **Golden files** (syrupy) for models, stage files and output formats; an unused snapshot fails; updating snapshots (`--snapshot-update`) is a deliberate act and the diff is reviewed like code.
- **Layout and timing are tested on models, not on pixels:** a scene model says what is visible at time *t*; text is measured from font metrics; fit, overlap, placement and timing are invariants checked in stage 1. Subtitles are parsed back and checked. Rendered frames are stage 2 only.
- **Contract tests** for the lyrics source on recorded responses; no live network in stages 0 and 1.
- **Stage-file schemas** are exported from the models and committed; stored files are validated against them, and a schema change without a version bump fails.

### Test discipline

pytest 9 in strict mode with pytest-randomly (random order), pytest-xdist (parallel), pytest-timeout (per test) and pytest-socket (network blocked in stages 0 and 1). Coverage with branch coverage; minimum per layer on the fast stage: **`core` 95 %, `stages` 90 %, `cli` 80 %, `engines` 60 %** (engines are mostly exercised in stage 2). diff-cover checks the lines a change touches.

### Local song corpus

Songs, stems and reference timings for stages 2 and 3 live in a local folder outside git (path given by an environment variable, default a git-ignored folder in the project). Tests that need it are skipped with a clear message when it is missing. CI runs stages 0 and 1 only.

### Definition of Done

A change is done when:

1. `make check` is green, and `make check-all` too if the change touches an engine or a slow-stage test.
2. New or changed behaviour has tests on the lowest fitting stage; nothing that can be tested in stage 1 is tested only in stage 2.
3. No quality gate is weakened: no lower threshold, no removed contract, no new ignore or suppression without a reason written next to it.
4. No new duplicated logic; each rule lives in one place.
5. Docstrings, user docs and developer docs are updated for what changed.
6. Every new decision has an ADR, and changed decisions supersede their ADR.
7. Snapshot and schema changes are intended and reviewed.
8. A change to a stage's code that changes its results raises the stage's version, so stored results made by the old code are not taken as current.

## Consequences

- A contributor learns within about a minute whether a change is acceptable, and `make summary` says exactly what failed and where.
- The fake engines and the fixture library must exist before the first stage is built (the pipeline frame provides them).
- Slow tests depend on a local corpus and a GPU, so they run on the maintainer's machine, not in CI.
- The Definition of Done can be quoted verbatim by contributor guidelines.
