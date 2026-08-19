---
name: check
description: Verify the current build-your-own-X step — run the mode's machine gate, then the reconcile gate that holds the learner's prediction against what reality did. Use when the user says "check my step", "I think it works", "run the tests", "/bmox:check", "I finished reading", "the failure happened", or believes a step is done.
---

# /bmox:check — the machine gate, then the reconcile gate

Two gates, in order. The machine gate establishes that reality answered; it
says nothing about whether the learner understood the answer, and that
asymmetry is the whole reason for the second gate.

Every `state.py` below means
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py"`.

Read `${CLAUDE_PLUGIN_ROOT}/references/contract.md` and `modes.md`. Then
`state.py status --json` for the current step's mode, phase, and concepts —
every branch below is on the mode.

## Procedure

1. **Machine gate.** What counts as reality answering is modes.md's `observed`
   row, one column per mode:

   - **build** — `make test`, then `make grade`. A `grade` that fails saying
     `no external grader is wired` is not a red gate: this project has none, so
     `make test` alone decides. Any other non-zero exit is red. Make collapses
     every recipe failure onto one exit status, so that phrase is the only thing
     separating the two — read it, do not infer from the code. Red:
     report which assertions failed and what each failure means at the *spec*
     level. Do not walk their code line by line unless they ask, and never
     repair it — contract.md's never-write list covers "fixed" versions. If the
     step is already `observed`, green went red on a refactor: `state.py
     regress`, then stop.
   - **probe** — open the trace file. Every hop needs actual-versus-predicted
     filled in. Say which hops are missing and stop.
   - **operate** — open the runbook and read the hypothesis before you read any
     observation. A hypothesis naming no observable makes this gate vacuous,
     since there is nothing for an observation to be recorded against, and it is
     the hypothesis modes.md's *operate* section rules out: do not
     `mark-observed`, cite that rule, and send them back to the commitment
     template. Once it does name observables, every one of them needs an
     observation recorded against it. Say which are missing and stop.

   On a pass: `state.py mark-observed --evidence "<one line>"` — what answered,
   concretely: "14 tests green including the truncated-frame case", "6 hops
   annotated against source". If `mark-observed` refuses because the phase is
   still `ready`, no prediction was ever recorded; send them to
   `record-commitment` and do not work around it.

2. **Reconcile gate.** Ask the mode's *Reconcile question* from modes.md — in
   your own words, not read aloud from the file, but every clause of it has to
   survive the rewording. A question asked with a clause dropped is a different
   and easier question. Evaluate the answer against the learner's own artifact
   rather than against what you know.

   - **probe** — steer onto the misses, for the reason modes.md gives. A trace
     with no wrong predictions is a fact about the question you set, not about
     the learner: say so, and set a harder one next time.
   - **operate** — the answer belongs in the runbook file, not only in the
     conversation. The artifact is what someone rereads at 3am; a good answer
     that stayed in the chat is not a runbook entry.

   Grade clause by clause. The question decomposes, and an answer that covers
   one clause convincingly has not touched the others; a clause left unanswered
   is a gap, however well the rest went.

   **Holds up** → transcribe a cleaned-up version into `<project>/NOTES.md` —
   their words tightened, not your summary — then `state.py record-reconciled`.
   **Has a real gap** → name the gap precisely, point at the part of their own
   artifact that answers it, let them retry, and **stop there** — nothing below
   runs until the explanation lands. A retry that reaches step 3 first would
   write a second round of evidence for the same concept. Retries are
   unlimited and the step stays `observed`. This is not a quiz to be passed by
   wordplay; it is the moment the learning consolidates.

3. **Write the profile, before you close the step.** `record-evidence`
   attributes to the step that is currently open, and step 4 clears that, so
   this ordering is load-bearing. Take the concept list from `status --json`.

   - Per concept the step names:
     `state.py record-evidence --concept C --outcome {reconciled,partial,none}
     --note "<what they demonstrated>"`. Grade what they said at the reconcile
     gate, not whether the tests went green — a bypassed gate and three tier-3
     hints still produce green tests.
   - Per wrong prediction: `state.py record-gap --concept C --note "<predicted
     X, reality was Y>"`. Record it even when the reconcile gate passed: a
     misconception talked through once is not the same as one rebuilt against,
     and the gap is what lets the next roadmap tell the difference.
   - If this step closed a gap the profile already carried:
     `state.py resolve-gap --concept C --gap <id>`, with the id from
     `state.py profile show`. Resolved gaps are kept, not deleted.

4. **Close the step.** `state.py complete-step`.

   If the learner wants to skip the reconcile gate, do not argue twice. State
   once that the bypass is recorded permanently and shows in every later
   status, then `state.py complete-step --force`. Step 3 still runs first: a
   bypassed step is exactly the one whose gaps the next roadmap needs.

5. **Close out.** Name one refactor worth doing and one deliberately not worth
   doing, with the reason each way, for their NOTES.md. Suggest; never perform.
   Then point at `/bmox:step`.
