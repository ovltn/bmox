import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")

TRACE = "kafka/TRACES/01-produce-path.md"
DESIGN = "kafka/DESIGN.md"
RUNBOOK = "kafka/RUNBOOK/01-leader-kill.md"

# Real prose rather than filler, at the length a step is actually expected to
# produce: the commitment gate weighs what a prediction is made of, so a test
# that feeds it repeated characters is testing a different function.
PREDICTED_PATH = """# Trace 01 — what happens between a socket read and the bytes being durable?

## Predicted path

### Hop 1
- Component: the network thread's selector loop
- Data structure: a per-connection receive buffer holding one length-prefixed frame
- What happens here: the frame is read in full, the four-byte size prefix is
  stripped, and the remaining bytes are handed to a request queue without being
  decoded, so that parsing never runs on the thread that owns the socket
- What could go wrong here: a frame larger than the configured maximum has to be
  rejected before its buffer is allocated, or one client sizes the broker's heap

### Hop 2
- Component: the request handler pool
- Data structure: a bounded queue of undecoded requests, plus a decoded produce
  request holding one record batch per partition
- What happens here: a handler picks the request up, decodes the header, resolves
  each partition to its local log, and checks that this broker leads every one of
  them before touching disk
- What could go wrong here: I expect the leadership check to be per partition and
  partially applied, so a request naming two partitions where only one has moved
  comes back as a partial error rather than a clean rejection

### Hop 3
- Component: the per-partition log
- Data structure: an active segment file plus a sparse offset index
- What happens here: the batch is appended at the current end offset, the index
  gains an entry only every few kilobytes, and the write lands in the page cache
- What could go wrong here: I expect durability to rest on the flush interval
  rather than on an fsync per batch, which means an acknowledged write can still
  be lost if the leader dies alone
"""

ACTUAL_PATH = """
## Actual path

### Hop 1 — predicted
- Component: SocketServer's Processor
- Data structure: a NetworkReceive accumulating one size-delimited frame
- What happens here: the frame is read to completion and pushed onto the request
  channel undecoded
- Read at (file and symbol): kafka/network/SocketServer.scala,
  Processor.processCompletedReceives
- Against my prediction: right about the split, wrong about where the size limit
  is enforced — it is checked while the receive is being built, not before the
  buffer exists

### Hop 2 — predicted
- Component: KafkaApis
- Data structure: a decoded ProduceRequest keyed by topic-partition
- What happens here: leadership and authorization are resolved per partition and
  the partitions that pass are carried on together
- Read at (file and symbol): kafka/server/KafkaApis.scala, handleProduceRequest
- Against my prediction: the partial-error shape was right, but the error is
  assembled per partition much earlier than I expected

### Hop 3 — predicted
- Component: Log and LogSegment
- Data structure: the active segment plus a sparse offset index
- What happens here: the batch is appended at the log end offset and an index
  entry is written only once enough bytes have accumulated
- Read at (file and symbol): kafka/log/Log.scala, Log.append
- Against my prediction: correct that there is no fsync per batch, wrong that
  durability rests on the flush interval — it rests on replication

### Hop 4 — not predicted
- Component: ReplicaManager
- Data structure: a delayed-produce operation held in a purgatory keyed by
  partition
- What happens here: the local append happens first, then the response waits on
  acknowledgements from the in-sync replicas instead of returning
- Read at (file and symbol): kafka/server/ReplicaManager.scala, appendRecords
- Against my prediction: I predicted nothing here at all; I had the wait for
  replicas collapsed into the append, and it is a separate stage with its own
  timeout

## Trace diff

- Hops I predicted that do not exist: none
- Hops that exist and I did not predict: the purgatory stage between the API
  layer and the log
- The prediction I was most wrong about, and what made me believe it: I thought
  acks=all was a blocking call inside the append, because that is how I would
  have written it
"""

DESIGN_NOTE = """
## Step 01 — the offset index

**Decision.** Whether an offset index entry is written for every record appended
or only every few kilobytes of appended log.
**Taking.** Sparse, one entry per four kilobytes, so the index stays small enough
to hold in memory whole and a lookup is a binary search plus a short forward scan.
**Rejected.** A dense entry per record, which makes every lookup a single step but
grows the index at the same rate as the log, so the file that exists to avoid
reading the log becomes as expensive to hold as the log.
**Costs.** Cheap: appends stay one write and the index stays resident. Expensive:
every read pays a scan whose length depends on the sparsity, and anything later
that needs an exact offset lookup has to build its own structure.
**Where I expect it to break.** A batch larger than the index interval, where the
forward scan walks into a record whose header claims more bytes than the segment
has left.
"""

HYPOTHESIS = """# Runbook 01 — killing the partition leader under load

## Hypothesis

If I send SIGKILL to the broker leading the partition a producer is writing to at
five thousand records a second, I predict:

- the client sees a not-leader error on the in-flight batch, retries it, and
  succeeds inside one metadata refresh interval
- the log shows the surviving brokers running an election and one of them
  reporting that it now leads the partition
- metric produce p99 latency moves up by roughly the refresh interval for the
  length of one refresh, then returns to where it was
- recovery takes under ten seconds end to end, dominated by the refresh rather
  than by the election itself
"""

RUNBOOK_OBSERVED = """
## What actually happened

- the client saw a not-leader error on two batches and retried both, read from the
  producer's own error log
- the log showed the controller electing a new leader within 1.2 seconds, read
  from the surviving broker's server log
- metric produce p99 moved from 12ms to 340ms for about nine seconds, read from
  the produce request metrics
- recovery took eleven seconds, a little longer than predicted, read from the
  producer's throughput chart
- what I did not predict at all: the first retry went back to the dead leader
  because the cached metadata had not expired, burning an attempt before the
  refresh happened

## How this gets detected

- The signal that moves first: the under-replicated partition count, before any
  client-visible latency does
- The alert or query that catches it in production: under-replicated partitions
  above zero for longer than sixty seconds
- What it looks like while it is degrading but not yet worth waking anyone: a
  brief produce latency bump with no change in error rate

## At 3am

- First thing to check, and where: whether a broker is down at all, from the
  controller's live broker count
- The action that stops the bleeding: let the election finish, and do not restart
  the remaining brokers
- The plausible action that makes it worse: forcing an unclean leader election,
  which trades the outage for silent data loss
- What stops it recurring: a minimum in-sync replica count above one, so a single
  leader loss cannot acknowledge a write nobody else holds
"""

LOREM = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do "
         "eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim "
         "ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
         "aliquip ex ea commodo consequat. Duis aute irure dolor in "
         "reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla "
         "pariatur. Excepteur sint occaecat cupidatat non proident, sunt in "
         "culpa qui officia deserunt mollit anim id est laborum.\n")


BUILD_OBSERVED = """
### What actually happened

- Where it actually broke: the forward scan, on a segment whose last index entry
  sat exactly on a four-kilobyte boundary, which the binary search stepped past
- What the tests caught that I did not predict: a lookup for an offset below the
  first index entry returned that entry rather than scanning from the start
- The prediction above I was most wrong about, and why I believed it: I assumed
  the index always holds an entry at or before any offset I ask it for
"""


