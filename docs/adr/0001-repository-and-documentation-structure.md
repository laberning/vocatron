---
id: ADR-0001
status: accepted
date: 2026-10-28
superseded_by: null
---
# ADR-0001: Repository and documentation structure

## Context and problem

Vocatron needs one clear place for each kind of information: code, user and developer documentation, decisions, and planning. The repository is private until the first tagged release and public afterwards, so anything that should stay private must never enter it. Decisions must be findable and must not be reopened by accident, and the history must show who is responsible for each change.

## Considered options

1. **Everything in the repository**: code, docs, decisions, stories and research notes.
2. **Code, docs and decisions in the repository; planning outside it**: stories, research notes and drafts live in a private planning workspace.
3. **Decisions in a wiki or issue tracker** next to the repository.

## Decision

Option 2.

- **The repository holds** the code, the tests, the user documentation, the developer documentation and the Architecture Decision Records (ADRs). It is self-contained: nothing in it needs the planning workspace to be understood.
- **Planning lives outside the repository** in a private workspace (stories, research, roadmap). Its content is never copied into the repository; where a decision comes out of planning, the decision is written as an ADR here.
- **English** is the only language in the repository: code, comments, docs, commit messages, ADRs.
- **ADRs** live in `docs/adr/` as `NNNN-kebab-title.md` with the index in `docs/adr/README.md`. Format: a simplified MADR with frontmatter `id`, `status` (`proposed`, `accepted`, `superseded`), `date`, `superseded_by`, and the sections Context and problem, Considered options, Decision, Consequences. ADRs are written as `accepted` once the maintainer has agreed them; the maintainer can set one back to `proposed`. An ADR may be edited freely until it is first committed. After that it is changed only by a new ADR that supersedes it fully or in part; the old one gets `superseded_by` and stays in place.
- **Local tooling files** of a contributor (editor and assistant configuration) are kept out of git through the clone's own `.git/info/exclude`, not through `.gitignore`, so the repository carries no trace of any one contributor's setup.
- **Commit identity**: every commit is authored under the identity of the person who takes responsibility for it, signed, with a conventional commit message. Tools are never listed as author or co-author.
- **Releases** are git tags; Vocatron is installed from the repository and is never published to PyPI.

## Consequences

- A reader of the public repository finds every decision and its reasons in `docs/adr/` without access to the planning workspace.
- Planning can stay informal and private without leaking into the history.
- The ADR rules make decisions stable: changing one means writing a new ADR, which makes the change visible.
- Contributors' tooling files must be excluded in each clone; this is documented in the developer docs.
