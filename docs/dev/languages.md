# Language modules

A language is a module in a registry ([ADR-0005](../adr/0005-language-support.md)). The
alignment and the syllables stages ask the registry for the module of the song's language
(`lyrics.json` says which) and do nothing else that depends on a language. German
(`de.py`) and English (`en.py`, the worked example below) are registered.

## What a module provides

`LanguageModule` (`vocatron.core.languages.base`) is a protocol:

| Member | Meaning |
|---|---|
| `code`, `name` | ISO 639-1 code and English name. |
| `model` | The registry name of the alignment model (`vocatron.core.models`). |
| `alphabet` | The letters the model knows, lower case, without the word delimiter. `normalise` returns only these. |
| `together_two`, `together_all` | The words for lines sung together, shown on the title screen of a song with such lines ([ADR-0020](../adr/0020-a-silent-intro-before-the-song.md)): "Beide"/"Both" for two singers, "Alle"/"All" for three or more. The layout stage takes them from the module of the song's language (`syllables.json`) and hands them to the layout in `SongText`. |
| `normalise(word)` | The letters the model should hear for a written word: lower case, letters outside the alphabet replaced (`ß` as `ss`, `æ` as `ae`) or dropped, accents removed, apostrophes and hyphens dropped. May be empty. |
| `spell_numbers(text)` | The text with its numbers written out, word by word. |
| `syllables(word)` | The syllables the word is sung in. They always join to the word; punctuation stays with its syllable. |

## The rules modules share

What does not depend on the language lives once in `vocatron.core.languages.base`:

- `fold(word, alphabet, replacements)` for `normalise`: lower case, `replacements`, accents
  dropped, the rest dropped.
- `spell_run` and `is_cardinal` for runs of digits: a lone four-digit run from 1100 to 2099
  is a year, anything up to a million a cardinal, longer runs are spelled digit by digit.
- `edges(word)`, `is_lone_number(core)` and `spell_words(text, spell_core)`: a word is its
  punctuation before, its core and its punctuation after; a module only says how the core of a
  word is spelled.
- `Hyphenation`: the dictionary split with one letter allowed on each side (so "a-ber" splits),
  a part without a vowel joined to its neighbour, hyphenated words split part by part, and an
  exception list for what the dictionary gets wrong (found on the fixtures; the word is cut
  where its exception says and keeps its own case, so `MAYBE` gives `MAY`, `BE`). A language
  states its dictionary, its vowels, its exceptions and, where it needs them, the characters
  after which a word is cut first (`joiners`), the ones that bind a vowel-less or listed ending
  to the part before (`glued`, `endings`) and `lone_edges`.

A module is the part that is left: its alphabet, its replacements, its number words and its
settings for `Hyphenation`. `vocatron.core.languages` must never import `vocatron.core.models`
(an import contract); the model registry imports the languages, to say which models a song in a
language needs (`language_models`).

## English, the worked example

`vocatron/core/languages/en.py` is the module of a second language:

1. **Alphabet and `normalise`:** `a`-`z`, `æ` as `ae`, `œ` as `oe`, everything else folded or
   dropped. The apostrophes of "don't", "'cause" and "goin'" are dropped for the model only; the
   screen shows the word as written.
2. **Numbers:** an own small speller, no dependency. Cardinals up to a million in the sung form
   ("one hundred and one"); a lone four-digit number from 1100 to 2099 is a year ("nineteen
   ninety-nine", "nineteen oh five", "nineteen hundred", "two thousand five", "twenty ten");
   `1st`/`22nd` are ordinals of any cardinal; `60s`, `'60s` and `1960s` are decades ("sixties",
   "nineteen sixties"); digits inside a word are spelled and joined to it (`4ever`). A spelled
   number stays one word for the aligner: its letters run on, as German compounds do.
3. **Syllables:** pyphen's `en_US` dictionary (BSD-style licence, see `THIRD_PARTY.md`) with a
   small exception list ("maybe", "tonight", "Mary"). A word-initial lone `y` before a vowel
   ("you") and a final lone `e` ("inside") are no syllables (`lone_edges`). An apostrophe stays
   with its syllable, and the ending of a contraction ("'t", "'re", "'ve") is sung with its word.
4. **Model:** the `wav2vec2-en` entry of the registry (`facebook/wav2vec2-large-960h-lv60-self`,
   pinned by revision, sizes and SHA-256, [ADR-0016](../adr/0016-english-alignment-model.md)).
   Its vocabulary is upper case; the alignment compares lower-case letters, so
   `load_vocabulary` passes the tokens through `lower_case_vocabulary` (`core/alignment/tokens.py`;
   the German vocabulary is already lower case and comes out unchanged, two tokens that become
   the same are an error).
5. **Fixtures:** `tests/conformance/fixtures_en.py` from public-domain songs and invented text,
   registered in `FIXTURES`; the kit also runs property tests (no digit survives, syllables join
   to the word). Module-specific tests are in `tests/fast/core/languages/test_en.py`.
6. **Benchmark:** English songs with human line times go to `.corpus/songs-en`; `make bench`
   reports and gates each language on its own (see [Alignment and benchmark](alignment.md)).

## Adding a language

1. Write the module and register it in `LANGUAGES` (`vocatron/core/languages/__init__.py`). Use
   `fold`, `spell_words` and `Hyphenation` instead of writing the shared rules again.
2. Add the alignment model to the model registry and to `THIRD_PARTY.md`, with the licences of
   the model and of the hyphenation dictionary. If its vocabulary is not lower case nothing else
   is needed: `load_vocabulary` lowers it.
3. Write its fixtures in `tests/conformance/` and register them in `FIXTURES`.
4. Put songs of that language in the benchmark corpus, in the folder `bench_files(code).songs`
   names (`songs-<code>`), and write the fixtures of its number words and syllables.
5. Add its demo song to `tests/data/demo/demo.toml` if it has one; the end-to-end test runs
   once per song.

The conformance kit (`tests/conformance/language_kit.py`) runs the same checks over every
registered module: metadata and model registry entry, the two words for singing together (not
empty, no digits, different), normalisation stays inside the alphabet and is stable, numbers leave no digit, syllables join to the word, and any text is handled. A
module without fixtures fails.

## The model of the song's language

The alignment stage asks `declared_settings(ctx, config)` and `required_models(ctx, config)`
with the song's context. Both take the language from the song's `lyrics.json` (the lyrics stage
has already applied `lyrics.language` or the detection there), and fall back to the configured
language, else `DEFAULT_LANGUAGE`, when the file does not exist yet (the batch plans a song
before its lyrics stage has run, and the missing input already makes the alignment not current
then). The model is therefore pinned in the fingerprint and fetched just before the alignment
runs. A German song gives exactly the pin it had before the second language existed, so stored
German results stay current.