def _append(bmox, relpath, text):
    path = os.path.join(bmox.root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(text)


def _wire_make(bmox, green=True):
    """build's machine gate shells out to `make test`, so a build step needs a
    Makefile to be gated against at all. Written per test rather than in a
    fixture because whether the suite is green is what half of these vary."""
    recipe = "\t@echo '3 tests passed'\n" if green else \
             "\t@echo 'FAIL: 2 assertions'; exit 1\n"
    bmox.write("kafka/Makefile", ".PHONY: test\ntest:\n" + recipe)


def _capture(bmox, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bmox.run(*argv)
    return buf.getvalue()


def _rewrite_state(bmox, mutate):
    """Reach past the CLI to plant a state file the CLI cannot produce quickly
    enough to test: same-second timestamps, and shapes a hand repair leaves."""
    path = os.path.join(bmox.root, ".bmox", "state.json")
    with open(path) as f:
        data = json.load(f)
    mutate(data)
    with open(path, "w") as f:
        json.dump(data, f)


def _spawn(bmox, *argv):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=bmox.root, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.Popen(
        [sys.executable, os.path.join(SCRIPTS, "state.py"), *argv],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_init_creates_state_in_project_dir(bmox):
    bmox.run("init")
    assert bmox.state()["schema_version"] == 2


def test_init_refuses_to_clobber_existing_state(bmox):
    bmox.run("init")
    with pytest.raises(SystemExit):
        bmox.run("init")


def test_two_tests_do_not_share_state(bmox):
    """Guards the lazy-path refactor: a module-level constant fails this."""
    bmox.run("init")
    assert bmox.state()["projects"] == {}


def test_new_project_records_goal_and_step_count(bmox):
    bmox.run("init")
    bmox.run("new-project", "kafka", "--language", "go",
             "--goal", "debug a consumer-lag incident", "--steps", "7")
    proj = bmox.state()["projects"]["kafka"]
    assert proj["goal"] == "debug a consumer-lag incident"
    assert proj["steps_total"] == 7
    assert proj["current_step"] is None
    assert proj["steps"] == {}


def test_new_project_focuses_it(bmox):
    bmox.run("init")
    bmox.run("new-project", "kafka", "--language", "go", "--goal", "g", "--steps", "3")
    assert bmox.state()["current"]["project"] == "kafka"


def test_new_project_refuses_a_duplicate_name(bmox):
    bmox.run("init")
    bmox.run("new-project", "kafka", "--language", "go", "--goal", "g", "--steps", "3")
    with pytest.raises(SystemExit):
        bmox.run("new-project", "kafka", "--language", "rust", "--goal", "g", "--steps", "3")


def test_focus_switches_between_projects(bmox):
    bmox.run("init")
    bmox.run("new-project", "kafka", "--language", "go", "--goal", "g", "--steps", "3")
    bmox.run("new-project", "redis", "--language", "c", "--goal", "g", "--steps", "3")
    bmox.run("focus", "kafka")
    assert bmox.state()["current"]["project"] == "kafka"


def test_focus_rejects_an_unknown_project(bmox):
    bmox.run("init")
    with pytest.raises(SystemExit):
        bmox.run("focus", "nope")


def test_schema_version_is_two(bmox):
    bmox.run("init")
    assert bmox.state()["schema_version"] == 2


def test_a_v1_state_file_is_refused(bmox):
    bmox.write(".bmox/state.json", '{"schema_version": 1, "projects": {}}')
    with pytest.raises(SystemExit):
        bmox.run("status")


def test_phase_and_mode_vocabularies_are_closed():
    import state
    assert state.PHASES == [
        "planned", "ready", "predicted", "observed", "explained", "done"
    ]
    assert state.MODES == ["build", "probe", "operate"]


@pytest.fixture
def project(bmox):
    bmox.run("init")
    bmox.run("new-project", "kafka", "--language", "go",
             "--goal", "debug a consumer-lag incident", "--steps", "3")
    return bmox


# ------------------------------------------------------- input validation

@pytest.mark.parametrize("steps", ["0", "-3"])
def test_new_project_refuses_a_roadmap_with_no_steps(bmox, steps):
    """A zero- or negative-step project registers as unusable: open-step refuses
    every number and status reports progress against a total nothing can reach."""
    bmox.run("init")
    with pytest.raises(SystemExit):
        bmox.run("new-project", "kafka", "--language", "go", "--goal", "g",
                 "--steps", steps)
    assert bmox.state()["projects"] == {}


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_new_project_refuses_a_blank_name(bmox, name):
    """The name is the handle every later command takes, and status prints the
    focused project by name — a blank one leaves it unnameable."""
    bmox.run("init")
    with pytest.raises(SystemExit):
        bmox.run("new-project", name, "--language", "go", "--goal", "g", "--steps", "3")
    assert bmox.state()["projects"] == {}


def test_replan_refuses_a_roadmap_with_no_steps(project):
    with pytest.raises(SystemExit):
        project.run("replan", "--steps", "0")
    assert project.state()["projects"]["kafka"]["steps_total"] == 3


# ---------------------------------------------------------------- open-step

def test_open_step_records_mode_and_moves_to_ready(project):
    project.run("open-step", "1", "--mode", "probe",
                "--artifact", TRACE, "--title", "produce-path")
    step = project.step(1)
    assert step["phase"] == "ready"
    assert step["mode"] == "probe"
    assert step["title"] == "produce-path"
    assert step["commitment"]["artifact"] == TRACE


def test_open_step_baselines_a_missing_artifact_at_zero(project):
    project.run("open-step", "1", "--mode", "probe", "--artifact", "kafka/TRACES/01-x.md")
    assert project.step(1)["commitment"]["baseline_bytes"] == 0


def test_open_step_baselines_an_existing_artifact_at_its_size(project):
    project.write(DESIGN, "x" * 900)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    assert project.step(1)["commitment"]["baseline_bytes"] == 900


def test_open_step_snapshots_the_artifacts_text_beside_the_state(project):
    """The gate measures what the step added, so it needs the artifact as it
    stood when the step opened — not only how long it was."""
    project.write(DESIGN, "already here\n")
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    with open(os.path.join(project.root, ".bmox", "baselines.json")) as f:
        assert json.load(f)["kafka/step_1"] == "already here\n"


def test_open_step_stores_the_concepts_the_step_touches(project):
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN,
                "--concept", "write-ahead-log", "--concept", "sparse-index")
    assert project.step(1)["concepts"] == ["write-ahead-log", "sparse-index"]


@pytest.mark.parametrize("mode,artifact", [
    ("build", DESIGN),
    ("probe", TRACE),
    ("operate", RUNBOOK),
])
def test_open_step_accepts_the_artifact_its_mode_pins(project, mode, artifact):
    project.run("open-step", "1", "--mode", mode, "--artifact", artifact)
    assert project.step(1)["commitment"]["artifact"] == artifact


@pytest.mark.parametrize("mode,artifact", [
    ("build", "kafka/NOTES.md"),
    ("probe", DESIGN),
    ("operate", "kafka/TRACES/01-leader-kill.md"),
])
def test_open_step_rejects_an_artifact_the_mode_does_not_pin(project, mode, artifact):
    """The commitment gate has one input; aiming it elsewhere weighs a file no
    prediction goes into."""
    with pytest.raises(SystemExit):
        project.run("open-step", "1", "--mode", mode, "--artifact", artifact)


def test_open_step_rejects_an_unknown_mode(project):
    with pytest.raises(SystemExit):
        project.run("open-step", "1", "--mode", "extend", "--artifact", DESIGN)


def test_open_step_rejects_a_number_out_of_range(project):
    with pytest.raises(SystemExit):
        project.run("open-step", "9", "--mode", "build", "--artifact", DESIGN)


def test_open_step_refuses_to_skip_ahead(project):
    with pytest.raises(SystemExit):
        project.run("open-step", "2", "--mode", "build", "--artifact", DESIGN)


def test_open_step_refuses_to_reopen_a_started_step(project):
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    with pytest.raises(SystemExit):
        project.run("open-step", "1", "--mode", "probe", "--artifact", "kafka/TRACES/01-x.md")


@pytest.fixture
def opened(project):
    project.run("open-step", "1", "--mode", "probe",
                "--artifact", TRACE, "--title", "produce-path")
    return project


# -------------------------------------------------------- commitment gate

def test_commitment_advances_to_predicted_on_a_real_prediction(opened):
    opened.write(TRACE, PREDICTED_PATH)
    opened.run("record-commitment")
    assert opened.step(1)["phase"] == "predicted"


def test_commitment_refuses_a_missing_artifact(opened):
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_refuses_an_empty_artifact(opened):
    opened.write(TRACE, "")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_refuses_growth_below_the_threshold(opened):
    opened.write(TRACE, "one hop, the selector loop, and then the log\n" * 8)
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


@pytest.mark.parametrize("junk,why", [
    ("\n" * 420, "newlines"),
    (" " * 600, "spaces"),
    ("\t" * 500, "tabs"),
])
def test_commitment_refuses_whitespace_that_clears_the_byte_count(opened, junk, why):
    """The gate counts non-whitespace characters because the whole claim made for
    it is that a byte count cannot be talked round, and 400 bytes of nothing
    would falsify that."""
    opened.write(TRACE, junk)
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_refuses_one_character_repeated(opened, capsys):
    opened.write(TRACE, "a" * 400)
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert "distinct characters" in capsys.readouterr().err
    assert opened.step(1)["phase"] == "ready"


def test_commitment_refuses_the_templates_own_unfilled_blanks(project, capsys):
    """A half-written blank is exactly what the README stakes the gate on
    catching: the build template ships angle-bracket blanks and the runbook ships
    underscore runs, and length alone cannot tell an answer from the question."""
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    project.write(DESIGN, DESIGN_NOTE +
                  "**Rejected.** <one alternative, and what made it lose>\n"
                  "**Recovery.** the client retries after ___ seconds\n")
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    err = capsys.readouterr().err
    assert "___" in err
    assert "<one alternative, and what made it lose>" in err
    assert project.step(1)["phase"] == "ready"


def test_a_blank_left_standing_in_the_template_is_refused(project, capsys):
    """The template lands before the step opens, which puts every one of its
    blanks in the baseline — so a check that reads only the added lines can never
    see one left standing, and prose written beside an untouched blank clears the
    gate while answering nothing. The blanks are read from the artifact."""
    project.write(DESIGN, "## Step 01 — the offset index\n\n"
                          "**Decision.** <the choice this step forces>\n"
                          "**Taking.** <the option chosen>\n")
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    assert "<the choice this step forces>" in capsys.readouterr().err
    assert project.step(1)["phase"] == "ready"


def test_an_unfilled_hypothesis_does_not_unlock_reality(project, capsys):
    """The exact shape the sanctioned ordering produces: the runbook skeleton lands
    before open-step, so every `___` sits in the baseline, and prose appended
    beside them answers no observable. Reality has to stay locked."""
    project.write(RUNBOOK, "# Runbook 01 — killing the leader\n\n"
                  "## Hypothesis\n\nIf I kill the leader, I predict:\n\n"
                  "- the client sees ___\n- the log shows ___\n"
                  "- recovery takes ___ seconds\n")
    project.run("open-step", "1", "--mode", "operate", "--artifact", RUNBOOK)
    _append(project, RUNBOOK, "\n## Notes\n\n" + (
        "I expect it to be broken briefly and then recover on its own, because "
        "Kafka is usually well behaved about this sort of thing and the consumers "
        "should pick up again once a new leader has been chosen for the partition. "
        "There may be a short blip in throughput while that settles down again. "
        "It is hard to say much more than this without standing the cluster up and "
        "watching what the dashboards actually do while the broker is going away, "
        "which is more or less the whole reason for running the experiment at all "
        "rather than reasoning about it from the documentation.\n"))
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    assert "___" in capsys.readouterr().err
    assert project.step(1)["phase"] == "ready"


def test_blanks_in_the_sections_due_later_do_not_block_the_commitment(project):
    """Every mode's template ships the reconciliation sections blank on purpose:
    they record what reality did, and reality has not answered at
    record-commitment. A gate that read them would refuse a complete prediction
    for not yet knowing the outcome."""
    project.write(DESIGN, "## Step 01 — the offset index\n")
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE +
            "\n### What actually happened\n\n"
            "- Where it actually broke: ___\n"
            "- The prediction I was most wrong about: ___\n")
    project.run("record-commitment")
    assert project.step(1)["phase"] == "predicted"


def test_commitment_refuses_a_prediction_pasted_from_earlier_in_the_file(project, capsys):
    """DESIGN.md is one append-only file across every build step, so pasting the
    previous step's note under a new heading is the cheapest way past a length
    check and says nothing about this step."""
    project.write(DESIGN, DESIGN_NOTE)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE.replace("Step 01", "Step 02"))
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    assert "already stands elsewhere in that file" in capsys.readouterr().err
    assert project.step(1)["phase"] == "ready"


