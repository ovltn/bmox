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
    artifact must gain MIN_COMMITMENT_GROWTH non-whitespace characters of
    prose that is not one character repeated and not already elsewhere in the
    file, and no blank the template asked for may still stand anywhere the
    prediction is due — the sections recording what reality did are read
    around, since they are filled at `observed`. That is what stops a step
    from degrading into reading the answer. What build withholds is the design
    decision; the green tests were never the thing at risk.
  * `observed` is a hard precondition for explaining, gated per mode at
    mark-observed: build runs `make test` and requires this step's entry to
    record what actually happened, while probe and operate are gated on the
    shape of their own artifact.
  * You cannot reach `done` without passing through `explained`. Skipping
    requires --force, recorded permanently as "gate_bypassed".
  * Steps complete in order: each one motivates the next. A skipped step
    counts as closed, and records the phase it was abandoned at — changing
    your mind mid-step is a legal exit, not a bypassed gate.
  * Hints are recorded with their tier; they are data, not shame.
  * Every mutation is appended to an audit log inside the state file, under an
    exclusive lock, so two overlapping invocations cannot lose one another's
    entry.

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
  state.py record-evidence --concept C --outcome {reconciled,partial,none} --note N [--source {step,calibration}] [--project NAME]
  state.py record-gap --concept C --note N [--project NAME]
  state.py resolve-gap --concept C --gap ID
  state.py profile show
  state.py profile alias CONCEPT ALIAS
"""
import argparse
import contextlib
import difflib
import fcntl
import json
import os
import re
import subprocess
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


def lock_path() -> str:
    return os.path.join(bmox_dir(), ".lock")


def baselines_path() -> str:
    return os.path.join(bmox_dir(), "baselines.json")


def resolve_artifact(path: str) -> str:
    """Learner-supplied paths are relative to their repo root, not to cwd."""
    return path if os.path.isabs(path) else os.path.join(project_root(), path)


SCHEMA_VERSION = 2

# The unit is non-whitespace characters *added* to the commitment artifact, not
# bytes in it: 420 newlines, 600 spaces and one letter repeated 400 times are
# each 400+ bytes and none of them is a falsifiable claim.
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

# Every field an accessor in this file indexes without a default. A state file
# is documented as hand-repairable, so a repair that drops one of these has to
# come back as a sentence rather than as a KeyError from whichever command
# reached the damage first.
STEP_FIELDS = ("number", "phase", "commitment", "hints")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg: str, code: int = 1):
    print(f"bmox-state: ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


RECOVER = "Restore from git — it should be committed."


# ------------------------------------------------------------------- locking

@contextlib.contextmanager
def state_lock(exclusive: bool = True):
    """Serialize load -> mutate -> save on .bmox/.lock.

    Every command is a read-modify-write of one JSON document, so without a
    lock two overlapping invocations both read the same state and the second
    rename silently discards the first one's mutation *and its audit entry*,
    with both processes exiting 0. A lost audit entry is worse than a lost
    counter: the log is the only record that a hint was taken.

    The lock is never held across a call into knowledge.py. Holding it there
    would put this process in the state-then-profile order that knowledge.py's
    own lock has to be acquired in, and a single missed ordering — or a profile
    lock that happens to live on this same file — turns into a deadlock the
    learner can only escape with a kill. Read the state, release, then touch
    the profile: the ordering rule cannot then be violated at all.
    """
    directory = bmox_dir()
    if not exclusive and not os.path.isdir(directory):
        # A read-only command must not conjure .bmox/ just to lock it; there is
        # nothing yet to serialize against, and load() reports the absence.
        yield
        return
    try:
        os.makedirs(directory, exist_ok=True)
        fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        die(f"cannot use {directory} ({e.strerror}). bmox keeps its state in "
            f"the project directory named by CLAUDE_PROJECT_DIR, which must be "
            f"a writable directory.")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(fd)


# ------------------------------------------------------------------- storage

def _write_json(path: str, payload: dict):
    """Atomic write: temp file + rename, so a crash never corrupts the file.

    Both fsyncs matter and neither is redundant. Without the file fsync the
    rename can reach disk before the bytes it points at, so a power loss lands
    an empty state.json instead of the previous good one — worse than the crash
    it was meant to survive. Without the directory fsync the rename itself can
    be the thing that is lost. The unlink is what keeps an interrupted save
    from leaving .tmp files behind in a directory the learner commits.
    """
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            tmp = None
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
    except OSError as e:
        die(f"cannot write {path} ({e.strerror}). bmox keeps its state in the "
            f"project directory named by CLAUDE_PROJECT_DIR, which must be a "
            f"writable directory.")


def _validate(state: dict):
    def corrupt(what: str):
        die(f"state.json is corrupt ({what}). {RECOVER}")

    if not isinstance(state.get("current"), dict):
        corrupt("no 'current' object at the top level")
    if not isinstance(state.get("projects"), dict):
        corrupt("no 'projects' object at the top level")
    for name, proj in state["projects"].items():
        if not isinstance(proj, dict):
            corrupt(f"project '{name}' is not an object")
        if not isinstance(proj.get("steps"), dict):
            corrupt(f"project '{name}' has no 'steps' object")
        if not isinstance(proj.get("steps_total"), int):
            corrupt(f"project '{name}' has no whole-number 'steps_total'")
    # Checked here rather than at each reader so that `status` and every
    # mutating command give the same verdict on the same file. Split between
    # readers, the one command a learner runs to find out what is wrong is the
    # one that can report the damage as ordinary progress.
    cur = state["current"].get("project")
    if cur is not None and cur not in state["projects"]:
        die(f"state.json names '{cur}' as the current project, but no such "
            f"project is registered. {RECOVER} Or pick a project that exists: "
            f"state.py focus NAME")


def load() -> dict:
    path = state_path()
    if not os.path.exists(path):
        die(f"no state file at {path}. Run: state.py init")
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except ValueError as e:
        die(f"state.json is corrupt ({e}). {RECOVER}")
    except OSError as e:
        die(f"cannot read {path} ({e.strerror}). state.json must be a readable "
            f"file. {RECOVER}")
    if not isinstance(state, dict):
        die(f"state.json is corrupt (its top level is not an object). {RECOVER}")
    found = state.get("schema_version")
    if found != SCHEMA_VERSION:
        have = f"schema v{found}" if found is not None else "unversioned"
        die(f"state.json is {have}, but this bmox needs schema v{SCHEMA_VERSION}. "
            f"There is no upgrade path: archive {path} and run state.py init, then "
            f"re-register your projects. Finished work stays in your repo and its git "
            f"history — only the progress record restarts.")
    _validate(state)
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
    _write_json(state_path(), state)


def read_artifact(path: str):
    """None when the artifact cannot be read at all.

    errors="replace" because a learner's artifact is whatever their editor
    wrote, and a stray byte in a markdown file is not a reason to answer a
    lifecycle command with a UnicodeDecodeError.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def load_baselines() -> dict:
    """The commitment artifact's text as of open-step, keyed '<project>/step_N'.

    Kept beside state.json rather than inside it: state.json is the file the
    learner is told to hand-repair and restore from git, and a multi-kilobyte
    escaped copy of DESIGN.md wedged into the middle of it would end that. Only
    one entry exists at a time — it is dropped the moment the commitment it
    measures is recorded.

    Damage here is never worth refusing over: this is a cache of a file the
    learner still has, and losing it degrades record-commitment to its byte
    fallback rather than blocking the step.
    """
    path = baselines_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_baselines(baselines: dict):
    _write_json(baselines_path(), baselines)


