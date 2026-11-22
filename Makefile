# Vocatron: one entry point for setup and every check (ADR-0004, ADR-0007).
# Everything stays inside the project folder: tools in .tools/, caches in .cache/, venv in .venv/.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# The one uv pin lives in pyproject.toml ([tool.uv] required-version = "==X.Y.Z").
UV_VERSION := $(shell sed -nE 's/^required-version[[:space:]]*=[[:space:]]*"==([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' pyproject.toml)
UV ?= $(CURDIR)/.tools/bin/uv
GATE := $(UV) run --no-sync python tools/gate.py
RUN := $(UV) run --no-sync

export UV_CACHE_DIR := $(CURDIR)/.cache/uv
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.cache/python
export XDG_CACHE_HOME := $(CURDIR)/.cache/xdg
export TMPDIR := $(CURDIR)/.cache/tmp
export UV_LINK_MODE := copy
export UV_PYTHON_PREFERENCE := only-managed

# PyTorch comes from the CUDA index on Linux with an NVIDIA GPU, else from the CPU index
# (ADR-0002). Override with: make env TORCH_EXTRA=cpu
TORCH_EXTRA ?= $(shell if [ "$$(uname -s)" = Linux ] && nvidia-smi -L >/dev/null 2>&1; then echo cuda; else echo cpu; fi)

# Make targets that CI must run as a job of the same name (tools/check_ci_targets.py).
CI_TARGETS := static fast dup docs ci-targets diff-cover licenses tag-check

# Where 'make install' puts the vocatron command (a link into this clone, ADR-0044).
# Override with: make install BINDIR=/some/folder/on/the/PATH
BINDIR ?= $(HOME)/.local/bin

DIFF_BASE ?= origin/main
# At most this many fast-test workers: on the 20-thread development laptop (WSL) the fast stage
# takes about 21 s with 4 to 14 workers but 30 s with 20, as the processes compete for the
# same cores; 6 leaves room for other work.
# Override with: make check TEST_WORKERS=12
TEST_WORKERS ?= 6
# Stage 2 without the GPU tests runs on this many workers, one test file per worker (the tests of a
# file share module fixtures; the files share no state). 'make slow' stays one at a time (GPU).
# Override with: make slow-cpu SLOW_WORKERS=2
SLOW_WORKERS ?= 4
PYTEST_BASE := -n auto --maxprocesses=$(TEST_WORKERS) --cov --cov-report=json:reports/coverage.json --cov-report=xml:reports/coverage.xml --cov-report=term

CDGRAPHICS_VERSION := 7.0.0
# The registry's integrity value of the tarball (sha512, base64); the download is checked against it.
CDGRAPHICS_INTEGRITY := sha512-bjEV5gX496slsgr8a4O3mhxpDOklgzyhharAA5dV6Adw8obkkA0Xg+MofCE55I4AUIbo0ndNMUVTdRikA3vcpA==

.PHONY: help setup install uninstall env check check-all static fast slow slow-cpu bench bench-accept demo-songs demo-accept summary format dup mutation docs schemas profile-pictures picture-song readme-gif logo word-voice \
        ty ci-targets diff-cover licenses history-scan tag-check cdg-js clean

help: ## List the targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: env ## Create the environment inside the project folder (with PyTorch) and check ffmpeg with libass
	$(UV) run --no-sync python tools/check_system.py
	@echo "Next: run 'make install' to use the vocatron command from any folder."

install: ## Link the vocatron command into BINDIR (default ~/.local/bin) to use it from any folder
	@test -x .venv/bin/vocatron || { echo ".venv/bin/vocatron is missing: run 'make setup' first."; exit 1; }
	@$(RUN) python tools/install_command.py install --bindir "$(BINDIR)"

uninstall: ## Remove the link made by 'make install' from BINDIR, if it points into this clone
	@test -x .venv/bin/vocatron || { echo ".venv is missing: run 'make setup' first."; exit 1; }
	@$(RUN) python tools/install_command.py uninstall --bindir "$(BINDIR)"

