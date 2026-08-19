---
name: hint
description: Give a tiered hint for the current build-your-own-X step without revealing the implementation, the source coordinates, or the answer. Use whenever the learner is stuck on their bmox project — "I'm stuck", "give me a hint", "how do I even start this", "/bmox:hint" — INSTEAD of explaining the solution directly.
---

# /bmox:hint — the smallest hint that unblocks

Read `${CLAUDE_PLUGIN_ROOT}/references/contract.md`. Its *Hint tiers* table
defines all three tiers per mode, and the delivery rules under it bind here.
Over-helping in this skill quietly defeats the entire repo, and it is the
easiest place in the plugin to do it by accident, because someone is asking.

Every `state.py` below means
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py"`.

## Procedure

1. **Check the phase before anything else.** `state.py status --json`. If the
   current step is in phase `ready`, the prediction is not on record yet, and
   there is no hint to give: a hint delivered now is the answer arriving before
   the guess, which is the one thing the step exists to prevent. Say that, name
   what the template is asking for, and stop. **That refusal is the hint.**

   Being stuck on *how to phrase* a prediction is a different problem, and it
   is answered with questions — what do you expect to happen, and what would
   surprise you — never by supplying a blank's content.

2. **Read the ladder if this mode has one.** A build step's brief at
   `<project>/STEPS/NN-<slug>.md` carries a pre-authored three-tier ladder;
   deliver from it rather than improvising. Probe and operate steps have no
   ladder file — take their tiers from the mode's column in contract.md's
   table.

3. **Diagnose before hinting.** Ask one question — "what have you tried, and
   where exactly does it break?" Articulating that often unblocks with no hint
   at all; record nothing in that case. If the blocker is tooling trivia
   unrelated to the learning goal — a compiler flag, an import path — answer it
   outright. The contract protects design decisions, not toil.

4. **Deliver tier 1 and stop there.** Escalate to tier 2 only on a follow-up
   ask, and to tier 3 only once tier 2 has demonstrably failed to land — not
   because they asked for "just the pseudocode" up front.

5. **Record every tier you delivered**: `state.py record-hint --tier <n>`. Say
   that you recorded it. An honest tier-2 count is worth more to the next
   roadmap than a clean one that was bluffed, because the profile carries hint
   counts into the evidence for every concept this step touches.

6. **Hand the problem back.** End on one concrete next action, phrased as the
   learner's move rather than yours.
