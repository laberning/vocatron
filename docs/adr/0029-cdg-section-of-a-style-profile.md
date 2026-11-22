---
id: ADR-0029
status: accepted
date: 2026-11-02
superseded_by: "ADR-0041 (in part: the first fallback step of page looks; a song still late needs review)"
---
# ADR-0029: The CD+G section of a style profile and the CD+G check

Adds to ADR-0009 (style profiles), ADR-0019 (the profile check) and ADR-0023 (CD+G output from the same layout).

## Context and problem

CD+G output (ADR-0023) lays the song out with the video profile as it is and moves the wipe in a fixed step; only one look was made and checked for it. A CD+G screen is 288×192 visible pixels with at most 16 colours of 12 bits, so each look needs its own simplification: sizes in pixels, fewer colours, no shadow, a coarser wipe. A look must also say whether it is made for CD+G at all, and a profile that does not fit must be refused before a song is drawn badly. When a real song is denser than the sample songs, the packets may not keep up.

## Considered options

1. **A `cdg` section in the style profile** from which a CD+G profile is made, checked by `vocatron profiles check`, with fixed fallback steps for real songs.
2. **Fixed CD+G values for every look** in the code, as today.
3. **A separate CD+G look file** next to each video look.

## Decision

Option 1.

- A profile may carry an optional `cdg` section: `made_for_cdg` (the marker), `slots`, `font_px` and `min_font_px` on the 192 px safe area, `edge_px` (1 or 2 only; a look without a visible edge gives the edge the background colour), `wipe_columns` and optional colour overrides written as `#rgb` or `#rrggbb`. Colours without an override are rounded to the nearest 12-bit value.
- On CD+G the shadow and the end-screen fade are always dropped; there is no key for them.
- From the video profile and its `cdg` section one pure function makes a CD+G profile, a normal profile that the unchanged layout and CD+G writer use. The stage and the check call the same functions.
- A look without the section, or with `made_for_cdg: false`, is MP4 only. With `cdg` in `outputs` the `cdg` stage fails for each song with the reason `cdg-not-made-for-cdg`; the video is still made. A check of the profile before the batch starts is not part of this decision.
- `vocatron profiles check` runs a CD+G check on every look with the marker, built-in or own: the palette fits in 16 entries with all five singers and the group, the contrast rules hold on the rounded colours, the lines and slots fit the safe area, the scene rules hold, and on the sample songs plus one dense invented song every line is fully drawn before it is sung and the wipe is at most 50 ms behind. Problems are located at the `cdg` key that fixes them.
- When a real song misses the timing although the samples pass, the stage falls back in fixed steps: the line appears earlier (the lead-in minimum raised to the look's target, then to its maximum), then the wipe gets coarser (6 px). `cdg.json` records the step; if none is in time, the last step is written and the song log warns.
- Every classic built-in look is made for CD+G and passes the check. Lines are not snapped to the CD+G tile rows.

## Consequences

- Each built-in look gets a `cdg` section; own profiles without one keep loading and are MP4 only.
- `vocatron profiles` shows which looks are made for CD+G.
- `cdg.json` and the `cdg` stage raise their versions, so CD+G files made before are made again. The video of every look is unchanged.
