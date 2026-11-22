# Test harness

One entry point for every check: `make`. `make help` lists the targets. The stages and the
Definition of Done are decided in [ADR-0004](../adr/0004-test-harness-and-definition-of-done.md),
the gates in [ADR-0007](../adr/0007-architecture-and-code-quality.md).

## Setup

`make setup` installs the uv version pinned in `pyproject.toml` (`[tool.uv] required-version`, the
one place for it) into `.tools/bin` (if `uv` is not given with `UV=uv`), syncs the
locked environment into `.venv/` and checks ffmpeg and libass. Caches live in `.cache/`,
including `TMPDIR`; nothing is written outside the project folder. The one exception is the opt-in
`make install`, which links the `vocatron` command into `BINDIR` (default `~/.local/bin`);
`make uninstall` removes the link (`tools/install_command.py`,
[ADR-0044](../adr/0044-the-command-on-the-path-is-a-link-into-the-clone.md)).

## Stages

| Stage | Target | What |
|---|---|---|
| 0 Static | `make static` | `ruff format --check`, `ruff check`, Pyrefly (strict), import-linter, deptry, vulture, `uv lock --check` |
| 1 Fast | `make fast` | `tests/fast`: no GPU, no network (sockets are blocked), no ffmpeg in the tool tests (soundfile decodes made-up files), 10 s per test, at most `TEST_WORKERS` (6) parallel workers, branch coverage per layer (core 95 %, lab 95 %, stages 90 %, cli 80 %, engines 60 %) |
| 1 Fast | `make diff-cover` | the lines a change touches (against `origin/main`, new untracked files included) are covered at least 90 %; run by `make check` after the fast tests, skipped with a message while there is no `origin/main` yet; in CI a job on pull requests only |
| 2 Slow | `make slow`, `make slow-cpu` | `tests/slow`: real engines and the local corpus. Tests that need a GPU carry the marker `gpu` and are skipped with a reason without one; `make slow-cpu` runs the others on `SLOW_WORKERS` (4) parallel workers, one test file per worker (`--dist loadfile`, so the module fixtures of a file are made once; the files share no state), in about a minute and a half on a laptop (any machine, ADR-0015); `make slow` stays one test at a time, as the GPU tests need. A test that reads the corpus is skipped without any corpus or without the corpus folder it reads, with a message that names [the corpus page](corpus.md), and fails, naming the file, when that folder lacks a file it needs; so `make slow-cpu` is no CI job |
| 3 Benchmark | `make bench` | `tests/bench`: sync quality on the local corpus (`VOCATRON_CORPUS`, default `.corpus/`), one folder and one gate per language (`LANGUAGE=en` for one; an unsupported code is an error); a language without its folder is skipped |

The size of a module is capped too ([ADR-0051](../adr/0051-modules-stay-below-a-thousand-lines.md)),
next to the complexity limits of Ruff: `tests/fast/test_module_size.py` fails, naming file and line
count, for every Python file in `src` and `tests` above 1000 lines. A file that needs more goes
into the list `RAISED` of that test with its limit and a reason; the list is empty, and a
raised limit is a review finding.

A run of stage 2 or 3 that finds no tests says "stage 2 has no tests yet" (or stage 3) and
passes; an empty `tests/fast` still fails.

A failed test of stage 2 or 3 is reported without any value of the run, since the corpus holds
copyrighted lyrics: only the last line of test code that took part, the type of the error, and
the message of a `pytest.fail` or of an `assert` in test code (its first line, without the values
pytest adds); an `assert` in Vocatron or a library keeps its message to itself (`safe_failure` in
`tests/conftest.py`, whatever `--tb` or `-l` says). The captured output of every stage 2 or 3
test is hidden, passed ones too (`-rA`, `junit_logging`), and so is the message of a warning
raised in one (the warnings summary keeps place, category and line of code). This holds for the
terminal, the JUnit files in `reports/` and so for `make summary`. So the message of a corpus
test holds numbers and file names only. `VOCATRON_FULL_REPORTS=1` shows everything, for the
owner of the corpus at their own terminal.