def audit(state: dict, event: str, **details):
    state.setdefault("audit", []).append({"at": now(), "event": event, **details})


def current(state: dict):
    cur = state["current"]
    proj = cur.get("project")
    if not proj:
        die("no current project. Run: state.py new-project NAME ... or state.py focus NAME")
    return proj, state["projects"][proj]


def cur_step(project: dict) -> dict:
    n = project.get("current_step")
    if n is None:
        die("no active step. Run: state.py open-step N")
    key = f"step_{n}"
    step = project["steps"].get(key)
    if step is None:
        die(f"state.json says {key} is open, but no such step is recorded. {RECOVER}")
    if not isinstance(step, dict):
        die(f"state.json is corrupt ({key} is not an object). {RECOVER}")
    missing = [f for f in STEP_FIELDS if f not in step]
    if missing:
        die(f"state.json is corrupt ({key} is missing {', '.join(missing)}). {RECOVER}")
    if not isinstance(step["hints"], dict):
        die(f"state.json is corrupt ({key} has no 'hints' object). {RECOVER}")
    if not isinstance(step["commitment"], dict):
        die(f"state.json is corrupt ({key} has no 'commitment' object). {RECOVER}")
    return step


def hint_total(step: dict) -> int:
    return sum(v for v in step.get("hints", {}).values() if isinstance(v, int))


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


# --------------------------------------------------------- artifact content

# The commitment gate reads a file the learner controls completely, so the
# question is never "is there text" but "is this text a prediction". These are
# the shapes that clear any length check while committing to nothing: the
# template's own blanks, one character repeated, and the previous step's note
# pasted forward.
PLACEHOLDER_RE = re.compile(r"_{3,}|<[a-z][a-z ,.'\-]+>")
# Generics and paths live in code spans, and `Vec<u8>` is not an unfilled
# blank. Stripping spans first is what lets the placeholder pattern stay simple
# enough to be tolerant of prose.
CODE_SPAN_RE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
HOP_RE = re.compile(r"^hop\s*#?\s*(\d+)")
# `## Step 01 — <title>`, the heading modes.md's build template ships. Leading
# zeros are matched because the templates pad step numbers and the state file
# does not.
STEP_HEADING_RE = re.compile(r"^step\s*#?\s*0*(\d+)\b")

MIN_DISTINCT_CHARS = 10
MAX_DUPLICATED_SHARE = 0.4
# Lines this short are structure — `- Component:`, a heading, a bullet marker —
# and structure repeats across steps by design, so it cannot count as either
# content or duplication.
SUBSTANTIVE_LINE = 20
# A hop or bullet carrying less than this after its labels is a template stub
# the learner never extended, not an unanswered question.
FILLED_FIELD = 10
# The outcome lines build's template ships: where it actually broke, what the
# tests caught that was not predicted, and the prediction most wrong.
BUILD_OUTCOME_LINES = 3
# Long enough for a real suite on a cold cache, short enough that a test run
# waiting on input fails the step instead of hanging the session forever.
MAKE_TIMEOUT = 600

# The sections every mode's template ships blank on purpose, because they record
# what reality did and reality has not answered yet at `record-commitment`. The
# commitment gate reads the artifact minus these, so a blank it is *supposed* to
# find is not mistaken for a prediction the learner declined to make.
DEFERRED_SECTIONS = ("actual path", "trace diff", "what actually happened",
                     "what happened", "how this gets detected", "at 3am")

# The section holding the prediction, per mode. Checked at `record-commitment`,
# because a learner who wrote over the heading instead of under it has an
# artifact the mode's observation gate will reject — and finding that out then
# means finding out after reality was already unlocked.
COMMITMENT_SECTION = {
    "probe": ("predicted path",),
    "operate": ("hypothesis",),
}


