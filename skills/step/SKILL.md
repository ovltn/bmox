---
name: step
description: Open the next step of the current build-your-own-X learning project. Recommends a learning mode (build, probe, or operate), sets up that mode's materials — failing tests, a trace question, or a chaos environment — and issues the prediction the learner must commit before reality unlocks. Use when the user says "next step", "continue my project", "start step 3", "/bmox:step", or is ready to keep going.
---

# /bmox:step — open the next step

This skill sets a step up and stops. Everything it writes is scaffolding;
everything the learner writes is the prediction. The mode is chosen here rather
than read off the roadmap, because the roadmap's suggestion was made before the
last few steps moved the profile.

Read `${CLAUDE_PLUGIN_ROOT}/references/contract.md` (what you may write, what
you may never write, what stays withheld) and `modes.md` (the three modes,
their setup, and their templates) before doing anything below.

Every `state.py` below means
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py"`.

## Procedure

1. **Read state.** `state.py status --json`. The next step is the
   lowest-numbered one whose entry is absent or `planned`. If a step is
   mid-flight — any phase from `ready` to `explained` — summarize where it
   stands, name the single action that moves it forward, and stop. One step at
   a time is the point: a second open step is somewhere to escape to when the
   first one gets hard.

2. **Recommend a mode**, per modes.md's *Choosing a mode*, including its
   closing rule about whose choice it is. Then wait for the answer. Do not
   proceed on a recommendation nobody accepted — the learner knows what the
   last step left them wanting, and you do not.

3. **Set up the chosen mode**, per that mode's section in modes.md. Its
   *You supply* list is your work for this step, minus the entries that section
   itself gates on the phase `predicted` — those are not due yet and are the
   ones an eager agent hands over early. Its *You do not supply* list is not
   yours at any point.

4. **Compute the artifact path.** The mode's **Artifact** line in modes.md
   gives it. `NN` is the step number zero-padded to two digits; `<slug>` is the
   roadmap title lowercased and hyphenated — `03-sparse-index`.

5. **Write the commitment template into that artifact.** Copy the chosen mode's
   *Commitment template* from modes.md: append it to `DESIGN.md`, or create the
   trace or runbook file carrying it. Copy it as it stands — filling one blank,
   even as an example, even the easy one, is writing the learner's commitment,
   which contract.md's never-write list puts beside writing their
   implementation.

6. **Then open the step**, and not before step 5 has written the file:

   ```
   state.py open-step N --mode <mode> --artifact <path> --title <slug> \
     --concept <c> [--concept <c> ...]
   ```

   with the concepts the roadmap entry names. `open-step` baselines the
   artifact at the moment it runs, which is why step 5 comes first; modes.md's
   *The template lands before the step opens* gives the argument in full, and
   the order of 5 and 6 here is that rule made procedural. Handing the learner
   the template to paste in themselves fails the same gate from the other side
   — pasted bytes grow the file exactly as yours would.

   If `open-step` refuses because the previous step is not done, the refusal is
   correct. Explain the lifecycle and finish the open step; contract.md's
   *State discipline* is not negotiable in either direction.

7. **Hand over and stop.** Point at the artifact and at whatever step 3
   produced, tell the learner to write their prediction into the artifact and
   then run `state.py record-commitment`, and mention `/bmox:hint`. Then stop —
   no starter code, no sketch of what hop 1 will be, no worked example of a
   blank. An example is the answer at one remove.

## Withholding reality

contract.md's *Withholding reality* binds every message this skill sends,
including the ones after step 7 has stopped. Obey it in full.

They will ask early — the file is open, the prediction is hard, and you
obviously know. Say plainly that the ordering *is* the method rather than a
formality, and offer `/bmox:hint`, which can move them without spending the
prediction.
