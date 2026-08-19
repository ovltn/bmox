import pytest


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


def test_open_step_records_mode_and_moves_to_ready(project):
    project.run("open-step", "1", "--mode", "probe",
                "--artifact", "kafka/TRACES/01-produce-path.md", "--title", "produce-path")
    step = project.step(1)
    assert step["phase"] == "ready"
    assert step["mode"] == "probe"
    assert step["title"] == "produce-path"
    assert step["commitment"]["artifact"] == "kafka/TRACES/01-produce-path.md"


def test_open_step_baselines_a_missing_artifact_at_zero(project):
    project.run("open-step", "1", "--mode", "probe", "--artifact", "kafka/TRACES/01-x.md")
    assert project.step(1)["commitment"]["baseline_bytes"] == 0


def test_open_step_baselines_an_existing_artifact_at_its_size(project):
    project.write("kafka/DESIGN.md", "x" * 900)
    project.run("open-step", "1", "--mode", "build", "--artifact", "kafka/DESIGN.md")
    assert project.step(1)["commitment"]["baseline_bytes"] == 900


def test_open_step_stores_the_concepts_the_step_touches(project):
    project.run("open-step", "1", "--mode", "build", "--artifact", "kafka/DESIGN.md",
                "--concept", "write-ahead-log", "--concept", "sparse-index")
    assert project.step(1)["concepts"] == ["write-ahead-log", "sparse-index"]


@pytest.mark.parametrize("mode,artifact", [
    ("build", "kafka/DESIGN.md"),
    ("probe", "kafka/TRACES/01-produce-path.md"),
    ("operate", "kafka/RUNBOOK/01-leader-kill.md"),
])
def test_open_step_accepts_the_artifact_its_mode_pins(project, mode, artifact):
    project.run("open-step", "1", "--mode", mode, "--artifact", artifact)
    assert project.step(1)["commitment"]["artifact"] == artifact


@pytest.mark.parametrize("mode,artifact", [
    ("build", "kafka/NOTES.md"),
    ("probe", "kafka/DESIGN.md"),
    ("operate", "kafka/TRACES/01-leader-kill.md"),
])
def test_open_step_rejects_an_artifact_the_mode_does_not_pin(project, mode, artifact):
    """The commitment gate has one input; aiming it elsewhere weighs a file no
    prediction goes into."""
    with pytest.raises(SystemExit):
        project.run("open-step", "1", "--mode", mode, "--artifact", artifact)


def test_open_step_rejects_an_unknown_mode(project):
    with pytest.raises(SystemExit):
        project.run("open-step", "1", "--mode", "extend", "--artifact", "kafka/DESIGN.md")


def test_open_step_rejects_a_number_out_of_range(project):
    with pytest.raises(SystemExit):
        project.run("open-step", "9", "--mode", "build", "--artifact", "kafka/DESIGN.md")


def test_open_step_refuses_to_skip_ahead(project):
    with pytest.raises(SystemExit):
        project.run("open-step", "2", "--mode", "build", "--artifact", "kafka/DESIGN.md")


def test_open_step_refuses_to_reopen_a_started_step(project):
    project.run("open-step", "1", "--mode", "build", "--artifact", "kafka/DESIGN.md")
    with pytest.raises(SystemExit):
        project.run("open-step", "1", "--mode", "probe", "--artifact", "kafka/TRACES/01-x.md")


@pytest.fixture
def opened(project):
    project.run("open-step", "1", "--mode", "probe",
                "--artifact", "kafka/TRACES/01-produce-path.md", "--title", "produce-path")
    return project


def test_commitment_advances_to_predicted_when_the_artifact_grows(opened):
    opened.write("kafka/TRACES/01-produce-path.md", "p" * 500)
    opened.run("record-commitment")
    assert opened.step(1)["phase"] == "predicted"


