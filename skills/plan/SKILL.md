---
name: plan
description: Plan or replan a build-your-own-X learning project. Assesses what the learner already knows from their bmox profile plus a short calibration probe, researches primary sources and operational practice, and generates a gap-driven roadmap whose steps each carry a suggested learning mode. Use whenever the user wants to start learning a technology deeply — "build my own kafka", "start redis from scratch", "I want to understand redis", "learn how postgres works", "I want to know what happens inside a database" — or wants to revise, extend, shorten, or replan an existing bmox roadmap.
disable-model-invocation: false
---

# /bmox:plan — decide what the learner spends the next weeks on

You are planning weeks of one person's work. This is the most expensive
decision in the plugin to get wrong: everything downstream executes the roadmap
you write here, and the rules for writing one live in curriculum.md.

Read all three references now and hold them for the whole session:
`${CLAUDE_PLUGIN_ROOT}/references/contract.md` (what you may and may never
write), then `curriculum.md` (how a gap-driven roadmap is derived — most of
what you need is there), then `modes.md` (the three modes and the mode
heuristic).

Every `state.py` below means
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/state.py"`.

## Procedure

1. **State first.** `state.py init` if `.bmox/state.json` is absent, then
   `state.py status`. If a project of this name is already registered, this is
   a replan — go to *Replanning* below.

2. **Read the profile out loud.** `state.py profile show`. Say what it claims
   before you ask anything: which concepts carry reconciled evidence, which
   carry open gaps. A record the learner has never seen is one they cannot
   correct, and you are about to plan weeks of work on it.

   Read the indented lines under each concept, not just the outcome. They are
   what makes the outcome mean anything: an outcome shown as `none→reconciled`
   got there, and a concept marked reconciled that also says it was answered in
   calibration only, or earned with a tier-3 hint, or closed on a bypassed
   reconcile gate, is not ground you may compress away. "Do not re-teach what is
   reconciled" applies to a concept that was demonstrated, and those lines are
   how you tell the difference.

3. **Interview.** curriculum.md's *Interview* — three questions, no more. One
   question per message, and wait for each answer before sending the next;
   asked together they get answered together, briefly. The time budget answer
   is not just a number: resolve it against curriculum.md's *Structural rules*
   into a band and what that band buys, and do so before moving to the next
   question.

4. **Calibrate** per curriculum.md's *Calibration* — four to six questions, one
   per message. Say aloud which concepts you are skipping and on what evidence.
   Record every answer with the invocations curriculum.md gives, grading as you
   go: their words go in the note **verbatim**, unedited, even when the answer
   is short or wrong, and a `partial` or `none` also gets a gap recorded, in
   their words too. Those gaps are what step 6 aims steps at; on a first project
   they are the only ones the profile will hold. Attribute the evidence to this
   project's `{{TECH}}` name (*Placeholders* below) — the same string step 7
   passes to `new-project`, because two spellings leave the profile holding two
   unrelated projects.

5. **Research** per curriculum.md's *Research before drafting a single step*.
   Collect 4–8 primary links for `RESOURCES.md`. Collect *links*: search tools
   return prose, and a paragraph of the RESP or Kafka protocol spec quoted into
   this conversation has been delivered to the learner before a single step
   exists to predict against it. Read what you need, write down where it was, and
   keep the passage out of the transcript.

6. **Draft the roadmap, then get approval.** Every step carries curriculum.md's
   mandatory fields. Its *why* line has to name the specific profile evidence
   behind the mode — "two reconciled entries on log segments, so this one
   builds" — because "probe feels right here" cites nothing the learner can
   check. Before showing the draft, apply curriculum.md's *Mode balance*. Then
   show the draft in the conversation, not in a file — nothing lands on disk
   until they approve — ask for approval in as many words, and wait for it.
   Editing now is cheap; editing once they are three steps in costs them work
   they have already done.

