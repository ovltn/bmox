---
name: hint
description: Give a tiered hint for the current build-your-own-X stage without revealing the implementation. Use whenever the learner is stuck on their bmox project — "I'm stuck", "give me a hint", "how do I even start this stage", "/bmox:hint" — INSTEAD of explaining the solution directly.
---

# /bmox:hint — smallest unblocking hint

Read `${CLAUDE_PLUGIN_ROOT}/references/contract.md`; the tier definitions
there are binding. Your job is the *smallest* hint that plausibly unblocks —
over-helping here quietly defeats the entire repo.

## Procedure

1. Read the current stage's brief in `<project>/STAGES/` — it contains a
   pre-authored hint ladder written when nobody was frustrated. Prefer
   delivering from the ladder over improvising.

2. **Diagnose before hinting.** Ask one question: "what have you tried, and
   where exactly does it break?" Often articulating this unblocks them with
   no hint at all (record nothing in that case). If their blocker is a
   syntax/tooling triviality unrelated to the learning goal — a compiler
   flag, an import — just answer it directly; the contract protects design
   decisions, not toil.

3. Deliver **tier 1** first. Only escalate to tier 2 on a follow-up request,
   and tier 3 only after tier 2 demonstrably didn't land. Never skip tiers on
   the first ask, even if they ask for "just the pseudocode".

4. **Record every delivered tier**:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py" record-hint --tier <n>`.
   Tell them it's recorded and that hints are data, not failure — a stage
   with honest tier-2s teaches more than a bypassed gate.

5. End by handing the problem back: one concrete next action *they* will
   take, phrased as their move, not yours.
