# Architecture Decision Records

Each decision that shapes Vocatron is recorded here as a short ADR.

## Process

- File name `NNNN-kebab-title.md`, numbered in order, never reused.
- Format: frontmatter `id`, `status`, `date`, `superseded_by`; sections Context and problem, Considered options, Decision, Consequences.
- Status: `proposed` (under discussion), `accepted` (in force), `superseded` (replaced; `superseded_by` names the successor).
- An ADR can be edited freely until it is first committed. After that, a change is a new ADR that supersedes the old one fully or in part; the old ADR stays in place.
- Details: [ADR-0001](0001-repository-and-documentation-structure.md).

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [ADR-0001](0001-repository-and-documentation-structure.md) | Repository and documentation structure | accepted | 2026-10-28 |
| [ADR-0002](0002-tech-stack.md) | Tech stack | accepted, in part superseded by ADR-0010, ADR-0011 and ADR-0016 | 2026-10-28 |
| [ADR-0003](0003-code-documentation.md) | Code documentation | accepted | 2026-10-28 |
| [ADR-0004](0004-test-harness-and-definition-of-done.md) | Test harness and Definition of Done | accepted, in part superseded by ADR-0042 | 2026-10-28 |
| [ADR-0005](0005-language-support.md) | Language support | accepted | 2026-10-28 |
| [ADR-0006](0006-pipeline-stages-and-files.md) | Pipeline stages and files | accepted | 2026-10-28 |
| [ADR-0007](0007-architecture-and-code-quality.md) | Architecture and code quality | accepted, in part superseded by ADR-0042 | 2026-10-28 |
| [ADR-0008](0008-lyrics-format.md) | Lyrics format | accepted, in part superseded by ADR-0018 | 2026-10-28 |
| [ADR-0009](0009-style-profiles-and-output-presets.md) | Style profiles and output presets | accepted, in part superseded by ADR-0018, ADR-0022, ADR-0043 and ADR-0048 | 2026-10-28 |
| [ADR-0010](0010-model-licences.md) | Model licences | accepted | 2026-10-29 |
| [ADR-0011](0011-default-separation-model.md) | Default separation model | accepted | 2026-10-29 |
| [ADR-0012](0012-voice-activity-from-vocal-loudness.md) | Voice activity from the loudness of the separated vocals | accepted, in part superseded by ADR-0021 | 2026-10-31 |
| [ADR-0013](0013-word-ends-at-the-voice-end.md) | Word ends at the end of the voice | accepted, in part superseded by ADR-0017 | 2026-10-31 |
| [ADR-0014](0014-the-model-hears-the-backing-where-the-lead-is-silent.md) | The model hears the backing vocals where the lead is silent | accepted | 2026-10-31 |
| [ADR-0015](0015-the-cpu-part-of-the-slow-tests-in-every-change.md) | The CPU part of the slow tests in every change | accepted | 2026-10-31 |
| [ADR-0016](0016-english-alignment-model.md) | English alignment model | accepted | 2026-11-01 |
| [ADR-0017](0017-short-words-are-judged-on-their-held-length.md) | Short words are judged on their held length | accepted | 2026-11-01 |
| [ADR-0018](0018-singer-marks-in-braces.md) | Singer marks in braces, and duet lines never merged | accepted | 2026-11-01 |
| [ADR-0019](0019-own-profiles-by-name.md) | Own profiles by name, a profile check and pictures of the looks | accepted, in part superseded by ADR-0045 | 2026-11-01 |
| [ADR-0020](0020-a-silent-intro-before-the-song.md) | A silent intro before the song | accepted | 2026-11-01 |
| [ADR-0021](0021-uncertain-words-keep-the-model-position.md) | Uncertain words keep the model's position, and estimated words stay in their line | accepted | 2026-11-01 |
| [ADR-0022](0022-countdown-in-beats.md) | The countdown counts beats of the song's tempo | accepted, in part superseded by ADR-0028 | 2026-11-01 |
| [ADR-0023](0023-cdg-output.md) | CD+G output from the same layout, by our own writer | accepted | 2026-11-01 |
| [ADR-0024](0024-mp3-for-cdg.md) | The MP3 of the CD+G pair is encoded by LAME through ffmpeg | accepted | 2026-11-01 |
| [ADR-0025](0025-cdgraphics-as-a-test-decoder.md) | A third CD+G decoder, run unchanged, in an optional test | accepted | 2026-11-01 |
| [ADR-0026](0026-countdown-after-the-line-before.md) | A countdown never starts before the line before it ends | accepted | 2026-11-02 |
| [ADR-0027](0027-place-unheard-lines-at-their-lrc-time.md) | Place unheard lines at their `.lrc` time | accepted | 2026-11-02 |
| [ADR-0028](0028-countdown-ends-one-beat-early.md) | A countdown in beats ends one beat before the line | accepted | 2026-11-02 |
| [ADR-0029](0029-cdg-section-of-a-style-profile.md) | The CD+G section of a style profile and the CD+G check | accepted, in part superseded by ADR-0041 | 2026-11-02 |
| [ADR-0030](0030-mp3g-zip.md) | The MP3+G pair can be packed into one zip | accepted | 2026-11-02 |
| [ADR-0031](0031-artist-and-title-tags-in-the-outputs.md) | Artist and title tags in the outputs | accepted | 2026-11-02 |
| [ADR-0032](0032-effects-for-video-only-looks.md) | Effects for video-only looks | accepted | 2026-11-02 |
| [ADR-0033](0033-scrolling-lyrics.md) | Scrolling lyrics | accepted, in part superseded by ADR-0036 and ADR-0040 | 2026-11-02 |
| [ADR-0034](0034-rows-after-a-break-and-the-order-lines-leave.md) | Rows after a break and the order in which lines leave | accepted | 2026-11-03 |
| [ADR-0035](0035-the-id3-tag-of-the-mp3.md) | Vocatron writes the ID3 tag of the MP3 | accepted | 2026-11-03 |
| [ADR-0036](0036-a-minimum-glide-in-scroll-mode.md) | A minimum glide in scroll mode | accepted | 2026-11-03 |
| [ADR-0037](0037-the-last-hold-gives-way-to-the-end-screen.md) | The last hold gives way to the end screen | accepted | 2026-11-03 |
| [ADR-0038](0038-lines-turn-in-blocks.md) | Lines turn in blocks | accepted, in part superseded by ADR-0039 | 2026-11-03 |
| [ADR-0039](0039-a-short-group-sits-next-to-the-middle.md) | A short group sits next to the middle | accepted | 2026-11-04 |
| [ADR-0040](0040-the-break-screen-stands-alone-in-scroll-mode.md) | The break screen stands alone in scroll mode | accepted | 2026-11-04 |
| [ADR-0041](0041-cdg-page-changes-without-mixed-letters.md) | CD+G page changes without mixed letters | accepted | 2026-11-04 |
| [ADR-0042](0042-module-map.md) | The module map: topic folders in core, a lab package, and the frame of stages | accepted | 2026-11-05 |
| [ADR-0043](0043-four-line-stack-is-the-default-look.md) | `four-line-stack` is the default look | accepted | 2026-11-06 |
| [ADR-0044](0044-the-command-on-the-path-is-a-link-into-the-clone.md) | The command on the PATH is a link into the clone | accepted | 2026-11-06 |
| [ADR-0045](0045-pictures-of-the-looks-from-the-duet-demo-song.md) | Pictures of the looks from the duet demo song | accepted | 2026-11-06 |
| [ADR-0046](0046-characters-the-font-cannot-draw.md) | Characters the bundled font cannot draw | accepted | 2026-11-06 |
| [ADR-0047](0047-vocatron-writes-the-tags-of-every-output.md) | Vocatron writes the tags of every output itself, with Duet to Quintet in `TAG` | accepted | 2026-11-07 |
| [ADR-0048](0048-no-audio-file-next-to-the-video-by-default.md) | No audio file next to the video by default, and the options of `make` | accepted | 2026-11-09 |
| [ADR-0049](0049-the-moments-of-the-look-pictures-follow-the-song.md) | The pictures of the looks show a line sung together, in song order | accepted | 2026-11-09 |
| [ADR-0050](0050-the-front-page-animation-is-the-title-and-the-first-singing.md) | The front page animation is the title screen and the first singing | accepted | 2026-11-09 |
| [ADR-0051](0051-modules-stay-below-a-thousand-lines.md) | Modules stay below a thousand lines | accepted | 2026-11-10 |
| [ADR-0052](0052-two-voices-sing-at-once.md) | Two voices can sing at once | accepted | 2026-11-10 |
| [ADR-0053](0053-a-line-split-after-weak-first-words-is-reported.md) | A line split after weak first words is reported | accepted | 2026-11-12 |
| [ADR-0054](0054-the-second-voice-takes-the-slot-below.md) | The second voice takes the slot below | accepted | 2026-11-12 |
| [ADR-0055](0055-the-start-screen-carries-the-wordmark.md) | The start screen carries the Vocatron wordmark | accepted | 2026-11-16 |
| [ADR-0056](0056-the-cdg-start-screen-has-its-own-palette.md) | The CD+G start screen has its own palette | accepted | 2026-11-16 |
| [ADR-0057](0057-the-end-and-break-screens-carry-the-mark.md) | The end and break screens carry the mark | accepted | 2026-11-16 |
