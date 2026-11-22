# Contributing

Issues are open. Pull requests are welcome for fixes, tests, documentation and targeted
improvements. For a larger feature or a change of the architecture, open an issue first so that we
agree on the scope before you write code.

## Set up

```sh
git clone https://github.com/laberning/vocatron.git
cd vocatron
make setup
make help
```

Everything stays inside the clone: the environment, the tools, the caches and the models. Add
editor and assistant configuration of your own to `.git/info/exclude` of your clone, not to
`.gitignore` ([ADR-0001](adr/0001-repository-and-documentation-structure.md)).

## Check your change

```sh
make check      # static checks, the fast tests and duplicated code, every gate even after a failure
make summary    # only the failures, with file and line
make docs       # the documentation site in strict mode
```

`make check` needs no GPU and no network. `make check-all` adds the slow tests, which use real
models and a GPU and are skipped without one. Write each test on the lowest stage that can show
the behaviour ([ADR-0004](adr/0004-test-harness-and-definition-of-done.md), [Test
harness](dev/harness.md)).

## The Definition of Done

A pull request is ready when:

1. `make check` is green (and `make check-all` if you touched an engine or a slow test).
2. New or changed behaviour has tests on the lowest fitting stage.
3. No quality gate is weakened: no lower threshold, no removed import contract, no suppression
   (`noqa`, `type: ignore`) without a reason written next to it.
4. No duplicated logic: each rule lives in one place.
5. Docstrings (Google style, full type hints), user docs (`docs/user/`) and developer docs
   (`docs/dev/`) are updated.
6. A new decision has an ADR ([ADR-0001](adr/0001-repository-and-documentation-structure.md)); a
   changed decision supersedes its ADR with a new one.
7. A changed JSON schema or snapshot is intended: bump `schema_version`, export the schema with
   `make schemas`, and say so in the pull request.
8. A change that alters what a stage produces raises that stage's version.
9. `CHANGELOG.md` has a line under "Unreleased" for what users will notice.

## Rules to know

- The layers `core`, `lab`, `engines`, `stages` and `cli` and their import rules are enforced
  ([Architecture](dev/architecture.md)); never weaken a contract to make a change pass.
- Every engine has a protocol and a fake; clock and randomness are injected; heavy imports stay
  inside engines.
- Diagrams are Mermaid with the hand-drawn config and no colours; no `> [!note]` callouts in
  `docs/` ([ADR-0003](adr/0003-code-documentation.md)).
- The docs describe Vocatron as it is: pages for users link no ADR, no page or code credits a
  person with a decision, and no page names a private place ([Test harness](dev/harness.md)).
- **No real song lyrics, songs, stems or model files in the repository**: not in code, tests,
  fixtures, snapshots, docs, issues or pull requests. Fixtures use public-domain texts (German folk
  songs, for example) or invented text. The two demo songs are freely licensed and are downloaded,
  not committed ([Test harness](dev/harness.md)).
- Commits use conventional messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).

## Where to start

- [Architecture](dev/architecture.md) and the [decisions](adr/README.md).
- [Adding a stage](dev/adding-a-stage.md), [a language](dev/languages.md), [a style profile or a
  renderer](dev/video.md).
- [Releasing](dev/releasing.md), for maintainers.

By contributing you agree that your contribution is licensed under the MIT licence of the project.
Report a security problem as described in `SECURITY.md`, not in a public issue.
