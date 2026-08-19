#!/usr/bin/env python3
"""bmox state lifecycle manager.

Single source of truth for learning progress, stored in the LEARNER'S REPO at
.bmox/state.json (never in the plugin cache, which is wiped on plugin update).

The model must NEVER edit state.json by hand. All mutations go through this
script so that lifecycle rules are enforced by code, not by prompt discipline:
prompt discipline degrades over long sessions and model updates, argparse does
not.

Step lifecycle (strictly ordered):

    planned -> ready -> predicted -> observed -> explained -> done
                            ^            |
                            +-- regress -+   (tests broke after refactor)

Every mode -- build, probe, operate -- runs this one path. What each phase
means per mode is defined in references/modes.md.

Rules enforced here:
  * `predicted` is a hard precondition for reality. A step's commitment
    artifact must grow by MIN_COMMITMENT_GROWTH bytes before the phase
    advances, which is what stops probe and operate from degrading into
    reading the answer. In build the same ordering is enforced by physics.
  * You cannot reach `done` without passing through `explained`. Skipping
    requires --force, recorded permanently as "gate_bypassed".
  * Steps complete in order: each one motivates the next. A skipped step
    counts as closed.
  * Hints are recorded with their tier; they are data, not shame.
  * Every mutation is appended to an audit log inside the state file.

Usage:
  state.py init
  state.py status [--json]
  state.py new-project NAME --language L --goal G --steps N
  state.py focus NAME
  state.py open-step N --mode M --artifact PATH [--title T] [--concept C ...]
  state.py record-commitment
  state.py record-hint --tier {1,2,3}
  state.py mark-observed [--evidence E]
  state.py regress
  state.py record-reconciled
  state.py complete-step [--force]
  state.py skip-step N --reason R
  state.py replan --steps N [--goal G]
  state.py record-evidence --concept C --outcome {reconciled,partial,none} --note N [--source {step,calibration}]
  state.py record-gap --concept C --note N
  state.py resolve-gap --concept C --gap ID
  state.py profile show
  state.py profile alias CONCEPT ALIAS
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# knowledge.py lives beside this file, and a script's own directory is
# sys.path[0] when run directly -- which is how every skill invokes it.
import knowledge


def project_root() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def bmox_dir() -> str:
    return os.path.join(project_root(), ".bmox")


def state_path() -> str:
    return os.path.join(bmox_dir(), "state.json")


def resolve_artifact(path: str) -> str:
    """Learner-supplied paths are relative to their repo root, not to cwd."""
    return path if os.path.isabs(path) else os.path.join(project_root(), path)


SCHEMA_VERSION = 2
MIN_COMMITMENT_GROWTH = 400

PHASES = ["planned", "ready", "predicted", "observed", "explained", "done"]
MODES = ["build", "probe", "operate"]

# references/modes.md pins one artifact per mode. Enforced here because the
# commitment gate has exactly one input: a step aimed at any other file weighs
# growth that no prediction went into, and the gate is the whole method.
ARTIFACT_SHAPE = {
    "build": "a path ending in DESIGN.md",
    "probe": "a path with a TRACES/ component, e.g. <project>/TRACES/NN-<slug>.md",
    "operate": "a path with a RUNBOOK/ component, e.g. <project>/RUNBOOK/NN-<slug>.md",
}

TRANSITIONS = {
    "open-step":         ("planned",   "ready"),
    "record-commitment": ("ready",     "predicted"),
    "mark-observed":     ("predicted", "observed"),
    "regress":           ("observed",  "predicted"),
    "record-reconciled": ("observed",  "explained"),
    "complete-step":     ("explained", "done"),
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg: str, code: int = 1):
    print(f"bmox-state: ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load() -> dict:
    path = state_path()
    if not os.path.exists(path):
        die(f"no state file at {path}. Run: state.py init")
    with open(path) as f:
        try:
            state = json.load(f)
        except json.JSONDecodeError as e:
            die(f"state.json is corrupt ({e}). Restore from git — it should be committed.")
    found = state.get("schema_version")
    if found != SCHEMA_VERSION:
        have = f"schema v{found}" if found is not None else "unversioned"
        die(f"state.json is {have}, but this bmox needs schema v{SCHEMA_VERSION}. "
            f"There is no upgrade path: archive {path} and run state.py init, then "
            f"re-register your projects. Finished work stays in your repo and its git "
            f"history — only the progress record restarts.")
    return state


def load_profile() -> dict:
    """knowledge.load() raises ValueError on a corrupt profile.json; state.py's
    own load() dies cleanly on the same failure for state.json, so the profile
    gets the same CLI-failure treatment rather than a raw traceback."""
    try:
        return knowledge.load()
    except ValueError as e:
        die(str(e))


def save(state: dict):
    """Atomic write: temp file + rename, so a crash never corrupts state."""
    directory = bmox_dir()
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, state_path())


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


def cur_step(project: dict) -> dict:
    n = project.get("current_step")
    if n is None:
        die("no active step. Run: state.py open-step N")
    key = f"step_{n}"
    if key not in project["steps"]:
        die(f"{key} not found")
    return project["steps"][key]


def check_artifact(mode: str, artifact: str):
    parts = artifact.replace("\\", "/").split("/")
    if mode == "build":
        ok = parts[-1] == "DESIGN.md"
    else:
        ok = ("TRACES" if mode == "probe" else "RUNBOOK") in parts[:-1]
    if not ok:
        die(f"a {mode} step commits into {ARTIFACT_SHAPE[mode]}, but --artifact "
            f"is '{artifact}'. The commitment gate weighs that one file and "
            f"nothing else.")


def require_phase(step: dict, action: str) -> str:
    want_from, want_to = TRANSITIONS[action]
    have = step["phase"]
    if have != want_from:
        die(
            f"illegal transition: '{action}' requires phase '{want_from}', "
            f"but step {step['number']} is in phase '{have}'. "
            f"Lifecycle: {' -> '.join(PHASES)}"
        )
    return want_to


# ---------------------------------------------------------------- commands

def cmd_init(_):
    if os.path.exists(state_path()):
        die(f"{state_path()} already exists")
    state = {
        "schema_version": SCHEMA_VERSION,
        "created": now(),
        "current": {"project": None},
        "projects": {},
        "audit": [],
    }
    audit(state, "init")
    save(state)
    print(f"initialized {state_path()}")


def cmd_new_project(args):
    state = load()
    name = args.name
    if name in state["projects"]:
        die(f"project '{name}' already exists (use: focus {name})")
    state["projects"][name] = {
        "language": args.language,
        "goal": args.goal,
        "steps_total": args.steps,
        "created": now(),
        "current_step": None,
        "steps": {},
    }
    state["current"]["project"] = name
    audit(state, "new_project", project=name, language=args.language,
          goal=args.goal, steps=args.steps)
    save(state)
    print(f"project '{name}' registered ({args.steps} steps, {args.language}); now in focus")
    print(f"goal: {args.goal}")


def cmd_focus(args):
    state = load()
    if args.name not in state["projects"]:
        die(f"unknown project '{args.name}'. Known: {', '.join(state['projects']) or '(none)'}")
    state["current"]["project"] = args.name
    audit(state, "focus", project=args.name)
    save(state)
    print(f"focused on '{args.name}'")


def cmd_open_step(args):
    state = load()
    proj_name, proj = current(state)
    n = args.number
    if not (1 <= n <= proj["steps_total"]):
        die(f"step {n} out of range 1..{proj['steps_total']}")
    if n > 1:
        prev = proj["steps"].get(f"step_{n-1}")
        if not prev or prev["phase"] != "done":
            die(f"step {n-1} is not done yet — steps complete in order. "
                f"(This is the point: each step motivates the next.)")
    key = f"step_{n}"
    if key in proj["steps"] and proj["steps"][key]["phase"] != "planned":
        die(f"step {n} already opened (phase: {proj['steps'][key]['phase']})")

    artifact = args.artifact
    check_artifact(args.mode, artifact)
    resolved = resolve_artifact(artifact)
    baseline = os.path.getsize(resolved) if os.path.exists(resolved) else 0

    proj["steps"][key] = {
        "number": n,
        "title": args.title or f"step {n}",
        "mode": args.mode,
        "phase": "ready",
        "started": now(),
        # Baselined at open time, not at record-commitment time: DESIGN.md is
        # one append-only file across every build step, so an absolute size
        # check would pass trivially forever after step 1.
        "commitment": {"artifact": artifact, "baseline_bytes": baseline},
        "concepts": list(args.concept or []),
        "hints": {"tier1": 0, "tier2": 0, "tier3": 0},
        "reconciled": False,
        "gate_bypassed": False,
        "skipped": False,
        "skip_reason": None,
    }
    proj["current_step"] = n
    audit(state, "open_step", project=proj_name, step=n, mode=args.mode,
          title=args.title, artifact=artifact)
    save(state)
    print(f"[{proj_name}] step {n} '{proj['steps'][key]['title']}' [{args.mode}]: "
          f"planned -> ready")
    print(f"write your prediction into {artifact}, then: state.py record-commitment")


def cmd_record_commitment(_args):
    state = load()
    proj_name, proj = current(state)
    step = cur_step(proj)
    new_phase = require_phase(step, "record-commitment")

    c = step["commitment"]
    path = resolve_artifact(c["artifact"])
    if not os.path.exists(path):
        die(f"commitment artifact {c['artifact']} does not exist. "
            f"Write your prediction there first — reality stays locked until it is on record.")
    grown = os.path.getsize(path) - c["baseline_bytes"]
    if grown < MIN_COMMITMENT_GROWTH:
        die(f"{c['artifact']} has grown {grown} bytes since this step opened; "
            f"{MIN_COMMITMENT_GROWTH} are required. Predicting before looking is "
            f"the entire method — a guess you never wrote down cannot be wrong, "
            f"and being wrong on the record is what makes the reading stick.")

    c["recorded"] = now()
    c["growth_bytes"] = grown
    step["phase"] = new_phase
    audit(state, "record_commitment", project=proj_name, step=step["number"],
          artifact=c["artifact"], growth_bytes=grown)
    save(state)
    print(f"[{proj_name}] step {step['number']}: ready -> predicted "
          f"({grown} bytes committed). Reality is unlocked.")


def cmd_record_hint(args):
    state = load()
    proj_name, proj = current(state)
    step = cur_step(proj)
    if step["phase"] not in ("predicted", "observed"):
        die(f"hints are recorded between committing a prediction and reconciling it "
            f"(phase: {step['phase']})")
    step["hints"][f"tier{args.tier}"] += 1
    audit(state, "hint", project=proj_name, step=step["number"], tier=args.tier)
    save(state)
    total = sum(step["hints"].values())
    print(f"[{proj_name}] step {step['number']}: tier-{args.tier} hint recorded "
          f"(total this step: {total}). Hints are data, not failure.")


def _simple_transition(action, extra_msg=""):
    def run(args):
        state = load()
        proj_name, proj = current(state)
        step = cur_step(proj)
        new_phase = require_phase(step, action)
        step["phase"] = new_phase
        if action == "record-reconciled":
            step["reconciled"] = True
        details = {}
        if action == "mark-observed" and getattr(args, "evidence", None):
            details["evidence"] = args.evidence
        audit(state, action.replace("-", "_"), project=proj_name,
              step=step["number"], **details)
        save(state)
        print(f"[{proj_name}] step {step['number']}: -> {new_phase}. {extra_msg}".rstrip())
    return run


cmd_mark_observed = _simple_transition(
    "mark-observed", "Do NOT advance: reconciling prediction against reality comes next.")
cmd_regress = _simple_transition(
    "regress", "Back to predicted — reality must be re-observed before reconciling.")
cmd_record_reconciled = _simple_transition(
    "record-reconciled", "Reconciliation recorded. complete-step is now unlocked.")


def cmd_complete_step(args):
    state = load()
    proj_name, proj = current(state)
    step = cur_step(proj)
    if step["phase"] != "explained":
        if args.force and step["phase"] == "observed":
            step["gate_bypassed"] = True
            audit(state, "gate_bypassed", project=proj_name, step=step["number"])
            print("WARNING: reconciliation gate bypassed. Recorded permanently.", file=sys.stderr)
        else:
            die(f"complete-step requires phase 'explained' (have '{step['phase']}'). "
                f"Reconcile prediction against reality first, or use --force to "
                f"bypass — the bypass is recorded forever.")
    step["phase"] = "done"
    step["completed"] = now()
    audit(state, "complete_step", project=proj_name, step=step["number"])
    nxt = step["number"] + 1
    proj["current_step"] = None
    if nxt <= proj["steps_total"]:
        msg = f"next up: step {nxt}"
    else:
        msg = "PROJECT COMPLETE. Consider a review pass, then /bmox:plan for the next tech."
    save(state)
    print(f"[{proj_name}] step {step['number']} done. {msg}")


def cmd_skip_step(args):
    state = load()
    proj_name, proj = current(state)
    n = args.number
    if not (1 <= n <= proj["steps_total"]):
        die(f"step {n} out of range 1..{proj['steps_total']}")
    if n > 1:
        prev = proj["steps"].get(f"step_{n-1}")
        if not prev or prev["phase"] != "done":
            die(f"step {n-1} is not done yet — steps close in order.")
    key = f"step_{n}"
    existing = proj["steps"].get(key)
    if existing and existing["phase"] not in ("planned", "ready"):
        die(f"step {n} is in phase '{existing['phase']}'. A step can only be "
            f"skipped before its commitment is recorded.")
    proj["steps"][key] = {
        "number": n,
        "title": (existing or {}).get("title") or f"step {n}",
        "mode": (existing or {}).get("mode"),
        "phase": "done",
        "started": (existing or {}).get("started") or now(),
        "completed": now(),
        "commitment": (existing or {}).get("commitment")
                      or {"artifact": None, "baseline_bytes": 0},
        "concepts": (existing or {}).get("concepts") or [],
        "hints": (existing or {}).get("hints") or {"tier1": 0, "tier2": 0, "tier3": 0},
        "reconciled": False,
        "gate_bypassed": False,
        "skipped": True,
        "skip_reason": args.reason,
    }
    if proj.get("current_step") == n:
        proj["current_step"] = None
    audit(state, "skip_step", project=proj_name, step=n, reason=args.reason)
    save(state)
    print(f"[{proj_name}] step {n} skipped: {args.reason}")
    print("Recorded and shown in status. Skipping is a choice, not a failure.")


def cmd_replan(args):
    state = load()
    proj_name, proj = current(state)
    if proj.get("current_step") is not None:
        die(f"step {proj['current_step']} is in flight. Finish, skip, or let it "
            f"close before replanning — a roadmap cannot be re-derived around a "
            f"step whose outcome is not yet known.")
    closed = sum(1 for s in proj["steps"].values() if s["phase"] == "done")
    if args.steps < closed:
        die(f"{closed} steps are already closed; --steps cannot be below that. "
            f"Closed steps are immutable.")
    was = proj["steps_total"]
    proj["steps_total"] = args.steps
    if args.goal:
        proj["goal"] = args.goal
    audit(state, "replan", project=proj_name, steps_from=was, steps_to=args.steps)
    save(state)
    print(f"[{proj_name}] roadmap replanned: {was} -> {args.steps} steps "
          f"({closed} closed and preserved)")


def _step_context(state):
    """Tag evidence with the step that produced it, when one is open."""
    proj_name = state.get("current", {}).get("project")
    if not proj_name:
        return None, None, None, None
    proj = state["projects"][proj_name]
    n = proj.get("current_step")
    if n is None:
        return proj_name, None, None, None
    step = proj["steps"][f"step_{n}"]
    return proj_name, n, step.get("mode"), step.get("hints")


def cmd_record_evidence(args):
    state = load()
    proj_name, step_n, mode, hints = _step_context(state)
    if args.source == "step" and step_n is None:
        die("no open step to attribute this evidence to. "
            "Use --source calibration for pre-roadmap answers.")
    profile = load_profile()
    try:
        key = knowledge.add_evidence(
            profile, args.concept, args.outcome, args.note,
            source=args.source, project=proj_name,
            step=step_n if args.source == "step" else None,
            mode=mode if args.source == "step" else None,
            hints=hints if args.source == "step" else None,
        )
    except ValueError as e:
        die(str(e))
    knowledge.save(profile)
    print(f"evidence recorded: {key} = {args.outcome}")


def cmd_record_gap(args):
    state = load()
    proj_name, step_n, _, _ = _step_context(state)
    profile = load_profile()
    gap_id = knowledge.add_gap(profile, args.concept, args.note,
                               project=proj_name, step=step_n)
    knowledge.save(profile)
    print(f"gap {gap_id} recorded on '{args.concept}'. "
          f"Being wrong on the record is what the next plan aims at.")


def cmd_resolve_gap(args):
    state = load()
    proj_name, step_n, _, _ = _step_context(state)
    if step_n is None:
        die("no open step to credit this resolution to. resolve-gap runs while "
            "the step that closed the gap is still open — before complete-step, "
            "which clears it.")
    profile = load_profile()
    try:
        knowledge.resolve_gap(profile, args.concept, args.gap, f"{proj_name}/{step_n}")
    except ValueError as e:
        die(str(e))
    knowledge.save(profile)
    print(f"gap {args.gap} on '{args.concept}' resolved by {proj_name}/{step_n}")


def cmd_profile(args):
    profile = load_profile()
    if args.action == "alias":
        if not args.concept or not args.alias:
            die("profile alias requires both a concept and an alias. "
                "Usage: state.py profile alias CONCEPT ALIAS")
        knowledge.add_alias(profile, args.concept, args.alias)
        knowledge.save(profile)
        print(f"'{args.alias}' now resolves to '{knowledge.normalize(args.concept)}'")
        return
    concepts = profile.get("concepts", {})
    if not concepts:
        print("profile is empty — /bmox:plan builds it as you go")
        return
    for key, c in sorted(concepts.items()):
        gaps = [g for g in c["open_gaps"] if g["resolved_by"] is None]
        modes = sorted({e["mode"] for e in c["evidence"] if e.get("mode")})
        print(f"{key:<28} evidence={len(c['evidence'])} "
              f"modes={','.join(modes) or '-'} open_gaps={len(gaps)}")
        for g in gaps:
            print(f"    gap {g['id']}: {g['note']}")


def cmd_status(args):
    state = load()
    profile = load_profile()
    if args.json:
        print(json.dumps({"state": state, "profile": profile}, indent=2))
        return
    cur = state["current"].get("project")
    print(f"current project: {cur or '(none)'}")
    for name, proj in state["projects"].items():
        done = sum(1 for s in proj["steps"].values() if s["phase"] == "done")
        marker = "*" if name == cur else " "
        print(f"{marker} {name} [{proj['language']}]: {done}/{proj['steps_total']} steps done")
        print(f"    goal: {proj['goal']}")
        for key in sorted(proj["steps"], key=lambda k: proj["steps"][k]["number"]):
            s = proj["steps"][key]
            hints = sum(s["hints"].values())
            flags = []
            if s["reconciled"]:
                flags.append("reconciled")
            if s["gate_bypassed"]:
                flags.append("GATE BYPASSED")
            if s["skipped"]:
                flags.append(f"SKIPPED: {s['skip_reason']}")
            print(f"    step {s['number']:>2} {s['title']:<26} "
                  f"{(s['mode'] or '-'):<8} {s['phase']:<10} hints={hints} "
                  f"{' '.join(flags)}")
    concepts = profile.get("concepts", {})
    if concepts:
        total_gaps = sum(
            len([g for g in c["open_gaps"] if g["resolved_by"] is None])
            for c in concepts.values()
        )
        print(f"profile: {len(concepts)} concepts, {total_gaps} open gaps "
              f"(state.py profile show)")


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
    sp.add_argument("--goal", required=True)
    sp.add_argument("--steps", type=int, required=True)
    sp.set_defaults(fn=cmd_new_project)

    sp = sub.add_parser("focus")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_focus)

    sp = sub.add_parser("open-step")
    sp.add_argument("number", type=int)
    sp.add_argument("--mode", choices=MODES, required=True)
    sp.add_argument("--artifact", required=True)
    sp.add_argument("--title")
    sp.add_argument("--concept", action="append")
    sp.set_defaults(fn=cmd_open_step)

    sp = sub.add_parser("record-hint")
    sp.add_argument("--tier", type=int, choices=[1, 2, 3], required=True)
    sp.set_defaults(fn=cmd_record_hint)

    sub.add_parser("record-commitment").set_defaults(fn=cmd_record_commitment)

    sp = sub.add_parser("mark-observed")
    sp.add_argument("--evidence")
    sp.set_defaults(fn=cmd_mark_observed)

    sub.add_parser("regress").set_defaults(fn=cmd_regress)
    sub.add_parser("record-reconciled").set_defaults(fn=cmd_record_reconciled)

    sp = sub.add_parser("complete-step")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_complete_step)

    sp = sub.add_parser("skip-step")
    sp.add_argument("number", type=int)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(fn=cmd_skip_step)

    sp = sub.add_parser("replan")
    sp.add_argument("--steps", type=int, required=True)
    sp.add_argument("--goal")
    sp.set_defaults(fn=cmd_replan)

    sp = sub.add_parser("record-evidence")
    sp.add_argument("--concept", required=True)
    sp.add_argument("--outcome", choices=knowledge.OUTCOMES, required=True)
    sp.add_argument("--note", required=True)
    sp.add_argument("--source", choices=["step", "calibration"], default="step")
    sp.set_defaults(fn=cmd_record_evidence)

    sp = sub.add_parser("record-gap")
    sp.add_argument("--concept", required=True)
    sp.add_argument("--note", required=True)
    sp.set_defaults(fn=cmd_record_gap)

    sp = sub.add_parser("resolve-gap")
    sp.add_argument("--concept", required=True)
    sp.add_argument("--gap", required=True)
    sp.set_defaults(fn=cmd_resolve_gap)

    sp = sub.add_parser("profile")
    sp.add_argument("action", choices=["show", "alias"])
    sp.add_argument("concept", nargs="?")
    sp.add_argument("alias", nargs="?")
    sp.set_defaults(fn=cmd_profile)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
