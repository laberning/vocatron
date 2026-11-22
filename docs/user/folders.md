# Files and folders

Where Vocatron reads and writes, and what each file is. Read it to find a result or to edit a stage file.

```text
~/Music/party/              the folder holding the songs
├── Queen - Radio Ga Ga.mp3
├── Queen - Radio Ga Ga.txt     the lyrics (yours, or found and written by Vocatron)
└── karaoke/                the output folder
    ├── Queen - Radio Ga Ga.mp4     the finished karaoke video
    ├── Queen - Radio Ga Ga.m4a     with audio.export: m4a: its audio
    ├── Queen - Radio Ga Ga.lrc     the timed lyrics, with word times
    ├── Queen - Radio Ga Ga.mp3     with outputs: [mp4, cdg]: the CD+G audio
    ├── Queen - Radio Ga Ga.cdg     with outputs: [mp4, cdg]: the CD+G graphics
    ├── Queen - Radio Ga Ga.zip     with cdg_zip: true: both of them in one file, instead of the two
    ├── vocatron-report.txt         the summary of the last run, with its date
    └── Queen - Radio Ga Ga/    the work folder of one song
        ├── song.json
        ├── lyrics.json
        ├── separation.json
        ├── tempo.json
        ├── alignment.json
        ├── syllables.json
        ├── layout.json
        ├── lyrics.ass
        ├── render.json
        ├── cdg.json
        ├── audio.m4a
        ├── stems/
        │   ├── lead.flac
        │   ├── backing.flac
        │   ├── instrumental.flac
        │   └── karaoke.flac
        ├── status.json
        ├── report.json
        └── log.txt
```

## Rules

| What | Rule |
|---|---|
| Input folder | Not written to, with one exception: when no lyrics file exists, the lyrics found online are written next to the song as `Song.lrc` or `Song.txt` (see [Lyrics](lyrics.md)). |
| Output folder | `karaoke/` next to the songs, or whatever `--output` or `output.folder` say (see [relative output folders](config.md#relative-output-folders)). Deleting it removes everything Vocatron made. |
| Work folder | One subfolder per song inside the output folder, named `Artist - Title`. |
| Name | Artist and title come from the tags; without a title tag the file name is used (`Artist - Title` is split at the first ` - `). Characters that file systems forbid become `_`, and a name Windows reserves (such as `CON` or `con.txt`) gets a `_` after it. |
| Same name twice | Songs do not overwrite each other: names are made unique in sorted path order, the first keeps `Artist - Title`, the next is `Artist - Title (2)`, and so on. A song gets the same name whether you run it alone or with the folder. |

## Files in a work folder

| File | Content |
|---|---|
| `song.json` | Artist, title, name and duration of the song (stage `probe`). |
| `lyrics.json` | The cleaned lyrics with singers (and the second voice of a line, if the file says so, and whether a line has a singer mark of its own), the language, the status with reasons, the original text and what was removed (stage `lyrics`). |
| `separation.json` | How the stems were made: models, device, time, peak GPU memory, the gains that keep them from clipping (stage `separation`, see [Separating the vocals](separation.md)). |
| `tempo.json` | The tempo of the song in beats per minute (or none when it is unclear) and how clear it is (stage `tempo`, see [The karaoke video](video.md)). |
| `alignment.json` | When every word is sung (start, end, confidence, estimated or not), the lines, what became of the `.lrc` line times, and the quality report (stage `alignment`, see [Synchronising the lyrics](sync.md)). |
| `syllables.json` | When every syllable is sung, and the voice of every line (stage `syllables`). |
| `layout.json` | What is on screen when: every line with its place, size, colours and the time of every syllable, the title, break and end screens and the countdowns (stage `layout`, see [The karaoke video](video.md)). |
| `lyrics.ass` | The same as a subtitle file, which ffmpeg burns into the video; you can open it in a subtitle editor (stage `layout`). |
| `render.json` | The preset, the audio encoder and the files the render made in the output folder (stage `render`). |
| `cdg.json` | Whether CD+G is on; if so the files made (the zip with `cdg_zip`), the CD+G values used and the fallback step taken, whether the song was in time, the 16 colours, the packets and the longest waits of drawings and wipe steps (stage `cdg`, see [CD+G](cdg.md)). |
| `audio.m4a` | The karaoke audio, encoded once; copied into the MP4 and, with `audio.export: m4a`, to `Artist - Title.m4a`. |
| `stems/*.flac` | `lead`, `backing`, `instrumental` and `karaoke`: 24-bit FLAC, 44.1 kHz stereo. |
| `status.json` | State of the song (`running` with the current stage, then `ok`, `review` with reasons or `failed` with the error) and what happened to each stage; written before every stage and at the end, so an interrupted run stays visible. |
| `report.json` | The verdict on the song (`ok`, `review` with reasons, or `failed` with the error), the quality numbers of the alignment, the lines of a second voice and where each came from, the time each stage took, and the files made; written after the last stage and read by `vocatron status`. |
| `progress.json` | Only while the song is being made: the stage, how far it is and the time left, for `vocatron status` from another terminal. Removed when the song is done. |
| `log.txt` | One line per event, written to disk as it happens, with the traceback of an unexpected error. |

## Editing stage files

Stage files are JSON with a `schema_version` and a `fingerprint`: the SHA-256 of every input and
of the stage's settings. You may edit a stage file; the stages after it notice the new content
and run again.
