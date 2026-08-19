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
    import os
    # Write malformed JSON to profile.json
    bmox_dir = knowledge.bmox_dir()
    os.makedirs(bmox_dir, exist_ok=True)
    profile_file = knowledge.profile_path()
    with open(profile_file, "w") as f:
        f.write("{invalid json")

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