def test_commitment_refuses_a_missing_artifact(opened):
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_refuses_an_empty_artifact(opened):
    opened.write("kafka/TRACES/01-produce-path.md", "")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_refuses_growth_below_the_threshold(opened):
    opened.write("kafka/TRACES/01-produce-path.md", "p" * 399)
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    assert opened.step(1)["phase"] == "ready"


def test_commitment_measures_growth_not_absolute_size(project):
    """DESIGN.md is append-only across every build step, so a step that adds
    nothing must fail even when the file is already long."""
    project.write("kafka/DESIGN.md", "old content " * 500)
    project.run("open-step", "1", "--mode", "build", "--artifact", "kafka/DESIGN.md")
    with pytest.raises(SystemExit):
        project.run("record-commitment")
    assert project.step(1)["phase"] == "ready"


def test_commitment_passes_when_an_already_long_file_grows_enough(project):
    project.write("kafka/DESIGN.md", "old content " * 500)
    project.run("open-step", "1", "--mode", "build", "--artifact", "kafka/DESIGN.md")
    with open(f"{project.root}/kafka/DESIGN.md", "a") as f:
        f.write("n" * 400)
    project.run("record-commitment")
    assert project.step(1)["phase"] == "predicted"


def test_the_commitment_refusal_says_why_the_ordering_exists(opened, capsys):
    """This refusal is read at the moment the learner most wants past the gate,
    so it has to carry the argument for the gate, not just the verdict."""
    opened.write("kafka/TRACES/01-produce-path.md", "p" * 100)
    with pytest.raises(SystemExit):
        opened.run("record-commitment")
    err = capsys.readouterr().err
    assert "Predicting before looking is the entire method" in err
    assert "being wrong on the record" in err


def test_commitment_records_how_much_was_written(opened):
    opened.write("kafka/TRACES/01-produce-path.md", "p" * 512)
    opened.run("record-commitment")
    c = opened.step(1)["commitment"]
    assert c["growth_bytes"] == 512
    assert c["recorded"]


def test_commitment_cannot_run_twice(opened):
    opened.write("kafka/TRACES/01-produce-path.md", "p" * 500)
    opened.run("record-commitment")
    with pytest.raises(SystemExit):
        opened.run("record-commitment")


@pytest.fixture
def committed(opened):
    opened.write("kafka/TRACES/01-produce-path.md", "p" * 500)
    opened.run("record-commitment")
    return opened


def test_full_happy_path_reaches_done(committed):
    committed.run("mark-observed", "--evidence", "read through six hops")
    assert committed.step(1)["phase"] == "observed"
    committed.run("record-reconciled")
    assert committed.step(1)["phase"] == "explained"
    assert committed.step(1)["reconciled"] is True
    committed.run("complete-step")
    assert committed.step(1)["phase"] == "done"
    assert committed.state()["projects"]["kafka"]["current_step"] is None


def test_regress_returns_to_predicted_not_ready(committed):
    committed.run("mark-observed")
    committed.run("regress")
    assert committed.step(1)["phase"] == "predicted"


def test_mark_observed_requires_predicted(opened):
    with pytest.raises(SystemExit):
        opened.run("mark-observed")


def test_complete_step_requires_explained(committed):
    committed.run("mark-observed")
    with pytest.raises(SystemExit):
        committed.run("complete-step")
    assert committed.step(1)["phase"] == "observed"


def test_force_bypasses_the_gate_and_flags_it_permanently(committed):
    committed.run("mark-observed")
    committed.run("complete-step", "--force")
    step = committed.step(1)
    assert step["phase"] == "done"
    assert step["gate_bypassed"] is True
    assert step["reconciled"] is False


def test_force_cannot_skip_from_predicted(committed):
    with pytest.raises(SystemExit):
        committed.run("complete-step", "--force")


def test_completing_a_step_unlocks_the_next(committed):
    committed.run("mark-observed")
    committed.run("record-reconciled")
    committed.run("complete-step")
    committed.run("open-step", "2", "--mode", "build", "--artifact", "kafka/DESIGN.md")
    assert committed.step(2)["phase"] == "ready"