`make check` runs stages 0 and 1 and `make dup` (jscpd, also a CI job of its own), and **every**
gate even after a failure; `make check-all` adds stage 2. Other targets: `make summary`,
`make format`, `make mutation` (mutation testing of `core` and `lab`, on demand, see below),
`make demo-songs`, `make demo-accept`, `make docs`, `make clean`, `make ty` (advisory),
`make ci-targets`, `make licenses`, `make history-scan` and `make tag-check` (see below and
[Releasing](releasing.md)).

## Mutation testing

`make mutation FUNCS="vocatron.core.cdg.encode.plan_tile vocatron.core.cdg.screen.CdgScreen.apply"`
runs the mutants of exactly those functions (a method as `module.Class.method`) and nothing else.
`tools/mutate.py` lets mutmut write the mutants into `mutants/` (it rewrites only the sources
that changed, and refreshes the copy of `tests/`), prints how many mutants it will run, and runs
each as mutmut does: pytest in `mutants/` with `MUTANT_UNDER_TEST` set to the mutant and
`PYTHONPATH=src`, so the tests import the mutated code. It runs the test files of `tests/fast`
that name the module, the class or the function (`--tests` gives them by hand, `--jobs` how many mutants run
at once, `--timeout` the seconds per mutant; call `tools/mutate.py` directly for these), first once
without a mutant to see that they pass. A mutant a test fails on (or hangs) is killed; one that
survives is named, and the exit code is 1. Without `FUNCS` the target refuses; `ALL=1` runs
`mutmut run` on all of `core`, which takes hours because mutmut also runs every test to
learn which covers which function. mutmut does not mutate a decorated function, so logic that
is remembered with `functools.lru_cache` is written plain and wrapped by assignment (see
`core/cdg/encode.py`).

## Demo songs and the end-to-end test

Two freely licensed songs are the public demo and test songs: Systemabsturz "Verdächtig"
(German, CC0) and Josh Woodward "My Favorite Regret" (English duet with a long break, CC BY 4.0).
Their audio never enters git. `make demo-songs` downloads it into the git-ignored `.corpus/demo/`
and checks the SHA-256 of each file; a good file is not fetched again, a wrong checksum fails with
both sums and keeps nothing. This is the only network use for the demo songs (`tools/demo_songs.py`; the
fast tests use a fake downloader). `tests/data/demo/` holds the song list `demo.toml` (artist,
title, licence and its URL, source page, download URL, SHA-256, length), `CREDITS.md` and the
lyrics files `Systemabsturz - Verdächtig.txt` and `Josh Woodward - My Favorite Regret.txt` (named
`Artist - Title`, like every song, so the title screen and the track name are complete). The
lyrics are real song lyrics: agents and tests never print them.

`tests/slow/test_demo_real.py` runs `vocatron make` on each demo song, in its own folder
(`.corpus/demo/make-<code>`), with its lyrics file on the GPU and compares the start of every
word with `tests/slow/golden/demo/<code>/words.json` (median error at most 100 ms, no word more
than 1 s off) and five frames at fixed seconds with the golden PNGs in the same folder. A song
is skipped with a reason without a GPU, without the downloaded song, or while its references do
not exist. `make demo-accept` runs "My Favorite Regret" and writes its references; `make demo-accept
LANGUAGE=de` does the same for the German song. They are committed only after the video
has been watched. Anyone with a clone and a GPU can run it with `make demo-songs slow`, without
the private corpus.

## Definition of Done

A change is done when ([ADR-0004](../adr/0004-test-harness-and-definition-of-done.md)):

1. `make check` and `make slow-cpu` are green, and `make check-all` too if the change touches an engine or a test that needs the GPU (ADR-0015, superseding this item of ADR-0004).
2. New or changed behaviour has tests on the lowest fitting stage; nothing that can be tested in
   stage 1 is tested only in stage 2.
3. No quality gate is weakened: no lower threshold, no removed contract, no new ignore or
   suppression without a reason written next to it.
4. No new duplicated logic; each rule lives in one place.
5. Docstrings, user docs and developer docs are updated for what changed.
6. Every new decision has an ADR, and changed decisions supersede their ADR.
7. Snapshot and schema changes are intended and reviewed (`--snapshot-update` is a deliberate act).
8. A change to a stage's code that changes its results raises the stage's version, so stored
   results made by the old code are not taken as current.