def test_commitment_refuses_a_paragraph_pasted_twice_inside_one_addition(opened):
    """The same tally covers a new file, where there is no baseline to copy from
    and the duplication is inside the addition itself."""
    opened.write(TRACE, PREDICTED_PATH.split("## Predicted path")[1] * 2)
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_measures_growth_not_absolute_size(project):
    """DESIGN.md is append-only across every build step, so a step that adds
    nothing must fail even when the file is already long."""
    project.write(DESIGN, DESIGN_NOTE)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    assert project.step(1)["phase"] == "ready"


def test_commitment_passes_when_an_already_long_file_grows_by_a_real_note(project):
    project.write(DESIGN, "# kafka\n\nnotes from before this roadmap existed\n")
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    project.run("record-commitment")
    assert project.step(1)["phase"] == "predicted"


def test_a_prediction_of_around_two_hundred_words_clears_the_gate_comfortably(opened):
    """The threshold has to sit under a genuine prediction, not on top of it: a
    gate a real answer trips is a gate that gets bypassed."""
    opened.write(TRACE, PREDICTED_PATH)
    words = len(PREDICTED_PATH.split())
    assert 150 <= words <= 300
    opened.run("record-commitment")
    assert opened.step(1)["commitment"]["committed_chars"] > 1000


def test_an_empty_artifact_is_told_no_prediction_exists(opened, capsys):
    """This refusal is read at the moment the learner most wants past the gate,
    so it has to carry the argument for the gate, not just the verdict."""
    opened.write(TRACE, "")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    err = capsys.readouterr().err
    assert "no prediction for reality to contradict" in err
    assert "cannot be wrong" in err


def test_a_thin_prediction_is_not_told_it_never_wrote_one(opened, capsys):
    """A learner who filled every blank and came up short of the threshold did the
    thing the gate asks for. Telling them a guess they never wrote down cannot be
    wrong describes the opposite of what they just did, at the one moment the
    message is guaranteed to be read."""
    opened.write(TRACE, "the selector loop reads the frame, then the log appends it\n")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    err = capsys.readouterr().err
    assert "reads as a prediction" in err
    assert "cannot be wrong" not in err
    assert "where you expect it to break" in err


def test_filling_a_blank_in_place_is_not_punished_for_shrinking_the_file(project):
    """Answering a blank in fewer characters than the question took leaves the
    file smaller than the template was — and the blanks check above requires that
    answer, so a filesize floor would refuse the one edit the gate demands. The
    addition is weighed on what it says, not on what it displaced."""
    project.write(DESIGN, "## Step 01 — the offset index\n\n" + "\n".join(
        f"**Point {i}.** <the consideration this step forces you to weigh, at "
        f"length, in one carefully worded sentence which runs on and on>"
        for i in range(1, 9)) + "\n")
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    before = len(project.read(DESIGN))
    project.write(DESIGN, "## Step 01 — the offset index\n\n" + "\n".join(
        f"**Point {i}.** Sparse index, one entry every four kilobytes of log."
        for i in range(1, 9)) + "\n")
    assert len(project.read(DESIGN)) < before, "the fill has to shrink the file"
    project.run("record-commitment")
    assert project.step(1)["phase"] == "predicted"


def test_a_shrunk_artifact_is_judged_on_content_not_on_filesize(project, capsys):
    project.write(DESIGN, "x" * 800)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    project.write(DESIGN, "x" * 700)
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    err = capsys.readouterr().err
    assert "distinct characters" in err
    assert "smaller" not in err


def test_insufficient_growth_still_argues_for_the_gate(opened, capsys):
    """Growth that is merely short of the threshold is a different failure from
    a shrink, and the original argument is the right one for it."""
    opened.write(TRACE, "the selector loop reads the frame, then the log appends it")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    err = capsys.readouterr().err
    assert "has gained 48 non-whitespace characters" in err
    assert "smaller than when this step opened" not in err


def test_commitment_records_how_much_was_written(opened):
    opened.write(TRACE, PREDICTED_PATH)
    opened.run("record-commitment")
    c = opened.step(1)["commitment"]
    assert c["committed_chars"] > 1000
    assert c["growth_bytes"] == len(PREDICTED_PATH.encode())
    assert c["recorded"]


