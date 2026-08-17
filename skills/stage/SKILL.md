---
name: stage
description: Kick off the next stage of the current build-your-own-X learning project. Writes the stage brief (goal, design decision, definition of done, collapsed hint ladder) and the failing tests, then hands over to the learner. Use when the user says "next stage", "start stage N", "/bmox:stage", or is ready to continue their bmox project.
---

# /bmox:stage — open the next stage

Read `${CLAUDE_PLUGIN_ROOT}/references/contract.md` first. In this skill you
write TESTS and DOCS only. Tests are the spec made executable; that is your
legitimate contribution. The implementation is not.

## Procedure

1. **Read state**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py" status --json`.
   Determine the current project and the next stage N (first stage whose
   entry is absent or `planned`). If a stage is mid-flight, summarize where
   it stands and stop — one stage at a time is the point.

2. **Check the design note.** Open `<project>/DESIGN.md`. If the learner has
   not written an entry for stage N, ask them to write 150–300 words first
   (data structure, IO model, crash behavior, what they're skipping) and
   stop. The note is the input to everything below. Do not write it for them.

3. **Write the brief** at `<project>/STAGES/<NN>-<slug>.md`:
   - **Goal** — the observable behavior, from ROADMAP.md, made concrete.
   - **Decision you must make** — restated against *their* design note:
     if their note already answers it, say so; if it dodges it, name the dodge.
   - **Definition of done** — checklist: tests pass, DESIGN.md updated with
     the decision + one rejected alternative, (if applicable) bench evidence.
   - **Hint ladder** — three tiers, each in a collapsed `<details>` block,
     authored NOW while nobody is frustrated. Tier definitions are in the
     contract. Tier 3 pseudocode must not be in the project's language.

4. **Write the failing tests** for exactly this stage's observable behavior,
   in the project's test layout, named so `make test` picks them up. Include
   at least one malformed/hostile input case — protocol code that only sees
   friendly bytes teaches the wrong lessons. Run them and show they fail for
   the right reason (missing implementation, not broken harness).

5. **Transition**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py"
   start-stage N --title "<slug>"`. If the script refuses (previous stage not
   done), it is right — explain the lifecycle, don't work around it.

6. **Hand over.** Point at the brief and the failing tests, remind them
   `/bmox:hint` exists, and stop. No starter code, no "here's roughly how
   the function will look".