## Licences and history

`make licenses` (a CI job too) reads the licence of every installed runtime dependency from its
package metadata, without network, and fails on GPL, AGPL, a non-commercial licence or one it does
not know, unless the package is a documented exception (the NVIDIA CUDA runtime of the GPU build,
which `THIRD_PARTY.md` must mention). LGPL and MPL are allowed. The allow list and the exceptions
are in `tools/licenses.py`. `make history-scan` scans every commit for other projects' names,
planning notes, local paths of this machine, audio, model and lyrics files outside
`tests/data/demo/`, the local corpus, agent files and secrets, and prints counts and commit ids,
never the matched text. The names of other projects are not in the repository: put them, one regular
expression per line, in `.cache/history-scan-names.txt`.

## Documentation site

`make docs` removes `site/` and builds the site with Zensical in strict mode into it
(configuration in `mkdocs.yml`; API reference from the docstrings). Zensical keeps its own cache
in `.cache/`, next to ours, so never run `zensical build --clean` here: it deletes the whole
folder, including the Python and the packages that `make setup` installed there.

Mermaid diagrams keep the hand-drawn look and carry no colours (ADR-0003); the stylesheet
`docs/assets/mermaid-dark.css` only inverts them in the dark scheme of the site, because Mermaid
fixes the node fills in a closed shadow root. Pages under `docs/` use no `> [!note]` callouts
(Zensical does not render them). `tests/fast/test_docs_rules.py` checks both rules: no callouts
in `docs/`, and every Mermaid diagram starts with the hand-drawn config and carries no colours,
themes, `click` or icons.

The same file keeps the docs about the present and public:

- Pages for users (`docs/user/`, `docs/index.md`, `README.md`) link no ADR and name no ADR id;
  only the README row for developers links the ADR index.
- No page, source file, tool or test credits a person with a decision (a name with a date in
  brackets, "decided by", "'s decision"); with `.cache/history-scan-names.txt` present (see
  `tools/history_scan.py`), none of its names appears either. CI has no such file.
- Pages for users and developers describe the present, not an earlier state: a short list of
  history phrases (`HISTORY` in the test) fails. ADRs are not
  checked, since their context describes the state they change.
- No page of `docs/` or the repository root names a private place: local or Windows paths,
  file links, wiki links, story ids or the trials folder (`PRIVATE` in the test).

Each failure names the file and the line.

## Reports and summary

Each gate runs through `tools/gate.py`, which writes `reports/<gate>.txt` (output) and
`reports/<gate>.status` (exit code); the fast stage also writes `reports/fast.xml` (JUnit) and
`reports/coverage.json`. `make summary` prints only the failed gates with file, line and message.

## Writing tests

Write the test on the lowest fitting stage, first or alongside the code. Property tests use the
Hypothesis `ci` profile (derandomised). Tests of the tools in `tools/` live in
`tests/fast/tools/`. `make profile-pictures` draws the pictures of the built-in looks for the user
docs (CPU, ffmpeg with libass); a fast test fails when they are stale (ADR-0019). Do not lower a
threshold, remove an import contract or add a suppression without a written reason.

## Continuous integration

`.github/workflows/ci.yml` runs one job per make target listed in `CI_TARGETS` in the Makefile
(`static`, `fast`, `dup`, `docs`, `ci-targets`, `diff-cover` on pull requests, `licenses`, and
`tag-check` on tags that start with `v`) on every push and pull request, plus an advisory `ty` job. `make ci-targets` fails if a listed target has no job.
Every job runs on `ubuntu-26.04` (its apt ffmpeg is version 8); `astral-sh/setup-uv` is named by a
full version (it publishes no major tags) and reads the uv version from `pyproject.toml`, so the
workflows name none (a fast test checks both).

`.github/workflows/docs.yml` builds the site with `make docs` and publishes it to GitHub Pages
from `main`. Both of its jobs are skipped while the repository is private
(`github.event.repository.private == false`); once it is public, enable Pages with the source
"GitHub Actions" once and the next push to `main` publishes.
