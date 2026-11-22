---
id: ADR-0023
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0023: CD+G output from the same layout, by our own writer

Adds to ADR-0006 (a new stage and its file), ADR-0007 (layers) and ADR-0009 (output presets).

## Context and problem

Karaoke players and much karaoke software expect CD+G: an MP3 with a `.cdg` file of graphics packets, 300 per second, drawing 6×12-pixel tiles on a 300×216 screen of 16 colours. The only open-source CD+G writer has no licence and is not maintained. Vocatron already decodes CD+G with its own pure code.

## Considered options

1. **No CD+G**; MP4 only.
2. **A CD+G writer of our own**, fed by the same layout as the video, in a separate stage.
3. **Render the video and convert its frames** into CD+G afterwards.

## Decision

Option 2.

- The setting `outputs` lists the products: `[mp4]` by default, `[mp4, cdg]` adds `Song.mp3` and `Song.cdg` next to the MP4. `mp4` must stay in the list for now.
- A new stage `cdg` runs after `render`, so turning CD+G on or off never encodes the MP4 again. It lays the song out again with the same pure layout and profile on the CD+G screen, with the 288×192 safe area, and writes `cdg.json` (what was made, the palette, the packet count, the worst lags).
- The writer is pure code in `core/cdg`, the inverse of the decoder: the scene becomes target frames, the tiles that differ from the modelled screen are queued by the time they are due (a wipe when it is sung, a line when it appears), and each packet slot sends the oldest one. The decoder is the model of the screen and the test oracle.
- Colours are rounded to 12 bits, and each colour group's sung colour is its unsung colour XOR one mask, so a wipe step is a single XOR packet; more than 16 colours is an error.
- Text is drawn with the bundled font at CD+G size (CD+G carries no font), with one shade level for smooth edges. Until each look declares its own simplification, the same one applies to all: one shade level, an edge of whole pixels, no shadow, fades become cuts, the wipe as smooth as the packet budget allows.

## Consequences

- MP4 and CD+G show the same lines at the same times; a look changes both.
- The packet budget limits how fast a page can be drawn; the stage records the worst lag of draws and wipes, and the tests bound it.
- Per-look simplification, a check that a look fits CD+G and a zip of the pair come later.