def nonspace(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _norm(line: str) -> str:
    return " ".join(line.split()).lower()


def added_lines(baseline: str, current_text: str) -> list:
    """The lines this step is credited for: what the artifact holds now and its
    state at open-step does not account for.

    A line diff rather than a suffix comparison because a template is filled in
    place as often as it is appended to, and a suffix comparison credits the
    learner nothing for either.
    """
    before = baseline.splitlines()
    after = current_text.splitlines()
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    out = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            out.extend(after[j1:j2])
    return out


def duplicated_share(added: list, baseline: str) -> float:
    """How much of the addition's prose already stood somewhere in the file.

    DESIGN.md is one append-only file across every build step, so the cheapest
    way past a length check is to paste the previous step's note under a new
    heading. The same tally catches a paragraph pasted twice inside one
    addition, because a line becomes "already there" as soon as it is counted.

    Measured against the addition's substantive lines rather than all of it, so
    that padding the paste with blank lines and headings cannot dilute the
    ratio below the threshold.
    """
    seen = {_norm(line) for line in baseline.splitlines()
            if nonspace(line) >= SUBSTANTIVE_LINE}
    duplicated = 0
    substantive = 0
    for line in added:
        weight = nonspace(line)
        if weight < SUBSTANTIVE_LINE:
            continue
        substantive += weight
        key = _norm(line)
        if key in seen:
            duplicated += weight
        else:
            seen.add(key)
    return duplicated / substantive if substantive else 0.0


def _due_now(lines: list) -> list:
    """The artifact minus the sections that record what reality did.

    Those ship blank on purpose and are filled at `observed`, so a gate running
    at `record-commitment` has to read around them. Scoped by section rather than
    by what the learner added, because the ordering modes.md requires lays the
    template down before `open-step` — which puts every blank in the baseline,
    where a diff of added lines cannot reach it.
    """
    out = []
    skip_level = None
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip().lower()
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and any(n in title for n in DEFERRED_SECTIONS):
                skip_level = level
                continue
        if skip_level is None:
            out.append(line)
    return out


def _thin_commitment(label: str, count: int) -> str:
    """Absence and thinness need different advice, and telling a learner who just
    filled every blank that they never wrote a prediction is worse than saying
    nothing: it describes the opposite of what they did, at the one moment they
    did the work the gate exists to demand."""
    head = (f"{label} has gained {count} non-whitespace characters since this "
            f"step opened; {MIN_COMMITMENT_GROWTH} are required. ")
    if count == 0:
        return head + ("Nothing has been added, so there is no prediction for "
                       "reality to contradict — and predicting before looking is "
                       "the entire method, because a guess you never wrote down "
                       "cannot be wrong.")
    return head + ("What is there reads as a prediction; it is the detail that "
                   "is short. The bar is not a word count for its own sake — it "
                   "is roughly the length at which a claim stops being "
                   "restatable as something else once reality has answered. The "
                   "blank that usually closes the gap is where you expect it to "
                   "break: name the input or condition, and what you would "
                   "expect to see happen if you are right about it.")


def gate_commitment(label: str, mode: str, baseline: str, current_text: str) -> int:
    """Weigh the addition and return its non-whitespace character count."""
    added = added_lines(baseline, current_text)
    text = "\n".join(added)
    count = nonspace(text)
    if count < MIN_COMMITMENT_GROWTH:
        die(_thin_commitment(label, count))
    lines = current_text.splitlines()
    due = "\n".join(_due_now(lines))
    blanks = sorted(set(PLACEHOLDER_RE.findall(CODE_SPAN_RE.sub(" ", due))))
    if blanks:
        die(f"{label} still carries the template's own blanks: "
            f"{', '.join(blanks[:6])}. Each one is a question, and the answer is "
            f"the prediction this gate exists to collect — fill it in, or delete "
            f"the line if the question does not apply, then: "
            f"state.py record-commitment")
    distinct = len({ch.lower() for ch in text if not ch.isspace()})
    if distinct < MIN_DISTINCT_CHARS:
        die(f"what was added to {label} uses {distinct} distinct characters, "
            f"which is filler rather than a sentence. The "
            f"gate is not a length quota: it is here to make you name what you "
            f"expect to happen, so that reality can contradict it.")
    duplicated = duplicated_share(added, baseline)
    if duplicated > MAX_DUPLICATED_SHARE:
        die(f"{round(100 * duplicated)}% of what was added to {label} "
            f"already stands elsewhere in that file. A prediction copied forward "
            f"cannot be wrong about this step — write what you expect *here* to "
            f"do, including where you expect it to break.")
    # Last, because it is the only check about where the prose sits rather than
    # what it says: a learner who pasted 400 characters of filler is better told
    # that than sent looking for a heading.
    required = COMMITMENT_SECTION.get(mode)
    if required and _find_section(lines, *required) is None:
        die(f"{label} has no '{required[0]}' section, so the {mode} gate at "
            f"mark-observed will not find the prediction either. The template in "
            f"references/modes.md ships that heading: write your prediction below "
            f"it rather than over it, so the question you were answering is still "
            f"legible when you come back to check whether you were right.")
    return count


# ------------------------------------------------------- observation gating

def _sections(lines: list) -> list:
    """(level, lowercased title, body lines) per heading, each body running to
    the next heading at the same level or shallower."""
    heads = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip().lower()))
    out = []
    for pos, (i, level, title) in enumerate(heads):
        end = len(lines)
        for j, deeper, _t in heads[pos + 1:]:
            if deeper <= level:
                end = j
                break
        out.append((level, title, lines[i + 1:end]))
    return out


def _find_section(lines: list, *names):
    """Matched on a substring of the heading text, so a deeper heading level or
    a parenthesized aside still finds the section. The gate is here to catch an
    unfilled artifact, not to police formatting."""
    for _level, title, body in _sections(lines):
        if any(name in title for name in names):
            return body
    return None


def _step_entry(lines: list, number: int):
    """The build entry for one step.

    DESIGN.md holds one entry per build step in a single append-only file, so a
    section lookup across the whole file finds whichever step wrote that heading
    first — and every later step then reconciles against step 1's outcome. The
    heading that names this step number is the only reliable scope.
    """
    for _level, title, body in _sections(lines):
        m = STEP_HEADING_RE.match(title)
        if m and int(m.group(1)) == number:
            return body
    return None


def _hops(body: list) -> list:
    return [(int(m.group(1)), hop_body)
            for _level, title, hop_body in _sections(body)
            if (m := HOP_RE.match(title))]


def _field(body: list, label: str):
    """The value written after `- Label:`, or None when that line is absent."""
    for line in body:
        stripped = line.strip().lstrip("-*• \t")
        head, sep, rest = stripped.partition(":")
        if sep and label in head.strip().lower():
            return rest.strip().strip("*").strip()
    return None


def _value_chars(body: list) -> int:
    """How much the learner wrote after the labels a template supplied."""
    total = 0
    for line in body:
        stripped = line.strip().lstrip("-*• \t")
        _head, sep, rest = stripped.partition(":")
        if sep:
            total += nonspace(rest)
    return total


def _is_filled(value) -> bool:
    return (value is not None
            and nonspace(value.replace("…", "")) >= 3
            and not PLACEHOLDER_RE.search(value))


