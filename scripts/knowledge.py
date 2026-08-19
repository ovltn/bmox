#!/usr/bin/env python3
"""bmox knowledge profile.

Stores what the learner has demonstrated, indexed by concept rather than by
project, so a second project can build on the first. Lives beside state.json
in the learner's repo and is committed with it.

Evidence, not scores: a numeric confidence would rot silently and could not be
argued with, whereas evidence can be re-read. Confidence is derived at planning
time by /bmox:plan, never stored here.

Concept keys are normalized names. Matching is exact on the normalized form,
through keys and then aliases — deliberately not fuzzy, because a wrong merge
is silent and permanent while a duplicate concept is visible and repairable
with `state.py profile alias`.
"""
import json
import os
import tempfile
from datetime import datetime, timezone

OUTCOMES = ["reconciled", "partial", "none"]
VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bmox_dir() -> str:
    return os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()), ".bmox")


def profile_path() -> str:
    return os.path.join(bmox_dir(), "profile.json")


def load() -> dict:
    """The profile is documented as hand-repairable, so a typo has to come back
    as a sentence the learner can act on rather than as a traceback from
    whichever accessor happened to touch the damage first."""
    path = profile_path()
    if not os.path.exists(path):
        return {"version": VERSION, "created": now(), "concepts": {}}
    with open(path) as f:
        try:
            profile = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"profile.json is corrupt ({e}). Restore from git — it should be committed.") from e
    if not isinstance(profile, dict):
        raise ValueError("profile.json is corrupt (its top level is not an object). "
                         "Restore from git — it should be committed.")
    found = profile.get("version")
    if found != VERSION:
        raise ValueError(f"profile.json is corrupt (version {found!r}, expected {VERSION}). "
                         f"Restore from git — it should be committed.")
    return profile


def save(profile: dict) -> None:
    """Atomic write: temp file + rename, so a crash never truncates the file."""
    d = bmox_dir()
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(profile, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, profile_path())


def normalize(name: str) -> str:
    return "-".join(name.strip().lower().replace("_", " ").replace("-", " ").split())


def resolve(profile: dict, name: str) -> tuple[str, bool]:
    """Return (concept_key, created). Matches keys first, then aliases."""
    norm = normalize(name)
    concepts = profile.setdefault("concepts", {})
    if norm in concepts:
        return norm, False
    for key, concept in concepts.items():
        if norm in [normalize(a) for a in concept.get("aliases", [])]:
            return key, False
    concepts[norm] = {"aliases": [], "evidence": [], "open_gaps": []}
    return norm, True


def add_evidence(profile, concept, outcome, note, source="step",
                 project=None, step=None, mode=None, hints=None) -> str:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    key, _ = resolve(profile, concept)
    profile["concepts"][key]["evidence"].append({
        "project": project,
        "step": step,
        "mode": mode,
        "source": source,
        "outcome": outcome,
        "date": now(),
        "hints": hints or {"tier1": 0, "tier2": 0, "tier3": 0},
        "note": note,
    })
    return key


def add_gap(profile, concept, note, project=None, step=None) -> str:
    key, _ = resolve(profile, concept)
    gaps = profile["concepts"][key]["open_gaps"]
    gap_id = f"g{len(gaps) + 1}"
    gaps.append({
        "id": gap_id,
        "project": project,
        "step": step,
        "date": now(),
        "note": note,
        "resolved_by": None,
    })
    return gap_id


def resolve_gap(profile, concept, gap_id, by) -> None:
    """Mark a gap closed. Entries are never deleted: the record of having been
    wrong is the most useful thing in the profile."""
    key, _ = resolve(profile, concept)
    for gap in profile["concepts"][key]["open_gaps"]:
        if gap["id"] == gap_id:
            gap["resolved_by"] = by
            return
    raise ValueError(f"no gap {gap_id!r} on concept {key!r}")


def open_gaps(profile, concept) -> list:
    key, _ = resolve(profile, concept)
    return [g for g in profile["concepts"][key]["open_gaps"] if g["resolved_by"] is None]


def add_alias(profile, concept, alias) -> None:
    key, _ = resolve(profile, concept)
    aliases = profile["concepts"][key]["aliases"]
    if normalize(alias) not in [normalize(a) for a in aliases]:
        aliases.append(alias)