env: ## Install the pinned uv if needed and sync the locked environment (PyTorch: cuda or cpu)
	@mkdir -p $(UV_CACHE_DIR) $(UV_PYTHON_INSTALL_DIR) $(XDG_CACHE_HOME) $(TMPDIR)
	@test -n "$(UV_VERSION)" || { echo "pyproject.toml: [tool.uv] required-version = \"==X.Y.Z\" is missing"; exit 1; }
	@if [ "$(UV)" = "$(CURDIR)/.tools/bin/uv" ] && ! "$(UV)" --version 2>/dev/null | grep -qE "^uv $(subst .,\.,$(UV_VERSION))( |$$)"; then \
	  set -e; \
	  case "$$(uname -s)-$$(uname -m)" in \
	    Linux-x86_64) triple=x86_64-unknown-linux-gnu;; \
	    Linux-aarch64) triple=aarch64-unknown-linux-gnu;; \
	    Darwin-arm64) triple=aarch64-apple-darwin;; \
	    Darwin-x86_64) triple=x86_64-apple-darwin;; \
	    *) echo "Unsupported platform; install uv $(UV_VERSION) and run: make env UV=uv"; exit 1;; \
	  esac; \
	  echo "Installing uv $(UV_VERSION) into .tools/bin"; \
	  mkdir -p .tools/bin $(TMPDIR)/uv-dl; \
	  curl -fsSL -o $(TMPDIR)/uv-dl/uv.tar.gz \
	    https://github.com/astral-sh/uv/releases/download/$(UV_VERSION)/uv-$$triple.tar.gz; \
	  tar -xzf $(TMPDIR)/uv-dl/uv.tar.gz -C $(TMPDIR)/uv-dl; \
	  cp $(TMPDIR)/uv-dl/uv-$$triple/uv .tools/bin/uv; \
	  rm -rf $(TMPDIR)/uv-dl; \
	fi
	$(UV) sync --locked --extra $(TORCH_EXTRA)

check: ## Stages 0 and 1 plus duplication: static checks, fast tests, jscpd (every gate, then fails if any failed)
	@rm -rf reports; mkdir -p reports; rc=0; \
	$(MAKE) --no-print-directory static || rc=1; \
	$(MAKE) --no-print-directory fast || rc=1; \
	$(MAKE) --no-print-directory dup || rc=1; \
	$(MAKE) --no-print-directory diff-cover || rc=1; \
	$(MAKE) --no-print-directory ci-targets || rc=1; \
	if [ $$rc -ne 0 ]; then echo; echo "make check FAILED; run 'make summary'"; fi; exit $$rc

check-all: ## Stages 0 to 2: check plus the slow tests (real engines, GPU, corpus)
	@rc=0; $(MAKE) --no-print-directory check || rc=1; \
	$(MAKE) --no-print-directory slow || rc=1; exit $$rc

static: ## Stage 0: format, lint, types, layers, dependencies, dead code, lock file
	@mkdir -p reports; rc=0; \
	$(GATE) ruff-format -- $(RUN) ruff format --check || rc=1; \
	$(GATE) ruff-check -- $(RUN) ruff check --output-format concise || rc=1; \
	$(GATE) pyrefly -- $(RUN) pyrefly check --output-format min-text || rc=1; \
	$(GATE) layers -- $(RUN) lint-imports || rc=1; \
	$(GATE) deptry -- $(RUN) deptry . || rc=1; \
	$(GATE) vulture -- $(RUN) vulture || rc=1; \
	$(GATE) lock -- $(UV) lock --check || rc=1; \
	exit $$rc

fast: ## Stage 1: fast tests (no GPU, no network) with per-layer coverage minimums
	@mkdir -p reports; rc=0; \
	$(GATE) fast -- $(RUN) pytest tests/fast $(PYTEST_BASE) --junitxml=reports/fast.xml || rc=1; \
	$(GATE) coverage -- $(RUN) python tools/coverage_layers.py reports/coverage.json || rc=1; \
	exit $$rc

