# Synchronising the lyrics

How Vocatron finds when every word and syllable is sung, and what makes a song need review. Two
stages do it, so that the highlighting in the karaoke video follows the singer.

- **`alignment`** listens to the lead vocals (the `lead.flac` of the [separation](separation.md))
  and places every word of the lyrics in time. It writes `alignment.json`: for each word its
  start, its end and a confidence, whether it was only estimated, and for each line where it
  starts and ends.
- **`syllables`** splits each word into the syllables it is sung in and shares the word's time
  among them. It writes `syllables.json`.

Both stages are skipped when what they read and their settings did not change.

## How the words are placed

The lyrics are aligned on the singing with an AI model that knows the letters of the song's
language (German or English; see [Languages](languages.md) and [Models](models.md)).

- Numbers are spelled out for the model (`1999` is heard as "neunzehnhundertneunundneunzig" in a
  German song and as "nineteen ninety-nine" in an English one) but shown as written.
- Characters the model does not know are left out when listening (`ß` is heard as `ss`, the
  apostrophe of "don't" is not heard).
- A word is *estimated* when the model was not sure about it, or when it has no sound at all (a
  dash, say). Estimated words are marked in `alignment.json` and counted in the quality report.
- Inside a word, a syllable starts where its first letter was heard; for an estimated word the
  time is shared by the length of the syllables.

## Where an estimated word is placed

Vocatron measures how loud the lead vocals are in every 20 ms and derives from it where the
singing voice sounds. An estimated word is then placed on the voice between the words around it.

- After a pause it starts where the voice starts again, and it lasts as long as its letters need at
  the speed of the song's own measured words.
- It never leaves the time between its neighbours, so a short, shouted word after a pause is
  highlighted when it is sung and not already during the pause.
- A measured word of moderate confidence that lies almost entirely in silence is judged misplaced:
  it is estimated instead and placed the same way (if the voice cannot place it, it keeps its
  measured time).
- Measured words that the model heard clearly are not changed.

### Unsure words the voice backs up

An unsure word is not thrown away when the voice backs it up. The model often finds short words
("I", "I'm", "bin", "ich") in the right place but with a low confidence.

- Such a word keeps the position the model found for it when at least half of that position is
  voiced, or when it ends right before the next word of its line (within 0.3 s).
- The first word of a line counts as voiced only if the voice began after the word before it, or if
  the word follows that word directly (within 0.1 s); otherwise the held note of the previous line
  does not count.
- It stays an estimated word, and its length is at least what its letters need.
- The other estimated words (those the model has no position for, those whose position the voice
  does not back up, and measured words in silence) are placed on the voice as described above, so
  with the voice in use most estimated words are usually kept and only a few placed.
- A run of estimated words never reaches over a line break: the first words of a line are placed
  backwards from the word that follows them (at the last voice start that leaves room, or right
  before that word), and the last words of a line go forward from the word before them, at most 3
  seconds. This keeps a short word at the start of a line from lighting up during the held note of
  the line before.
- The `voice` block of `alignment.json` counts the kept words (`kept`) apart from the placed ones
  (`placed`).

### Lines that are not heard

Some lines are not heard at all: the model finds none of their words (for example a vowel phrase
sung only by the backing vocals over a busy mix), so its path through them is arbitrary.

- When the line times of the `.lrc` fit the recording up to one offset (`shifted`, see below), such
  a line is placed at its time instead (plus that offset, never before the start of a measured word
  before it and never after the start of the next line). Its words follow the voice up to the next
  line, else they share the time by letters.
- The `voice` block counts these lines (`unheard`) and the song log says so.
- If less than half of the line's window is voiced, the song needs review.
- Lines without a time in the `.lrc` and lines with at least one heard word are not touched.

### Two voices at once

Some songs have a second voice that sings a different line while the first is still singing. One
path through all words in order cannot time both: the first line would be cut short, the next one
squeezed, and the lines after them late. Vocatron therefore gives every line a voice (first or
second) and searches each voice in a path of its own, so lines of the two voices may overlap.

- The second voice comes from the lyrics file (the same `.lrc` time, or `{&}`; see
  [Lyrics files](lyrics.md)) or from the audio. Without line times that fit, only the file counts.
