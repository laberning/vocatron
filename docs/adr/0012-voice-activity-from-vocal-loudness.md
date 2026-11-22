---
id: ADR-0012
status: accepted
date: 2026-10-31
superseded_by: "ADR-0021 (in part: placement of estimated words)"
---
# ADR-0012: Voice activity from the loudness of the separated vocals

Adds to ADR-0002 (alignment by forced CTC alignment with confidence per word).

## Context and problem

Words the acoustic model cannot measure with confidence are estimated. Until now an estimated word shared the whole time between its measured neighbours in proportion to its letters, without knowing whether the voice sounds there. A short word after a pause therefore started at the end of the previous word and stretched over the pause: the highlight entered it too early and filled it slowly. To place such words, the alignment needs to know where the singing voice sounds.

## Considered options

1. **The model's own output:** the share of the CTC blank per frame as a sign of speech.
2. **A separate voice-detection model** run on the lead vocals.
3. **The loudness of the separated vocals** per frame (the lead vocals, or the lead and backing vocals together), with a threshold taken from the song itself and a plausibility check.

## Decision

Option 3. The acoustic worker measures the RMS loudness (dBFS) of the separated vocals in the same frames as the model's output. The setting `alignment.voice_source` chooses `lead` (the lead vocals) or `vocals` (lead and backing vocals summed); the default is `vocals`: on the eleven benchmark songs both sources keep the corrected median at 70 ms and no song moves by more than 10 ms, while `vocals` places more estimated words by the voice (for example 159 instead of 114 on the densest song) and, on the demo song, places 12 instead of 7 of the 14 estimated title words, with a median length of 0.47 s instead of 0.93 s. A song's threshold comes from the loudness of its confidently measured words against its noise floor. Voice activity is used for a song only when it is plausible (enough contrast between voice and floor, a sensible share of voiced time); for a single gap only when the gap has a plausible voiced span. Otherwise the earlier placement applies. A setting switches it off.

- The vocals are already separated (ADR-0002, separation before alignment), so their loudness is a direct measure of the voice; no extra model, download or licence is needed, and it costs almost no time.
- The blank share of option 1 is weakest exactly where it is needed: at words the model does not recognise.
- A separate model (option 2) adds weight and another dependency for a question the separated lead track already answers in most songs.

## Consequences

- The alignment stage gets the loudness from the worker and a voice-activity step in `core`; its version goes up, so songs are aligned again.
- Shouted or group-sung words can land in the backing vocals during separation; then the lead track is silent where they are sung (seen on the demo song: 7 of 14 estimated title words). Summing lead and backing finds them, at the risk of counting harmonies as voice. Bleed of instruments into the vocals can mislead the loudness too; the plausibility checks fall back to the earlier placement for such songs or gaps.
- Estimated words placed at the voice start can reveal pauses inside lines and more words can count as estimated, so some songs may change their verdict to `review`; this is the more honest timing and is reported.
- Extending measured words to where the voice stops is a separate decision and change.