slow: ## Stage 2: slow tests with real engines (the GPU ones skipped without a GPU)
	@mkdir -p reports; $(GATE) slow -- $(RUN) pytest tests/slow -n 0 -rs --junitxml=reports/slow.xml --timeout=1800

slow-cpu: ## Stage 2 without the GPU tests: real tools and the local corpus, in parallel (ADR-0015)
	@mkdir -p reports; $(GATE) slow-cpu -- $(RUN) pytest tests/slow -m "not gpu" -n $(SLOW_WORKERS) --dist loadfile -rs --junitxml=reports/slow-cpu.xml --timeout=1800

# A language is chosen on the command line (make bench LANGUAGE=en); the LANGUAGE of the
# environment (a locale setting) is not meant.
CHOSEN_LANGUAGE := $(if $(filter command line,$(origin LANGUAGE)),$(LANGUAGE))

bench: ## Stage 3: sync benchmark per language on the local corpus (GPU; about 15 minutes the first time; LANGUAGE=en for one)
	@mkdir -p reports; VOCATRON_BENCH_LANGUAGE=$(CHOSEN_LANGUAGE) $(GATE) bench -- $(RUN) pytest tests/bench -n 0 -rs -s --force-enable-socket --junitxml=reports/bench.xml --timeout=3600

CORPUS ?= .corpus

bench-accept: ## Accept the last benchmark run as the baseline that 'make bench' compares with (LANGUAGE=en for English)
	@$(RUN) python tools/bench_accept.py $(or $(CHOSEN_LANGUAGE),de) --corpus $(CORPUS)

demo-songs: ## Download the freely licensed demo songs into .corpus/demo/ (network; checks SHA-256)
	$(RUN) python tools/demo_songs.py

demo-accept: ## Make a demo song on the GPU and write the references of its end-to-end test (default English; LANGUAGE=de)
	@mkdir -p reports; VOCATRON_DEMO_ACCEPT=1 VOCATRON_DEMO_LANGUAGE=$(or $(CHOSEN_LANGUAGE),en) $(RUN) pytest tests/slow/test_demo_real.py -n 0 -rs --junitxml=reports/demo-accept.xml --timeout=1800

diff-cover: ## Stage 1: lines changed against origin/main must be 90 % covered (skipped before the first push)
	@mkdir -p reports; $(GATE) diff-cover -- $(RUN) python tools/diff_cover_gate.py --base $(DIFF_BASE)

ci-targets: ## Check that CI has a job for every target in CI_TARGETS
	@mkdir -p reports; $(GATE) ci-targets -- $(RUN) python tools/check_ci_targets.py

licenses: ## List the licence of every runtime dependency; fail on a copyleft or unknown one (no network)
	@mkdir -p reports; $(GATE) licenses -- $(RUN) python tools/licenses.py

history-scan: ## Scan every commit for other projects, vault content, local paths, media, lyrics, secrets (ids only)
	@mkdir -p reports; $(RUN) python tools/history_scan.py

tag-check: ## Fail if TAG (for example v0.1.0) differs from the version in pyproject.toml or the changelog
	@test -n "$(TAG)" || { echo "usage: make tag-check TAG=v0.1.0"; exit 2; }
	$(RUN) python tools/check_version.py "$(TAG)"

ty: ## Advisory type check with ty (allowed to fail while ty is 0.0.x)
	@mkdir -p reports; $(GATE) ty -- $(RUN) ty check

summary: ## Print only the failures of the last run (file, line, message)
	@$(UV) run --no-sync python tools/summary.py reports

format: ## Fix what can be fixed (Ruff format and safe lint fixes)
	$(RUN) ruff format
	$(RUN) ruff check --fix

dup: ## Find duplicated code with jscpd (threshold in .jscpd.json)
	@mkdir -p reports; $(GATE) dup -- $(RUN) jscpd --no-colors