def test_the_baseline_snapshot_is_dropped_once_it_has_been_weighed(opened):
    """One entry at a time: the snapshot exists to measure one addition, and
    .bmox/ is committed."""
    opened.write(TRACE, PREDICTED_PATH)
    opened.run("record-commitment")
    with open(os.path.join(opened.root, ".bmox", "baselines.json")) as f:
        assert json.load(f) == {}


def test_a_step_with_no_baseline_snapshot_falls_back_to_the_byte_delta(opened):
    """A step opened before its artifact's text was snapshotted is already in
    flight; stranding it would be worse than measuring it the older way."""
    os.unlink(os.path.join(opened.root, ".bmox", "baselines.json"))
    opened.write(TRACE, "n" * 400)
    opened.run("record-commitment")
    assert opened.step(1)["phase"] == "predicted"
    assert opened.step(1)["commitment"]["growth_bytes"] == 400


def test_commitment_cannot_run_twice(opened):
    opened.write(TRACE, PREDICTED_PATH)
    opened.run("record-commitment")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")


@pytest.fixture
def committed(opened):
    opened.write(TRACE, PREDICTED_PATH)
    opened.run("record-commitment")
    return opened


@pytest.fixture
def observed(committed):
    _append(committed, TRACE, ACTUAL_PATH)
    committed.run("mark-observed")
    return committed


# --------------------------------------------------- observation machine gate

def test_a_lorem_ipsum_probe_artifact_cannot_reach_observed(committed, capsys):
    """Without a gate here a whole probe step reaches done, flagged reconciled,
    on filler: mark-observed is a claim about a file, so it has to read it."""
    committed.write(TRACE, LOREM * 6)
    with pytest.raises(SystemExit):
        committed.run("mark-observed")
    assert "Predicted path" in capsys.readouterr().err
    assert committed.step(1)["phase"] == "predicted"


def test_a_probe_with_no_actual_path_cannot_reach_observed(committed, capsys):
    with pytest.raises(SystemExit):
        committed.run("mark-observed")
    assert "no 'Actual path' section" in capsys.readouterr().err
    assert committed.step(1)["phase"] == "predicted"


def test_a_probe_hop_predicted_but_never_annotated_is_named(committed, capsys):
    _append(committed, TRACE, ACTUAL_PATH.split("### Hop 3")[0])
    with pytest.raises(SystemExit):
        committed.run("mark-observed")
    assert "predicts hop 3" in capsys.readouterr().err


def test_a_probe_hop_with_an_empty_against_my_prediction_line_is_named(committed, capsys):
    _append(committed, TRACE, ACTUAL_PATH.replace(
        "- Against my prediction: correct that there is no fsync per batch, wrong that\n"
        "  durability rests on the flush interval — it rests on replication",
        "- Against my prediction:"))
    with pytest.raises(SystemExit):
        committed.run("mark-observed")
    err = capsys.readouterr().err
    assert "hop 3" in err
    assert "Against my prediction" in err


def test_an_annotated_trace_reaches_observed(committed):
    _append(committed, TRACE, ACTUAL_PATH)
    committed.run("mark-observed")
    assert committed.step(1)["phase"] == "observed"


def test_the_probe_gate_tolerates_a_different_heading_level(committed):
    """The gate catches an unfilled artifact; it does not police style."""
    _append(committed, TRACE, ACTUAL_PATH.replace("## Actual path", "# Actual path (six hops)")
                                         .replace("### Hop", "## Hop")
                                         .replace("## Trace diff", "# Trace diff"))
    committed.run("mark-observed")
    assert committed.step(1)["phase"] == "observed"


def test_an_unextended_hop_stub_does_not_block_observation(project):
    """The trace skeleton ships numbered hops for the learner to extend as far as
    they think the path runs, so a stub they left alone is not a prediction."""
    project.run("open-step", "1", "--mode", "probe", "--artifact", TRACE)
    project.write(TRACE, PREDICTED_PATH + "\n### Hop 4\n- …\n")
    project.run("record-commitment")
    _append(project, TRACE, ACTUAL_PATH)
    project.run("mark-observed")
    assert project.step(1)["phase"] == "observed"


@pytest.fixture
def operate_committed(project):
    project.run("open-step", "1", "--mode", "operate",
                "--artifact", RUNBOOK, "--title", "leader-kill")
    project.write(RUNBOOK, HYPOTHESIS)
    project.run("record-commitment")
    return project


def test_an_operate_step_with_no_observations_cannot_reach_observed(operate_committed, capsys):
    with pytest.raises(SystemExit):
        operate_committed.run("mark-observed")
    assert "What actually happened" in capsys.readouterr().err
    assert operate_committed.step(1)["phase"] == "predicted"


def test_an_operate_step_missing_a_reading_per_prediction_is_counted(operate_committed, capsys):
    _append(operate_committed, RUNBOOK,
            "\n## What actually happened\n\n"
            "- the client saw a not-leader error on two batches, read from its log\n"
            "- the log showed ___\n"
            "- metric ___ moved ___\n"
            "- recovery took ___\n")
    with pytest.raises(SystemExit):
        operate_committed.run("mark-observed")
    err = capsys.readouterr().err
    assert "predicts 4 observables but 'What actually happened' records 1" in err


def test_a_filled_runbook_reaches_observed(operate_committed):
    _append(operate_committed, RUNBOOK, RUNBOOK_OBSERVED)
    operate_committed.run("mark-observed")
    assert operate_committed.step(1)["phase"] == "observed"


def test_an_operate_hypothesis_left_blank_cannot_reach_observed(project, capsys):
    """A hypothesis whose blanks are still open was never a hypothesis: 'it will
    break' cannot come out false."""
    project.run("open-step", "1", "--mode", "operate", "--artifact", RUNBOOK)
    project.write(RUNBOOK, "# Runbook 01 — killing the leader\n\n## Hypothesis\n\n"
                           "- the client sees ___\n- the log shows ___\n")
    os.unlink(os.path.join(project.root, ".bmox", "baselines.json"))
    _append(project, RUNBOOK, "x" * 400)
    project.run("record-commitment")
    _append(project, RUNBOOK, RUNBOOK_OBSERVED)
    with pytest.raises(SystemExit):
        project.run("mark-observed")
    assert "unfilled" in capsys.readouterr().err


def test_a_build_step_reaches_observed_on_a_green_suite(project):
    """build's machine gate is the exit code of `make test`, which no wording can
    argue with — so mark-observed runs it rather than believing a claim about it."""
    project.write(DESIGN, "# kafka\n")
    _wire_make(project, green=True)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    project.run("record-commitment")
    _append(project, DESIGN, BUILD_OBSERVED)
    project.run("mark-observed", "--evidence", "3 tests green")
    assert project.step(1)["phase"] == "observed"


def test_a_build_step_with_a_red_suite_stays_at_predicted(project, capsys):
    """The claim passed to --evidence is the model's, and a model reading its own
    test output over a long session can be talked into believing a red suite was
    green. The exit code cannot be."""
    project.write(DESIGN, "# kafka\n")
    _wire_make(project, green=False)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    project.run("record-commitment")
    _append(project, DESIGN, BUILD_OBSERVED)
    with pytest.raises(SystemExit):
        project.run("mark-observed", "--evidence", "14 tests green")
    err = capsys.readouterr().err
    assert "make test` exited" in err
    assert "FAIL: 2 assertions" in err
    assert project.step(1)["phase"] == "predicted"


def test_a_build_step_with_no_makefile_is_refused_rather_than_waved_through(project, capsys):
    """Nothing to run is not the same as nothing to check. A build step over a
    directory with no test runner is the vacuous green the gate exists to stop."""
    project.write(DESIGN, "# kafka\n")
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    project.run("record-commitment")
    with pytest.raises(SystemExit):
        project.run("mark-observed", "--evidence", "green")
    assert "no Makefile" in capsys.readouterr().err
    assert project.step(1)["phase"] == "predicted"