def _is_bullet(line: str) -> bool:
    return line.strip()[:2] in ("- ", "* ") or line.strip()[:2].startswith("•")


def gate_probe(label: str, lines: list):
    predicted = _find_section(lines, "predicted path")
    actual = _find_section(lines, "actual path")
    if predicted is None:
        die(f"{label} has no 'Predicted path' section, so there is no prediction "
            f"for reality to contradict. The trace skeleton in "
            f"references/modes.md ships both halves; restore its headings and "
            f"fill the predicted hops.")
    if actual is None:
        die(f"{label} has no 'Actual path' section. observed means the source has "
            f"answered: one block per hop it actually takes, in source order.")
    pred_hops = {n: body for n, body in _hops(predicted)
                 if _value_chars(body) >= FILLED_FIELD}
    if not pred_hops:
        die(f"no hop under 'Predicted path' in {label} carries a prediction. Each "
            f"hop names a component, a data structure, what happens there, and "
            f"what could go wrong — the hop count is itself a prediction.")
    # Every annotated block is checked rather than one per number, because two
    # blocks numbered the same is exactly how a hop's annotation goes missing.
    act_blocks = _hops(actual)
    act_numbers = {n for n, _body in act_blocks}
    missing = sorted(n for n in pred_hops if n not in act_numbers)
    if missing:
        die(f"{label} predicts hop {', '.join(f'{n}' for n in missing)} but "
            f"annotates no such hop under 'Actual path'. A predicted hop that "
            f"does not exist in the source is the most useful way to be wrong, "
            f"and it only counts once it is written down as one.")
    unanswered = sorted({n for n, body in act_blocks
                         if (n in pred_hops or _value_chars(body) >= FILLED_FIELD)
                         and not _is_filled(_field(body, "against my prediction"))})
    if unanswered:
        die(f"hop {', '.join(f'{n}' for n in unanswered)} under 'Actual path' in "
            f"{label} has no 'Against my prediction:' line filled in. That line "
            f"is the whole observation: reading the source without holding it "
            f"against what you predicted leaves the wrong model in place.")


def gate_operate(label: str, lines: list):
    hypothesis = _find_section(lines, "hypothesis")
    happened = _find_section(lines, "what actually happened", "what happened")
    if hypothesis is None:
        die(f"{label} has no 'Hypothesis' section, so nothing was committed for "
            f"the injection to falsify. The runbook skeleton in "
            f"references/modes.md ships it; restore its headings.")
    if happened is None:
        die(f"{label} has no 'What actually happened' section. observed means the "
            f"failure was injected and read: one line per hypothesis blank, in "
            f"the same order, each naming where it was read.")
    open_blanks = PLACEHOLDER_RE.findall("\n".join(hypothesis))
    if open_blanks:
        die(f"the hypothesis in {label} still has {len(open_blanks)} unfilled "
            f"blanks. Every blank names an observable and where to read it — "
            f"'it will break' cannot come out false, so nothing can be learned "
            f"from it.")
    predicted = [line for line in hypothesis if _is_bullet(line) and nonspace(line) >= 5]
    if not predicted:
        die(f"the hypothesis in {label} predicts no observables. List what the "
            f"client sees, what the log shows, which metric moves and by roughly "
            f"how much, and how long recovery takes.")
    filled = [line for line in happened
              if _is_bullet(line) and nonspace(line) >= 15
              and not PLACEHOLDER_RE.search(line)]
    if len(filled) < len(predicted):
        die(f"the hypothesis in {label} predicts {len(predicted)} observables but "
            f"'What actually happened' records {len(filled)}. Each prediction "
            f"needs the reading that confirms or contradicts it, and where it was "
            f"read — a blank left there is the one the memory quietly reshapes to "
            f"match.")


def gate_build(label: str, lines: list, number: int):
    entry = _step_entry(lines, number)
    if entry is None:
        die(f"{label} has no heading naming step {number}, so there is nothing to "
            f"read this step's outcome out of. The build template in "
            f"references/modes.md opens each entry with `## Step {number:02d} — "
            f"<title>`; that heading is what scopes the entry to this step in a "
            f"file every step appends to.")
    happened = _find_section(entry, "what actually happened", "what happened")
    if happened is None:
        die(f"step {number}'s entry in {label} has no 'What actually happened' "
            f"section. observed means the tests answered — and the answer has to "
            f"land beside the prediction it is answering, not in the conversation. "
            f"The template in references/modes.md ships the heading.")
    filled = [line for line in happened
              if _is_bullet(line) and nonspace(line) >= 15
              and not PLACEHOLDER_RE.search(line)]
    if len(filled) < BUILD_OUTCOME_LINES:
        die(f"'What actually happened' in {label} records {len(filled)} of "
            f"{BUILD_OUTCOME_LINES} lines. Green tests say the code works; they do "
            f"not say your prediction was right. Name where it actually broke, "
            f"what the tests caught that you did not predict, and which "
            f"prediction you were most wrong about — a step whose commitment was "
            f"wrong and whose tests are green is the most useful step there is, "
            f"and that is only true if the wrongness gets written down.")


def run_make_test(step: dict):
    """`make test` for a build step, run from the directory holding the Makefile.

    Called here rather than trusted from the conversation because this is the one
    gate in build mode that physics can settle. A model reading its own test
    output can be talked into believing a red suite was green — by a learner, or
    by its own summary of a long session — and an exit code cannot.
    """
    artifact = step["commitment"].get("artifact")
    if not artifact:
        die("this build step records no commitment artifact, so there is no "
            "project directory to run `make test` in. Reopen the step with "
            "--artifact <project>/DESIGN.md.")
    where = os.path.dirname(resolve_artifact(artifact))
    if not os.path.exists(os.path.join(where, "Makefile")):
        die(f"no Makefile in {where}, so nothing can establish that the tests "
            f"pass. build's gate is the test run: scaffold the project from "
            f"assets/templates/project/ and wire `make test` to its runner, or "
            f"close this step with skip-step if it is not going to be built.")
    try:
        return subprocess.run(["make", "test", f"STEP={step['number']}"],
                              cwd=where, capture_output=True, text=True,
                              timeout=MAKE_TIMEOUT)
    except FileNotFoundError:
        die("`make` is not on PATH, so build's machine gate cannot run. Install "
            "make, or close this step with skip-step.")
    except subprocess.TimeoutExpired:
        die(f"`make test` did not finish within {MAKE_TIMEOUT}s. A suite that "
            f"hangs has not gone green: it is usually a test waiting on input or "
            f"on a port nothing is listening to.")


