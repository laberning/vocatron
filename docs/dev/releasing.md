# Releasing

Vocatron is released as git tags on GitHub, never on PyPI. Every release is a signed tag
`vMAJOR.MINOR.PATCH`, a section in `CHANGELOG.md` and a GitHub release with notes.

## Versioning rule

[Semantic versioning](https://semver.org/) while below 1.0:

- a new **minor** version (0.2.0) for new features or changed behaviour, including a change that
  makes stored results be made again;
- a **patch** (0.1.1) for fixes that change no behaviour users rely on.

The version is written once, in `pyproject.toml` (`version = "X.Y.Z"`), and in `uv.lock` for the
package itself (`uv lock` updates it). The tag must equal it: CI runs `make tag-check TAG=vX.Y.Z`
on every pushed tag that starts with `v` and fails when the tag and the version differ or
`CHANGELOG.md` has no `## [X.Y.Z]` section.

## Checklist

1. All work for the release is merged; `make check` and `make check-all` are green on the GPU
   machine; `make docs` is green.
2. `make licenses` is green and `THIRD_PARTY.md` is up to date (new dependencies, models, assets).
3. `make history-scan` reports no findings (see below).
4. Set the version in `pyproject.toml`, run `uv lock`, and rename "Unreleased" in `CHANGELOG.md` to
   `## [X.Y.Z] - YYYY-MM-DD` (add an empty "Unreleased" above it). For 0.1.0 this is prepared as
   `## [0.1.0] - unreleased`: replace "unreleased" with the date of the tag, and move anything
   that has since been added under "Unreleased" into it.
5. Write the release notes of the GitHub release from the `CHANGELOG.md` section of the version.
6. Commit, then create the signed tag and push it:

   ```sh
   git tag -s vX.Y.Z -m "Vocatron X.Y.Z"
   git push origin main vX.Y.Z
   ```

7. Check that the `tag-check` job of CI is green, then create the GitHub release from the tag
   with the notes.

## The history scan

`make history-scan` reads every commit of every ref and reports, by kind, how many commits hold
other projects' names, planning notes, local paths, audio, model or lyrics files outside
`tests/data/demo/`, the local corpus, agent files or secrets, with the commit ids and never the
matched text. Look at a finding with `git show <id>`. If something that must not be public was
committed by accident, the history has to be cleaned before the repository is made public; that is
the maintainer's decision and work, because it rewrites commits.

## Making the repository public

Publishing is a separate step from releasing. When the repository becomes public: enable GitHub
Pages with the source "GitHub Actions" (the workflow `.github/workflows/docs.yml` skips its jobs
while the repository is private and publishes the site on the next push to `main`), and turn on
private vulnerability reporting for `SECURITY.md`.