- From the audio, a line goes to the second voice when the backing vocals hear it clearly better
  than the lead, the lead vocals are silent while it is due or hear nothing of it, its letters
  come at least 1.5 times faster than the song's lines usually do, and the second voice is free
  (its last line started at least 0.65 of a usual line spacing earlier).
- The first voice is searched on the lead vocals (with the backing mixed in where the lead is
  silent), the second on the backing vocals (and on the lead where the backing is silent). Lines
  that share one `.lrc` time end at most 0.2 s after the time of the next line; other
  second-voice lines at most 3 s after it.
- `alignment.json` tells every line's voice; the song log and `report.json` name the lines of the
  second voice and where each came from. A song with one voice is searched in one path, as is a song whose second voice cannot be searched.

### When the voice is trusted

- The loudness is trusted per song only when the voice stands out clearly from the noise of the
  lead track (a lead track full of backing vocals or instruments does not) and when a sensible
  share of the song is voiced.
- Per word it is trusted only when the voice starts inside its gap. Otherwise the word takes the
  time between its neighbours in proportion to its letters.
- The `voice` block of `alignment.json` tells whether the voice was used for the song, why not, and
  how many words it placed, kept or re-estimated; the song log says so too.
- Placing words on the voice can show pauses inside lines that the old placement hid, and
  re-estimated words count as estimated, so a song can turn to `review` that was `ok` before.
- `alignment.voice_activity: false` switches the whole step off; see [Configuration](config.md).

### Which loudness

The loudness is measured on the lead and backing vocals added together (`alignment.voice_source:
vocals`, the default): the separation sometimes puts shouted or doubled words into the backing
vocals, and they would look silent on the lead alone.

- On the benchmark songs and the demo song this placed more words and moved no song's line starts
  by more than 10 ms.
- A song whose backing harmonies mislead it can use `lead` instead.
- The model aligns on the lead vocals either way, and changing the setting re-runs the alignment.

### Where a word ends

The model hears the last letter of a word for a fraction of a second, so a word would end before
the singer stops and the highlight of a held note would finish early. Where the voice is used for
the song, a word the model heard clearly therefore ends where the voice stops.

- It ends at the end of the voiced stretch that holds its last letter, but never after the next
  word starts and never more than 4 seconds after its last letter (a guard against an outro).
- Starts never change, so the line starts, and with them the check against an `.lrc`, stay as they
  are.
- Words inside a sung phrase touch each other, as on classic karaoke discs, while real pauses
  (from about 0.15 s) stay.
- The last syllable of a word gets the held time.
- For the review rules a word is too long only when the model heard it for long, so a held note is
  not too long, and too short only when it is not held either; a held note is not a gap.
- A line ends with its last word, so the pause before a break or the end screen starts later,
  closer to the singing.
- The `voice` block of `alignment.json` counts the words whose end moved (`held`) and the median
  move (`held_median`).
- With `voice_source: vocals`, backing harmonies that continue after a lead word can stretch its
  end; `lead` is the remedy for such a song.

### Words in the backing vocals

The separation sometimes puts a sung word into the backing vocals, for example a word shouted by
several voices. The lead track is silent there, the model cannot recognise the word, and its time
has to be estimated. With `alignment.hear_backing` (on by default) the model also listens to the
backing vocals.

- It listens only in frames where the lead vocals are silent, the backing vocals sound and the
  model heard no letter in the lead. Frames inside a word that the model heard clearly in the lead
  are never taken, so a quiet lead line under a doubled backing keeps its result.
- Wherever the lead sings, the alignment uses the lead alone; a song without such frames gives
  exactly the same words, and a song whose lead voice is not plausible (see above) is left alone
  too.
- Words that the backing makes measurable get normal confidence and letter times, are highlighted
  when they are sung and end where the voice stops like any other.
- Call-and-response lines sung at the same time with different words are not shown apart yet: the
  alignment places them one after the other.
- The `backing` block of `alignment.json` tells whether the backing was used, why not (`switched
  off`, `lead voice not plausible`, `no backing frames`), in how many frames and for how many
  measured words; the song log says so too.
- The second pass of the model costs a few seconds per song on the GPU.
- `alignment.hear_backing: false` switches the step off; see [Configuration](config.md).

