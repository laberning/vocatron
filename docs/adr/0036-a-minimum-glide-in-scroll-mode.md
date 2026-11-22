---
id: ADR-0036
status: accepted
date: 2026-11-03
superseded_by: null
---
# ADR-0036: A minimum glide in scroll mode

Supersedes ADR-0033 in part: that a line never moves while it is being sung, and that the column moves in one step when a line follows the one before without silence. Everything else of ADR-0033 stays as it is.

## Context and problem

In scroll mode the column glides up only in the silence between two lines. When lines follow quickly, that silence is very short or missing: the glide becomes very fast, or the column moves in one step. The column then looks jumpy and the lyrics are hard to follow. The distance of a glide is fixed by the column, so the glide time alone sets its speed.

## Considered options

1. **A minimum glide time; where the silence is shorter, the glide starts during the end of the line that is finishing.**
2. A minimum glide time that runs into the start of the next line, so that line arrives while its first syllable is sung.
3. Keep the glide in the silence and show fewer lines, so each glide is shorter.

## Decision

Option 1.

- The `scroll` section gains `min_glide` (seconds, 0.1 to 1.0, not more than `glide`; if left out 0.3, or `glide` if that is shorter).
- A glide between two lines lasts at least `min_glide`. Where the silence leaves less, the glide starts earlier by the missing time, while the line that is finishing is still sung; it ends before the next line is sung, as before. The line being started never moves while it is sung.
- A glide never starts before the column has come to rest at the stop before; only where a line is sung for less time than the glide needs may its glide out stay shorter than `min_glide`.
- A line moves while it is sung only in its last `min_glide` seconds, and only up; its wipe continues during the glide. The scene rules check this and the minimum length of a glide.
- Glides with enough silence and the glide after the title stay as in ADR-0033.

## Consequences

- Fast passages scroll at a steady, limited speed instead of jumping; the end of a finishing line can be seen drifting up.
- Own scroll profiles keep working; the default applies to them. The layout stage raises its version.
- The ASS writer draws the wipe of a line across a moving event.
