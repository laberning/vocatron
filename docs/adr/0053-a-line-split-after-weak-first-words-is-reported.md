---
id: ADR-0053
status: accepted
date: 2026-11-12
superseded_by: null
---

# ADR-0053: A line split after weak first words is reported

Adds to ADR-0008 (two alignment passes with the `.lrc` times as rails) and ADR-0027 (unheard
lines are placed at their `.lrc` time).

## Context and problem

The second pass uses the `.lrc` line times, shifted by one offset for the whole song, as rails:
a line may start at most a second and a half before its time. Times that break the order of the
lines are skipped. A single time that is in order but several seconds early is kept, and it pulls
its line: the first words of the line were placed at the end of the phrase before, followed by a
long silent gap inside the line. The gap stayed under the review limit, so nothing reported it.

## Considered options

1. Keep every time in order; report nothing more.
2. Skip a time that lies far from where the first pass (without times) found its line, and report
   a split line.
3. Report a line that is split by a silent gap after weak first words; keep the times.
4. Search each line twice, with and without its time, and keep the better fit.

## Decision

Option 3.

- A line whose words before its longest inner gap are all measured with low confidence, where the
  gap (on the held ends, ADR-0013) is long and the voice is silent for most of it, makes the song
  `review` with a reason that names the line and says its time looks early. The limits are named
  constants in the fingerprint.
- Option 2 was built and tried on the corpus: of nine skipped times, seven were right, and their
  lines moved by two to twenty seconds; the pass without times also put the first words of the
  case seen too early, so skipping did not even help there.
- Option 4 doubles the search for every line and was not needed.

## Consequences

- A wrong time is not corrected, but the song is held for review and the reason names the line,
  so the time can be fixed in the `.lrc`.
- The alignment results do not change; the stage version goes up because its reasons do.
- The limits are set from few cases; the benchmark guards the alignment, not the reason.