def gate_observation(step: dict):
    """The machine gate, one branch per mode.

    Each mode has something that can settle "did reality answer" without the
    model's opinion entering into it. In build it is `make test`'s exit code. probe
    and operate have no such physics, so the artifact's own structure is the
    substitute: mode-shaped, keyed to the sections the templates ship, and an
    unfilled artifact is the only thing it refuses.

    Without one, the transition to observed is the model deciding it is satisfied
    — which is enough to carry a whole step to done, flagged reconciled, over an
    empty directory.
    """
    mode = step.get("mode")
    if mode == "build":
        result = run_make_test(step)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-15:]
            die("`make test` exited {} — reality has not answered yet, so the "
                "step stays at 'predicted'. The last of its output:\n{}".format(
                    result.returncode, "\n".join(tail) or "(no output)"))
    artifact = step["commitment"].get("artifact")
    if not artifact:
        return
    text = read_artifact(resolve_artifact(artifact))
    if text is None:
        die(f"cannot read the commitment artifact {artifact}. observed is a claim "
            f"about what that file now records, so it has to be readable.")
    lines = text.splitlines()
    if mode == "build":
        gate_build(artifact, lines, step["number"])
    elif mode == "probe":
        gate_probe(artifact, lines)
    elif mode == "operate":
        gate_operate(artifact, lines)


# --------------------------------------------------------------- audit reads

TRANSITION_EVENTS = ("open_step", "record_commitment", "mark_observed", "regress",
                     "record_reconciled", "complete_step")


def audit_flags(state: dict) -> list:
    """Timings the audit log records that no other view surfaces.

    A phase that advanced in the same second as the one before it, and a hint
    ladder climbed inside one second, are the same finding: the record says
    work happened where no time passed. Reported, never blocked — the log is
    evidence for the learner to read, and a gate here would only teach whoever
    tripped it to wait a second.
    """
    by_step = {}
    for entry in state.get("audit", []):
        if not isinstance(entry, dict):
            continue
        key = (entry.get("project"), entry.get("step"))
        if key[0] is None or key[1] is None:
            continue
        by_step.setdefault(key, []).append(entry)

    flags = []
    for (proj, number), entries in by_step.items():
        moves = [e for e in entries if e.get("event") in TRANSITION_EVENTS]
        for before, after in zip(moves, moves[1:]):
            if before.get("at") and before.get("at") == after.get("at"):
                flags.append(f"{proj} step {number}: {before['event']} -> "
                             f"{after['event']} in the same second "
                             f"({before['at']})")
        bursts = {}
        for entry in entries:
            if entry.get("event") == "hint":
                bursts.setdefault(entry.get("at"), []).append(entry.get("tier"))
        for at, tiers in bursts.items():
            if len(tiers) >= 2:
                shown = ", ".join(str(t) for t in sorted(t for t in tiers if t is not None))
                flags.append(f"{proj} step {number}: {len(tiers)} hints in the "
                             f"same second (tier {shown}) at {at}")
    return flags


# ---------------------------------------------------------------- commands

GITIGNORE = """# state.json and profile.json are your progress and live nowhere
# else, so this directory is committed on purpose. Only what is per-machine or
# mid-write is excluded here.
.lock
.profile.lock
*.tmp
"""


def write_gitignore():
    """The advice to commit .bmox/ is what makes an ignore file necessary: two
    lock files and a temp file live in there, none of them meaning anything on
    another machine, and a directory committed wholesale takes them along."""
    path = os.path.join(bmox_dir(), ".gitignore")
    if os.path.exists(path):
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(GITIGNORE)
    except OSError as e:
        die(f"cannot write {path} ({e.strerror}). bmox keeps its state in the "
            f"project directory named by CLAUDE_PROJECT_DIR, which must be a "
            f"writable directory.")


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
    write_gitignore()
    print(f"initialized {state_path()}")


def require_steps(count: int):
    if count < 1:
        die(f"--steps is {count}; a roadmap needs at least 1 step. A project with "
            f"no steps registers as unusable: open-step refuses every number, and "
            f"the only way out is state.py replan --steps N.")


def cmd_new_project(args):
    state = load()
    name = args.name
    if not name.strip():
        die("the project name is blank. It is the handle every later command "
            "takes — state.py focus NAME, and the '*' beside it in status — so a "
            "name made of spaces leaves the focused project unnameable.")
    require_steps(args.steps)
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
        if not prev or prev.get("phase") != "done":
            die(f"step {n-1} is not done yet — steps complete in order. "
                f"(This is the point: each step motivates the next.)")
    key = f"step_{n}"
    if key in proj["steps"] and proj["steps"][key].get("phase") != "planned":
        die(f"step {n} already opened (phase: {proj['steps'][key].get('phase')})")

    artifact = args.artifact
    check_artifact(args.mode, artifact)
    resolved = resolve_artifact(artifact)
    baseline = os.path.getsize(resolved) if os.path.isfile(resolved) else 0
    text = read_artifact(resolved) if os.path.isfile(resolved) else ""

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
        "abandoned_at": None,
    }
    proj["current_step"] = n
    audit(state, "open_step", project=proj_name, step=n, mode=args.mode,
          title=args.title, artifact=artifact)
    save(state)
    if text is not None:
        baselines = load_baselines()
        baselines[f"{proj_name}/{key}"] = text
        save_baselines(baselines)
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
    text = read_artifact(path)
    if text is None:
        die(f"cannot read the commitment artifact {c['artifact']}. The gate weighs "
            f"that one file, so it has to be a readable file.")
    grown = os.path.getsize(path) - c.get("baseline_bytes", 0)

    baselines = load_baselines()
    key = f"{proj_name}/step_{step['number']}"
    baseline = baselines.get(key)
    if baseline is None:
        # A step opened before the artifact's text was snapshotted has only its
        # byte count to be weighed against, and refusing it would strand a step
        # already in flight.
        if grown < MIN_COMMITMENT_GROWTH:
            die(f"{c['artifact']} has grown {grown} bytes since this step opened; "
                f"{MIN_COMMITMENT_GROWTH} are required. Predicting before looking is "
                f"the entire method — a guess you never wrote down cannot be wrong, "
                f"and being wrong on the record is what makes the reading stick.")
        committed = grown
    else:
        # Weighed on content, not on filesize, so filling a blank in place is
        # worth what it says rather than what it displaced: answering `<the
        # choice this step forces>` in fewer characters than the question took
        # shrinks the file, and the blanks check above requires that answer.
        committed = gate_commitment(c["artifact"], step.get("mode"), baseline, text)
        baselines.pop(key, None)
        save_baselines(baselines)

    c["recorded"] = now()
    c["growth_bytes"] = grown
    c["committed_chars"] = committed
    step["phase"] = new_phase
    audit(state, "record_commitment", project=proj_name, step=step["number"],
          artifact=c["artifact"], growth_bytes=grown, committed_chars=committed)
    save(state)
    print(f"[{proj_name}] step {step['number']}: ready -> predicted "
          f"({committed} non-whitespace characters committed). Reality is unlocked.")


