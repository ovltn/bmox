# Designing a gap-driven bmox roadmap

A roadmap is a sequence of steps, and each step exists to close one gap between
what the profile says the learner knows and one capability they said they want.
No gap, no step. That is the whole test — it is what stops a roadmap from being
a table of contents for the technology.

## Goals are capabilities, not topics

"Debug a consumer-lag incident" determines the roadmap: it implies operate
steps against a real cluster, a probe of the fetch path, and probably one build
step for offset tracking. "Learn Kafka" determines nothing — every possible
step is equally defensible, which means none of them is chosen for a reason.

If the learner offers a topic, ask once what they want to be able to *do* with
it, and draft against the answer. The goal is usable when you can name, for
every step, the capability it unlocks and trace that capability back to the
goal in one line.

Then read the profile — `state.py profile show` — before drafting anything.
Concepts with reconciled evidence are not re-taught; compress or drop those
steps and say so out loud. Unresolved gaps are the highest-value targets in the
file: each one is a place the learner has already been wrong on the record, so
a step aimed at one lands on a misconception that is known to exist rather than
one you guessed at.

## Interview: three questions, no more

- **The capability goal** — what they want to be able to do.
- **The time budget** — it decides the step count, and through the count it
  decides how deep the project goes. An honest small number beats an
  aspirational large one.
- **The implementation language** — asked only if the goal makes build steps
  likely. Asking it up front frames the project as a reimplementation and
  biases every later decision toward build.

## Calibration: four to six questions

Diagnostic, not trivia. The test of a good calibration question is that its
*plausible wrong answer* identifies a specific misconception. "When a producer
gets an ack, where is the record?" is a good question: the plausible wrong
answer — durable on every replica — is a real, common, and consequential
belief. "What port does Kafka listen on?" grades nothing, because being wrong
about it means only that you have not memorized it.

Skip concepts the profile already records as reconciled. Calibration shortens
as the profile grows, which is the point of keeping a profile at all.

Grade each answer `reconciled` / `partial` / `none` and record it:

```
state.py record-evidence --concept <name> --outcome <grade> \
  --note "<the learner's answer, verbatim>" --source calibration
```

Store the answer verbatim. The grade is your judgement and can be wrong; the
evidence behind it must be re-readable by anyone who later doubts the grade,
including you.

## Research before drafting a single step

Aim research at all three modes. A procedure that gathers only specs and
graders can only produce a roadmap of build steps, because those are the only
steps its sources support.

1. **Primary sources.** Official protocol specs, design docs in the project's
   own repo, the original papers. Blog summaries belong in RESOURCES.md under
   further reading, never in roadmap facts.
   - Kafka: the protocol guide (kafka.apache.org/protocol), KIP documents.
   - Redis: the RESP spec, redis.io internals docs, antirez's design notes.
   - Generally: search "<tech> protocol specification", "<tech> design
     document", "<tech> architecture internals site:github.com".
2. **The real project's directory layout.** It shows the natural module seams
   (log/, network/, replication/). Build steps that follow real seams make the
   post-hoc comparison meaningful, and probe steps need the real paths anyway.
3. **Operational practice.** How the system is actually run, its documented
   failure modes, public postmortems. This is where operate steps come from,
   and a failure that really happened to someone beats one you invented.
4. **Community consensus on what is genuinely hard** or commonly
   misunderstood. These are the known misconception sites; they feed both
   calibration questions and probe questions.
5. **Maintainer talks and design documents.** The rejected alternatives are the
   payload — a step that asks the learner to make a decision is much stronger
   when you know what the real project decided and why.
6. **External graders**, as one input among several. Check
   `github.com/codecrafters-io/<tech>-tester`, then official conformance suites
   and test-vector sets. A grader that cannot be sweet-talked is worth more
   than any prompt-level rule in this plugin, so if one exists, wire it into
   the project Makefile (`make grade`) and align build-step boundaries with the
   boundaries it checks.

## Step template — the mandatory fields

Every step in ROADMAP.md names:

1. **The capability it unlocks**, traced to the stated goal.
2. **The concepts it touches**, matched against the profile. Before naming a
   new concept, check it against existing concept names and aliases and add an
   alias where it matches — `state.py profile alias <concept> <alias>` — so
   evidence accumulates in one place rather than fragmenting across three
   spellings of the same idea.
3. **A suggested mode with one line of why.** The heuristic that produces the
   suggestion, and how much weight it carries, are in [`modes.md`](modes.md).
4. **What reality answering looks like** for this step — the concrete event
   that ends the prediction and starts the reconciliation.

Build steps carry three more fields:

5. **Observable behavior** that proves it works, and that maps to a test.
6. **The design decision** the learner must make. If there is no decision,
   merge the step into a neighbor — it is scaffolding, not learning.
7. **What the real system does here**, one sentence, for the later comparison.

If you cannot fill the fields, the step is too vague. Split it or merge it.

## Structural rules

- The time budget picks the band, and the band is what the project reaches:

  | Total hours the learner expects to spend | Steps | Reaches |
  |---|---|---|
  | under ~15 | 4–6 | the core data structures |
  | ~15–40 | 7–10 | a single node that is durable and correct |
  | 40+ | 11–14 | replication and consensus |

  The hours are rough and meant to be — they set a starting point that `replan`
  corrects once the first steps have been lived through. Say which band the
  budget affords and what it buys, so the learner trades depth for time
  deliberately rather than discovering the trade at step 7.
- Order by dependency. Completion is enforced in order, so a step that
  motivates a later one has to land before it.
- At least one build step is **deliberately naive** and says so in its brief,
  with a pointer to the step that fixes it. Pain precedes the cure: the learner
  scans a log linearly in step 3 so that the sparse index in step 5 answers a
  problem they have personally suffered.
- Step 1 is trivially end-to-end — "TCP server answers one hardcoded request" —
  so there is a running system on day one.
- Optimization comes after `observed`, never before. "Make it work, then
  measure" is its own step, placed after the step it measures.

## Mode balance

The heuristic in [`modes.md`](modes.md) grades one step at a time; a roadmap is
a sequence, and you are the only one positioned to see the sequence. Run the
heuristic over the whole draft before showing it, and honor its last row — a
run of one mode is a defect of the roadmap, not of any step in it.

Where breaking a run costs you the best mode for a single step, break it
anyway: that last row outranks the three above it, which is why it is last.