## Line times from an `.lrc`

If the lyrics came from an `.lrc` with line times, those times are used as hints, never as the
truth. Vocatron first aligns the song without them, then compares:

| What it finds | What happens | `rails` in `alignment.json` |
|---|---|---|
| The `.lrc` lies by one steady offset away from the singing (the median difference, with most lines within half a second of it) | The offset is added to the times, and each line must lie between 1.5 seconds before its corrected time and 1.5 seconds after the corrected time of the next line, always inside the song. The alignment then runs again inside these windows. | `shifted`, with the offset |
| The times disagree with the singing | They are ignored. The song needs review: "lyrics times do not fit". | `ignored` |
| Fewer than three lines have a time, or `alignment.use_lrc_times` is `false` | Nothing is compared. | `none` |

A time tag that is out of order (a line that is tagged later than the next line, for example
`[02:23]` typed for `[01:23]`) does not spoil the others.

- Before the comparison, Vocatron keeps the largest set of times that are in order and skips the
  rest, as few as possible. Of two times that contradict each other, the one further from where the
  singing was found is skipped.
- Each skipped line is named in the song log and in `rails.dropped` of `alignment.json` (its line
  number and time tag), and `vocatron make` and `vocatron lyrics` print a warning about it at the
  end.
- The line number counts the sung lines of the lyrics, not the rows of the file (ID tags such as
  `[ti:]` and removed headings are not counted), so look for the time tag.
- The remaining times are compared and used as above.

Your `.lrc` is never changed. Where the `.lrc` and the singing disagree, the singing wins.

## What makes a song need review

The quality report in `alignment.json` feeds the song status ([`vocatron status`](commands.md)).
A song is marked `review`, with the reason named in the status, when:

| Reason | Meaning |
|---|---|
| `N% of words estimated (max 10%)` | More than 10 % of the words could not be measured. The lyrics may differ from what is sung, or the singer is hard to hear. |
| `X s gap in line N (max 3 s)` | Two words of one line are more than 3 seconds apart. The line may be split in the wrong place or a word may be misplaced. |
| `N words of odd length (max 5)` | More than five measured words are held for less than 60 ms or heard for longer than 3 s, an implausible length. A held note does not count as too long, and a short word like "a" that the singer holds does not count as too short. The exact counts are in `report.json`. |
| `line N: its time looks early` | The first words of the line were measured with low confidence (mean under 0.5) and sit before a gap of at least 1.5 seconds in which the voice is silent, while the rest of the line is sung later: the line time is probably early and the first words were pulled into the line before. With several lines, `lines N, M: their times look early` (up to five numbers, then a count). Check the time tag of the line in the `.lrc`. |
| `little voice where line N was placed at its time` | A line the model did not hear was placed at its `.lrc` time, and less than half of its window is voiced: nothing in the audio backs the time up. With several such lines the reason names up to five line numbers (`lines N, M were placed at their time`), then a count of the rest. |
| `lyrics times do not fit` | See above: the line times of the `.lrc` do not match this recording. |

Words that were estimated do not count towards the odd-length reason, since their length is a
guess.
Syllables have no reasons of their own.

## When the run did not finish

A partial run such as `vocatron lyrics` stops after the lyrics. If the lyrics changed meanwhile,
the alignment and the syllables no longer match them: the song is `review` with the reason
"not finished, run `vocatron make`", and `vocatron make` finishes it. The same reason appears
for a stage that was running when an earlier run was interrupted.

## Errors

| Error | Cause and what to do |
|---|---|
| `alignment-failed` | The lyrics cannot be aligned: they have no sound the model knows, or are far too long for the recording. The message says which. |
| `alignment-timeout` | The model did not finish in time and was stopped. The limit is one song length plus two minutes on the GPU and 15 song lengths plus two minutes on the CPU; change `alignment.timeout_factor_gpu` or `timeout_factor_cpu`. |
| `out-of-memory` | The GPU is too full. Close other programs that use it, or use `--device cpu`. |

The acoustic model runs in a separate process that Vocatron watches, with half precision and at
most 75 % of the GPU memory, like the [separation](separation.md). Its steps are written to the
`log.txt` of the song.
