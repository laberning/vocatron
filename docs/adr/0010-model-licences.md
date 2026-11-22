---
id: ADR-0010
status: accepted
date: 2026-10-29
superseded_by: null
---
# ADR-0010: Model licences

Supersedes ADR-0002 in part: the exclusion of models because of a non-commercial licence.

## Context and problem

ADR-0002 rejected models under non-commercial licences (for example MMS for alignment), on the reasoning that an MIT tool should not depend on them. That mixed two different things. Code that Vocatron installs or ships becomes part of every installation, and its licence matters for everyone who installs Vocatron. Model weights are different: Vocatron downloads them at runtime on the user's machine and never ships or bundles them, so they do not change the licence of Vocatron's code; their terms bind whoever uses them. Excluding non-commercial weights therefore costs quality (some of the best open separation models are non-commercial) without protecting anyone.

## Considered options

1. **Keep excluding non-commercial models.**
2. **Change Vocatron's own licence to a non-commercial one**, to match such models.
3. **Keep MIT for the code and allow any model licence for weights downloaded at runtime**, with clear labelling.

## Decision

Option 3. Vocatron's code stays MIT.

- **Model weights may have any licence** (permissive, copyleft such as GPL-3.0, non-commercial, or none stated), provided that:
  - they are downloaded at runtime from their source and never shipped in the repository or a package;
  - the model registry records the licence, and `THIRD_PARTY.md` and `vocatron models` show it;
  - for a non-commercial model, Vocatron writes a warning to the song log and the stage file when it is used, and the user docs explain that such a model may not be used commercially.
- **A non-commercial model may be the default.** The user docs then state plainly which default models are for non-commercial use only and how to choose others.
- **Code is unchanged:** libraries Vocatron installs stay permissive, LGPL or MPL (ADR-0002); copied code needs a licence that allows copying (code without any licence is never copied).
- Non-commercial **data** (for example test sets) may be used locally for evaluation and is never put into the repository.

## Consequences

- Model choices are made on quality, speed and fit, with the licence documented rather than deciding.
- Commercial users must check the licences of the models they use; Vocatron tells them which ones.
- A multilingual alignment model under a non-commercial licence could serve as a fallback for languages without their own module; that is a separate decision.
- The registry, `THIRD_PARTY.md` and the user docs carry the licence of every model and the warning for non-commercial ones.
