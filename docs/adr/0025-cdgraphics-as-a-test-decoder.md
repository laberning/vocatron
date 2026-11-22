---
id: ADR-0025
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0025: A third CD+G decoder, run unchanged, in an optional test

Adds to ADR-0004 (tests).

## Context and problem

Our CD+G writer is tested against our own decoder and against ffmpeg's `cdgraphics` decoder. A mistake in reading the format that our writer and our decoder share would pass the first check; a second independent player catches it, but ffmpeg is only one. The JavaScript library cdgraphics (permissive licence) renders CD+G in browsers and in Node.

## Considered options

1. **Only our decoder and ffmpeg.**
2. **Port cdgraphics to Python.**
3. **Run cdgraphics unchanged in Node** in an optional stage 2 test.

## Decision

Option 3. `make cdg-js` downloads one pinned version of the package from the npm registry into `.tools/`, checks its pinned checksum and unpacks it; nothing of it enters git. A small test script of ours runs it and writes frames that the test compares with ours. Without Node or the folder the test is skipped with a reason. The code is used, never ported or copied.

## Consequences

- Three independent decoders agree on our files, or the test says where they differ.
- Node is an optional tool for this one test, not a dependency of Vocatron.
