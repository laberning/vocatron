---
id: ADR-0016
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0016: English alignment model

Supersedes ADR-0002 in part: the English alignment model (ADR-0002 named `jonatasgrosman/wav2vec2-large-xlsr-53-english`). Adds to ADR-0005 (language modules).

## Context and problem

English is the second language (ADR-0005). Its language module needs an acoustic model for the forced alignment, chosen like the German one: by measuring candidates on real songs against human line times.

## Considered options

Three Apache-2.0 models, each aligned on five English songs (pop, folk-pop, disco, a ballad with a long echoing outro, a jazz standard; 218 lines) with Vocatron's own pipeline and today's defaults (voice activity, hearing the backing), without `.lrc` hints, compared with the songs' human line times:

| Model | Corrected median | Lines within 200 ms | Estimated words | Model time per song | Peak VRAM |
|---|---|---|---|---|---|
| `jonatasgrosman/wav2vec2-large-xlsr-53-english` (sibling of the German model) | 110 ms | 74 % | 20 % | 3.0–4.7 s | 0.96 GiB |
| `facebook/wav2vec2-large-960h-lv60-self` | 85 ms | 80 % | 12 % | 2.6–4.6 s | 0.96 GiB |
| `facebook/wav2vec2-base-960h` | 100 ms | 78 % | 10 % | 1.8–2.8 s | 0.47 GiB |

## Decision

`facebook/wav2vec2-large-960h-lv60-self` (chosen by measurement). It is best overall and on three of five songs, estimates the fewest words of the large models, and costs the same as the sibling of the German model. Its vocabulary is upper case; the alignment compares letters in lower case, so the vocabulary is lower-cased when it is loaded.

## Consequences

- English songs are aligned with this model; it is downloaded when a song needs it.
- The choice rests on five songs; two more (a song with a choir backing, a rap) are to come and are measured when they are there. A clearly better result for another model would supersede this ADR.
- `wav2vec2-base-960h` stays a smaller fallback candidate for machines with little GPU memory.
