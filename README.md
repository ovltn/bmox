# bmox — Build My Own X, without letting the agent steal the learning

A Claude Code plugin that turns your `build-my-own-x` repo into a
CodeCrafters-style learning harness: researched roadmaps, failing tests per
stage, tiered hints, and a script-enforced state lifecycle that gates
progression on you explaining your own design out loud.

## The contract

The agent writes **docs, tests, and scaffolding**. It never writes the
implementation. When you're stuck, `/bmox:hint` gives the smallest tiered
hint and records it. When tests go green, `/bmox:check` makes you explain
your design from memory before the next stage unlocks. Bypasses are allowed —
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
| `/bmox:new <tech>` | Research primary sources + external graders, interview you, generate a staged roadmap, scaffold `<tech>/` |
| `/bmox:stage` | Write the next stage's brief + failing tests, hand over |
| `/bmox:hint` | Smallest unblocking hint (tier 1→2→3), recorded |
| `/bmox:check` | Run tests; if green, administer the explain-aloud gate; advance |
| `/bmox:status` | Progress, phases, hint counts, gate-bypass flags |

## State lifecycle

Stored in **your repo** at `.bmox/state.json` (commit it — the plugin cache is
wiped on updates, your progress isn't in it), mutated only by
`scripts/state.py`, which enforces:

```
planned → implementing → green → explained → done
              ↑            |
              └── regress ─┘
```

- `green` is reachable only via `/bmox:check` running your tests.
- `done` requires `explained` — or an explicit `--force`, permanently
  flagged as `GATE BYPASSED` in status output.
- Stages complete strictly in order (the naive stage must hurt before the
  fix stage teaches).
- Writes are atomic; every mutation lands in an audit log.

## Repo layout

The repo **is** the plugin — its root is `CLAUDE_PLUGIN_ROOT`. The marketplace
catalog sits alongside the plugin manifest and points at `./`:

```
.claude-plugin/
├── plugin.json                   # the plugin manifest
└── marketplace.json              # the catalog listing it (source: "./")
skills/{new,stage,hint,check,status}/SKILL.md
scripts/state.py                  # state lifecycle enforcer
references/{contract,curriculum}.md
assets/templates/project/         # scaffolded into each learning project
```

## Design notes

- State transitions live in a script, not in prompts, because prompt
  discipline degrades over long sessions and model updates; `argparse` does
  not. The model is instructed to treat script refusals as correct.
- Hint ladders are authored at stage-open time (calm) rather than at
  hint-request time (frustrated), so escalation policy isn't negotiated
  in the moment.
- External graders (e.g. `codecrafters-io/kafka-tester`) are preferred over
  agent-written tests wherever they exist: a binary can't be sweet-talked.

## Releasing changes

`version` lives **only** in `.claude-plugin/plugin.json` (setting it in
`marketplace.json` too is a documented footgun — plugin.json silently wins).
Users receive updates **only when you bump it**, so:

1. Make changes, then validate: `claude plugin validate . --strict`
2. Bump `version` in `.claude-plugin/plugin.json`
3. Commit, push. Users pick it up via `/plugin marketplace update ovltn-plugins`
   or auto-update.

## Local development

```bash
# iterate without installing:
claude --plugin-dir .

# or test the marketplace flow end-to-end:
/plugin marketplace add ./path/to/this/repo
/plugin install bmox@ovltn-plugins
```

## Roadmap

`/bmox:review` (post-green pattern extraction + real-system diff),
`/bmox:grill` (pre-implementation design interrogation), repo-level
`docs/patterns.md` automation, SessionStart hook surfacing current stage.
