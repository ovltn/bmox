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
with `state.py profile alias`. A name reaches at most one concept: a second
claimant is refused by name rather than resolved by iteration order, since a
name that answers to two concepts is that same silent wrong merge arriving one
lookup at a time.
"""
import contextlib
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

OUTCOMES = ["reconciled", "partial", "none"]
VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bmox_dir() -> str:
    return os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()), ".bmox")


def profile_path() -> str:
    return os.path.join(bmox_dir(), "profile.json")


def lock_path() -> str:
    """A lock file of the profile's own, never state.json's. Commands that write
    both files take the state lock first, so the one order that can deadlock is
    profile-then-state; nothing here ever reaches for the state lock."""
    return os.path.join(bmox_dir(), ".profile.lock")


_held = None


def _hold_lock() -> None:
    """One exclusive lock spans load -> mutate -> save, and is kept for the rest
    of the process rather than dropped at save: every profile command is a
    read-modify-write, so two runs that merely take turns at the file still lose
    the earlier one's entry. It is exclusive even for a pure read because a
    reader cannot know whether its caller will go on to write, and upgrading a
    shared lock mid-flight would let a writer in between.

    The path is re-checked because it is resolved per call: the lock has to be
    the one guarding the file that is about to be written.
    """
    global _held
    path = lock_path()
    if _held is not None:
        if _held[0] == path:
            return
        _drop_lock()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            os.close(fd)
            raise
    except OSError as e:
        raise ValueError(f"cannot lock the profile at {path} ({e}). Check that "
                         f"{os.path.dirname(path)} is a writable directory.") from e
    _held = (path, fd)


def _drop_lock() -> None:
    global _held
    if _held is None:
        return
    _, fd = _held
    _held = None
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _corrupt(detail: str) -> ValueError:
    return ValueError(f"profile.json is corrupt ({detail}). "
                      f"Restore from git — it should be committed.")


def _unusable(detail: str) -> ValueError:
    return ValueError(f"profile.json at {profile_path()} cannot be used ({detail}). "
                      f"Check that the path is a readable, writable file.")


def _check_shape(profile: dict) -> None:
    """Left unchecked, a concepts map of the wrong type reads as an empty
    profile — telling the learner their whole history is gone when it is only
    mis-shaped, and a confident wrong answer about what has been learned is the
    worst thing this file can produce. Every accessor below trusts these three
    lists to exist, so the shape is checked once on the way in, where the refusal
    can name the damaged concept instead of surfacing as a KeyError from
    whichever accessor happened to touch it first."""
    concepts = profile.setdefault("concepts", {})
    if not isinstance(concepts, dict):
        raise _corrupt(f"'concepts' is a {type(concepts).__name__}, not an object")
    for key, concept in concepts.items():
        where = f"concept {key!r}"
        if not isinstance(concept, dict):
            raise _corrupt(f"{where} is a {type(concept).__name__}, not an object")
        for field in ("aliases", "evidence", "open_gaps"):
            if field not in concept:
                raise _corrupt(f"{where} has no {field!r}")
            if not isinstance(concept[field], list):
                raise _corrupt(f"{where} has a {field!r} that is a "
                               f"{type(concept[field]).__name__}, not a list")
        for alias in concept["aliases"]:
            if not isinstance(alias, str):
                raise _corrupt(f"{where} has an alias {alias!r} that is not a name")
        for entry in concept["evidence"]:
            if not isinstance(entry, dict):
                raise _corrupt(f"{where} has an evidence entry that is not an object")
            if entry.get("outcome") not in OUTCOMES:
                raise _corrupt(f"{where} has evidence with outcome "
                               f"{entry.get('outcome')!r}, expected one of {OUTCOMES}")
        for gap in concept["open_gaps"]:
            if not isinstance(gap, dict):
                raise _corrupt(f"{where} has a gap that is not an object")
            if not isinstance(gap.get("id"), str):
                raise _corrupt(f"{where} has a gap whose 'id' is not a string")
            if not isinstance(gap.get("note"), str):
                raise _corrupt(f"{where} has gap {gap['id']!r} whose 'note' is not a string")
            if "resolved_by" not in gap:
                raise _corrupt(f"{where} has gap {gap['id']!r} with no 'resolved_by'")


def load() -> dict:
    """The profile is documented as hand-repairable, so a typo has to come back
    as a sentence the learner can act on rather than as a traceback from
    whichever accessor happened to touch the damage first. Unreadable is the same
    class of accident as mis-typed — a directory or a chmod 000 file is a
    sentence too."""
    try:
        if os.path.isdir(bmox_dir()):
            _hold_lock()
        # A read must not conjure .bmox/ just to hold a lock inside it, and until
        # state.py init has made that directory there is no profile to race over.
        with open(profile_path()) as f:
            raw = f.read()
    except FileNotFoundError:
        return {"version": VERSION, "created": now(), "concepts": {}}
    except OSError as e:
        raise _unusable(str(e)) from e
    try:
        profile = json.loads(raw)
    except json.JSONDecodeError as e:
        raise _corrupt(str(e)) from e
    if not isinstance(profile, dict):
        raise _corrupt("its top level is not an object")
    found = profile.get("version")
    if found != VERSION:
        raise _corrupt(f"version {found!r}, expected {VERSION}")
    _check_shape(profile)
    return profile


def save(profile: dict) -> None:
    """Atomic write: temp file + rename, so a crash never truncates the file.

    Neither fsync is redundant. Without the file fsync a power loss can land the
    rename while the bytes it points at are still in cache, which loses the
    evidence the learner just earned behind a file that parses — worse than the
    crash it was meant to survive. Without the directory fsync the rename itself
    is what goes missing. The unlink runs on every exit path, because an
    interrupted save otherwise leaves .tmp files in a directory the learner
    commits."""
    d = bmox_dir()
    try:
        os.makedirs(d, exist_ok=True)
        _hold_lock()
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(profile, f, indent=2, sort_keys=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, profile_path())
            dir_fd = os.open(d, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
    except OSError as e:
        raise _unusable(str(e)) from e


def normalize(name: str) -> str:
    return "-".join(name.strip().lower().replace("_", " ").replace("-", " ").split())


def _claimants(profile: dict, name: str) -> list[str]:
    """Every concept key that answers to name, as its key or through an alias,
    sorted — so a profile that already holds a name twice reports the same pair
    on every run instead of whichever one iteration order reached first."""
    norm = normalize(name)
    concepts = profile.get("concepts") or {}
    found = {key for key, concept in concepts.items()
             if norm in [normalize(a) for a in concept.get("aliases", [])]}
    if norm in concepts:
        found.add(norm)
    return sorted(found)


def lookup(profile: dict, name: str) -> Optional[str]:
    """The concept this name reaches, or None if the profile has never seen it.
    Separate from resolve() because "does this name already exist, and where"
    cannot be asked of a function that answers by creating the concept."""
    claimants = _claimants(profile, name)
    if len(claimants) > 1:
        named = ", ".join(repr(c) for c in claimants)
        raise ValueError(
            f"{name!r} reaches {len(claimants)} concepts ({named}), so there is no one "
            f"concept to record against. Join them into one: "
            f"state.py profile alias {claimants[0]} {claimants[1]}")
    return claimants[0] if claimants else None


def resolve(profile: dict, name: str) -> tuple[str, bool]:
    """Return (concept_key, created). Matches keys first, then aliases."""
    concepts = profile.setdefault("concepts", {})
    key = lookup(profile, name)
    if key is not None:
        return key, False
    norm = normalize(name)
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


def _next_gap_number(gaps: list) -> int:
    """Gap ids have to stay unique within a concept: resolve_gap and `profile
    show` both address a gap by its id alone, and absorbing a duplicate concept
    brings in ids that were numbered from g1 there too."""
    used = [int(g["id"].removeprefix("g")) for g in gaps if g["id"].removeprefix("g").isdigit()]
    return max(used, default=0) + 1


def _same_note(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def add_gap(profile, concept, note, project=None, step=None) -> str:
    """Record a gap, returning its id. The same note already open on the same
    concept returns that gap instead of a second one: /bmox:plan reads the open
    count as a signal for what to aim the next step at, and one wrongness typed
    twice would double the signal while recording nothing the open gap does not
    already say. Nothing is dropped, because there was nothing new to keep.

    Only open gaps match. The same note after a resolution is the learner being
    wrong about it again, which is the most informative entry in the file."""
    key, _ = resolve(profile, concept)
    gaps = profile["concepts"][key]["open_gaps"]
    for gap in gaps:
        if gap["resolved_by"] is None and _same_note(gap["note"], note):
            return gap["id"]
    gap_id = f"g{_next_gap_number(gaps)}"
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
    wrong is the most useful thing in the profile — which is also why a gap is
    only closed once. Re-stamping resolved_by would overwrite the step that
    actually closed it, and a second attempt on the same id usually means the
    id is not the one the learner meant."""
    key = lookup(profile, concept)
    if key is None:
        raise ValueError(f"no concept {normalize(concept)!r} in the profile, so it has "
                         f"no gap {gap_id!r}")
    for gap in profile["concepts"][key]["open_gaps"]:
        if gap["id"] == gap_id:
            if gap["resolved_by"] is not None:
                raise ValueError(f"gap {gap_id!r} on {key!r} is already resolved by "
                                 f"{gap['resolved_by']!r}, and that credit stands. If a "
                                 f"different gap is still open, `state.py profile show` "
                                 f"lists the open ids.")
            gap["resolved_by"] = by
            return
    raise ValueError(f"no gap {gap_id!r} on concept {key!r}")


