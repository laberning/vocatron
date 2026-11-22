---
id: ADR-0015
status: accepted
date: 2026-10-31
superseded_by: null
---
# ADR-0015: The CPU part of the slow tests in every change

Supersedes ADR-0004 in part: item 1 of the Definition of Done.

## Context and problem

ADR-0004 runs the slow tests (stage 2) only when a change touches an engine or a slow-stage test, through `make check-all`, which needs the GPU and about a quarter of an hour. Many slow tests need no GPU at all: rendering with the real ffmpeg and comparing golden frames, the CD+G analysis on the local discs, the language detector, the model downloader. Because they ran only with the GPU tests, they went unrun for days: a golden title frame stayed out of date for three days, and two slow tests broken by a changed default were found only at the end of a story.

## Considered options

1. **Keep item 1 as it is.**
2. **`make check-all` for every change.** Safe, but a quarter of an hour of GPU time per change, and impossible on a machine without a GPU.
3. **Split stage 2 by what it needs:** the tests that need a GPU are marked `gpu`; `make slow-cpu` runs the rest in a few minutes on any machine, and every change runs it.

## Decision

Option 3. A stage 2 test that needs an NVIDIA GPU carries the marker `gpu` and is skipped with a reason where there is none; the other stage 2 tests run everywhere (they need the local corpus where they read it). `make slow-cpu` runs stage 2 without the `gpu` tests. Item 1 of the Definition of Done becomes:

1. `make check` and `make slow-cpu` are green, and `make check-all` too if the change touches an engine or a test that needs the GPU.

## Consequences

- Golden frames, the CD+G analysis and the real tools are checked in every change, a few minutes more per change and no GPU needed.
- Stage 2 no longer skips as a whole without a GPU; only its `gpu` tests do. A missing corpus file still fails the test that needs it.
- `make slow-cpu` is not a CI job (`CI_TARGETS`): most of it reads the private local corpus, which CI does not have, and would only skip there.
- `make check-all` stays the full run before a story with engine or GPU work is done.
