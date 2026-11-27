"""Tests for define_stable_ke_groups — the deterministic split of one group
type into groups that are identical in every replicate run, groups seen in
only some runs, and the KEs that need attention.

Run directly:    python -m tests.test_define_stable_ke_groups
Under pytest:    python -m pytest tests/test_define_stable_ke_groups.py
"""

from __future__ import annotations

import json

import pytest

from aop_wiki_cli.annotation_scripts.define_stable_ke_groups import (
    define_stable_groups,
    load_run,
    write_csvs,
)


def _snapshot(merge=None, soda=None, ungrouped=()):
    """A minimal grouping snapshot in collect_similar_events' output shape."""
    return {
        "events_to_merge": {
            key: {"merged_event_titles": {i: f"title {i}" for i in ids}, "rationale": f"r {key}"}
            for key, ids in (merge or {}).items()
        },
        "soda_events": {
            key: {"event_ids": list(ids), "event_titles": {i: f"title {i}" for i in ids}}
            for key, ids in (soda or {}).items()
        },
        "ungrouped_processed_events": {i: f"title {i}" for i in ungrouped},
    }


def _runs(*snapshots):
    return {f"run_{n}": load_run(s) for n, s in enumerate(snapshots, 1)}


def test_identical_member_sets_are_stable_regardless_of_key():
    runs = _runs(
        _snapshot(merge={"pxr": ["239", "245"]}),
        _snapshot(merge={"pxr_activation": ["245", "239"]}),  # key drifts, order differs
        _snapshot(merge={"pxr_act_2": ["239", "245"]}),
    )
    result = define_stable_groups(runs, "merge")
    assert [g["set_id"] for g in result["stable_groups"]] == ["239+245"]
    assert result["stable_groups"][0]["keys_by_run"] == {
        "run_1": "pxr", "run_2": "pxr_activation", "run_3": "pxr_act_2"}
    assert result["unstable_groups"] == []
    assert result["attention_events"] == []


def test_membership_change_makes_every_member_need_attention():
    runs = _runs(
        _snapshot(merge={"a": ["1", "2", "3"]}),
        _snapshot(merge={"a": ["1", "2"]}, ungrouped=["3"]),
        _snapshot(merge={"a": ["1", "2", "3"]}),
    )
    result = define_stable_groups(runs, "merge")
    assert result["stable_groups"] == []
    assert sorted(g["set_id"] for g in result["unstable_groups"]) == ["1+2", "1+2+3"]
    reasons = {a["event_id"]: a["reason"] for a in result["attention_events"]}
    # 1 and 2 are in a merge group every run (but not the same one);
    # 3 drops out of merge in run 2.
    assert reasons == {"1": "membership_differs", "2": "membership_differs", "3": "not_in_every_run"}
    three = next(a for a in result["attention_events"] if a["event_id"] == "3")
    assert three["by_run"]["run_2"] == {"status": "ungrouped", "groups": []}


def test_type_change_is_not_stable_and_reports_the_other_type():
    runs = _runs(
        _snapshot(merge={"vtg": ["7", "8"]}),
        _snapshot(soda={"vtg": ["7", "8"]}),  # same members, classified differently
    )
    result = define_stable_groups(runs, "merge")
    assert result["stable_groups"] == []
    assert result["unstable_groups"][0]["absent_from"] == ["run_2"]
    seven = next(a for a in result["attention_events"] if a["event_id"] == "7")
    assert seven["reason"] == "not_in_every_run"
    assert seven["by_run"]["run_2"]["groups"] == [
        {"key": "vtg", "type": "soda", "member_ids": ["7", "8"]}]


def test_event_missing_from_a_run_is_reported_as_not_in_run():
    runs = _runs(_snapshot(merge={"a": ["1", "2"]}), _snapshot())
    result = define_stable_groups(runs, "merge")
    one = next(a for a in result["attention_events"] if a["event_id"] == "1")
    assert one["by_run"]["run_2"]["status"] == "not_in_run"


def test_other_types_are_ignored_for_the_requested_type():
    runs = _runs(_snapshot(soda={"s": ["5", "6"]}), _snapshot(soda={"s": ["5", "6"]}))
    merge = define_stable_groups(runs, "merge")
    assert merge["summary"]["distinct_sets_seen"] == 0
    soda = define_stable_groups(runs, "soda")
    assert [g["set_id"] for g in soda["stable_groups"]] == ["5+6"]


def test_output_is_deterministic_and_numerically_ordered(tmp_path):
    snaps = [
        _snapshot(merge={"b": ["10", "11"], "a": ["2", "3"], "c": ["100", "101"]}),
        _snapshot(merge={"c": ["101", "100"], "a": ["3", "2"], "b": ["11", "10"]}),
    ]
    first = define_stable_groups(_runs(*snaps), "merge")
    second = define_stable_groups(_runs(*snaps), "merge")
    assert json.dumps(first) == json.dumps(second)
    assert [g["set_id"] for g in first["stable_groups"]] == ["2+3", "10+11", "100+101"]
    paths = write_csvs(first, tmp_path)
    assert [p.name for p in paths] == [
        "merge_stable_groups.csv", "merge_unstable_groups.csv", "merge_attention_events.csv"]


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError):
        define_stable_groups(_runs(_snapshot(), _snapshot()), "not_a_type")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__]))
