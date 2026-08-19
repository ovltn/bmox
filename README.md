# bmox — Build My Own X, without letting the agent steal the learning

A Claude Code plugin that turns your `build-my-own-x` repo into a learning
harness: a gap-driven roadmap, one of three learning modes per step, and a
script-enforced state lifecycle that gates progression on a prediction you
write down before you're allowed to see reality.

## The contract

`/bmox:plan` picks a mode per step — **build** (reimplement it), **probe**
(read the real source and trace one path through it), or **operate** (run the
real system and break it) — based on what your knowledge profile says you
already know. Whatever the mode, the agent supplies scaffolding — tests, a
trace skeleton, a chaos environment — and never the thing you're there to
produce: an implementation, a trace answer, or a failure hypothesis. Full
rules for what the agent may and may never write are in
[`references/contract.md`](references/contract.md). Bypasses are allowed —
it's your repo — but recorded forever.

## Install

```bash
# inside Claude Code:
/plugin marketplace add ovltn/bmox
/plugin install bmox@ovltn-plugins
```

The marketplace catalog is named **`ovltn-plugins`** (see
`.claude-plugin/marketplace.json`), which is why installs are qualified with
`@ovltn-plugins` even though the repo is `ovltn/bmox`.

Or share it with anyone cloning a project by adding to that project's
`.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "ovltn-plugins": { "source": { "source": "github", "repo": "ovltn/bmox" } }
  },
  "enabledPlugins": { "bmox@ovltn-plugins": true }
}
```

## Commands

| Command | What it does |
|---|---|
| `/bmox:plan` | Read your knowledge profile, interview and calibrate you, research the tech, and draft a gap-driven roadmap — also replans an existing project |
| `/bmox:step` | Recommend a mode for the next step, set up its materials, and hand you the commitment template to fill in |
| `/bmox:hint` | The smallest hint that unblocks (tier 1→2→3), recorded — refuses outright before your prediction is on record |
| `/bmox:check` | Run the mode's machine gate (tests, trace diff, or captured observations), then the reconcile gate that holds your prediction against what reality did |
| `/bmox:status` | Current project and step, phase, hint counts, gate-bypass flags, and the knowledge profile underneath them |

## Lifecycle

Every step, in every mode, moves through the same six phases:

```
planned → ready → predicted → observed → explained → done
                      ↑            |
                      └── regress ─┘
```

Reality — green tests, the real source, the live system — stays locked until
your prediction is on record: `record-commitment` refuses to advance a step
from `ready` to `predicted` until the commitment artifact has gained 400
non-whitespace characters of prose that is not the template's own blanks, not
one repeated character, and not a paragraph carried forward from an earlier
step — so there's always a written, falsifiable claim before you look.

Stored in **your repo**, mutated only by `scripts/state.py`: `.bmox/state.json`
holds project and step progress, `.bmox/profile.json` holds what you've
demonstrated. Commit both — the plugin cache is wiped on updates, and neither
file lives anywhere else.

## Repo layout

The repo **is** the plugin — its root is `CLAUDE_PLUGIN_ROOT`. The marketplace
catalog sits alongside the plugin manifest and points at `./`:

```
.claude-plugin/
├── plugin.json                   # the plugin manifest
└── marketplace.json              # the catalog listing it (source: "./")
skills/{plan,step,hint,check,status}/SKILL.md
scripts/state.py                  # state lifecycle enforcer
scripts/knowledge.py              # knowledge profile store
references/{contract,curriculum,modes}.md
assets/templates/project/         # scaffolded into each learning project
AGENTS.md                         # conventions for changing this repo
CHANGELOG.md                      # what each release changed
```

## Design notes

- State transitions live in a script, not in prompts, because prompt
  discipline degrades over long sessions and model updates; `argparse` does
  not. The model is instructed to treat script refusals as correct.
- The reveal gate — the byte-growth check in `record-commitment` — lives in
  the same script for the same reason: a model can be talked into believing a
  half-written blank counts as a prediction, and a byte count can't be.
- The knowledge profile stores evidence, not scores. A score rots silently and
  can't be argued with; evidence can be re-read months later, and the wrong
  predictions sitting in it are the most useful thing in the file.
- Hint ladders are authored at step-open time (calm) rather than at
  hint-request time (frustrated), so escalation policy isn't negotiated
  in the moment.
- External graders (e.g. `codecrafters-io/kafka-tester`) are preferred over
  agent-written tests wherever they exist: a binary can't be sweet-talked.

## Releasing changes

The release procedure and versioning rules are in [AGENTS.md](AGENTS.md); what
changed in each release is in [CHANGELOG.md](CHANGELOG.md).

## Local development

```bash
# iterate without installing:
claude --plugin-dir .

# or test the marketplace flow end-to-end:
/plugin marketplace add ./path/to/this/repo
/plugin install bmox@ovltn-plugins
```

## Roadmap

`/bmox:review` (post-completion diff against the real implementation),
`/bmox:grill` (pre-implementation design interrogation), repo-level
reporting across profiles, a SessionStart hook surfacing the current step.
