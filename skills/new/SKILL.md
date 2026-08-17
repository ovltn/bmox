---
name: new
description: Start a new build-your-own-X learning project (e.g. "build my own kafka", "start redis from scratch", "new bmox project"). Researches primary sources on the web, finds an external grader, interviews the learner, generates a staged learning roadmap, and scaffolds a project folder with script-managed state. Use whenever the user wants to begin rebuilding a technology from scratch as a learning exercise, even if they don't say "bmox".
disable-model-invocation: false
---

# /bmox:new <tech> — start a learning project

You are setting up a learning harness, not building software. Read
`${CLAUDE_PLUGIN_ROOT}/references/contract.md` now and hold it for the whole
session. Then read `${CLAUDE_PLUGIN_ROOT}/references/curriculum.md` — it
defines the research procedure and the mandatory three-field stage template.

## Procedure

1. **State first.** If `.bmox/state.json` doesn't exist, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py" init`.
   If a project of this name already exists in state, stop and tell the
   learner to `focus` it instead.

2. **Research** per curriculum.md: primary specs, real repo layout, and —
   critically — an external grader (`codecrafters-io/<tech>-tester` first).
   Collect 4–8 primary links for RESOURCES.md.

3. **Interview** — exactly three questions (language, depth, what they most
   want to understand). Wait for answers before drafting.

4. **Draft the roadmap** obeying curriculum.md's structural rules: every
   stage has observable behavior + learner's design decision + what the real
   system does; one stage deliberately naive; stage 1 trivially end-to-end.
   Show the draft and get explicit approval before scaffolding. The learner
   editing the roadmap now is cheap; after stage 3 it's disruptive.

5. **Scaffold** on approval:
   - Copy `${CLAUDE_PLUGIN_ROOT}/assets/templates/project/` to `./<tech>/`
     and fill every `{{PLACEHOLDER}}`.
   - Write the approved roadmap into `ROADMAP.md` and links into
     `RESOURCES.md`. Wire `make grade` to the external grader if found.
   - Register: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py" new-project
     <tech> --language <lang> --stages <N>`.
   - Leave `DESIGN.md` empty beyond headers — it is the learner's file.

6. **Stop.** Do not start stage 1, do not write any implementation code, do
   not "get them going with a quick example". End by telling them:
   write your stage-1 design note in DESIGN.md, then run `/bmox:stage`.

If the learner asks you to also implement something "to save time", the
contract's refusal-and-offer applies.
