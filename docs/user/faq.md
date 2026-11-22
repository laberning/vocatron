# FAQ and known limits

What Vocatron cannot do, and short answers to common questions.

## Known limits

| Limit | Detail |
|---|---|
| Platform | Linux is the platform it is developed and tested on (WSL2 included). The setup also knows macOS, but it is not tested there and there is no GPU path for it. |
| Languages | German and English. One language per song; a song in another language fails with a message that names the language, and a song that switches language is not handled (see [Languages](languages.md)). |
| No editor | To fix a result you fix the lyrics file and run `vocatron make` again. Timings are not edited by hand in the usual workflow (you may edit a stage file, see [Files and folders](folders.md)). |
| GPU | Strongly recommended: an NVIDIA GPU (CUDA) with 6 GiB of memory at least; other GPUs are not used. Without one the separation runs on the CPU, about 20 times slower. See [Installation](install.md). |
| CD+G | New. Switch it on with `outputs: [mp4, cdg]` ([CD+G](cdg.md)). Every classic built-in look is made and checked for it (the modern looks `neon`, `lyric-video` and `lyric-scroll` are for the video only), and `cdg_zip: true` packs the pair into one zip. |
| Lyrics | They come from you or from LRCLIB. There is no other source; a song without lyrics fails. |

## Questions

### Why is a song marked `review`?

It has its track; a stage was unsure. The reasons in brackets name the stage and give numbers.
See [Everyday use](everyday.md) for what to look at.

### Why does a song say a character is "not in the font"?

Vocatron draws all text in one bundled font and checks every character when it reads the lyrics.
A stray symbol (`√`, a heart, an emoji) is dropped from its line and the song is marked
`review` with the line and the character; note signs (`♩ ♪ ♫ ♬`) are dropped without a reason. A letter or digit the font lacks, as in a script it does
not cover, stops the song with a message that names the line and the character; replace or remove
it in your lyrics file and run again. The same rule applies to the title, the artist and the
singer names on the start screen.

### Where are my files?

The video, the audio and the enhanced lyrics are in a `karaoke/` folder next to the song; the
intermediate files of each song are in its work folder. See [Files and folders](folders.md).

### How do I fix wrong lyrics?

Edit `Song.txt` next to the song and run `vocatron make` again. Only what depends on the lyrics
runs again. See [Lyrics](lyrics.md).

### Can I use my own lyrics with line times?

Yes: a `Song.lrc` next to the song is used as it is. Its line times are checked against the
singing and guide the alignment.

### Does it need the internet?

For the first setup, for downloading the models, and for the lyrics lookup. With the models
downloaded, your own lyrics files (or `lyrics.lookup: false`) and `vocatron make --offline`, it
works without it.

### Can I run it without a GPU?

Yes, with the CPU build of PyTorch (`make setup TORCH_EXTRA=cpu` or when no NVIDIA GPU is found).
With an AMD, Intel or Apple GPU it runs on the CPU, too. A song takes much longer; the separation
is the slow part.

### Is `fdkaac` really needed?

For the default AAC encoder, yes. Set `audio.encoder: ffmpeg-aac` to use ffmpeg's own encoder
instead; see [Installation](install.md).

### Can I change how the lyrics look?

Yes: profiles and presets. See [The karaoke video](video.md), [Looks](looks.md) (with pictures,
and how to make your own) and [Configuration](config.md).

### Which licence do the songs and models have?

Vocatron is MIT. The models keep their own licences, which bind whoever uses them; Vocatron warns
when it runs a non-commercial one. See [Models](models.md) and `THIRD_PARTY.md`.

### Where do I report a problem?

In an issue on GitHub; please do not paste real song lyrics. For a security problem, see
`SECURITY.md`.