def test_a_green_build_step_still_needs_its_outcome_written_down(project, capsys):
    """Green tests say the code works. They say nothing about whether the
    prediction was right, and build is the mode where that gap is widest: the
    tests are authored before the commitment, so none of them is aimed at it."""
    project.write(DESIGN, "# kafka\n")
    _wire_make(project, green=True)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    project.run("record-commitment")
    with pytest.raises(SystemExit):
        project.run("mark-observed", "--evidence", "3 tests green")
    assert "What actually happened" in capsys.readouterr().err
    assert project.step(1)["phase"] == "predicted"


def test_build_reconciliation_is_read_from_the_current_step_not_the_first(project):
    """DESIGN.md carries one entry per build step in one file. Matching the first
    'What actually happened' would grade step 2 against step 1's outcome."""
    project.write(DESIGN, "# kafka\n")
    _wire_make(project, green=True)
    project.run("open-step", "1", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, DESIGN_NOTE)
    project.run("record-commitment")
    _append(project, DESIGN, BUILD_OBSERVED)
    project.run("mark-observed", "--evidence", "3 tests green")
    project.run("record-reconciled")
    project.run("complete-step")
    project.run("open-step", "2", "--mode", "build", "--artifact", DESIGN)
    _append(project, DESIGN, """
## Step 02 — recovering the tail after an unclean shutdown

**Decision.** Whether startup trusts the last index entry it finds or rescans the
final segment from that entry forward to confirm the records behind it landed.
**Taking.** Rescan from the last index entry, because a crash between appending a
record and flushing the index leaves an entry pointing at bytes nobody wrote.
**Rejected.** Trusting the index outright, which makes startup constant-time and
makes a torn tail indistinguishable from a healthy one until the first read.
**Costs.** Cheap afterwards: every offset the index names is known to resolve.
Expensive at boot, proportional to segment size rather than to damage.
**Where I expect it to break.** A segment whose final record is truncated
mid-header, where the length prefix itself is partially written.
""")
    project.run("record-commitment")
    with pytest.raises(SystemExit):
        project.run("mark-observed", "--evidence", "3 tests green")
    assert project.step(2)["phase"] == "predicted"


# ------------------------------------------------------------- lifecycle

def test_full_happy_path_reaches_done(committed):
    _append(committed, TRACE, ACTUAL_PATH)
    committed.run("mark-observed", "--evidence", "read through four hops")
    assert committed.step(1)["phase"] == "observed"
    committed.run("record-reconciled")
    assert committed.step(1)["phase"] == "explained"
    assert committed.step(1)["reconciled"] is True
    committed.run("complete-step")
    assert committed.step(1)["phase"] == "done"
    assert committed.state()["projects"]["kafka"]["current_step"] is None


def test_regress_returns_to_predicted_not_ready(observed):
    observed.run("regress")
    assert observed.step(1)["phase"] == "predicted"


def test_mark_observed_requires_predicted(opened):
    with pytest.raises(SystemExit):
        opened.run("mark-observed")


def test_complete_step_requires_explained(observed):
    with pytest.raises(SystemExit):
        observed.run("complete-step")
    assert observed.step(1)["phase"] == "observed"


def test_force_bypasses_the_gate_and_flags_it_permanently(observed):
    observed.run("complete-step", "--force")
    step = observed.step(1)
    assert step["phase"] == "done"
    assert step["gate_bypassed"] is True
    assert step["reconciled"] is False


def test_force_cannot_skip_from_predicted(committed):
    with pytest.raises(SystemExit):
        committed.run("complete-step", "--force")


def test_completing_a_step_unlocks_the_next(observed):
    observed.run("record-reconciled")
    observed.run("complete-step")
    observed.run("open-step", "2", "--mode", "build", "--artifact", DESIGN)
    assert observed.step(2)["phase"] == "ready"


def test_skip_step_closes_it_with_a_reason(project):
    project.run("skip-step", "1", "--reason", "already operate this daily")
    step = project.step(1)
    assert step["phase"] == "done"
    assert step["skipped"] is True
    assert step["skip_reason"] == "already operate this daily"


def test_a_skipped_step_unlocks_the_next(project):
    project.run("skip-step", "1", "--reason", "not worth the time")
    project.run("open-step", "2", "--mode", "build", "--artifact", DESIGN)
    assert project.step(2)["phase"] == "ready"


def test_skip_from_predicted_records_the_phase_it_was_abandoned_at(committed):
    """Changing your mind after committing a prediction needs a legal exit; the
    only alternatives were a false GATE BYPASSED or hand-editing state.json."""
    committed.run("skip-step", "1", "--reason", "changed my mind")
    step = committed.step(1)
    assert step["phase"] == "done"
    assert step["skipped"] is True
    assert step["abandoned_at"] == "predicted"
    assert step["gate_bypassed"] is False


def test_skip_from_observed_is_allowed(observed):
    observed.run("skip-step", "1", "--reason", "this is not the mechanism I need")
    assert observed.step(1)["abandoned_at"] == "observed"
    assert observed.step(1)["phase"] == "done"


def test_skip_refuses_a_step_that_is_already_done(observed):
    observed.run("record-reconciled")
    observed.run("complete-step")
    with pytest.raises(SystemExit):
        observed.run("skip-step", "1", "--reason", "changed my mind")
    assert observed.step(1)["skipped"] is False


def test_skip_clears_the_open_step(committed):
    committed.run("skip-step", "1", "--reason", "changed my mind")
    assert committed.state()["projects"]["kafka"]["current_step"] is None


def test_skip_before_the_step_is_opened_records_no_abandoned_phase(project):
    project.run("skip-step", "1", "--reason", "already operate this daily")
    assert project.step(1)["abandoned_at"] is None


def test_status_names_the_phase_a_skipped_step_was_abandoned_at(committed):
    committed.run("skip-step", "1", "--reason", "changed my mind")
    assert "SKIPPED at predicted: changed my mind" in _capture(committed, "status")


def test_replan_refusal_only_names_commands_that_work_in_that_phase(committed, capsys):
    """Every command a refusal names has to be runnable in the phase it printed
    from, or the advice walks the learner into a second refusal."""
    with pytest.raises(SystemExit):
        committed.run("replan", "--steps", "6")
    err = capsys.readouterr().err
    assert "complete-step" in err
    assert "skip-step 1" in err


def test_skip_refuses_to_jump_ahead(project):
    with pytest.raises(SystemExit):
        project.run("skip-step", "2", "--reason", "nope")


def test_hints_are_counted_by_tier(committed):
    committed.run("record-hint", "--tier", "1")
    committed.run("record-hint", "--tier", "2")
    committed.run("record-hint", "--tier", "2")
    assert committed.step(1)["hints"] == {"tier1": 1, "tier2": 2, "tier3": 0}


def test_hints_are_rejected_before_a_commitment(opened):
    with pytest.raises(SystemExit):
        opened.run("record-hint", "--tier", "1")


def test_operate_runs_the_same_path_end_to_end(operate_committed):
    _append(operate_committed, RUNBOOK, RUNBOOK_OBSERVED)
    operate_committed.run("mark-observed", "--evidence", "client retried for 11s")
    operate_committed.run("record-reconciled")
    operate_committed.run("complete-step")
    step = operate_committed.step(1)
    assert step["mode"] == "operate"
    assert step["phase"] == "done"
    assert step["reconciled"] is True


def test_replan_changes_the_remaining_step_count(project):
    project.run("replan", "--steps", "5")
    assert project.state()["projects"]["kafka"]["steps_total"] == 5


def test_replan_preserves_closed_steps(observed):
    observed.run("record-reconciled")
    observed.run("complete-step")
    before = observed.step(1)
    observed.run("replan", "--steps", "6")
    assert observed.step(1) == before


def test_replan_cannot_drop_below_the_closed_step_count(observed):
    observed.run("record-reconciled")
    observed.run("complete-step")
    with pytest.raises(SystemExit):
        observed.run("replan", "--steps", "0")


def test_replan_refuses_while_a_step_is_in_flight(committed):
    with pytest.raises(SystemExit):
        committed.run("replan", "--steps", "6")


# ----------------------------------------------------------------- profile

