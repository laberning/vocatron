---
id: ADR-0043
status: accepted
date: 2026-11-06
superseded_by: null
---
# ADR-0043: `four-line-stack` is the default look

Supersedes ADR-0009 in part: the default profile is `four-line-stack` instead of
`two-line-turns`. Everything else of ADR-0009 stays as it is.

## Context and problem

ADR-0009 made `two-line-turns` the default when it was the only look. There are now ten. The
default is what a new user sees first and what every song without a `profile` setting gets.
`two-line-turns` shows only one line ahead of the line being sung, and the eye jumps on every
line.

## Considered options

1. Keep `two-line-turns`: large text, the most familiar classic style.
2. `four-line-stack`: four lines in two blocks of two; three lines ahead, the eye moves every two
   lines; made for CD+G.
3. A modern look (`neon`, `lyric-video`, `lyric-scroll`): striking in a video, but not made for
   CD+G, so `outputs: [mp4, cdg]` would be a configuration error until the user picks another
   look.

## Decision

Option 2. The default must be made for CD+G, so that adding `cdg` to `outputs`
works without other changes; among those looks `four-line-stack` gives singers the most lines to
read ahead while keeping the neutral white on black that reads well on any screen.

## Consequences

- A song without a `profile` setting gets `four-line-stack`. The layout stage keys on the
  profile's text, so the next run lays out and renders such songs again; nothing stored is
  taken as current by mistake.
- Users who want the old look set `profile: two-line-turns` in `vocatron.yaml`.
- Tests and pictures that relied on the default name it explicitly or follow the new default.
