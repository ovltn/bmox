---
name: status
description: Show where a build-your-own-X learner stands — steps done, the current step's mode and phase, hint counts, and the knowledge profile underneath them. Use when the user asks "where am I", "how's my kafka project going", "bmox status", "/bmox:status", or wants a summary of their learning repo.
---

# /bmox:status — where things stand

Read-only. Every `state.py` below means
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py"`.

    state.py status
    state.py profile show

## Present it conversationally, not as a dump

**The project.** Current project and step, the step's mode, the phase it sits
in, and — the part the learner actually wants — what that phase means for their
next action. The phase table in `${CLAUDE_PLUGIN_ROOT}/references/modes.md`
says what each phase means in each mode; translate it into the one thing to do
next.

**Hint totals as data.** "Step 4 took three tier-2 hints — worth a revisit in
NOTES someday", not a verdict.

**Flags plainly.** `GATE BYPASSED` and `SKIPPED` are entries in a record, not
misconduct. Say them, say what they were, move on. A record that costs
something to read is a record that gets avoided.

## Then the profile — the part that outlives the project

- **Concepts by evidence count**, heaviest first, each with the sequence of
  outcomes it has been graded. Read the indented lines with it and say what they
  say: hints taken, a bypassed reconcile gate, a concept answered in calibration
  and never demonstrated since. The outcome alone is what the learner *reached*;
  those lines are what it cost, and a reconciled concept that cost a tier-3 hint
  is not the same claim as one that cost nothing.
- **Open gaps**, each with the concept it sits on. `/bmox:plan` aims the next
  roadmap at these, so reading them out here is the learner's chance to argue
  with one before it steers weeks of work.
- **Concepts seen in more than one technology.** `profile show` names them under
  the concept: a concept carrying two distinct projects has been met twice in
  different clothes. That is the transfer story, and it is the only thing in the
  file that shows the learning generalized rather than accumulated. Say so when
  it happens — it is the return on the whole exercise.

  It undercounts, and say that too when it is relevant: a concept the last plan
  correctly declined to re-calibrate carries evidence from one project only, so
  the clearest transfers — the ones that deleted a step from the second roadmap —
  are exactly the ones this line cannot see.

## Bounds

`status --json` returns `{"state": ..., "profile": ...}`; the audit log — for
"when did I finish step 2" — is `state.audit`.

Never modify state from this skill, and never `record-` anything to make the
picture tidier. If `.bmox/state.json` is missing, point at `/bmox:plan` rather
than running `init` yourself: an initialized state file with no project in it
is a confusing artifact that looks like a lost project.