def test_record_evidence_tags_the_current_step(observed):
    observed.run("record-hint", "--tier", "2")
    observed.run("record-evidence", "--concept", "write-ahead-log",
                 "--outcome", "reconciled", "--note", "six hops, one wrong")
    ev = observed.profile()["concepts"]["write-ahead-log"]["evidence"][0]
    assert ev["project"] == "kafka"
    assert ev["step"] == 1
    assert ev["mode"] == "probe"
    assert ev["source"] == "step"
    assert ev["hints"]["tier2"] == 1


def test_calibration_evidence_needs_no_open_step(project):
    project.run("record-evidence", "--concept", "quorum", "--outcome", "partial",
                "--note", "answered 'majority of nodes'", "--source", "calibration")
    ev = project.profile()["concepts"]["quorum"]["evidence"][0]
    assert ev["source"] == "calibration"
    assert ev["step"] is None


def test_record_evidence_rejects_an_unknown_outcome(committed):
    with pytest.raises(SystemExit):
        committed.run("record-evidence", "--concept", "wal",
                      "--outcome", "solid", "--note", "n")


def test_record_gap_then_resolve_it(committed):
    committed.run("record-gap", "--concept", "write-ahead-log",
                  "--note", "predicted fsync before index write")
    gaps = committed.profile()["concepts"]["write-ahead-log"]["open_gaps"]
    assert gaps[0]["id"] == "g1"
    assert gaps[0]["resolved_by"] is None
    committed.run("resolve-gap", "--concept", "write-ahead-log", "--gap", "g1")
    assert committed.profile()["concepts"]["write-ahead-log"]["open_gaps"][0]["resolved_by"]


def test_resolve_gap_refuses_when_no_step_is_open(observed):
    """resolved_by is permanent — gaps are never deleted — and it is what the
    next roadmap reads, so it must never be written as a project/None pair."""
    observed.run("record-gap", "--concept", "write-ahead-log", "--note", "wrong order")
    observed.run("record-reconciled")
    observed.run("complete-step")
    with pytest.raises(SystemExit):
        observed.run("resolve-gap", "--concept", "write-ahead-log", "--gap", "g1")
    gaps = observed.profile()["concepts"]["write-ahead-log"]["open_gaps"]
    assert gaps[0]["resolved_by"] is None


def test_profile_alias_merges_a_later_lookup(project):
    project.run("record-evidence", "--concept", "write-ahead-log",
                "--outcome", "reconciled", "--note", "n", "--source", "calibration")
    project.run("profile", "alias", "write-ahead-log", "WAL")
    project.run("record-evidence", "--concept", "WAL",
                "--outcome", "reconciled", "--note", "n2", "--source", "calibration")
    concepts = project.profile()["concepts"]
    assert list(concepts) == ["write-ahead-log"]
    assert len(concepts["write-ahead-log"]["evidence"]) == 2


def test_calibration_evidence_can_name_the_project_it_calibrates_for(project):
    """/bmox:plan calibrates before new-project exists, and cross-project
    evidence is the only thing in the profile that shows transfer."""
    project.run("record-evidence", "--concept", "quorum", "--outcome", "partial",
                "--note", "answered 'majority of nodes'", "--source", "calibration",
                "--project", "etcd")
    ev = project.profile()["concepts"]["quorum"]["evidence"][0]
    assert ev["project"] == "etcd"
    assert ev["step"] is None
    assert ev["source"] == "calibration"


def test_naming_a_project_does_not_register_it(project):
    project.run("record-evidence", "--concept", "quorum", "--outcome", "none",
                "--note", "n", "--source", "calibration", "--project", "etcd")
    assert list(project.state()["projects"]) == ["kafka"]


def test_calibration_evidence_without_the_flag_still_falls_back_to_focus(project):
    project.run("record-evidence", "--concept", "quorum", "--outcome", "partial",
                "--note", "n", "--source", "calibration")
    assert project.profile()["concepts"]["quorum"]["evidence"][0]["project"] == "kafka"


def test_naming_a_project_conflicts_with_step_sourced_evidence(committed):
    """A step already names its project; a disagreeing --project would file a
    step number under a project that has no such step."""
    with pytest.raises(SystemExit):
        committed.run("record-evidence", "--concept", "quorum", "--outcome",
                      "reconciled", "--note", "n", "--project", "etcd")


def test_a_calibration_gap_can_name_the_project_it_was_found_for(bmox):
    """Calibration records a gap for every partial and none, and it runs before
    new-project, so this is the common path for gaps rather than an edge case."""
    bmox.run("init")
    bmox.run("record-gap", "--concept", "quorum",
             "--note", "thought a quorum was every node", "--project", "etcd")
    gap = bmox.profile()["concepts"]["quorum"]["open_gaps"][0]
    assert gap["project"] == "etcd"
    assert gap["step"] is None
    assert bmox.state()["projects"] == {}


def test_a_gap_without_the_flag_still_falls_back_to_the_open_step(committed):
    committed.run("record-gap", "--concept", "write-ahead-log", "--note", "wrong order")
    gap = committed.profile()["concepts"]["write-ahead-log"]["open_gaps"][0]
    assert gap["project"] == "kafka"
    assert gap["step"] == 1


def test_naming_a_project_conflicts_with_an_open_step(committed):
    """A gap carries a step number beside its project, so a disagreeing
    --project would file it against a project that has no such step."""
    with pytest.raises(SystemExit):
        committed.run("record-gap", "--concept", "quorum", "--note", "n",
                      "--project", "etcd")


def _profile_show(bmox):
    return _capture(bmox, "profile", "show")


def _calibrate(bmox, concept, outcome):
    bmox.run("record-evidence", "--concept", concept, "--outcome", outcome,
             "--note", "n", "--source", "calibration")


def test_profile_show_names_each_concepts_outcome(project):
    _calibrate(project, "key-expiry", "reconciled")
    _calibrate(project, "quorum", "none")
    out = _profile_show(project)
    assert "outcome=reconciled" in out
    assert "outcome=none" in out


def test_profile_show_prints_the_sequence_a_concept_was_graded(project):
    """Three skills read grades off this view to decide what not to re-teach. The
    best grade reached answers "has this been reconciled?" while hiding how it got
    there — and `none` then `reconciled` is a different state of knowledge from
    `reconciled` twice, in the direction that still wants a step aimed at it."""
    _calibrate(project, "quorum", "none")
    _calibrate(project, "quorum", "reconciled")
    assert "outcome=none→reconciled" in _profile_show(project)


def test_profile_show_collapses_a_repeated_outcome(project):
    _calibrate(project, "quorum", "partial")
    _calibrate(project, "quorum", "partial")
    out = _profile_show(project)
    assert "outcome=partial " in out
    assert "partial→partial" not in out


def test_profile_show_says_when_only_calibration_has_answered(project):
    """A concept quizzed once and never built against displays the same outcome as
    one demonstrated in a step, and modes.md's heuristic reads that outcome to
    hand out a build step. One good guess should not buy one."""
    _calibrate(project, "memory-encodings", "reconciled")
    assert "calibration only" in _profile_show(project)


def test_profile_show_names_the_hints_behind_a_reconciled_concept(observed):
    observed.run("record-hint", "--tier", "3")
    observed.run("record-evidence", "--concept", "write-ahead-log",
                 "--outcome", "reconciled", "--note", "explained the flush order")
    out = _profile_show(observed)
    assert "outcome=reconciled" in out
    assert "tier3 x1" in out


def test_profile_show_marks_a_concept_whose_gate_was_bypassed(observed):
    """/bmox:plan drops steps for concepts it reads as reconciled, so a bypass
    invisible here silently drops the step that would have re-taught the one
    concept nobody ever explained."""
    observed.run("record-evidence", "--concept", "write-ahead-log",
                 "--outcome", "reconciled", "--note", "tests went green")
    observed.run("complete-step", "--force")
    out = _profile_show(observed)
    assert "bypassed on: kafka/1" in out


def test_a_bypass_reaches_the_evidence_the_step_already_wrote(observed):
    """record-evidence runs before complete-step, so at the moment the entry is
    written nobody has decided yet whether the gate will be bypassed."""
    observed.run("record-evidence", "--concept", "write-ahead-log",
                 "--outcome", "reconciled", "--note", "tests went green")
    assert observed.profile()["concepts"]["write-ahead-log"]["evidence"][0]["bypassed"] is False
    observed.run("complete-step", "--force")
    assert observed.profile()["concepts"]["write-ahead-log"]["evidence"][0]["bypassed"] is True


