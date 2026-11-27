"""Tests for compare_grouping_runs.compare_runs — the member-overlap matcher
and its per-type breakdown (the review categories churn far more than
merge/soda between runs, and the aggregate counts hide that).

Run directly:    python -m tests.test_compare_grouping_runs
Under pytest:    python -m pytest tests/test_compare_grouping_runs.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.compare_grouping_runs import compare_runs


def _group(gtype, *ids):
    return {"type": gtype, "member_ids": set(ids), "titles": {}}


def test_by_type_breakdown_counts_statuses_and_new():
    groups_a = {
        "m1": _group("merge", "1", "2"),                                   # identical in B
        "m2": _group("merge", "3", "4"),                                   # changed in B (gains 5)
        "sodp1": _group("same_object_different_process", "6", "7"),        # dropped
        "sedc1": _group("similar_event_different_biological_context", "8", "9"),  # identical
    }
    groups_b = {
        "b_m1": _group("merge", "1", "2"),
        "b_m2": _group("merge", "3", "4", "5"),
        "b_sedc1": _group("similar_event_different_biological_context", "8", "9"),
        "b_new_sodp": _group("same_object_different_process", "10", "11"),  # new in B
    }
    result = compare_runs(groups_a, groups_b, min_overlap=0.5)
    by_type = result["summary"]["by_type"]

    assert by_type["merge"] == {
        "a_groups": 2, "identical": 1, "changed": 1, "dropped": 0, "new_in_b": 0}
    assert by_type["same_object_different_process"] == {
        "a_groups": 1, "identical": 0, "changed": 0, "dropped": 1, "new_in_b": 1}
    assert by_type["similar_event_different_biological_context"] == {
        "a_groups": 1, "identical": 1, "changed": 0, "dropped": 0, "new_in_b": 0}
    assert by_type["soda"] == {
        "a_groups": 0, "identical": 0, "changed": 0, "dropped": 0, "new_in_b": 0}

    # The breakdown tallies with the aggregate summary.
    s = result["summary"]
    assert sum(t["identical"] for t in by_type.values()) == s["identical"]
    assert sum(t["dropped"] for t in by_type.values()) == s["dropped_only_in_a"]
    assert sum(t["new_in_b"] for t in by_type.values()) == s["new_only_in_b"]


if __name__ == "__main__":
    test_by_type_breakdown_counts_statuses_and_new()
    print("ALL TESTS PASSED ✓")
