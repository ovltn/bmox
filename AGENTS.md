# Conventions for working on bmox

This repo **is** a Claude Code plugin — mostly prose, so prose discipline is
engineering discipline. Rules for what you may write inside a *learner's*
project live in `references/{contract,curriculum}.md`. This file covers how you
change *this* repo.

## Files describe the present

A reader must not be able to tell whether a line was written today or a year
ago. So: no `# changed from ...`, no `# new in 0.2`, no "as of version X" or
"this used to ...", no deprecated section kept beside its replacement, no
commented-out code, no TODOs. Delete the old thing — git remembers it and
`CHANGELOG.md` says it went away.

Comments explain **why**: an invariant, a constraint, a rejected alternative.
Never what the code does, never when it changed.

## One home per fact

| Information | Home |
|---|---|
| How something works now | the file itself |
| Why a design is the way it is | `README.md` design notes, or a *why* comment |
| What each release changed | `CHANGELOG.md` |
| Why one change was made | the commit body |
| Rules for the learner's project | `references/{contract,curriculum}.md` |

Anything asserted in two places is a bug: one file owns it, the other links.

## CHANGELOG.md

Written at release time only. Bumping `version` means adding the matching
section; ordinary commits get no entry — their reasoning lives in the commit
body.

```markdown
## [0.2.0] — 2026-09-01     <- one section per release, newest first

### Added                   <- this category order, empty ones omitted
- `/bmox:review` extracts patterns once a stage goes green.

### Changed
- `/bmox:hint` records a tier-3 hint before delivering it, not after.

### Internal
- pytest coverage for every illegal state transition.
```

- Order: `Added` · `Changed` · `Fixed` · `Removed` · `Internal`.
- `Internal` is what no plugin user can observe: tests, refactors, contributor
  docs. Everything else is user-facing.
- Summarize from `git log` since the previous release, grouped by category
  rather than by commit — five commits reworking one skill are one line.
- One sentence per change, naming a surface the user touches — not "improved
  hint handling", not "various fixes".
- No issue numbers, no author names.

## Releasing

`version` lives **only** in `.claude-plugin/plugin.json`; users get a change
only when it is bumped.

1. `claude plugin validate . --strict`
2. Bump `version` in `.claude-plugin/plugin.json`
3. Add `## [X.Y.Z] — YYYY-MM-DD` at the top of `CHANGELOG.md`, summarizing
   everything since the previous release
4. Commit and push

- **major** — the `.bmox/state.json` schema breaks, or a command is removed or
  renamed. Also bump `schema_version` and provide a migration.
- **minor** — a new skill, command, or `state.py` subcommand.
- **patch** — prompt wording, documentation, bug fixes.
