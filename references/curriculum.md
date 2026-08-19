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
  --note "<the learner's answer, verbatim>" --source calibration \
  --project <tech>
```

Store the answer verbatim. The grade is your judgement and can be wrong; the
evidence behind it must be re-readable by anyone who later doubts the grade,
including you.

`--project` takes the technology being calibrated for, spelled exactly as
`new-project` will register it. Calibration runs before the project exists, so
without the flag every answer lands attributed to no project at all, and a
concept met once in Kafka and once in Redis reads as two unrelated entries
instead of one that transferred — the comparison `/bmox:status` presents as the
return on the whole exercise. Calibration evidence is the part of it worth the
most: a misconception caught cold, in the learner's own words, before any step
could have coached it away. A spelling that does not match the one
`new-project` gets breaks that join exactly as thoroughly as omitting the flag.

A grade of `partial` or `none` records a gap as well:

```
state.py record-gap --concept <name> --project <tech> \
  --note "<what they said they were unsure of, in their words>"
```

The evidence entry says how well they answered; the gap says what is still
wrong, and only the gap is a target. "I'm fuzzy on whether the consumer can see
the same offset with different data" names its own misconception precisely
enough to aim a step at — so record it in that phrasing, not in your
paraphrase, which will have quietly corrected it. Skip this and a first project
begins against an empty profile: gap-driven ordering has no gaps to order by,
and the only signal left is the conversation you just had, which is the signal
you would have had with no profile at all.

`--project` carries the same name here as it does above, for the same reason:
the two calls describe one answer, and a gap naming no project beside evidence
that names one reads as a leftover from some other conversation. `record-gap`
refuses the flag while the project in focus has a step open, since a gap
recorded then carries that step's number and belongs with it — so a calibration
that collides with an unfinished step is telling you to close it (`/bmox:check`)
or skip it, not to drop the flag.

Check the concept name against the ones already in the profile and their aliases
before recording — filed under a second spelling of a concept the profile
already tracks, a gap will not be found by the plan that should have aimed at
it.

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

Build steps carry two more fields:

5. **Observable behavior** that proves it works, and that maps to a test.
6. **The design decision** the learner must make. If there is no decision,
   merge the step into a neighbor — it is scaffolding, not learning.

If you cannot fill the fields, the step is too vague. Split it or merge it.

### The roadmap is read on day one

`ROADMAP.md` lands before step 1 opens and the learner re-reads it for weeks, so
it is the file in the project most able to spoil its own steps.

What the real system does at each step does not go in it. That comparison is owed
to the learner *after* they have committed and reconciled, and `/bmox:check`
delivers it at close-out. Parked in the roadmap it answers a later step's
prediction on day one — and it reliably does, because the mode heuristic hands one
concept a probe step and then a build step, so the build entry's account of the
real mechanism is the answer to the probe step that precedes it.
[`modes.md`](modes.md) states the general rule this is an instance of: anything
the contract owes the learner later cannot be parked in a file they read now.

The same applies to what a step is *called*. For probe and operate steps the
title and the *Reality answers when* field name the question, not the mechanism:
"what makes a broker's write durable", never "the broker acks before it flushes".
A title that asserts the answer is a spoiler nothing downstream will catch,
because no gate reads titles.

`RESOURCES.md` carries the same risk more quietly. Collect the links, and do not
paste specification prose into the conversation while researching: a passage that
lands in the transcript has been delivered to the learner whether or not any file
records it. Say in the file that a link is not to be opened before the step that
needs it.

## Structural rules

- The time budget picks the band, and the band is the step count:

  | Total hours the learner expects to spend | Steps |
  |---|---|
  | under ~15 | 4–6 |
  | ~15–40 | 7–10 |
  | 40+ | 11–14 |

  The hours are rough and meant to be — they set a starting point that `replan`
  corrects once the first steps have been lived through.
- Order by dependency. Completion is enforced in order, so a step that
  motivates a later one has to land before it.
- Optimization comes after `observed`, never before. "Make it work, then
  measure" is its own step, placed after the step it measures.

### What the band buys

What a band of steps reaches depends on which modes fill it, because the three
modes leave different things behind — an implementation, a trace, a runbook.
Read the row for each mode the draft actually spends steps on:

| Mode | 4–6 steps | 7–10 steps | 11–14 steps |
|---|---|---|---|
| **build** | the core data structures | a single node that is durable and correct | replication and consensus |
| **probe** | one path through the real source, traced hop by hop, and the misconceptions that path exposes | several paths and the seams between them: how the subsystems compose, and what each side assumes of the other | why the system is shaped this way — the constraints behind those seams and the alternatives the project's own history rejected |
| **operate** | two or three of the system's failures injected against a real deployment, each turned into a runbook entry | a runbook for the failure modes the system is documented to have, including the ones that only appear under load | failure across nodes and degraded operation — partition, partial availability, recovery — and where the operating envelope ends |

Most roadmaps mix modes, so most depth statements are a join, named in
proportion to the steps spent on each mode and silent about a mode the roadmap
does not use: two probe steps and two operate steps reach "the fetch path traced
against real source, plus runbook entries for two of the failures behind
consumer lag". That sentence is what `{{DEPTH}}` carries into ROADMAP.md, where
the learner re-reads it for weeks, so it has to be true of the roadmap you
drafted rather than of the technology.

Say which band the budget affords and what it buys as soon as the budget is
named, so the learner trades depth for time deliberately rather than discovering
the trade at step 7. No draft exists yet at that point, so name the reach the
likely mix affords — whether build is in play is already implied by whether you
asked for a language — and let the draft sharpen it into the sentence above.

### The build spine, where there is one

Two rules shape the build steps, and they reach exactly as far as the roadmap
has any:

- The first build step is trivially end-to-end — "TCP server answers one
  hardcoded request" — so a running system exists from the moment the learner
  starts writing code, and every step after it changes something that runs.
  When step 1 is that build step, which is the usual case, that is day one.
- Where the roadmap has two or more build steps, at least one is **deliberately
  naive** and says so in its brief, with a pointer to the step that fixes it.
  Pain precedes the cure: the learner scans a log linearly in step 3 so that the
  sparse index in step 5 answers a problem they have personally suffered. A lone
  build step has no later step to point at, so it promises no cure and should be
  the honest version.

A roadmap with no build step in it breaks neither rule — there is no spine for
them to be about — and that is a first-class outcome, not a draft to go fix. The
heuristic in [`modes.md`](modes.md) hands probe and operate steps to a learner
who already has schema for the mechanisms the goal names, and a senior engineer
who says they will not spend a third of the budget writing Go has made a correct
call about their own bottleneck. Adding a build step so these rules have
something to apply to spends that third anyway, on the one thing they declined.
The interview above anticipates the case by asking for a language only when the
goal makes build steps likely; a draft that comes out build-free is that
judgement holding, not slipping.

The absence narrows what the scaffold can claim: no implementation language, and
nothing to wire behind `make test`. `/bmox:plan`'s placeholder table gives
`{{LANGUAGE}}` and `{{TEST_CMD}}` their build-free values and says what each
still has to guarantee — take them from there, rather than naming a language the
learner never agreed to write in. The rest of the scaffold is unchanged, the
depth line included: a build-free roadmap states what it reaches from the bands
above like any other.

## Mode balance

The heuristic in [`modes.md`](modes.md) grades one step at a time; a roadmap is
a sequence, and you are the only one positioned to see the sequence. Run the
heuristic over the whole draft before showing it, and honor its last row — a
run of one mode is a defect of the roadmap, not of any step in it.

Where breaking a run costs you the best mode for a single step, break it
anyway: that last row outranks the three above it, which is why it is last.
