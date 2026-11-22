---
id: ADR-0032
status: accepted
date: 2026-11-02
superseded_by: null
---
# ADR-0032: Effects for video-only looks

Adds to ADR-0009 (style profiles), ADR-0019 (the profile check) and ADR-0029 (the CD+G section of a style profile).

## Context and problem

The built-in looks follow classic karaoke discs, which had to fit the limits of CD+G. A video can show more: glow, motion, soft transitions and moving backgrounds, as current karaoke apps do. The renderer (libass through ffmpeg) can draw all of this without a new dependency, but a profile has no way to ask for it, and the checks know nothing about it.

## Considered options

1. **Five optional profile sections, off by default**, carried into the scene so stage 1 can test them, and only for looks without CD+G.
2. **Separate modern renderers** per look, outside the profile model.
3. **No effects**; modern looks only through colours and sizes.

## Decision

Option 1.

- New optional sections: `glow` (a blurred copy of the sung text), `pop` (the word being sung grows by at most 15 % and settles back), `transition` (lines fade or slide in and out), `upcoming` (lines shown before they are sung are dimmed) and `background_motion` (a slowly moving colour gradient instead of the plain background). All are off by default, so existing looks draw exactly as before.
- The effects are part of the scene. The fit is measured at the pop size, so a popping word never pushes a line out of the safe area. A transition ends before the line's first syllable and starts after its last. The contrast rules run against the darkest and lightest gradient colour and against dimmed lines.
- CD+G cannot draw these effects, so a profile that uses any of them and has a `cdg` section is refused; such looks are MP4 only (ADR-0029).
- Two built-in looks use them: `neon` and `lyric-video`.
- Own background pictures or videos are not part of this decision.

## Consequences

- Modern looks can be made by profile, own profiles included, and are checked like every other look.
- The scene and `layout.json` gain fields; the layout stage raises its version.