def open_gaps(profile, concept) -> list:
    """A read never creates: asking what is open about a concept nobody has
    recorded must not put that concept in the file."""
    key = lookup(profile, concept)
    if key is None:
        return []
    return [g for g in profile["concepts"][key]["open_gaps"] if g["resolved_by"] is None]


def _absorb(target: dict, duplicate: dict) -> None:
    """Fold a duplicate concept's records into target. Nothing is dropped: the
    record of having been wrong is the most useful thing in the profile."""
    target["evidence"] = sorted(target["evidence"] + duplicate["evidence"],
                                key=lambda e: e.get("date") or "")
    gaps = target["open_gaps"]
    number = _next_gap_number(gaps)
    for gap in duplicate["open_gaps"]:
        # The incoming ids are the ones renumbered, never the target's, so an id
        # the learner has already read out of `profile show` keeps pointing at
        # the same gap.
        gap["id"] = f"g{number}"
        number += 1
        gaps.append(gap)


def add_alias(profile, concept, alias) -> str:
    """Make alias resolve to concept, returning the surviving concept key.

    An alias whose normalized form is already a concept key of its own would be
    unreachable, since resolve() matches keys before aliases. That case is the
    whole reason this command exists — one concept typed two ways, each having
    collected its own evidence — so the duplicate is absorbed into the target
    and its key deleted.

    A name some third concept already answers to is refused instead. The
    duplicate-key case says which two concepts the learner means to join,
    because the alias is that concept's name; a nickname hanging off a third
    concept says nothing about whether that concept is the same one, and folding
    it in on a guess is the silent, permanent wrong merge this module is built to
    avoid."""
    key, _ = resolve(profile, concept)
    incoming = normalize(alias)
    if incoming == key:
        raise ValueError(f"{alias!r} already is the concept {key!r}, so aliasing it changes "
                         f"nothing. profile alias joins two concepts that should be one: "
                         f"pass the duplicate's name as the alias.")
    concepts = profile["concepts"]
    target = concepts[key]
    aliases = target["aliases"]
    strays = [k for k in _claimants(profile, alias) if k not in (key, incoming)]
    if strays:
        named = ", ".join(repr(k) for k in strays)
        raise ValueError(
            f"{alias!r} is already a name for {named}, so making it an alias of {key!r} "
            f"would leave one name reaching two concepts. Nothing has changed. If "
            f"{strays[0]!r} and {key!r} are one concept, join them by name: "
            f"state.py profile alias {key} {strays[0]}")
    if incoming in concepts:
        duplicate = concepts[incoming]
        # Checked before anything moves, so a refusal leaves the file exactly as
        # it was rather than half-joined.
        for name in duplicate["aliases"]:
            conflict = [k for k in _claimants(profile, name) if k not in (key, incoming)]
            if conflict:
                raise ValueError(
                    f"joining {incoming!r} into {key!r} would carry its alias {name!r} "
                    f"across, and {conflict[0]!r} already answers to that name. Nothing "
                    f"has changed. Join {conflict[0]!r} into {key!r} first, or drop that "
                    f"alias from {incoming!r} by hand.")
        del concepts[incoming]
        _absorb(target, duplicate)
        for name in duplicate["aliases"]:
            if normalize(name) != key and normalize(name) not in [normalize(a) for a in aliases]:
                aliases.append(name)
    # After an absorb this entry is what keeps the deleted key resolvable, so
    # names recorded under it before the repair still find their evidence.
    if incoming not in [normalize(a) for a in aliases]:
        aliases.append(alias)
    return key
