---
name: status
description: Show progress across all build-your-own-X learning projects — stages done, current phase, hint counts, explain-aloud record. Use when the user asks "where am I", "how's my kafka project going", "bmox status", "/bmox:status", or wants a summary of their learning repo.
---

# /bmox:status — where things stand

Read-only. Run:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py" status

Present it conversationally, not as a dump: current project and stage, what
phase it's in and what that phase means for their next action, hint totals
framed as data ("stage 4 took three tier-2 hints — worth a revisit in NOTES
someday"), and any `GATE BYPASSED` flags mentioned plainly, without scolding.

If they ask about history ("when did I finish stage 2"), the audit log is in
`status --json` under `audit`.

Never modify state from this skill. If the state file is missing, suggest
`/bmox:new` rather than running `init` yourself — an empty state file with no
project is a confusing artifact.
