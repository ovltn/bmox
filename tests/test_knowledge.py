import json
import os
import subprocess
import sys

import knowledge
import pytest


def test_load_returns_empty_profile_when_absent(bmox):
    p = knowledge.load()
    assert p["version"] == 1
    assert p["concepts"] == {}


def test_save_then_load_roundtrips(bmox):
    p = knowledge.load()
    p["concepts"]["write-ahead-log"] = {"aliases": [], "evidence": [], "open_gaps": []}
    knowledge.save(p)
    assert "write-ahead-log" in knowledge.load()["concepts"]


def test_normalize_lowercases_and_hyphenates():
    assert knowledge.normalize("Write Ahead Log") == "write-ahead-log"
    assert knowledge.normalize("write_ahead_log") == "write-ahead-log"
    assert knowledge.normalize("  WAL  ") == "wal"


def test_resolve_creates_concept_on_first_sight(bmox):
    p = knowledge.load()
    key, created = knowledge.resolve(p, "Write Ahead Log")
    assert (key, created) == ("write-ahead-log", True)
    assert p["concepts"]["write-ahead-log"] == {
        "aliases": [], "evidence": [], "open_gaps": []
    }


def test_resolve_matches_existing_concept_without_creating(bmox):
    p = knowledge.load()
    knowledge.resolve(p, "write-ahead-log")
    key, created = knowledge.resolve(p, "Write_Ahead_Log")
    assert (key, created) == ("write-ahead-log", False)
    assert len(p["concepts"]) == 1


def test_resolve_matches_through_an_alias(bmox):
    p = knowledge.load()
    knowledge.resolve(p, "write-ahead-log")
    p["concepts"]["write-ahead-log"]["aliases"].append("wal")
    key, created = knowledge.resolve(p, "WAL")
    assert (key, created) == ("write-ahead-log", False)


def test_load_raises_on_corrupt_profile(bmox):
    bmox.write(".bmox/profile.json", "{invalid json")
    with pytest.raises(ValueError, match="profile.json is corrupt"):
        knowledge.load()


def test_load_rejects_a_profile_that_is_not_an_object(bmox):
    bmox.write(".bmox/profile.json", "[]")
    with pytest.raises(ValueError, match="profile.json is corrupt"):
        knowledge.load()


def test_load_rejects_an_unrecognized_profile_version(bmox):
    bmox.write(".bmox/profile.json", '{"version": 7, "concepts": {}}')
    with pytest.raises(ValueError, match="profile.json is corrupt"):
        knowledge.load()


def test_add_evidence_appends_a_dated_record(bmox):
    p = knowledge.load()
    knowledge.add_evidence(
        p, "write-ahead-log", "reconciled", "segment append with fsync on roll",
        project="kafka", step=4, mode="build", hints={"tier1": 0, "tier2": 1, "tier3": 0},
    )
    ev = p["concepts"]["write-ahead-log"]["evidence"]
    assert len(ev) == 1
    assert ev[0]["outcome"] == "reconciled"
    assert ev[0]["project"] == "kafka"
    assert ev[0]["step"] == 4
    assert ev[0]["mode"] == "build"
    assert ev[0]["hints"]["tier2"] == 1
    assert ev[0]["date"]


def test_add_evidence_rejects_an_unknown_outcome(bmox):
    p = knowledge.load()
    with pytest.raises(ValueError):
        knowledge.add_evidence(p, "wal", "solid", "note")


def test_calibration_evidence_records_the_source(bmox):
    p = knowledge.load()
    knowledge.add_evidence(p, "quorum", "partial", "said 'majority of nodes'",
                           source="calibration", project="kafka")
    assert p["concepts"]["quorum"]["evidence"][0]["source"] == "calibration"


def test_gaps_get_sequential_ids_and_start_unresolved(bmox):
    p = knowledge.load()
    first = knowledge.add_gap(p, "write-ahead-log", "predicted fsync before index write",
                             project="kafka", step=4)
    second = knowledge.add_gap(p, "write-ahead-log", "missed the recovery scan",
                               project="kafka", step=5)
    assert (first, second) == ("g1", "g2")
    assert all(g["resolved_by"] is None for g in p["concepts"]["write-ahead-log"]["open_gaps"])


