"""Regression tests for compare_pass_2_vs_pass_3.py.

Locks in two fixes:
  - _extract_all_groups no longer silently drops a group when the same
    group_key is reused across buckets (older output files).
  - _sort_ids no longer crashes when numeric and non-numeric IDs are mixed.

Run directly::

    python -m tests.test_compare_pass_2_vs_pass_3

Or under pytest::

    python -m pytest tests/test_compare_pass_2_vs_pass_3.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts import compare_pass_2_vs_pass_3 as cmp


def test_cross_bucket_key_collision_keeps_both_groups():
    """A merge group and a soda group sharing a slug must both survive."""
    print("\n=== Test 1: cross-bucket key collision keeps both groups ===")
    data = {
        "events_to_merge": {
            "foo": {"merged_event_titles": {"1": "a", "2": "b"}, "rationale": "m"},
        },
        "soda_events": {
            "foo": {"event_ids": ["3", "4"], "event_titles": {"3": "c", "4": "d"}, "rationale": "s"},
        },
        "same_object_different_process_events": {},
        "similar_event_different_biological_context_events": {},
    }
    groups = cmp._extract_all_groups(data)
    print(f"  keys: {sorted(groups)}")
    assert len(groups) == 2, "both groups must be retained, not collapsed"
    types = sorted(g["type"] for g in groups.values())
    assert types == ["merge", "soda"]
    # No member IDs lost.
    assert cmp._all_grouped_ids(groups) == {"1", "2", "3", "4"}
    print("✓ Test passed")


def test_sort_ids_mixed_numeric_and_text():
    """Numeric IDs sort numerically and ahead of non-numeric; no TypeError."""
    print("\n=== Test 2: _sort_ids handles mixed ID kinds ===")
    out = cmp._sort_ids({"10", "2", "1", "abc", "KE:5"})
    print(f"  sorted: {out}")
    assert out[:3] == ["1", "2", "10"], "numeric IDs sort numerically"
    assert set(out[3:]) == {"abc", "KE:5"}, "non-numeric IDs follow, order-stable among themselves"
    print("✓ Test passed")


def test_compare_smoke_expand_and_new_group():
    """End-to-end compare(): one expanded group and one brand-new pass-3 group."""
    print("\n=== Test 3: compare() detects expansion and new groups ===")
    pass2 = {
        "events_to_merge": {
            "grp": {"merged_event_titles": {"1": "a", "2": "b"}, "rationale": "r"},
        },
        "soda_events": {},
        "same_object_different_process_events": {},
        "similar_event_different_biological_context_events": {},
        "ungrouped_processed_events": {"5": "e", "6": "f"},
    }
    pass3 = {
        "events_to_merge": {
            "grp": {"merged_event_titles": {"1": "a", "2": "b", "5": "e"}, "rationale": "r"},
        },
        "soda_events": {
            "newpair": {"event_ids": ["6", "9"], "event_titles": {"6": "f", "9": "i"}, "rationale": "n"},
        },
        "same_object_different_process_events": {},
        "similar_event_different_biological_context_events": {},
        "ungrouped_processed_events": {},
    }
    result = cmp.compare(pass2, pass3)
    t = result["totals"]
    print(f"  totals: {t}")
    assert t["groups_expanded_by_pass3"] == 1          # 'grp' gained member 5
    assert t["new_groups_created_by_pass3"] == 1        # 'newpair'
    assert t["events_newly_grouped_by_pass3"] == 2      # 5 and 6 left ungrouped
    assert t["pass2_total_ungrouped"] == 2
    assert t["pass3_total_ungrouped"] == 0
    # The expanded group reports the added id.
    eg = result["expanded_groups"][0]
    assert eg["group_key"] == "grp" and eg["added_ids"] == ["5"]
    print("✓ Test passed")


def run_all_tests() -> int:
    print("\n" + "=" * 68)
    print("COMPARE PASS 2 vs PASS 3 — REGRESSION TESTS")
    print("=" * 68)
    test_cross_bucket_key_collision_keeps_both_groups()
    test_sort_ids_mixed_numeric_and_text()
    test_compare_smoke_expand_and_new_group()
    print("\n" + "=" * 68)
    print("ALL TESTS PASSED ✓")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