def test_an_honest_close_leaves_no_bypass_mark(observed):
    observed.run("record-evidence", "--concept", "write-ahead-log",
                 "--outcome", "reconciled", "--note", "explained the flush order")
    observed.run("record-reconciled")
    observed.run("complete-step")
    assert "bypassed" not in _profile_show(observed)


def test_profile_show_names_a_concept_met_in_more_than_one_project(project):
    """The transfer story /bmox:status is told to report. Reachable only from the
    raw JSON, the most interesting line in the file needs a tool nobody reaches
    for in order to be found."""
    project.run("record-evidence", "--concept", "append-only-log", "--outcome",
                "partial", "--note", "n", "--source", "calibration",
                "--project", "kafka")
    project.run("record-evidence", "--concept", "append-only-log", "--outcome",
                "reconciled", "--note", "n", "--source", "calibration",
                "--project", "redis")
    assert "met in more than one project: kafka, redis" in _profile_show(project)


def test_record_evidence_refuses_before_the_step_has_been_observed(committed, capsys):
    """An entry written at `predicted` is stamped with the hint count as it stands
    then, so every hint delivered afterwards leaves the profile reading as an
    unhinted solve — and the entry claims a demonstration that has not happened."""
    with pytest.raises(SystemExit):
        committed.run("record-evidence", "--concept", "write-ahead-log",
                      "--outcome", "reconciled", "--note", "she gets it")
    assert "phase 'predicted'" in capsys.readouterr().err
    assert not os.path.exists(os.path.join(committed.root, ".bmox", "profile.json"))


def test_profile_show_orders_concepts_by_evidence_count_descending(project):
    _calibrate(project, "aaa-light", "none")
    _calibrate(project, "zzz-heavy", "partial")
    _calibrate(project, "zzz-heavy", "partial")
    rows = [line for line in _profile_show(project).splitlines() if "evidence=" in line]
    assert rows[0].startswith("zzz-heavy")
    assert rows[1].startswith("aaa-light")


def test_profile_show_keeps_its_empty_message(project):
    assert "profile is empty" in _profile_show(project)


# ---------------------------------------------------------- computed columns

def test_profile_show_widens_its_key_column_to_fit_the_longest_concept(project):
    """A fixed width lets a long concept name run into the column beside it,
    which is the one three skills read the outcome from."""
    long_name = "log-structured-merge-tree-compaction-and-write-amplification"
    _calibrate(project, long_name, "reconciled")
    _calibrate(project, "quorum", "none")
    rows = [line for line in _profile_show(project).splitlines() if "evidence=" in line]
    starts = {row.index("outcome=") for row in rows}
    assert len(starts) == 1
    assert min(starts) > len(long_name)


def test_status_widens_its_title_column_to_fit_the_longest_step_title(observed):
    long_title = "trace the produce path from the socket read to the replica acknowledgement"
    observed.run("record-reconciled")
    observed.run("complete-step")
    observed.run("open-step", "2", "--mode", "build", "--artifact", DESIGN,
                 "--title", long_title)
    rows = [line for line in _capture(observed, "status").splitlines()
            if line.strip().startswith("step ")]
    assert len(rows) == 2
    assert {row.index("hints=") for row in rows} == {max(row.index("hints=") for row in rows)}
    assert all(long_title not in row or row.index("hints=") > len(long_title) for row in rows)


# --------------------------------------------------------------- audit reads

def test_status_flags_a_hint_ladder_climbed_inside_one_second(committed):
    """The audit log already recorded tier 1, 2 and 3 in the same second; nothing
    read it back, so a walked-through step looked like a solved one."""
    committed.run("record-hint", "--tier", "1")
    committed.run("record-hint", "--tier", "2")
    committed.run("record-hint", "--tier", "3")

    def flatten(data):
        for entry in data["audit"]:
            if entry["event"] == "hint":
                entry["at"] = "2026-01-01T00:00:00Z"

    _rewrite_state(committed, flatten)
    out = _capture(committed, "status")
    assert "3 hints in the same second (tier 1, 2, 3)" in out


def test_status_flags_a_reconcile_that_took_no_time(observed):
    def flatten(data):
        for entry in data["audit"]:
            if entry["event"] in ("mark_observed", "record_reconciled"):
                entry["at"] = "2026-01-01T00:00:00Z"

    observed.run("record-reconciled")
    _rewrite_state(observed, flatten)
    out = _capture(observed, "status")
    assert "mark_observed -> record_reconciled in the same second" in out


def test_status_stays_quiet_when_the_timings_are_ordinary(committed):
    def spread(data):
        for i, entry in enumerate(data["audit"]):
            entry["at"] = f"2026-01-01T00:{i:02d}:00Z"

    _rewrite_state(committed, spread)
    assert "audit flags" not in _capture(committed, "status")


# -------------------------------------------------------------------- status

def test_status_json_carries_state_and_profile(committed):
    payload = json.loads(_capture(committed, "status", "--json"))
    assert payload["state"]["projects"]["kafka"]["steps_total"] == 3
    assert "concepts" in payload["profile"]


def test_status_shows_mode_and_flags(project):
    project.run("skip-step", "1", "--reason", "already know this")
    out = _capture(project, "status")
    assert "SKIPPED" in out
    assert "already know this" in out


def _rewrite_profile(bmox, mutate):
    path = os.path.join(bmox.root, ".bmox", "profile.json")
    with open(path) as f:
        data = json.load(f)
    mutate(data)
    with open(path, "w") as f:
        json.dump(data, f)


def _ambiguate(bmox):
    """A name two concepts answer to, which only a legacy or hand-edited profile
    holds — and which every profile command has to refuse by name."""
    _calibrate(bmox, "write-ahead-log", "reconciled")
    _calibrate(bmox, "wal", "none")
    _rewrite_profile(bmox, lambda p: p["concepts"]["wal"]["aliases"].append("write-ahead-log"))


@pytest.mark.parametrize("argv", [
    ("record-gap", "--concept", "write-ahead-log", "--note", "n"),
    ("record-evidence", "--concept", "write-ahead-log", "--outcome", "none",
     "--note", "n", "--source", "calibration"),
    ("resolve-gap", "--concept", "write-ahead-log", "--gap", "g1"),
    ("profile", "alias", "write-ahead-log", "commit-log"),
])
def test_an_ambiguous_concept_name_is_refused_as_a_sentence(committed, capsys, argv):
    _ambiguate(committed)
    with pytest.raises(SystemExit):
        committed.run(*argv)
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_an_unwritable_profile_directory_is_refused(committed, capsys):
    path = os.path.join(committed.root, ".bmox")
    os.chmod(path, 0o500)
    try:
        with pytest.raises(SystemExit):
            committed.run("record-gap", "--concept", "quorum", "--note", "n")
    finally:
        os.chmod(path, 0o700)
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_a_gap_already_open_with_that_note_is_not_reported_as_recorded(committed, capsys):
    """The same note on the same concept comes back with the id it already has,
    so calling that "recorded" would credit the learner with a second finding
    they did not make."""
    committed.run("record-gap", "--concept", "write-ahead-log",
                  "--note", "predicted fsync before the index write")
    assert "recorded on" in capsys.readouterr().out
    committed.run("record-gap", "--concept", "write-ahead-log",
                  "--note", "predicted fsync  before   the index write")
    assert "g1 on 'write-ahead-log' is already open with that note" in capsys.readouterr().out
    assert len(committed.profile()["concepts"]["write-ahead-log"]["open_gaps"]) == 1


def test_init_excludes_the_runtime_files_from_the_committed_directory(bmox):
    """The README has the learner commit .bmox/, and both scripts keep a lock
    file in there."""
    bmox.run("init")
    with open(os.path.join(bmox.root, ".bmox", ".gitignore")) as f:
        patterns = [line.strip() for line in f
                    if line.strip() and not line.startswith("#")]
    assert set(patterns) == {".lock", ".profile.lock", "*.tmp"}


