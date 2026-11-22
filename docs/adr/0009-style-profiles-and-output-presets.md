---
id: ADR-0009
status: accepted
date: 2026-10-28
superseded_by: "ADR-0018 (in part: duet lines are never merged); ADR-0022 (in part: the countdown counts beats); ADR-0043 (in part: the default profile is four-line-stack); ADR-0048 (in part: the m4a export is off by default)"
---
# ADR-0009: Style profiles and output presets

## Context and problem

Vocatron should look like classic karaoke, and fans should be able to choose or adjust the look without touching code. Presentation (what is on screen when, colours, lines, countdowns) and output (resolution, codecs, bitrates) change independently: a new look should not need a new encoder setting and the other way round. The same presentation must later be drawn as CD+G as well as MP4, and every look must be checkable without rendering video. Classic karaoke is 4:3; modern screens are 16:9. The output should be the same on every machine for the same song and settings.

## Considered options

1. **Looks in code**, one renderer per look.
2. **Style profiles as data** (YAML, with a schema) read by one format-independent layout, plus **output presets** as separate data.
3. **Raw ASS style files** supplied by the user.

## Decision

Option 2.

- **Style profiles** are YAML files with a Pydantic schema; errors name file, line and column. A profile sets the presentation: mode (`line` or `page`), number of line slots, alignment and position, font (family from the bundled fonts, size as a share of the safe-area height, minimum size), background, colours, edge and shadow, wipe, lead-in, hold and clear, breaks, countdown, title screen, ending, duet handling, and how it degrades to CD+G.
- **Singers:** a profile defines unsung, sung and edge colours for singers 1 to 5 and one `group` pair, used for `all:` and group lines such as `1,3:`. Names and colours from the lyrics file (ADR-0008) override the profile. Lines of different singers that overlap in time are drawn merged as a group line; a split screen may come later as a profile option.
- **Built-in profiles** ship with Vocatron and are selected by name; `two-line-turns` is the default. A profile can also be a path to the user's own YAML file. Single values can be overridden in `vocatron.yaml` (`profile_overrides`). No profile is named after a label or product.
- **Every profile passes the same conformance kit**: it loads, its colours meet the contrast rules, its lines fit the safe area of every preset at its sizes, and the layout rules hold on generated lyrics.
- **Layout** is a pure function from syllable timings, singers, song info and a profile to a format-independent scene model. Renderers (MP4 now, CD+G later) only draw the scene. Text is measured from the bundled font's metrics, so fit and overlap are checked without rendering.
- **Output presets** are separate data: frame size, frame rate, video codec and quality, audio encoder and bitrate. Built in: `4x3-720` (960×720, the default, as in classic karaoke), `16x9-720` (1280×720), `16x9-1080` (1920×1080), and an AV1 preset as an opt-in. Video is H.264 with libx264 by default; NVENC is an optional, faster preset.
- **Audio** is encoded once, as AAC with the Fraunhofer FDK encoder (`fdkaac`, an external program like ffmpeg) at 192 kbit/s by default, and copied unchanged into the MP4 and into `Artist - Title.m4a`. `fdkaac` is a required tool, checked by `make setup` and `vocatron doctor`. There is **no automatic fallback**: a user without `fdkaac` sets `audio.encoder: ffmpeg-aac` explicitly, which uses ffmpeg's own AAC encoder at 256 kbit/s by default. The bitrate can be overridden per preset.
- **Outputs** in the output folder: `Artist - Title.mp4`, `Artist - Title.lrc` (enhanced LRC with word times) and `Artist - Title.m4a` (the karaoke audio; can be switched off; FLAC as an option).

## Consequences

- A new look is a YAML file that passes the conformance kit; a new output format is a renderer over the same scene model.
- The same song and settings give the same MP4 on every machine, since the encoder never changes silently.
- Fans need one more system package (`fdkaac`), documented in the installation guide.
- The values of `two-line-turns` come from desk research; watching real tracks may change them, which changes data, not code.
