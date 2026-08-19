# Changelog

One section per released version, newest first. Format and versioning rules
are in [AGENTS.md](AGENTS.md).

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

### Removed

- `state.py add-pattern`. The profile records concepts with evidence behind them.

### Internal

- pytest coverage for every phase transition, the reveal gate, and the profile.

## [0.1.0] — 2026-08-17

### Added

- Initial release: staged roadmaps, failing tests per stage, tiered hints, and
  a script-enforced state lifecycle with an explain-aloud gate.
