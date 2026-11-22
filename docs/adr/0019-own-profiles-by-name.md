---
id: ADR-0019
status: accepted
date: 2026-11-01
superseded_by: "ADR-0045 (in part: the pictures show six moments of the English demo song)"
---
# ADR-0019: Own profiles by name, a profile check and pictures of the looks

Adds to ADR-0009 (style profiles).

## Context and problem

ADR-0009 lets `profile` name a built-in profile or give the path of a YAML file, and `profile_overrides` change single values. A fan who wants an own look has to find the package's YAML files, copy one, and learn by rendering whether it fits the screen; the docs describe the profile keys but show no look. A value without a path, such as `mine`, is taken as a file path.

## Considered options

1. **Paths only**, as today, with better docs.
2. **A folder of own profiles chosen by name, where an own profile of a built-in name replaces the built-in one.**
3. **A folder of own profiles chosen by name, where a name that is built in and in the folder is an error.**

## Decision

Option 3.

- The setting `profiles_folder` (no default, relative to the configuration file) holds own profiles; `profile: <name>` picks `<name>.yaml` there, like a built-in name.
- A value without a path separator and without the ending `.yaml` or `.yml` is a name; anything else is a path, as before.
- A name that is both built in and in the folder is an error whose message points to `profile_overrides` (to change single values of a built-in look) and to `vocatron profiles copy` (to start an own look from it). An unknown name is an error that lists the names that exist.
- `vocatron profiles` lists the profiles; `vocatron profiles check` checks one without rendering: it loads, passes the contrast rules, fits the safe area in every output preset and keeps the scene rules on sample lyrics, with the configuration's `profile_overrides` applied. The scene rules move from the tests into `core`, so the check and the tests use one set of rules.
- `vocatron profiles copy` writes an editable copy of a built-in profile and never overwrites a file.
- The user docs show one picture per built-in profile, four moments (start screen, a line being sung, a line or page change, the countdown) from a public-domain folk song, made by `make profile-pictures`. A fast test checks a manifest of the pictures' inputs, so a changed profile without new pictures fails.

## Consequences

- A shared name never silently changes a look: a configuration that says `blue-page` looks the same everywhere, and fixes to the built-in looks reach every user.
- A value such as `mine` that meant a file without an ending must now be written `./mine` or `mine.yaml`.
- The pictures' manifest covers their inputs, not their pixels, since ffmpeg builds differ between machines; a new ffmpeg or libass does not make them stale.
