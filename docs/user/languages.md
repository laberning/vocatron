# Languages

Which languages Vocatron supports and how it finds and uses them. Vocatron makes karaoke in
**German** and **English**. A song has one language, and Vocatron recognises it from the lyrics by
itself, so a folder with songs in both languages just works.

## How the language is found

The lyrics stage detects the language from the text of the lyrics (with the library lingua) and
writes it to `lyrics.json` in the work folder. The language decides which acoustic model aligns
the song, how numbers are spelled out for it and how words are split into syllables.

- **Automatic:** leave `lyrics.language` unset. Detection needs some text; a few words, an
  exclamation or a mostly instrumental song can be taken for another language, or for none.
- **Override:** name the language with `lyrics.language: en` in the [configuration](config.md)
  or `--language en` on `make` and `lyrics`. The detection is then skipped for every song of the
  run.
- **Unsupported:** a song in another language (or a setting such as `fr`) fails with a message
  that names the language and the supported ones. For a song that is wrongly taken for another
  language, set the language yourself.
- **Mixed songs:** a song is German or English as a whole; the language that most of the text
  is written in wins. A German song with one English line stays German.

## The model of a language

| Language | Model | Source |
|---|---|---|
| German (`de`) | `wav2vec2-de` | `jonatasgrosman/wav2vec2-large-xlsr-53-german` |
| English (`en`) | `wav2vec2-en` | `facebook/wav2vec2-large-960h-lv60-self` |

- Both are about 1.2 GB. A song needs only the model of its own language.
- Vocatron fetches it just before it aligns the song: a folder of German songs never downloads the
  English model.
- With `--offline` a song whose model is missing fails and names the command that fetches it.
- To fetch a language's models in advance, run `vocatron models download --language en` (see
  [Models](models.md)).
- A folder with German and English songs runs in one batch; each song is aligned with its own
  model, and the stored results of earlier German runs stay current.

## Numbers and syllables

Numbers are spelled out for the model, in the words of the song's language, and shown as written.

| Written | English | German |
|---|---|---|
| `21` | twenty-one | einundzwanzig |
| `101` | one hundred and one | einhunderteins |
| `1999` | nineteen ninety-nine | neunzehnhundertneunundneunzig |
| `2005` | two thousand five | zweitausendfünf |

Reading rules:

- A lone four-digit number from 1100 to 2099 is read as a year.
- Any other number up to a million is read as a cardinal.
- Digits inside a word (`4ever`) are spelled and joined to it.
- Longer numbers are read digit by digit.
- English also reads ordinals (`21st` as twenty-first) and decades (`60s` as sixties, `1960s` as
  nineteen sixties).

Syllables: words are split into the syllables they are sung in with a hyphenation dictionary
(`de_DE` for German, `en_US` for English), plus a short list of words the dictionaries get wrong.
In English an apostrophe stays with its syllable (`don't`, `'cause`, `goin'`) and the model does
not hear it.