def test_skip_step_closes_it_with_a_reason(project):
    project.run("skip-step", "1", "--reason", "already operate this daily")
    step = project.step(1)
    assert step["phase"] == "done"
    assert step["skipped"] is True
    assert step["skip_reason"] == "already operate this daily"


def test_a_skipped_step_unlocks_the_next(project):
    project.run("skip-step", "1", "--reason", "not worth the time")
    project.run("open-step", "2", "--mode", "build", "--artifact", "kafka/DESIGN.md")
    assert project.step(2)["phase"] == "ready"


def test_skip_refuses_once_a_commitment_exists(committed):
    with pytest.raises(SystemExit):
        committed.run("skip-step", "1", "--reason", "changed my mind")


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


def test_operate_runs_the_same_path_end_to_end(project):
    project.run("open-step", "1", "--mode", "operate",
                "--artifact", "kafka/RUNBOOK/01-leader-kill.md", "--title", "leader-kill")
    project.write("kafka/RUNBOOK/01-leader-kill.md", "hypothesis " * 60)
    project.run("record-commitment")
    project.run("mark-observed", "--evidence", "client retried for 9s")
    project.run("record-reconciled")
    project.run("complete-step")
    step = project.step(1)
    assert step["mode"] == "operate"
    assert step["phase"] == "done"
    assert step["reconciled"] is True


def test_replan_changes_the_remaining_step_count(project):
    project.run("replan", "--steps", "5")
    assert project.state()["projects"]["kafka"]["steps_total"] == 5


def test_replan_preserves_closed_steps(committed):
    committed.run("mark-observed")
    committed.run("record-reconciled")
    committed.run("complete-step")
    before = committed.step(1)
    committed.run("replan", "--steps", "6")
    assert committed.step(1) == before


def test_replan_cannot_drop_below_the_closed_step_count(committed):
    committed.run("mark-observed")
    committed.run("record-reconciled")
    committed.run("complete-step")
    with pytest.raises(SystemExit):
        committed.run("replan", "--steps", "0")


def test_replan_refuses_while_a_step_is_in_flight(committed):
    with pytest.raises(SystemExit):
        committed.run("replan", "--steps", "6")


def test_record_evidence_tags_the_current_step(committed):
    committed.run("record-hint", "--tier", "2")
    committed.run("record-evidence", "--concept", "write-ahead-log",
                  "--outcome", "reconciled", "--note", "six hops, one wrong")
    ev = committed.profile()["concepts"]["write-ahead-log"]["evidence"][0]
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


def test_resolve_gap_refuses_when_no_step_is_open(committed):
    """resolved_by is permanent — gaps are never deleted — and it is what the
    next roadmap reads, so it must never be written as a project/None pair."""
    committed.run("record-gap", "--concept", "write-ahead-log", "--note", "wrong order")
    committed.run("mark-observed")
    committed.run("record-reconciled")
    committed.run("complete-step")
    with pytest.raises(SystemExit):
        committed.run("resolve-gap", "--concept", "write-ahead-log", "--gap", "g1")
    gaps = committed.profile()["concepts"]["write-ahead-log"]["open_gaps"]
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


def test_status_json_carries_state_and_profile(committed):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        committed.run("status", "--json")
    import json as _json
    payload = _json.loads(buf.getvalue())
    assert payload["state"]["projects"]["kafka"]["steps_total"] == 3
    assert "concepts" in payload["profile"]


def test_status_shows_mode_and_flags(project):
    import io
    import contextlib
    project.run("skip-step", "1", "--reason", "already know this")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        project.run("status")
    out = buf.getvalue()
    assert "SKIPPED" in out
    assert "already know this" in out


def test_a_corrupt_profile_file_is_refused(project):
    project.write(".bmox/profile.json", "{not valid json")
    with pytest.raises(SystemExit):
        project.run("status")


def test_profile_alias_requires_both_positionals(project):
    with pytest.raises(SystemExit):
        project.run("profile", "alias")
