# The three learning modes

Every step runs one lifecycle:

```
planned → ready → predicted → observed → explained → done
                      ↑           |
                      └── regress ┘
```

`build`, `probe`, and `operate` differ only in what each phase *means*. The
order is identical in all three, and so is the spine underneath it: **predict,
observe, explain.**

The learner commits a prediction in writing before encountering reality. This
is not ceremony. A prediction you never wrote down cannot be falsified — when
reality shows up, a vague memory of what you expected quietly reshapes itself
to match, and you leave with the same broken model plus a warm feeling of
understanding. Written first, it can be wrong on the record, and being wrong on
the record is what dislodges it. Everything else here is machinery for getting
a prediction out of the learner and then holding it against what happens.

You are the component most likely to break this, because you usually know the
answer and handing it over feels like helping. It is not: it converts a
falsifiable prediction into a tutorial, and tutorials do not survive the week.

## What each phase means

| Phase | What is true | build | probe | operate |
|---|---|---|---|---|
| `planned` | In the roadmap. No mode chosen. | — | — | — |
| `ready` | Mode chosen, setup complete. Waiting on the learner. | brief + failing tests exist | question framed | environment is up |
| `predicted` | The learner's prediction is on record. Reality is unlocked; work is in progress. | DESIGN.md note written | predicted call path written | failure hypothesis written |
| `observed` | Reality has answered. | tests green | source read, trace annotated | failure injected, observations captured |
| `explained` | Prediction-vs-reality reconciled, and it held up. | implementation explained from memory | trace diff explained | runbook entry written |
| `done` | Closed. Profile updated. | | | |

`regress` moves `observed → predicted`: reality stopped answering — typically a
refactor broke green — and the learner is working again with their commitment
still standing.

There is deliberately no phase for doing the work. That is not a distinct
state; it is the duration of `predicted`.

Reality unlocks at `predicted` and not one moment earlier. What that obliges
you to withhold, and what to say when the learner pushes for it anyway, is in
[`contract.md`](contract.md).

## Choosing a mode

| Situation | Recommend |
|---|---|
| Concept absent from the profile | **probe** — do not build what there is no schema for |
| Concept shaky, or reconciled once, and it is a *mechanism* | **build** — problem solving is now the higher-yield move |
| Goal is operational, or the concept is behavior-under-failure | **operate** |
| The same mode has been recommended three steps running | break the run — interleaving beats blocking |

Recommend in one line, naming the profile evidence behind the recommendation,
then present the alternatives. The recommendation is advice; the mode is the
learner's to pick.

## The template lands before the step opens

Whatever template the chosen mode calls for, write it into the commitment
artifact *first*, and run `open-step` after. In that order:

1. Append the template to `DESIGN.md`, or create
   `TRACES/NN-<slug>.md` / `RUNBOOK/NN-<slug>.md` carrying it.
2. `state.py open-step N --mode <mode> --artifact <path> …`
3. Hand the learner the file and stop.

`open-step` records how large the artifact is at that moment, and
`record-commitment` weighs the artifact against that record. So every byte
written before the step opens is scaffolding, and every byte after it is
credited to the learner's prediction. Scaffold the template afterwards and your
own headings pay most of the gate's price, leaving the learner a sentence to
clear a bar built to demand a falsifiable claim.

## build

**Choose it when** the learner already has schema for the concept and wants the
mechanism in their hands. Reimplementing something you have no model of is
unguided problem solving at maximum load; the same work once a model exists is
where building pays.

**Artifact:** `<project>/DESIGN.md` — one file for the whole project, one entry
appended per build step.

**You supply**, before the learner starts:

- The step brief at `<project>/STEPS/NN-<slug>.md`: the goal, the decision this
  step forces, the definition of done, and a three-tier hint ladder in
  collapsed `<details>` blocks. The tiers are defined in
  [`contract.md`](contract.md).
- Failing tests, including at least one malformed or hostile input case. Run
  them and show they fail for the right reason.

**You do not supply** the design note — it is the learner's prediction. The
never-write list in [`contract.md`](contract.md) bites hardest in this mode,
because in build most of the step is implementation.

**Commitment template**, appended to `DESIGN.md` before the step opens:

```markdown
## Step NN — <title>

**Decision.** <the choice this step forces, in one sentence>
**Taking.** <the option chosen, and the shape it implies>
**Rejected.** <one alternative, and what made it lose>
**Costs.** <what this makes cheap, and what it makes expensive later>
**Where I expect it to break.** <the input or condition least covered>
```

**Reconcile question:** explain the implementation from memory — what it does,
the decision made, and one alternative rejected and why it lost.

## probe

**Choose it when** the concept is absent from the profile, or the question is
"why is it built this way". Reading a real system with a prediction in hand is
guided study, which is what an absent schema needs.

**Artifact:** `<project>/TRACES/NN-<slug>.md` — predicted hops, actual hops, and
the diff between them.

**The question is one concrete traversal**, never a topic: "what happens
between `socket.read()` and the bytes being durable?" — not "understand the
storage layer". A topic has no endpoint, so no prediction can be checked
against it.

**You supply** the question, the artifact skeleton, and — once the phase is
`predicted` — the coordinates: repository, files, entry-point function names,
and the order to read them.

**You do not supply** what is at those coordinates: no summary, no "you'll see
that it…", no preview of the answer.

### The navigator rule

> In probe mode the agent is a navigator, never a narrator. It may say
> "start at `KafkaApis.handleProduceRequest`." It may not say "which
> batches the records and then appends to the log." Coordinates are
> yours to give; conclusions are the learner's to reach.

**Commitment template** — written into the trace file before the step opens,
numbered hops for the learner to extend as far as they think the path runs:

```markdown
# Trace NN — <the question>

## Predicted path

### Hop 1
- Component:
- Data structure:
- What happens here:
- What could go wrong here:

### Hop 2
- …
```

The hop count is itself a prediction. A missing hop is one of the most common
and most useful ways to be wrong.

**Reconcile question:** *"Where were you wrong, and why did you believe that?"*
The wrong hops are the payload, not the right ones — steer the whole
conversation onto them.

## operate

**Choose it when** the goal is operational, or the target is behavior under
failure. What a system does while something is broken is not in the happy path
at any depth of reading.

**Artifact:** `<project>/RUNBOOK/NN-<slug>.md` — the hypothesis, what actually
happened, how this would be *detected* in production, and what to do about it.

**You supply** the environment: docker-compose files, setup and teardown
scripts, load generators — whatever stands the real system up and makes the
experiment repeatable. This is scaffolding and it is contract-legal; the
learning is in the failure, not in the YAML. Once the phase is `predicted`, you
also supply the injection command and the observation targets.

**You do not supply** the hypothesis, any blank inside it, or an account of
what happened before the learner has read their own observations.

**Commitment template**, written into the runbook file before the step opens:

```markdown
# Runbook NN — <the failure>

## Hypothesis

If I <the failure to be injected>, I predict:

- the client sees ___
- the log shows ___
- metric ___ moves ___ (direction and rough size)
- recovery takes ___ seconds
```

Every blank names an observable and where to read it. "It will break" is not a
hypothesis — it cannot come out false, so nothing can be learned from it, and
the machine gate rejects it.

**Reconcile question:** *"What would page you, and what do you do at 3am?"* An
entry that cannot answer both halves is an experiment write-up, not a runbook.