def cmd_record_hint(args):
    state = load()
    proj_name, proj = current(state)
    step = cur_step(proj)
    if step["phase"] not in ("predicted", "observed"):
        die(f"hints are recorded between committing a prediction and reconciling it "
            f"(phase: {step['phase']})")
    tier = f"tier{args.tier}"
    step["hints"][tier] = step["hints"].get(tier, 0) + 1
    audit(state, "hint", project=proj_name, step=step["number"], tier=args.tier)
    save(state)
    print(f"[{proj_name}] step {step['number']}: tier-{args.tier} hint recorded "
          f"(total this step: {hint_total(step)}). Hints are data, not failure.")


def _simple_transition(action, extra_msg=""):
    def run(_args):
        state = load()
        proj_name, proj = current(state)
        step = cur_step(proj)
        new_phase = require_phase(step, action)
        step["phase"] = new_phase
        if action == "record-reconciled":
            step["reconciled"] = True
        audit(state, action.replace("-", "_"), project=proj_name, step=step["number"])
        save(state)
        print(f"[{proj_name}] step {step['number']}: -> {new_phase}. {extra_msg}".rstrip())
    return run


def cmd_mark_observed(args):
    state = load()
    proj_name, proj = current(state)
    step = cur_step(proj)
    new_phase = require_phase(step, "mark-observed")
    gate_observation(step)
    step["phase"] = new_phase
    details = {"evidence": args.evidence} if args.evidence else {}
    audit(state, "mark_observed", project=proj_name, step=step["number"], **details)
    save(state)
    print(f"[{proj_name}] step {step['number']}: -> {new_phase}. Do NOT advance: "
          f"reconciling prediction against reality comes next.")


cmd_regress = _simple_transition(
    "regress", "Back to predicted — reality must be re-observed before reconciling.")
cmd_record_reconciled = _simple_transition(
    "record-reconciled", "Reconciliation recorded. complete-step is now unlocked.")


def cmd_complete_step(args):
    with state_lock():
        state = load()
        proj_name, proj = current(state)
        step = cur_step(proj)
        bypassed = False
        if step["phase"] != "explained":
            if args.force and step["phase"] == "observed":
                bypassed = True
                step["gate_bypassed"] = True
                audit(state, "gate_bypassed", project=proj_name, step=step["number"])
                print("WARNING: reconciliation gate bypassed. Recorded permanently.",
                      file=sys.stderr)
            else:
                die(f"complete-step requires phase 'explained' (have '{step['phase']}'). "
                    f"Reconcile prediction against reality first, or use --force to "
                    f"bypass — the bypass is recorded forever.")
        step_n = step["number"]
        step["phase"] = "done"
        step["completed"] = now()
        audit(state, "complete_step", project=proj_name, step=step_n)
        nxt = step_n + 1
        proj["current_step"] = None
        if nxt <= proj["steps_total"]:
            msg = f"next up: step {nxt}"
        else:
            msg = "PROJECT COMPLETE. Consider a review pass, then /bmox:plan for the next tech."
        save(state)
    # Outside the state lock, per state_lock's ordering rule. A bypass that
    # reached only the state file would leave `profile show` — the view /bmox:plan
    # is told to read before drafting — describing this step as a clean solve.
    if bypassed:
        profile = load_profile()
        flagged = knowledge.mark_bypassed(profile, proj_name, step_n)
        if flagged:
            knowledge.save(profile)
            print(f"{flagged} evidence entr{'y' if flagged == 1 else 'ies'} from "
                  f"this step marked as gate-bypassed in the profile.", file=sys.stderr)
    print(f"[{proj_name}] step {step_n} done. {msg}")


def cmd_skip_step(args):
    state = load()
    proj_name, proj = current(state)
    n = args.number
    if not (1 <= n <= proj["steps_total"]):
        die(f"step {n} out of range 1..{proj['steps_total']}")
    if n > 1:
        prev = proj["steps"].get(f"step_{n-1}")
        if not prev or prev.get("phase") != "done":
            die(f"step {n-1} is not done yet — steps close in order.")
    key = f"step_{n}"
    existing = proj["steps"].get(key)
    if existing and existing.get("phase") == "done":
        die(f"step {n} is already closed (phase 'done'); there is nothing left "
            f"to skip. Closed steps are immutable — to change the shape of what "
            f"remains, run: state.py replan --steps N")
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
        # A step abandoned after its prediction was on record is a different
        # event from one never started, and neither is a bypassed gate. Without
        # this the only honest-looking exit from mid-step is --force, which
        # brands the record with a bypass that never happened.
        "abandoned_at": (existing or {}).get("phase"),
    }
    if proj.get("current_step") == n:
        proj["current_step"] = None
    audit(state, "skip_step", project=proj_name, step=n, reason=args.reason,
          abandoned_at=(existing or {}).get("phase"))
    save(state)
    baselines = load_baselines()
    if baselines.pop(f"{proj_name}/{key}", None) is not None:
        save_baselines(baselines)
    print(f"[{proj_name}] step {n} skipped: {args.reason}")
    print("Recorded and shown in status. Skipping is a choice, not a failure.")


