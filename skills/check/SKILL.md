---
name: check
description: Verify the current build-your-own-X stage — run the tests/grader and, if green, administer the explain-aloud gate before unlocking the next stage. Use when the user says "check my stage", "I think it works", "run the tests", "/bmox:check", or believes their bmox implementation is done.
---

# /bmox:check — verify and gate

Read `${CLAUDE_PLUGIN_ROOT}/references/contract.md`. This skill runs the two
gates in order: the machine gate (tests) and the human gate (explain aloud).
Green tests alone are not evidence of understanding — that asymmetry is the
reason this skill exists.

## Procedure

1. **Run the machine gate**: `make test` (and `make grade` if wired). 
   - **Red**: report which assertions failed and what the failure *means* at
     the spec level. Do NOT diagnose the learner's code line-by-line unless
     they ask, and never fix it. If state shows the stage was previously
     `green` (a refactor broke it), run
     `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py" regress`.
     Stop here.
   - **Green**: run `... state.py mark-green`, then continue.

2. **Run the human gate.** Ask, in your own words for this stage:
   > Before this stage closes: from memory, explain (a) how your
   > implementation works, (b) the design decision you made and one
   > alternative you rejected — and why.
   Evaluate the answer honestly against their code and DESIGN.md:
   - **Holds up** → transcribe a cleaned version into `<project>/NOTES.md`,
     run `... state.py record-explained`, then `... state.py complete-stage`.
     If the stage exposed a recurring pattern (WAL, reactor, state machine,
     sparse index...), run `... state.py add-pattern <name>` and add a line
     to the repo-level `docs/patterns.md` if it exists.
   - **Has a real gap** → name the gap precisely, point at the part of their
     own code that answers it, and let them retry. No limit on retries; the
     stage stays `green` until the explanation lands. This is not a quiz to
     pass by wordplay — it's the moment the learning consolidates.

3. **If they want to skip the human gate**, don't argue twice. State once
   that the bypass is recorded permanently, then run
   `... state.py complete-stage --force`.

4. **Close out**: suggest (don't perform) one worthwhile refactor and one
   refactor deliberately not worth doing, for their NOTES.md. Then tell them
   the next stage unlocks via `/bmox:stage`.
