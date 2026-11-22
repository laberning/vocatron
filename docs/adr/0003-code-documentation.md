---
id: ADR-0003
status: accepted
date: 2026-10-28
superseded_by: null
---
# ADR-0003: Code documentation

## Context and problem

Vocatron is meant to be maintained for a long time and changed safely by contributors who did not write the code. Documentation must be close to the code, checked by tools rather than by convention, and must not be written twice (once in docstrings, once in CLI help, once on a website). Diagrams must render on GitHub and on the docs site, in light and dark mode.

## Considered options

1. **Docstring style:** Google, NumPy or reStructuredText (Sphinx).
2. **Docs site:** Sphinx; MkDocs with Material; Zensical with mkdocstrings; no site (Markdown in the repository only).
3. **Diagrams:** Mermaid in Markdown; images exported from a drawing tool; PlantUML.

## Decision

- **Docstrings:** Google style for every public module, class, function and method, enforced by Ruff's pydocstyle rules (`lint.pydocstyle.convention = "google"`). Code examples in docstrings are formatted by Ruff (`format.docstring-code-format = true`). Docstrings say what and why; the types live in the signature.
- **Type hints** on every function, checked strictly (ADR-0007). No types repeated in docstrings.
- **CLI help comes from the docstrings** of the command functions (Cyclopts, ADR-0002): one source for code docs and user help.
- **Docs site:** Zensical (pinned, currently 0.0.73, MIT) with mkdocstrings-python 2.0 for the API reference, built by `make docs`. Zensical is young but actively developed by the team behind Material for MkDocs, which is in maintenance mode with end of life on 2027-05-05. The site configuration stays minimal so a change in Zensical's API-docs support costs little.
- **Two audiences:**
  - *User docs* (`docs/user/`): installation, first track, commands, configuration, lyrics files, style profiles, troubleshooting. Written for a karaoke fan with a terminal.
  - *Developer docs* (`docs/dev/`): architecture (ADR-0007), pipeline and stage files (ADR-0006), how to add a language, a style profile or an output format, the test harness (ADR-0004), the API reference generated from docstrings.
  - ADRs (`docs/adr/`) are part of the site.
- **Diagrams are Mermaid** in Markdown, wherever a picture explains better than text; no images of diagrams. Rules:
  - Start every diagram with the hand-drawn look:
    ````markdown
    ```mermaid
    ---
    config:
      look: handDrawn
    ---
    flowchart LR
        A --> B
    ```
    ````
  - No own colours and no fixed theme: no `style`, `classDef`, `fill`, `color`, `themeVariables` or `theme`. GitHub and the docs site pick the theme from light or dark mode. Emphasis by shape, dashed or thick links, or a word in the label.
  - Only what GitHub's renderer supports: no `click` callbacks or scripts, no icon packs or `fa:` icons, no ZenUML.
  - The docs site may carry one site-only stylesheet that corrects renderer defaults, for example the node fill of the hand-drawn look in dark mode; the diagrams themselves never carry colours.
  - Narrow enough for a page: about four boxes side by side and five rows at most. Empty subgraph titles (`subgraph R1 [" "]`) for rows that only arrange boxes.
- **Callouts** only as `> [!note]`, `> [!tip]`, `> [!important]`, `> [!warning]`, `> [!caution]`, and only in files read on GitHub (README, `THIRD_PARTY.md`, files outside `docs/`). Pages of the docs site use none until Zensical renders them; the only maintained-enough extension for it is stale.
- **Changes to behaviour update the docs in the same change** (part of the Definition of Done, ADR-0004).

## Consequences

- Ruff fails the build on a missing or malformed docstring; the help text of the CLI can never drift from the code.
- The docs site has to be checked once for its Mermaid version, the hand-drawn look and dark mode when it is set up.
- If Zensical stalls, the same Markdown and `mkdocs.yml` can be built by MkDocs with little change.