def cmd_replan(args):
    state = load()
    proj_name, proj = current(state)
    if proj.get("current_step") is not None:
        n = proj["current_step"]
        die(f"step {n} is in flight. Close it first — state.py complete-step to "
            f"finish it, or state.py skip-step {n} --reason R to abandon it — "
            f"because a roadmap cannot be re-derived around a step whose outcome "
            f"is not yet known.")
    closed = sum(1 for s in proj["steps"].values() if s.get("phase") == "done")
    if args.steps < closed:
        die(f"{closed} steps are already closed; --steps cannot be below that. "
            f"Closed steps are immutable.")
    require_steps(args.steps)
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
    proj_name = state["current"].get("project")
    if not proj_name:
        return None, None, None, None, None
    proj = state["projects"][proj_name]
    if proj.get("current_step") is None:
        return proj_name, None, None, None, None
    step = cur_step(proj)
    return (proj_name, step["number"], step.get("mode"), step.get("hints"),
            step.get("phase"))


# The phases at which a step has something demonstrated to record. `explained` is
# the reconcile gate having held; `observed` is /bmox:check writing the profile
# ahead of a --force, which is deliberate — a bypassed step is exactly the one
# whose gaps the next roadmap needs.
EVIDENCE_PHASES = ("observed", "explained")


def cmd_record_evidence(args):
    with state_lock(exclusive=False):
        state = load()
        proj_name, step_n, mode, hints, phase = _step_context(state)
    if args.source == "step" and step_n is None:
        die("no open step to attribute this evidence to. "
            "Use --source calibration for pre-roadmap answers.")
    if args.source == "step" and phase not in EVIDENCE_PHASES:
        die(f"step {step_n} of '{proj_name}' is in phase '{phase}', and evidence "
            f"records what the learner demonstrated — which has not happened yet. "
            f"Recorded now it would also be stamped with the hint count as it "
            f"stands now, so hints delivered later in this step would leave the "
            f"profile reading as an unhinted solve. Reconcile first "
            f"(/bmox:check), then record.")
    if args.project and args.source == "step":
        die(f"--project is for calibration evidence, but --source is 'step' and "
            f"step {step_n} of '{proj_name}' is open. A step already names its "
            f"project; letting --project disagree with it would put a step "
            f"number next to a project that has no such step. Drop --project, "
            f"or pass --source calibration.")
    # Calibration runs before new-project, so the project it calibrates for is
    # not registered yet -- and cross-project evidence is the only thing in the
    # profile that shows transfer, so it cannot be left attributed to nothing.
    project = args.project or proj_name
    profile = load_profile()
    try:
        key = knowledge.add_evidence(
            profile, args.concept, args.outcome, args.note,
            source=args.source, project=project,
            step=step_n if args.source == "step" else None,
            mode=mode if args.source == "step" else None,
            hints=hints if args.source == "step" else None,
        )
        knowledge.save(profile)
    except ValueError as e:
        die(str(e))
    print(f"evidence recorded: {key} = {args.outcome}")


def cmd_record_gap(args):
    with state_lock(exclusive=False):
        state = load()
        proj_name, step_n, _, _, _ = _step_context(state)
    if args.project and step_n is not None:
        die(f"--project is for gaps recorded before a roadmap exists, but step "
            f"{step_n} of '{proj_name}' is open. A gap carries a step number "
            f"beside its project, so a --project that disagrees with the open "
            f"step files it against a project that has no such step. Drop "
            f"--project, or record it after the step closes.")
    # Calibration records a gap for every partial and none, and it runs before
    # new-project, so without this the most common gaps in the file are the ones
    # attributed to nothing.
    project = args.project or proj_name
    profile = load_profile()
    try:
        # add_gap returns the existing id when the same note is still open, so
        # the id alone does not say whether anything was written. Reporting
        # "recorded" for a note the profile already held would tell the learner
        # they had added a second finding they had not.
        already = {g["id"] for g in knowledge.open_gaps(profile, args.concept)}
        gap_id = knowledge.add_gap(profile, args.concept, args.note,
                                   project=project, step=step_n)
        knowledge.save(profile)
    except ValueError as e:
        die(str(e))
    if gap_id in already:
        print(f"gap {gap_id} on '{args.concept}' is already open with that note.")
    else:
        print(f"gap {gap_id} recorded on '{args.concept}'. "
              f"Being wrong on the record is what the next plan aims at.")


def cmd_resolve_gap(args):
    with state_lock(exclusive=False):
        state = load()
        proj_name, step_n, _, _, _ = _step_context(state)
    if step_n is None:
        die("no open step to credit this resolution to. resolve-gap runs while "
            "the step that closed the gap is still open — before complete-step, "
            "which clears it.")
    profile = load_profile()
    try:
        knowledge.resolve_gap(profile, args.concept, args.gap, f"{proj_name}/{step_n}")
        knowledge.save(profile)
    except ValueError as e:
        die(str(e))
    print(f"gap {args.gap} on '{args.concept}' resolved by {proj_name}/{step_n}")


def _outcome_sequence(evidence: list) -> str:
    """Every outcome the concept has been graded, oldest first, repeats collapsed.

    Not the strongest one reached. A reader of this column is asking "has this
    been reconciled?", and answering with the best grade hides the shape of how it
    got there: `none` in calibration and `reconciled` after a probe step is a
    different state of knowledge from `reconciled` twice, and it is the first that
    a roadmap should still be aiming a step at. The sequence answers both
    questions at once, and it is what the file already holds.
    """
    if not evidence:
        return "-"
    seq = []
    for e in evidence:
        if not seq or seq[-1] != e["outcome"]:
            seq.append(e["outcome"])
    return "→".join(seq)


def _hint_summary(evidence: list) -> str:
    """Hints across every step that fed this concept, or "" when there were none.

    Recorded per step and copied onto each concept the step named, so this
    over-attributes when a step named several concepts — which is the honest
    direction to be wrong in. Worth a line of its own because a concept
    reconciled after a tier-3 hint is not the same claim as one reconciled cold,
    and the outcome column cannot carry that difference.
    """
    tiers = [(f"tier{n}", sum((e.get("hints") or {}).get(f"tier{n}", 0)
                              for e in evidence)) for n in (1, 2, 3)]
    named = [f"{name} x{total}" for name, total in tiers if total]
    return ", ".join(named)


