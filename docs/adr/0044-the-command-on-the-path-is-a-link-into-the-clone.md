---
id: ADR-0044
status: accepted
date: 2026-11-06
superseded_by: null
---
# ADR-0044: The command on the PATH is a link into the clone

## Context and problem

Vocatron is used from a clone (ADR-0002): `make setup` builds the environment in `.venv/` of the
clone and writes nothing outside it. The command is then `.venv/bin/vocatron`, which users must
type with its path or put on their `PATH` by hand. The command already finds the clone, its
models and its caches from the location of the package, not from the current folder, so it works
from any folder once it can be found.

## Considered options

1. Leave it to the user (an alias or a `PATH` entry), documented.
2. `uv tool install --editable .`: a second environment outside the clone, with a second copy of
   PyTorch (about 6 GB), managed by uv outside the project folder.
3. An opt-in `make install` that puts one symbolic link to `.venv/bin/vocatron` into a folder on
   the `PATH`, by default `~/.local/bin`, and `make uninstall` that removes it.

## Decision

Option 3. `make setup` keeps writing nothing outside the clone; `make install`
is the one explicit step that does, and it writes only the link.

- The folder is `BINDIR`, by default `$HOME/.local/bin`; `make install BINDIR=…` chooses another.
- `make install` creates the folder if needed, replaces a symbolic link named
  `vocatron` that is already there, refuses to replace a regular file, and warns when the folder is not on the
  `PATH`.
- `make uninstall` removes the link only if it points into this clone.

## Consequences

- After `make install` the documentation writes plain `vocatron` for every command.
- The link follows the clone: `make setup` again, a new version pulled, all without a new
  install. Moving or deleting the clone breaks the link; `make uninstall` before deleting removes it.
- One clone at a time owns the command; installing from a second clone moves the link there.
