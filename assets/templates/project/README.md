# {{TECH}} — build my own

Part of [build-my-own-x](../README.md). Status: step {{N}}/{{TOTAL}}.

**Capability I'm after:** {{GOAL}}

- `ROADMAP.md` — the plan: what each step unlocks and how I'll learn it
- `DESIGN.md` — my design decisions for build steps, written *before* the code
- `STEPS/` — one brief per build step: goal, decision, definition of done
- `TRACES/` — my predicted vs. actual walks through the real source
- `RUNBOOK/` — what I broke, what I predicted, what actually happened, how it
  gets detected, and what to do at 3am
- `NOTES.md` — what surprised me; diffs vs. the real {{TECH}}
- `RESOURCES.md` — primary sources and operational practice

Run `make test` for the tests of the furthest step opened so far — or
`make test STEP=2` for any other step. `make grade` runs the external grader,
and fails saying so when no grader is wired for {{TECH}}.
