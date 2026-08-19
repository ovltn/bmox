# Changelog

One section per released version, newest first. Format and versioning rules
are in [AGENTS.md](AGENTS.md).

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