def _qualifiers(evidence: list, gaps: list) -> list:
    """The lines that say what the outcome column cannot."""
    out = []
    hints = _hint_summary(evidence)
    if hints:
        out.append(f"hints while earning it: {hints}")
    bypassed = sorted({f"{e.get('project')}/{e.get('step')}"
                       for e in evidence if e.get("bypassed")})
    if bypassed:
        out.append(f"reconcile gate bypassed on: {', '.join(bypassed)}")
    if evidence and all(e.get("source") == "calibration" for e in evidence):
        out.append("answered in calibration only — no step has demonstrated it")
    # The transfer story /bmox:status is told to report. Without it the only way
    # to see that a concept was met twice in different clothes is to read the raw
    # JSON, so the most interesting thing in the file needs a tool nobody reaches
    # for to find it.
    projects = sorted({e.get("project") for e in evidence if e.get("project")})
    if len(projects) > 1:
        out.append(f"met in more than one project: {', '.join(projects)}")
    for g in gaps:
        out.append(f"gap {g['id']}: {g['note']}")
    return out


def _width(rows, index: int, floor: int = 1) -> int:
    """Column widths come from the rows being printed, so a long slug or concept
    name pushes its column out instead of running into the next one."""
    return max([len(str(row[index])) for row in rows] + [floor])


def cmd_profile(args):
    profile = load_profile()
    if args.action == "alias":
        if not args.concept or not args.alias:
            die("profile alias requires both a concept and an alias. "
                "Usage: state.py profile alias CONCEPT ALIAS")
        try:
            key = knowledge.add_alias(profile, args.concept, args.alias)
            knowledge.save(profile)
        except ValueError as e:
            die(str(e))
        print(f"'{args.alias}' now resolves to '{key}'")
        return
    concepts = profile.get("concepts", {})
    if not concepts:
        print("profile is empty — /bmox:plan builds it as you go")
        return
    rows = []
    for key, c in sorted(concepts.items(), key=lambda kv: (-len(kv[1]["evidence"]), kv[0])):
        gaps = [g for g in c["open_gaps"] if g["resolved_by"] is None]
        modes = sorted({e["mode"] for e in c["evidence"] if e.get("mode")})
        rows.append((key, _outcome_sequence(c["evidence"]), len(c["evidence"]),
                     ",".join(modes) or "-", len(gaps),
                     _qualifiers(c["evidence"], gaps)))
    w_key, w_outcome, w_count, w_modes = (_width(rows, 0), _width(rows, 1),
                                          _width(rows, 2), _width(rows, 3))
    for key, outcome, count, modes, gap_count, qualifiers in rows:
        print(f"{key:<{w_key}} outcome={outcome:<{w_outcome}} "
              f"evidence={count:<{w_count}} "
              f"modes={modes:<{w_modes}} open_gaps={gap_count}")
        for line in qualifiers:
            print(f"    {line}")


def cmd_status(args):
    with state_lock(exclusive=False):
        state = load()
    profile = load_profile()
    if args.json:
        print(json.dumps({"state": state, "profile": profile}, indent=2))
        return
    cur = state["current"].get("project")
    print(f"current project: {cur or '(none)'}")
    rows = []
    for name, proj in state["projects"].items():
        for key in sorted(proj["steps"], key=lambda k: proj["steps"][k].get("number", 0)):
            s = proj["steps"][key]
            flags = []
            if s.get("reconciled"):
                flags.append("reconciled")
            if s.get("gate_bypassed"):
                flags.append("GATE BYPASSED")
            if s.get("skipped"):
                at = s.get("abandoned_at")
                flags.append(f"SKIPPED{f' at {at}' if at else ''}: {s.get('skip_reason')}")
            rows.append((name, s.get("number"), s.get("title") or "", s.get("mode") or "-",
                         s.get("phase") or "-", hint_total(s), " ".join(flags)))
    w_num, w_title = _width(rows, 1), _width(rows, 2)
    w_mode, w_phase = _width(rows, 3), _width(rows, 4)
    for name, proj in state["projects"].items():
        done = sum(1 for s in proj["steps"].values() if s.get("phase") == "done")
        marker = "*" if name == cur else " "
        print(f"{marker} {name} [{proj.get('language', '?')}]: "
              f"{done}/{proj['steps_total']} steps done")
        print(f"    goal: {proj.get('goal', '(none recorded)')}")
        for row in [r for r in rows if r[0] == name]:
            _, number, title, mode, phase, hints, flags = row
            print(f"    step {number:>{w_num}} {title:<{w_title}} "
                  f"{mode:<{w_mode}} {phase:<{w_phase}} hints={hints} "
                  f"{flags}".rstrip())
    flags = audit_flags(state)
    if flags:
        print("audit flags — the record says work happened where no time passed:")
        for flag in flags:
            print(f"    {flag}")
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
    # status and the profile commands take their own locks: they read state.json
    # and then profile.json, and the state lock has to be released between the
    # two.
    sp.set_defaults(fn=cmd_status, locking="self")

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
    sp.set_defaults(fn=cmd_complete_step, locking="self")

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
    sp.add_argument("--project")
    sp.set_defaults(fn=cmd_record_evidence, locking="self")

    sp = sub.add_parser("record-gap")
    sp.add_argument("--concept", required=True)
    sp.add_argument("--note", required=True)
    sp.add_argument("--project")
    sp.set_defaults(fn=cmd_record_gap, locking="self")

    sp = sub.add_parser("resolve-gap")
    sp.add_argument("--concept", required=True)
    sp.add_argument("--gap", required=True)
    sp.set_defaults(fn=cmd_resolve_gap, locking="self")

    sp = sub.add_parser("profile")
    sp.add_argument("action", choices=["show", "alias"])
    sp.add_argument("concept", nargs="?")
    sp.add_argument("alias", nargs="?")
    sp.set_defaults(fn=cmd_profile, locking="self")

    args = p.parse_args()
    if getattr(args, "locking", None) == "self":
        args.fn(args)
        return
    with state_lock():
        args.fn(args)


if __name__ == "__main__":
    main()
