---
id: ADR-0048
status: accepted
date: 2026-11-09
superseded_by: null
---

# ADR-0048: No audio file next to the video by default, and the options of `make`

Supersedes ADR-0009 in part (the `m4a` default of `audio.export`).

## Context and problem

A run wrote `Artist - Title.m4a` next to the video. The video already carries that audio, and most
people want the video and its lyrics only; the extra file has to be deleted by hand, or switched off
in the configuration. The look and the size of the video could be chosen with `vocatron render`
but not with `vocatron make`, so making a song in another look took a second command.

## Considered options

1. **No audio export by default**, `make` takes `--profile`, `--preset` and `--cdg`, and an export
   that Vocatron made and the setting no longer asks for is deleted.
2. **Keep `m4a` as the default**, and only add the options to `make`.
3. **No export by default**, and leave a stale export in place.

## Decision

Option 1.

- `audio.export` defaults to `none`; `m4a` and `flac` still write the export.
- `vocatron make` takes `--profile` and `--preset` with the meaning, help text and validation of
  `vocatron render` (one definition for both), and `--cdg`, which adds `cdg` to `outputs` for one
  run. The configuration still sets CD+G for good.
- When the render stage runs and the previous `render.json` lists an `.m4a` or `.flac` that the new
  run does not make, that file is deleted. Only files that `render.json` names, directly in the
  output folder, are deleted, and never a file with the name of the song's own audio or lyrics
  file (names, not paths, are compared, as a symlink or `..` can make two paths one file);
  nothing else.
- The render stage raises its version to 7, because a run now writes other files.

## Consequences

- A fresh run writes the video and the `.lrc`. Anyone who wants the audio file sets
  `audio.export`.
- A song made before with an `.m4a` is made again by the next `make` (the stage version and the
  setting changed); the old `.m4a` goes away with it, unless it has the very name of the song
  file.
- The options of `make` and `render` stay in one place, so they cannot drift apart.