# mutmut run spreads to all of core and lab even with one mutant name (hours); tools/mutate.py runs the
# mutants of the named functions only and prints their number first. ALL=1 is the old mutmut run.
mutation: ## Mutation testing of core and lab: FUNCS="vocatron.core.x.function ..." (ALL=1: all of them, hours)
	@if ! find src/vocatron/core src/vocatron/lab -name '*.py' ! -name '__init__.py' | grep -q .; then \
	  echo "src/vocatron/core and src/vocatron/lab have no code yet; nothing to mutate."; \
	elif [ -n "$(FUNCS)" ]; then $(RUN) python tools/mutate.py $(FUNCS); \
	elif [ "$(ALL)" = 1 ]; then $(RUN) mutmut run; \
	else $(RUN) python tools/mutate.py; exit 2; fi

# Not 'zensical build --clean': that deletes all of .cache/, where uv keeps Python and packages.
docs: ## Build the documentation site in strict mode into a fresh site/
	@mkdir -p reports; rm -rf site; $(GATE) docs -- $(RUN) zensical build --strict

profile-pictures: ## Draw the pictures of the built-in looks for the user docs (CPU; ffmpeg with libass)
	$(RUN) python tools/profile_pictures.py

picture-song: ## Write the timing file of the picture song from the English demo run (after make demo-accept LANGUAGE=en)
	$(RUN) python tools/picture_song.py

word-voice: ## Where the voice sounds under every word of a song, numbers only: make word-voice SONG=<work folder> [ROWS=flagged|all|none] (ALL=1: SONG holds work folders)
	@test -n "$(SONG)" || { echo "usage: make word-voice SONG=<work folder> [ROWS=flagged|all|none] [ALL=1]"; exit 1; }
	$(RUN) python tools/word_voice.py "$(SONG)" --rows $(or $(ROWS),flagged) $(if $(ALL),--all)

readme-gif: ## Draw the animation of the default look for the README and the start page (CPU; ffmpeg with libass)
	$(RUN) python tools/readme_gif.py

logo: ## Write the wordmark and the V symbol as SVG files into docs/assets/logo/ (no GPU, no network)
	$(RUN) python tools/logo_files.py

schemas: ## Export the JSON schemas of the stage files to schemas/ (after a schema_version bump)
	$(RUN) python tools/export_schemas.py

# An optional test tool (ADR-0025): the JavaScript CD+G player cdgraphics, run unchanged by Node in
# tests/slow/test_cdg_js.py. No npm install: one tarball, checked against the pinned integrity.
cdg-js: ## Fetch cdgraphics into .tools/ for the optional third-decoder test (network; checks sha512)
	@set -e; dir=.tools/cdgraphics-$(CDGRAPHICS_VERSION); \
	if [ -f $$dir/dist/cdgraphics.js ]; then echo "$$dir is there"; exit 0; fi; \
	mkdir -p $(TMPDIR)/cdg-js; \
	curl -fsSL -o $(TMPDIR)/cdg-js/cdgraphics.tgz https://registry.npmjs.org/cdgraphics/-/cdgraphics-$(CDGRAPHICS_VERSION).tgz; \
	got="sha512-$$(openssl dgst -sha512 -binary $(TMPDIR)/cdg-js/cdgraphics.tgz | base64 -w0)"; \
	if [ "$$got" != "$(CDGRAPHICS_INTEGRITY)" ]; then echo "cdgraphics: checksum differs: $$got"; rm -rf $(TMPDIR)/cdg-js; exit 1; fi; \
	mkdir -p $$dir; tar -xzf $(TMPDIR)/cdg-js/cdgraphics.tgz -C $$dir --strip-components=1; \
	rm -rf $(TMPDIR)/cdg-js; echo "cdgraphics $(CDGRAPHICS_VERSION) is in $$dir"

clean: ## Remove reports, built site and test caches (keeps .venv, .tools, .cache)
	rm -rf reports site mutants .pytest_cache .ruff_cache .hypothesis .coverage
