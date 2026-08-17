#!/usr/bin/env python3
"""bmox state lifecycle manager.

Single source of truth for learning progress, stored in the LEARNER'S REPO at
.bmox/state.json (never in the plugin cache, which is wiped on plugin update).

The model must NEVER edit state.json by hand. All mutations go through this
script so that lifecycle rules are enforced by code, not by prompt discipline.

Stage lifecycle (strictly ordered):

    planned -> implementing -> green -> explained -> done
                   ^             |
                   +---- regress-+   (tests broke after refactor)

Rules enforced here:
  * You cannot reach `green` except via `mark-green` (called by /bmox:check).
  * You cannot reach `done` without passing through `explained`
    (the say-it-out-loud gate). Skipping requires --force, which is recorded
    permanently in the audit log as "gate_bypassed".
  * Hints are recorded with their tier; they are data, not shame.
  * Every mutation is appended to an audit log inside the state file.

Usage:
  state.py init                                     # create .bmox/state.json
  state.py status [--json]                          # human or machine summary
  state.py new-project NAME --language L --stages N # register project, focus it
  state.py focus NAME                               # switch current project
  state.py start-stage N [--title T]                # planned -> implementing
  state.py record-hint --tier {1,2,3}               # count a hint at cur stage
  state.py mark-green                               # implementing -> green
  state.py regress                                  # green -> implementing
  state.py record-explained                         # green -> explained
  state.py complete-stage [--force]                 # explained -> done, advance
  state.py add-pattern NAME                         # cross-project pattern seen
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

STATE_DIR = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()), ".bmox")
STATE_PATH = os.path.join(STATE_DIR, "state.json")

PHASES = ["planned", "implementing", "green", "explained", "done"]

TRANSITIONS = {
    "start-stage":      ("planned",      "implementing"),
    "mark-green":       ("implementing", "green"),
    "regress":          ("green",        "implementing"),
    "record-explained": ("green",        "explained"),
    "complete-stage":   ("explained",    "done"),
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg: str, code: int = 1):
    print(f"bmox-state: ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load() -> dict:
    if not os.path.exists(STATE_PATH):
        die(f"no state file at {STATE_PATH}. Run: state.py init")
    with open(STATE_PATH) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            die(f"state.json is corrupt ({e}). Restore from git — it should be committed.")


def save(state: dict):
    """Atomic write: temp file + rename, so a crash never corrupts state."""
    os.makedirs(STATE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, STATE_PATH)


def audit(state: dict, event: str, **details):
    state.setdefault("audit", []).append({"at": now(), "event": event, **details})


def current(state: dict):
    cur = state.get("current") or {}
    proj = cur.get("project")
    if not proj:
        die("no current project. Run: state.py new-project NAME ... or state.py focus NAME")
    if proj not in state["projects"]:
        die(f"current project '{proj}' missing from projects map (state corrupted?)")
    return proj, state["projects"][proj]


def cur_stage(project: dict) -> dict:
    n = project.get("current_stage")
    if n is None:
        die("no active stage. Run: state.py start-stage N")
    key = f"stage_{n}"
    if key not in project["stages"]:
        die(f"{key} not found")
    return project["stages"][key]


def require_phase(stage: dict, action: str):
    want_from, want_to = TRANSITIONS[action]
    have = stage["phase"]
    if have != want_from:
        die(
            f"illegal transition: '{action}' requires phase '{want_from}', "
            f"but stage {stage['number']} is in phase '{have}'. "
            f"Lifecycle: {' -> '.join(PHASES)}"
        )
    return want_to


# ---------------------------------------------------------------- commands

def cmd_init(_):
    if os.path.exists(STATE_PATH):
        die(f"{STATE_PATH} already exists")
    state = {
        "schema_version": 1,
        "created": now(),
        "current": {"project": None},
        "projects": {},
        "patterns_observed": [],
        "audit": [],
    }
    audit(state, "init")
    save(state)
    print(f"initialized {STATE_PATH}")


def cmd_new_project(args):
    state = load()
    name = args.name
    if name in state["projects"]:
        die(f"project '{name}' already exists (use: focus {name})")
    state["projects"][name] = {
        "language": args.language,
        "stages_total": args.stages,
        "created": now(),
        "current_stage": None,
        "stages": {},
    }
    state["current"]["project"] = name
    audit(state, "new_project", project=name, language=args.language, stages=args.stages)
    save(state)
    print(f"project '{name}' registered ({args.stages} stages, {args.language}); now in focus")


def cmd_focus(args):
    state = load()
    if args.name not in state["projects"]:
        die(f"unknown project '{args.name}'. Known: {', '.join(state['projects']) or '(none)'}")
    state["current"]["project"] = args.name
    audit(state, "focus", project=args.name)
    save(state)
    print(f"focused on '{args.name}'")


def cmd_start_stage(args):
    state = load()
    proj_name, proj = current(state)
    n = args.number
    if not (1 <= n <= proj["stages_total"]):
        die(f"stage {n} out of range 1..{proj['stages_total']}")
    # enforce order: previous stage must be done
    if n > 1:
        prev = proj["stages"].get(f"stage_{n-1}")
        if not prev or prev["phase"] != "done":
            die(f"stage {n-1} is not done yet — stages complete in order. "
                f"(This is the point: each stage motivates the next.)")
    key = f"stage_{n}"
    if key in proj["stages"] and proj["stages"][key]["phase"] != "planned":
        die(f"stage {n} already started (phase: {proj['stages'][key]['phase']})")
    proj["stages"][key] = {
        "number": n,
        "title": args.title or f"stage {n}",
        "phase": "implementing",
        "started": now(),
        "hints": {"tier1": 0, "tier2": 0, "tier3": 0},
        "explained_aloud": False,
        "gate_bypassed": False,
    }
    proj["current_stage"] = n
    audit(state, "start_stage", project=proj_name, stage=n, title=args.title)
    save(state)
    print(f"[{proj_name}] stage {n} '{proj['stages'][key]['title']}': planned -> implementing")


def cmd_record_hint(args):
    state = load()
    proj_name, proj = current(state)
    stage = cur_stage(proj)
    if stage["phase"] not in ("implementing",):
        die(f"hints are recorded only while implementing (phase: {stage['phase']})")
    stage["hints"][f"tier{args.tier}"] += 1
    audit(state, "hint", project=proj_name, stage=stage["number"], tier=args.tier)
    save(state)
    total = sum(stage["hints"].values())
    print(f"[{proj_name}] stage {stage['number']}: tier-{args.tier} hint recorded "
          f"(total this stage: {total}). Hints are data, not failure.")


def _simple_transition(action, extra_msg=""):
    def run(_args):
        state = load()
        proj_name, proj = current(state)
        stage = cur_stage(proj)
        new_phase = require_phase(stage, action)
        stage["phase"] = new_phase
        if action == "record-explained":
            stage["explained_aloud"] = True
        audit(state, action.replace("-", "_"), project=proj_name, stage=stage["number"])
        save(state)
        print(f"[{proj_name}] stage {stage['number']}: -> {new_phase}. {extra_msg}".rstrip())
    return run


cmd_mark_green = _simple_transition(
    "mark-green", "Do NOT advance: the explain-aloud gate comes next (/bmox:check handles it).")
cmd_regress = _simple_transition(
    "regress", "Back to implementing — tests must pass again before re-explaining.")
cmd_record_explained = _simple_transition(
    "record-explained", "Explanation recorded. complete-stage is now unlocked.")


def cmd_complete_stage(args):
    state = load()
    proj_name, proj = current(state)
    stage = cur_stage(proj)
    if stage["phase"] != "explained":
        if args.force and stage["phase"] == "green":
            stage["gate_bypassed"] = True
            audit(state, "gate_bypassed", project=proj_name, stage=stage["number"])
            print("WARNING: explain-aloud gate bypassed. Recorded permanently.", file=sys.stderr)
        else:
            die(f"complete-stage requires phase 'explained' (have '{stage['phase']}'). "
                f"Pass the explain-aloud gate via /bmox:check, or use --force to "
                f"bypass — the bypass is recorded forever.")
    stage["phase"] = "done"
    stage["completed"] = now()
    audit(state, "complete_stage", project=proj_name, stage=stage["number"])
    nxt = stage["number"] + 1
    if nxt <= proj["stages_total"]:
        proj["current_stage"] = None  # next start-stage sets it
        msg = f"next up: stage {nxt} (run /bmox:stage when ready)"
    else:
        proj["current_stage"] = None
        msg = "PROJECT COMPLETE. Consider a review pass, then /bmox:new for the next tech."
    save(state)
    print(f"[{proj_name}] stage {stage['number']} done. {msg}")


def cmd_add_pattern(args):
    state = load()
    if args.name not in state["patterns_observed"]:
        state["patterns_observed"].append(args.name)
        audit(state, "pattern", name=args.name)
        save(state)
    print(f"patterns observed: {', '.join(state['patterns_observed'])}")


def cmd_status(args):
    state = load()
    if args.json:
        print(json.dumps(state, indent=2))
        return
    cur = state["current"].get("project")
    print(f"current project: {cur or '(none)'}")
    for name, proj in state["projects"].items():
        done = sum(1 for s in proj["stages"].values() if s["phase"] == "done")
        marker = "*" if name == cur else " "
        print(f"{marker} {name} [{proj['language']}]: {done}/{proj['stages_total']} stages done")
        for key in sorted(proj["stages"], key=lambda k: proj["stages"][k]["number"]):
            s = proj["stages"][key]
            hints = sum(s["hints"].values())
            flags = []
            if s["explained_aloud"]:
                flags.append("explained")
            if s["gate_bypassed"]:
                flags.append("GATE BYPASSED")
            print(f"    stage {s['number']:>2} {s['title']:<30} {s['phase']:<12}"
                  f" hints={hints} {' '.join(flags)}")
    if state["patterns_observed"]:
        print(f"patterns: {', '.join(state['patterns_observed'])}")


def main():
    p = argparse.ArgumentParser(prog="state.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    sp = sub.add_parser("status")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("new-project")
    sp.add_argument("name")
    sp.add_argument("--language", required=True)
    sp.add_argument("--stages", type=int, required=True)
    sp.set_defaults(fn=cmd_new_project)

    sp = sub.add_parser("focus")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_focus)

    sp = sub.add_parser("start-stage")
    sp.add_argument("number", type=int)
    sp.add_argument("--title")
    sp.set_defaults(fn=cmd_start_stage)

    sp = sub.add_parser("record-hint")
    sp.add_argument("--tier", type=int, choices=[1, 2, 3], required=True)
    sp.set_defaults(fn=cmd_record_hint)

    sub.add_parser("mark-green").set_defaults(fn=cmd_mark_green)
    sub.add_parser("regress").set_defaults(fn=cmd_regress)
    sub.add_parser("record-explained").set_defaults(fn=cmd_record_explained)

    sp = sub.add_parser("complete-stage")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_complete_stage)

    sp = sub.add_parser("add-pattern")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_add_pattern)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