def test_init_does_not_clobber_an_edited_gitignore(bmox):
    os.makedirs(os.path.join(bmox.root, ".bmox"))
    bmox.write(".bmox/.gitignore", "mine\n")
    bmox.run("init")
    with open(os.path.join(bmox.root, ".bmox", ".gitignore")) as f:
        assert f.read() == "mine\n"


def test_a_corrupt_profile_file_is_refused(project):
    project.write(".bmox/profile.json", "{not valid json")
    with pytest.raises(SystemExit):
        project.run("status")


def test_profile_alias_refuses_a_self_alias_as_a_sentence(project, capsys):
    """A hand-repairable file has to answer a typo with a refusal the learner can
    act on, not with whichever traceback the accessor raised."""
    _calibrate(project, "write-ahead-log", "reconciled")
    with pytest.raises(SystemExit):
        project.run("profile", "alias", "write-ahead-log", "write-ahead-log")
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_profile_alias_names_the_surviving_key_not_the_argument(project, capsys):
    """`profile alias WAL X` attaches X to whatever WAL resolves to; printing the
    normalized argument would report a resolution that did not happen."""
    _calibrate(project, "write-ahead-log", "reconciled")
    project.run("profile", "alias", "write-ahead-log", "WAL")
    capsys.readouterr()
    project.run("profile", "alias", "WAL", "commit-log")
    assert "'commit-log' now resolves to 'write-ahead-log'" in capsys.readouterr().out


def test_profile_alias_requires_both_positionals(project):
    with pytest.raises(SystemExit):
        project.run("profile", "alias")


# ------------------------------------------------- refusals, not tracebacks

def test_a_top_level_list_is_refused_as_corruption(bmox, capsys):
    bmox.write(".bmox/state.json", '[{"schema_version": 2}]')
    with pytest.raises(SystemExit):
        bmox.run("status")
    assert "bmox-state: ERROR:" in capsys.readouterr().err


@pytest.mark.parametrize("body", [
    '{"schema_version": 2, "projects": {}}',
    '{"schema_version": 2, "current": {"project": null}}',
    '{"schema_version": 2, "current": [], "projects": {}}',
    '{"schema_version": 2, "current": {"project": null}, "projects": {"k": 3}}',
    '{"schema_version": 2, "current": {"project": null}, "projects": {"k": {}}}',
])
def test_a_state_file_missing_a_key_the_code_indexes_is_refused(bmox, capsys, body):
    """A state file is documented as hand-repairable, so a repair that drops a
    key has to come back as a sentence naming the damage."""
    bmox.write(".bmox/state.json", body)
    with pytest.raises(SystemExit):
        bmox.run("status")
    err = capsys.readouterr().err
    assert "bmox-state: ERROR:" in err
    assert "Restore from git" in err


def test_a_step_record_missing_its_hints_is_refused(committed, capsys):
    def drop_hints(data):
        del data["projects"]["kafka"]["steps"]["step_1"]["hints"]

    _rewrite_state(committed, drop_hints)
    with pytest.raises(SystemExit):
        committed.run("record-hint", "--tier", "1")
    assert "hints" in capsys.readouterr().err


def test_a_ghost_current_project_is_refused_the_same_way_everywhere(committed, capsys):
    """`status` is the command a learner reaches for to find out what is wrong,
    so it must not report a focus no project answers to as ordinary progress
    while every other command refuses the same file."""
    def rename(data):
        data["current"]["project"] = "ghost"

    _rewrite_state(committed, rename)
    with pytest.raises(SystemExit):
        committed.run("status")
    assert "ghost" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        committed.run("open-step", "2", "--mode", "build", "--artifact", DESIGN)
    assert "ghost" in capsys.readouterr().err


def test_an_unreadable_state_file_is_refused(bmox, capsys):
    bmox.run("init")
    path = os.path.join(bmox.root, ".bmox", "state.json")
    os.chmod(path, 0o000)
    try:
        with pytest.raises(SystemExit):
            bmox.run("status")
    finally:
        os.chmod(path, 0o644)
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_a_state_file_that_is_a_directory_is_refused(bmox, capsys):
    os.makedirs(os.path.join(bmox.root, ".bmox", "state.json"))
    with pytest.raises(SystemExit):
        bmox.run("status")
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_a_bmox_path_that_is_a_regular_file_is_refused(bmox, capsys):
    with open(os.path.join(bmox.root, ".bmox"), "w") as f:
        f.write("not a directory\n")
    with pytest.raises(SystemExit):
        bmox.run("init")
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_a_project_dir_that_is_a_regular_file_is_refused(bmox, monkeypatch, capsys):
    path = os.path.join(bmox.root, "notadir")
    with open(path, "w") as f:
        f.write("x")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", path)
    with pytest.raises(SystemExit):
        bmox.run("init")
    assert "bmox-state: ERROR:" in capsys.readouterr().err


def test_a_read_only_project_dir_is_refused(bmox, monkeypatch, capsys):
    path = os.path.join(bmox.root, "locked")
    os.makedirs(path)
    os.chmod(path, 0o500)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", path)
    try:
        with pytest.raises(SystemExit):
            bmox.run("init")
    finally:
        os.chmod(path, 0o700)
    assert "bmox-state: ERROR:" in capsys.readouterr().err


# ---------------------------------------------------------------- durability

def test_concurrent_mutations_all_land(committed):
    """Without a lock across load -> mutate -> save, overlapping invocations read
    the same state and the last rename discards the others' mutation *and* their
    audit entry, with every process exiting 0. A lost audit entry is the worse
    half: the log is the only record that a hint was taken."""
    procs = [_spawn(committed, "record-hint", "--tier", "1") for _ in range(20)]
    for proc in procs:
        assert proc.wait() == 0, proc.communicate()
    assert committed.step(1)["hints"]["tier1"] == 20
    hints = [e for e in committed.state()["audit"] if e["event"] == "hint"]
    assert len(hints) == 20


def test_an_interrupted_save_leaves_no_temp_file_behind(committed, monkeypatch):
    """A .tmp file per interrupted save accumulates in a directory the learner
    commits, at the size of whatever it was writing."""
    import state
    monkeypatch.setattr(state.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        committed.run("record-hint", "--tier", "1")
    leftovers = [n for n in os.listdir(os.path.join(committed.root, ".bmox"))
                 if n.endswith(".tmp")]
    assert leftovers == []


def test_an_existing_schema_v2_state_file_still_drives_a_step(bmox):
    """Live state files exist. One written before the artifact snapshot and the
    per-commitment character count were recorded has to keep working, measured
    the older way rather than refused."""
    bmox.write(".bmox/state.json", json.dumps({
        "schema_version": 2,
        "created": "2026-01-01T00:00:00Z",
        "current": {"project": "kafka"},
        "projects": {
            "kafka": {
                "language": "go",
                "goal": "debug a consumer-lag incident",
                "steps_total": 2,
                "created": "2026-01-01T00:00:00Z",
                "current_step": 1,
                "steps": {
                    "step_1": {
                        "number": 1,
                        "title": "produce-path",
                        "mode": "build",
                        "phase": "ready",
                        "started": "2026-01-01T00:00:00Z",
                        "commitment": {"artifact": DESIGN, "baseline_bytes": 0},
                        "concepts": [],
                        "hints": {"tier1": 0, "tier2": 0, "tier3": 0},
                        "reconciled": False,
                        "gate_bypassed": False,
                        "skipped": False,
                        "skip_reason": None,
                    },
                },
            },
        },
        "audit": [],
    }))
    bmox.write(DESIGN, DESIGN_NOTE)
    _wire_make(bmox, green=True)
    bmox.run("record-commitment")
    bmox.run("record-hint", "--tier", "1")
    _append(bmox, DESIGN, BUILD_OBSERVED)
    bmox.run("mark-observed", "--evidence", "3 tests green")
    bmox.run("record-reconciled")
    bmox.run("complete-step")
    step = bmox.state()["projects"]["kafka"]["steps"]["step_1"]
    assert step["phase"] == "done"
    assert step["hints"]["tier1"] == 1
    assert "1/2 steps done" in _capture(bmox, "status")
