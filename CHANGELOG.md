# Changelog

One section per released version, newest first. Format and versioning rules
are in [AGENTS.md](AGENTS.md).

## [0.4.0] — 2026-08-19

### Added

- `state.py mark-observed` runs `make test` for a build step and refuses on a
  non-zero exit, so whether the tests passed is no longer the model's claim to
  make. A project with no Makefile is refused rather than passed over.
- The build commitment template carries a `What actually happened` section, and
  `mark-observed` refuses a build step whose entry for this step leaves it
  unfilled. Green tests say the code works and nothing about the prediction.
- `state.py profile show` reports what stands behind each concept: hints taken,
  a bypassed reconcile gate, an answer that only ever came from calibration, and
  the projects a concept has been met in.
- `/bmox:check` names what the real system does at this step during close-out,
  once the prediction has been committed and reconciled.

### Changed

- `record-commitment` reads the template's blanks from the whole prediction
  rather than from the lines the learner added, so a blank left standing refuses
  the commitment whoever wrote it, while the sections recording what reality did
  are read around until `observed`.
- `record-commitment` weighs an addition on what it says rather than on how the
  file grew, so answering a blank in fewer characters than the question took
  clears the gate, and a prediction that is merely thin is told so.
- A build step open at the moment of upgrading needs
  `### What actually happened` added to its `DESIGN.md` entry before
  `mark-observed` will pass; nothing else in flight is affected.
- `state.py record-evidence` refuses until the step reaches `observed`: an entry
  written earlier carries the hint count as it stood then, leaving a hinted step
  reading as an unhinted solve.
- `complete-step --force` marks every evidence entry the step wrote as
  gate-bypassed, so `profile show` stops presenting it as a clean solve.
- `profile show` reports the sequence of outcomes a concept has been graded
  rather than the strongest one it ever reached.
- `contract.md` governs what the agent may never *say* as well as what it may
  never write, the navigator rule binds from the moment a step opens rather than
  from the moment reality unlocks, and the override procedure names `skip-step`
  in the phase where `record-hint` can record nothing.
- Agent-written tests assert observable behavior rather than a chosen structure,
  which for a parser or a protocol is the design the step exists to force.
- `ROADMAP.md` carries no account of what the real system does at each step, and
  probe and operate step titles name the question rather than the mechanism.
- The mode heuristic reads "no schema for the concept" rather than "absent from
  the profile", which calibration makes untrue after the first plan.
- An operate step's injection has to be able to falsify each blank of the
  hypothesis, and probe coordinates carry the commit a tag points at.
- `RESOURCES.md` tells the learner not to open a link before the step that needs
  it.

### Internal

- pytest coverage for build's machine gate, a blank left standing in the
  baseline, a blank filled in place, the evidence phase guard, and the bypass
  marker reaching the profile.

## [0.3.0] — 2026-08-19

### Added

- `state.py record-evidence --project` and `record-gap --project` attribute a
  calibration answer to the project it was asked for, before that project is
  registered.
- `/bmox:plan` records a gap for every calibration answer it grades `partial` or
  `none`, so a first roadmap has gaps to be driven by.
- `state.py mark-observed` reads the artifact and refuses a probe step whose
  hops carry no annotation, or an operate step whose observables carry no
  observation.
- `state.py status` reports transitions the audit log timed at zero seconds, and
  hint tiers recorded in the same second.
- `references/curriculum.md` gives probe and operate their own depth bands, so a
  roadmap with no build step is a first-class outcome rather than a rule
  violation.
- `state.py init` writes a `.bmox/.gitignore` that keeps the lock files and
  interrupted writes out of git while leaving your state and profile tracked.

### Changed

- `record-commitment` weighs added non-whitespace prose rather than filesize,
  and refuses the template's own blanks, a repeated character, or a paragraph
  carried forward from an earlier step.
- `state.py skip-step` closes a step from any phase short of `done`, recording
  the phase it was abandoned at, so changing your mind mid-step is a legal exit
  rather than a bypassed gate.
- `state.py profile alias` joins a duplicate concept into its target, carrying
  every evidence entry and gap across, and refuses a name a third concept
  already answers to.
- `state.py profile show` reports each concept's outcome and lists the
  heaviest-evidenced first.
- The hint ladder stays in the conversation instead of being written into the
  step brief, where the learner read tier 3 on the way past the goal.
- Probe coordinates name a pinned revision, are verified to resolve before they
  are handed over, and carry no line numbers.
- The probe and operate commitment templates carry the sections `/bmox:check`
  gates on.
- `make grade` fails when no external grader is wired, instead of reporting a
  pass over an empty repo.

### Fixed

- `make test` resolves the step under test both while a step is being set up and
  after it closes, and tells you whether the state file is missing or unreadable.
- Every command holds a lock across its read and write, so two sessions in one
  repo no longer discard each other's hints, evidence, and audit entries.
- Writes are flushed to disk and leave no temporary files behind when
  interrupted.
- An unreadable, mis-shaped, or half-repaired `state.json` or `profile.json`
  refuses with an explanation instead of a Python traceback, and a mis-shaped
  profile no longer reports itself as empty.
- `record-gap` twice with the same note leaves one gap open; `resolve-gap`
  refuses to overwrite the step already credited with closing it.
- `new-project` and `replan` reject a step count below one, and `new-project`
  rejects a blank name.
- `status` and `profile show` size their columns to what they are printing.

### Internal

- pytest coverage for the content gate, the probe and operate machine gates,
  concurrent writes, and every corruption case that used to traceback.

## [0.2.0] — 2026-08-19

### Added

- `/bmox:plan` researches primary sources and operational practice, probes what
  you already know, and generates a roadmap whose steps each carry a suggested
  learning mode.
- Probe and operate modes: trace a request through the real source, or stand the
  real system up and break it, instead of reimplementing everything.
- `.bmox/profile.json` records what you have demonstrated against concepts
  rather than projects, so a second project builds on the first.
- `state.py skip-step` closes a step you have decided is not worth your time,
  with the reason shown in status.

### Changed

- `/bmox:new` becomes `/bmox:plan`; `/bmox:stage` becomes `/bmox:step`.
- A step's phases are `planned`, `ready`, `predicted`, `observed`, `explained`,
  `done`. Reality unlocks only once your prediction is written down.
- `/bmox:check` gates on the mode: tests for build, a completed trace diff for
  probe, captured observations for operate.
- The `.bmox/state.json` schema moves to v2, and a v1 file is refused outright
  with no migration path: archive it and run `state.py init`, then re-register
  your projects. Finished work stays in your repo and its git history.

### Removed

- `state.py add-pattern`. The profile records concepts with evidence behind them.

### Internal

- pytest coverage for every phase transition, the reveal gate, and the profile.

## [0.1.0] — 2026-08-17

### Added

- Initial release: staged roadmaps, failing tests per stage, tiered hints, and
  a script-enforced state lifecycle with an explain-aloud gate.