def test_resolve_gap_marks_it_without_deleting_it(bmox):
    p = knowledge.load()
    gid = knowledge.add_gap(p, "write-ahead-log", "wrong fsync order", project="kafka", step=4)
    knowledge.resolve_gap(p, "write-ahead-log", gid, "sqlite/2")
    gaps = p["concepts"]["write-ahead-log"]["open_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["resolved_by"] == "sqlite/2"


def test_open_gaps_hides_resolved_ones(bmox):
    p = knowledge.load()
    a = knowledge.add_gap(p, "wal", "first", project="kafka", step=1)
    knowledge.add_gap(p, "wal", "second", project="kafka", step=2)
    knowledge.resolve_gap(p, "wal", a, "kafka/3")
    assert [g["note"] for g in knowledge.open_gaps(p, "wal")] == ["second"]


def test_add_alias_lets_a_later_lookup_match(bmox):
    p = knowledge.load()
    knowledge.resolve(p, "write-ahead-log")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    key, created = knowledge.resolve(p, "wal")
    assert (key, created) == ("write-ahead-log", False)


def test_add_alias_is_idempotent(bmox):
    p = knowledge.load()
    knowledge.resolve(p, "write-ahead-log")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    knowledge.add_alias(p, "write-ahead-log", "wal")
    assert p["concepts"]["write-ahead-log"]["aliases"] == ["WAL"]


def test_add_alias_absorbs_a_name_that_is_already_its_own_concept(bmox):
    p = knowledge.load()
    knowledge.add_evidence(p, "write-ahead-log", "reconciled", "explained fsync ordering",
                           source="calibration")
    knowledge.add_evidence(p, "WAL", "partial", "typed it differently a week later",
                           source="calibration")
    assert knowledge.add_alias(p, "write-ahead-log", "WAL") == "write-ahead-log"
    assert list(p["concepts"]) == ["write-ahead-log"]
    assert knowledge.resolve(p, "WAL") == ("write-ahead-log", False)
    assert knowledge.resolve(p, "Write Ahead Log") == ("write-ahead-log", False)


def test_add_alias_keeps_every_evidence_entry_from_both_sides(bmox):
    p = knowledge.load()
    knowledge.add_evidence(p, "write-ahead-log", "reconciled", "explained fsync ordering",
                           source="calibration")
    knowledge.add_evidence(p, "wal", "partial", "typed it differently a week later",
                           source="calibration")
    knowledge.add_evidence(p, "wal", "reconciled", "third session", source="calibration")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    evidence = p["concepts"]["write-ahead-log"]["evidence"]
    assert len(evidence) == 3
    assert [e["note"] for e in evidence] == [
        "explained fsync ordering",
        "typed it differently a week later",
        "third session",
    ]


def test_add_alias_renumbers_colliding_gap_ids_and_keeps_them_resolvable(bmox):
    p = knowledge.load()
    knowledge.add_gap(p, "write-ahead-log", "predicted fsync before index write")
    knowledge.add_gap(p, "write-ahead-log", "missed the recovery scan")
    knowledge.add_gap(p, "wal", "thought the log was the index")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    gaps = p["concepts"]["write-ahead-log"]["open_gaps"]
    assert [(g["id"], g["note"]) for g in gaps] == [
        ("g1", "predicted fsync before index write"),
        ("g2", "missed the recovery scan"),
        ("g3", "thought the log was the index"),
    ]
    for gap in gaps:
        knowledge.resolve_gap(p, "WAL", gap["id"], "sqlite/2")
    assert knowledge.open_gaps(p, "write-ahead-log") == []


def test_a_gap_recorded_after_a_merge_gets_a_fresh_id(bmox):
    p = knowledge.load()
    knowledge.add_gap(p, "write-ahead-log", "predicted fsync before index write")
    knowledge.add_gap(p, "wal", "thought the log was the index")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    assert knowledge.add_gap(p, "wal", "missed the recovery scan") == "g3"


def test_add_alias_merges_the_absorbed_concepts_own_aliases(bmox):
    p = knowledge.load()
    knowledge.resolve(p, "write-ahead-log")
    knowledge.add_alias(p, "wal", "commit log")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    assert p["concepts"]["write-ahead-log"]["aliases"] == ["commit log", "WAL"]
    assert knowledge.resolve(p, "Commit Log") == ("write-ahead-log", False)


def test_add_alias_refuses_to_alias_a_concept_to_itself(bmox):
    p = knowledge.load()
    knowledge.add_evidence(p, "write-ahead-log", "reconciled", "explained fsync ordering",
                           source="calibration")
    with pytest.raises(ValueError, match="already is the concept"):
        knowledge.add_alias(p, "write-ahead-log", "Write_Ahead_Log")
    assert p["concepts"]["write-ahead-log"]["aliases"] == []
    assert len(p["concepts"]["write-ahead-log"]["evidence"]) == 1


def test_lookup_answers_without_creating_the_concept(bmox):
    p = knowledge.load()
    assert knowledge.lookup(p, "Write Ahead Log") is None
    assert p["concepts"] == {}
    knowledge.resolve(p, "write-ahead-log")
    knowledge.add_alias(p, "write-ahead-log", "WAL")
    assert knowledge.lookup(p, "Write_Ahead_Log") == "write-ahead-log"
    assert knowledge.lookup(p, "wal") == "write-ahead-log"


def test_lookup_refuses_a_name_two_concepts_answer_to(bmox):
    p = knowledge.load()
    p["concepts"]["foo"] = {"aliases": ["WAL"], "evidence": [], "open_gaps": []}
    p["concepts"]["write-ahead-log"] = {"aliases": ["wal"], "evidence": [], "open_gaps": []}
    with pytest.raises(ValueError, match="'foo', 'write-ahead-log'"):
        knowledge.lookup(p, "WAL")


def test_an_ambiguous_name_refuses_the_same_way_whatever_the_file_order(bmox):
    messages = []
    for order in (["foo", "write-ahead-log"], ["write-ahead-log", "foo"]):
        p = knowledge.load()
        for key in order:
            p["concepts"][key] = {"aliases": ["wal"], "evidence": [], "open_gaps": []}
        with pytest.raises(ValueError) as excinfo:
            knowledge.resolve(p, "WAL")
        messages.append(str(excinfo.value))
    assert messages[0] == messages[1]


def test_add_alias_refuses_a_name_a_third_concept_already_answers_to(bmox):
    p = knowledge.load()
    knowledge.add_evidence(p, "foo", "reconciled", "unrelated work")
    knowledge.add_alias(p, "foo", "WAL")
    knowledge.resolve(p, "write-ahead-log")
    with pytest.raises(ValueError, match="already a name for 'foo'"):
        knowledge.add_alias(p, "write-ahead-log", "WAL")
    assert p["concepts"]["write-ahead-log"]["aliases"] == []
    assert p["concepts"]["foo"]["aliases"] == ["WAL"]
    assert knowledge.lookup(p, "wal") == "foo"


def test_the_refused_alias_names_the_join_that_would_work(bmox):
    p = knowledge.load()
    knowledge.add_alias(p, "foo", "WAL")
    knowledge.resolve(p, "write-ahead-log")
    with pytest.raises(ValueError) as excinfo:
        knowledge.add_alias(p, "write-ahead-log", "WAL")
    assert "profile alias write-ahead-log foo" in str(excinfo.value)
    knowledge.add_alias(p, "write-ahead-log", "foo")
    assert knowledge.lookup(p, "WAL") == "write-ahead-log"


def test_add_alias_repairs_a_profile_whose_name_already_reached_two_concepts(bmox):
    p = knowledge.load()
    p["concepts"]["wal"] = {"aliases": [], "evidence": [], "open_gaps": []}
    knowledge.add_evidence(p, "wal", "partial", "recorded under the short name")
    p["concepts"]["write-ahead-log"] = {"aliases": ["WAL"], "evidence": [], "open_gaps": []}
    knowledge.add_evidence(p, "write-ahead-log", "reconciled", "recorded under the long name")
    assert knowledge.add_alias(p, "write-ahead-log", "wal") == "write-ahead-log"
    assert list(p["concepts"]) == ["write-ahead-log"]
    assert knowledge.lookup(p, "WAL") == "write-ahead-log"
    assert len(p["concepts"]["write-ahead-log"]["evidence"]) == 2


def test_add_alias_refuses_when_the_join_would_carry_a_claimed_alias_across(bmox):
    p = knowledge.load()
    p["concepts"]["commit-log"] = {"aliases": ["journal"], "evidence": [], "open_gaps": []}
    p["concepts"]["wal"] = {"aliases": ["Journal"], "evidence": [], "open_gaps": []}
    knowledge.add_evidence(p, "write-ahead-log", "reconciled", "long name")
    with pytest.raises(ValueError, match="'commit-log' already answers to that name"):
        knowledge.add_alias(p, "write-ahead-log", "wal")
    assert sorted(p["concepts"]) == ["commit-log", "wal", "write-ahead-log"]
    assert p["concepts"]["wal"]["aliases"] == ["Journal"]
    assert p["concepts"]["write-ahead-log"]["aliases"] == []


def test_recording_the_same_open_gap_twice_leaves_one_gap(bmox):
    p = knowledge.load()
    first = knowledge.add_gap(p, "write-ahead-log", "predicted fsync before index write",
                             project="kafka", step=4)
    second = knowledge.add_gap(p, "write-ahead-log", "predicted fsync before index write",
                               project="sqlite", step=2)
    assert first == second == "g1"
    gaps = p["concepts"]["write-ahead-log"]["open_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["project"] == "kafka"
    assert len(knowledge.open_gaps(p, "write-ahead-log")) == 1


def test_the_same_gap_matches_through_spacing_and_case(bmox):
    p = knowledge.load()
    knowledge.add_gap(p, "wal", "Predicted fsync before   index write")
    assert knowledge.add_gap(p, "wal", "predicted fsync before index write") == "g1"
    assert len(p["concepts"]["wal"]["open_gaps"]) == 1


def test_a_different_note_still_opens_its_own_gap(bmox):
    p = knowledge.load()
    knowledge.add_gap(p, "wal", "predicted fsync before index write")
    assert knowledge.add_gap(p, "wal", "missed the recovery scan") == "g2"


def test_the_same_gap_after_a_resolution_is_recorded_again(bmox):
    p = knowledge.load()
    first = knowledge.add_gap(p, "wal", "predicted fsync before index write")
    knowledge.resolve_gap(p, "wal", first, "kafka/4")
    again = knowledge.add_gap(p, "wal", "predicted fsync before index write")
    assert again == "g2"
    notes = [(g["id"], g["resolved_by"]) for g in p["concepts"]["wal"]["open_gaps"]]
    assert notes == [("g1", "kafka/4"), ("g2", None)]


def test_resolve_gap_refuses_to_overwrite_the_step_that_closed_it(bmox):
    p = knowledge.load()
    gid = knowledge.add_gap(p, "wal", "wrong fsync order")
    knowledge.resolve_gap(p, "wal", gid, "kafka/4")
    with pytest.raises(ValueError, match="already resolved by 'kafka/4'"):
        knowledge.resolve_gap(p, "wal", gid, "sqlite/2")
    assert p["concepts"]["wal"]["open_gaps"][0]["resolved_by"] == "kafka/4"


def test_resolve_gap_on_an_unknown_concept_refuses_without_creating_it(bmox):
    p = knowledge.load()
    with pytest.raises(ValueError, match="no concept 'write-ahead-log'"):
        knowledge.resolve_gap(p, "Write Ahead Log", "g1", "kafka/4")
    assert p["concepts"] == {}


def test_open_gaps_on_an_unknown_concept_creates_nothing(bmox):
    p = knowledge.load()
    assert knowledge.open_gaps(p, "write-ahead-log") == []
    assert p["concepts"] == {}


def test_load_refuses_a_profile_path_that_is_a_directory(bmox):
    os.makedirs(knowledge.profile_path())
    with pytest.raises(ValueError, match="cannot be used"):
        knowledge.load()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a chmod 000 file anyway")
def test_load_refuses_an_unreadable_profile(bmox):
    bmox.write(".bmox/profile.json", '{"version": 1, "concepts": {}}')
    os.chmod(knowledge.profile_path(), 0o000)
    try:
        with pytest.raises(ValueError, match="cannot be used"):
            knowledge.load()
    finally:
        os.chmod(knowledge.profile_path(), 0o600)


def test_load_refuses_a_concepts_map_that_is_not_an_object(bmox):
    bmox.write(".bmox/profile.json", '{"version": 1, "concepts": []}')
    with pytest.raises(ValueError, match="'concepts' is a list, not an object"):
        knowledge.load()


def test_a_mis_shaped_profile_never_reads_as_an_empty_one(bmox, capsys):
    bmox.run("init")
    bmox.write(".bmox/profile.json", '{"version": 1, "concepts": []}')
    for argv in (("status",), ("profile", "show")):
        with pytest.raises(SystemExit):
            bmox.run(*argv)
        assert "profile is empty" not in capsys.readouterr().out


def test_load_refuses_a_concept_entry_of_the_wrong_type(bmox):
    bmox.write(".bmox/profile.json", '{"version": 1, "concepts": {"wal": "reconciled"}}')
    with pytest.raises(ValueError, match="concept 'wal' is a str, not an object"):
        knowledge.load()


def test_load_refuses_a_concept_missing_its_gap_list(bmox):
    bmox.write(".bmox/profile.json",
               '{"version": 1, "concepts": {"wal": {"aliases": [], "evidence": []}}}')
    with pytest.raises(ValueError, match="concept 'wal' has no 'open_gaps'"):
        knowledge.load()


def test_load_refuses_a_gap_with_no_resolution_field(bmox):
    bmox.write(".bmox/profile.json", json.dumps({
        "version": 1,
        "concepts": {"wal": {"aliases": [], "evidence": [],
                             "open_gaps": [{"id": "g1", "note": "wrong order"}]}},
    }))
    with pytest.raises(ValueError, match="gap 'g1' with no 'resolved_by'"):
        knowledge.load()


def test_load_refuses_evidence_with_an_unknown_outcome(bmox):
    bmox.write(".bmox/profile.json", json.dumps({
        "version": 1,
        "concepts": {"wal": {"aliases": [], "open_gaps": [],
                             "evidence": [{"outcome": "solid", "note": "n"}]}},
    }))
    with pytest.raises(ValueError, match="outcome 'solid'"):
        knowledge.load()


def test_a_profile_written_by_an_earlier_run_loads_and_mutates(bmox):
    bmox.write(".bmox/profile.json", json.dumps({
        "version": 1,
        "created": "2026-01-01T00:00:00Z",
        "concepts": {"write-ahead-log": {
            "aliases": ["WAL"],
            "evidence": [{"project": "kafka", "step": 4, "mode": "build", "source": "step",
                          "outcome": "partial", "date": "2026-01-02T00:00:00Z",
                          "hints": {"tier1": 1, "tier2": 0, "tier3": 0},
                          "note": "fsync ordering"}],
            "open_gaps": [{"id": "g1", "project": "kafka", "step": 4,
                           "date": "2026-01-02T00:00:00Z", "note": "wrong fsync order",
                           "resolved_by": None}],
        }},
    }, indent=2))
    p = knowledge.load()
    assert p["created"] == "2026-01-01T00:00:00Z"
    assert knowledge.resolve(p, "wal") == ("write-ahead-log", False)
    knowledge.add_evidence(p, "WAL", "reconciled", "second pass", project="sqlite", step=2)
    knowledge.resolve_gap(p, "wal", "g1", "sqlite/2")
    assert knowledge.add_gap(p, "wal", "missed the recovery scan") == "g2"
    knowledge.save(p)
    reloaded = knowledge.load()
    assert reloaded["version"] == 1
    concept = reloaded["concepts"]["write-ahead-log"]
    assert [e["note"] for e in concept["evidence"]] == ["fsync ordering", "second pass"]
    assert [(g["id"], g["resolved_by"]) for g in concept["open_gaps"]] == [
        ("g1", "sqlite/2"), ("g2", None)
    ]


def test_save_leaves_no_temp_file_behind_when_the_write_fails(bmox, monkeypatch):
    p = knowledge.load()
    knowledge.add_gap(p, "wal", "wrong fsync order")
    monkeypatch.setattr(knowledge.json, "dump", _explode)
    with pytest.raises(RuntimeError):
        knowledge.save(p)
    assert os.listdir(knowledge.bmox_dir()) == [os.path.basename(knowledge.lock_path())]


def _explode(*_args, **_kwargs):
    raise RuntimeError("disk went away mid-write")


def test_concurrent_writers_keep_every_entry(bmox):
    """Each writer holds the profile lock from load through save, so the loser of
    a race re-reads the winner's entry instead of overwriting it."""
    os.makedirs(knowledge.bmox_dir())
    script = os.path.join(bmox.root, "writer.py")
    with open(script, "w") as f:
        f.write("import sys, time\n"
                "import knowledge\n"
                "p = knowledge.load()\n"
                "time.sleep(0.05)\n"
                "knowledge.add_gap(p, 'write-ahead-log', sys.argv[1])\n"
                "knowledge.save(p)\n")
    env = {**os.environ,
           "CLAUDE_PROJECT_DIR": bmox.root,
           "PYTHONPATH": os.path.dirname(os.path.abspath(knowledge.__file__)),
           "PYTHONDONTWRITEBYTECODE": "1"}
    writers = [subprocess.Popen([sys.executable, script, f"gap number {n}"], env=env,
                                stderr=subprocess.PIPE, text=True)
               for n in range(8)]
    for w in writers:
        _, err = w.communicate(timeout=60)
        assert w.returncode == 0, err
    gaps = bmox.profile()["concepts"]["write-ahead-log"]["open_gaps"]
    assert sorted(g["note"] for g in gaps) == [f"gap number {n}" for n in range(8)]
    assert sorted(g["id"] for g in gaps) == [f"g{n}" for n in range(1, 9)]
