---
id: ADR-0005
status: accepted
date: 2026-10-28
superseded_by: null
---
# ADR-0005: Language support

## Context and problem

Alignment quality depends on a model trained for the song's language; syllable splitting and the spelling of numbers ("20" sung as "zwanzig" or "twenty") are language rules too. Vocatron starts with German and adds English soon after; more languages should be addable without touching the pipeline. Multilingual alignment models exist, but the known one with good coverage is licensed for non-commercial use only and was clearly worse on German in our tests.

## Considered options

1. **One multilingual model** for every language.
2. **Language modules**: one module per language with its own model and rules, chosen per song.
3. **Language modules with a multilingual fallback** for unsupported languages.

## Decision

Option 2.

- **A language is a module** registered in a language registry. It provides:
  - the alignment model (name, revision, checksum) and its character set,
  - text normalisation for the model (case, characters outside the model's alphabet, e.g. `ß` → `ss` for German),
  - number spelling for cardinals and years, so the model sees the sung words while the screen shows the lyrics as written,
  - syllable rules (pyphen dictionary plus language-specific fixes).
- **One language per song.** The language is detected from the lyrics (lingua); a command-line or config option overrides it.
- **Unsupported language is an error** for that song, with a message that names the detected language and points to the developer docs on adding a module. There is no multilingual fallback.
- **Order:** German first, English next; others when someone adds a module.
- **Every module passes the same conformance test kit** (normalisation round trip, number spelling, syllables, model metadata) and gets its own sync benchmark set (ADR-0004, stage 3).

## Consequences

- Adding a language is a self-contained change: a module, its benchmark songs and its entry in `THIRD_PARTY.md` (model and dictionary licences).
- Songs that mix languages are not supported for now.
- The registry and the conformance kit follow the extension-point rules of ADR-0007.