7. **Scaffold on approval.**
   - Copy `${CLAUDE_PLUGIN_ROOT}/assets/templates/project/` to `./<tech>/`.
   - Fill every placeholder (table below), then run `grep -rn '{{' ./<tech>/`
     and fix every hit. A shipped `{{TECH}}` tells the learner the harness is
     unfinished before they have written a line.
   - Write the approved roadmap into `ROADMAP.md` and the links into
     `RESOURCES.md`.
   - Wire `make test` to the project's test runner — or, where the roadmap has
     no build step, to the failing command the table names — and `make grade` to
     the external grader if you found one. `make test` is build's machine gate in
     `/bmox:check`: leave it unwired and every build step passes that gate over
     an empty repo.
   - Register:
     `state.py new-project <tech> --language <lang> --goal "<capability>" --steps <N>`.
     `--language` is required and takes the same string as `{{LANGUAGE}}`, `n/a`
     included — a language invented here to satisfy the flag contradicts the
     roadmap the learner just approved.
   - Leave `DESIGN.md` and `NOTES.md` empty beyond their headers. Those are the
     learner's files.

8. **Stop.** Do not open step 1 — not its brief, not its tests, not its
   prediction template, and never `open-step`. `/bmox:step` owns that, and the
   ordering it follows is load-bearing: modes.md's *The template lands before
   the step opens* explains what breaks if the template and `open-step` swap
   places. End by telling the learner to run `/bmox:step`.

If they ask you to implement something "to save time" — and they may ask
before the project even exists — contract.md's refusal-and-offer applies.

## Placeholders

Every `{{PLACEHOLDER}}` in `assets/templates/project/` is one of these.

| Placeholder | Filled from |
|---|---|
| `{{TECH}}` | the technology, lowercase — also the directory name |
| `{{GOAL}}` | the capability from the interview, the same string you pass to `new-project --goal` |
| `{{LANGUAGE}}` | the interview's language answer, or `n/a` when no step is a build step |
| `{{DEPTH}}` | what this roadmap's band and mode mix reach, per curriculum.md's *What the band buys* — derived from the time budget and the approved draft, never asked for |
| `{{TEST_CMD}}` | the test runner for the step in `$(STEP)`, e.g. `go test ./... -run Step$(STEP)`; when the roadmap has no build step, a command that exits non-zero |
| `{{GRADER}}` | the command `make grade` runs to invoke the external grader you found — the Makefile executes it, so a URL or a description of one is a broken target — or the word `none`, which makes that target exit non-zero reporting that nothing was graded |
| `{{TOTAL}}` | the step count |
| `{{N}}` | a step number: `0` in the project status line, since no step is open yet; the step's own number in a roadmap entry |
| `{{TITLE}}` | that step's title |
| `{{MODE}}` | that step's suggested mode |
| `{{WHY}}` | the one line of profile evidence behind that suggestion |

## Replanning an existing project

Completed and skipped steps are immutable. A replan re-derives what is left of
the roadmap and nothing else.

1. `state.py focus <tech>` — `replan` acts on the project in focus.
2. `state.py profile show`, and read the project's current `ROADMAP.md`. Order
   the remaining steps to hit concepts with open gaps first, for the reason
   curriculum.md gives.
3. Ask what changed — the capability, the time budget — but do not re-run
   calibration. The closed steps have been writing evidence into the profile
   the whole time, and that evidence outranks a fresh quiz.
4. Show a **diff** against the existing `ROADMAP.md`: which remaining steps
   survive, which are reworded, which are dropped, which are new. Get explicit
   approval on the diff.
5. Rewrite `ROADMAP.md`, leaving the entries for closed steps exactly as they
   stand.
6. `state.py replan --steps <new total>` — the new total counts the closed
   steps too — plus `--goal "<capability>"` if the capability changed.
7. If `replan` refuses because a step is in flight, it is right. Finish that
   step (`/bmox:check`) or skip it
   (`state.py skip-step N --reason "<why>"`), then replan.
