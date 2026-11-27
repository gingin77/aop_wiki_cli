"""Regression tests for the duplicate group_key bug in collect_similar_events.py.

The LLM assigns group_keys independently per batch, so unrelated Pass-1 groups
from different batches can share a key. Before the fix, that collision collapsed
in `_apply_consolidation_merges` and silently dropped a group's members during
Pass 2. These tests lock in the fix: keys are made unique before consolidation,
and no members are lost.

Run directly::

    python -m tests.test_group_key_dedup

Or under pytest::

    python -m pytest tests/test_group_key_dedup.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts import collect_similar_events as cse


def test_dedupe_renames_collisions():
    """Colliding keys get suffixed; the first occurrence keeps the bare key."""
    print("\n=== Test 1: duplicate keys are renamed ===")
    groups = [
        {"group_key": "apoptosis", "type": "merge", "member_ids": ["1", "2"]},
        {"group_key": "apoptosis", "type": "merge", "member_ids": ["3", "4"]},
        {"group_key": "apoptosis", "type": "merge", "member_ids": ["5", "6"]},
    ]
    cse._dedupe_group_keys(groups)
    keys = [g["group_key"] for g in groups]
    print(f"  keys after dedupe: {keys}")
    assert keys == ["apoptosis", "apoptosis_2", "apoptosis_3"]
    assert len(set(keys)) == 3
    print("✓ Test passed")


def test_dedupe_leaves_unique_keys_untouched():
    print("\n=== Test 2: already-unique keys are left alone ===")
    groups = [
        {"group_key": "fibrosis", "type": "merge", "member_ids": ["1", "2"]},
        {"group_key": "steatosis", "type": "merge", "member_ids": ["3", "4"]},
    ]
    cse._dedupe_group_keys(groups)
    assert [g["group_key"] for g in groups] == ["fibrosis", "steatosis"]
    print("✓ Test passed")


def test_consolidation_keeps_all_members_with_duplicate_keys():
    """The core bug: two unrelated groups share key 'Y' across batches.

    A Pass-2 instruction that absorbs one of them must not delete the other.
    Before the fix, filtering by key removed BOTH 'Y' groups while only one's
    members were folded into 'X', losing a,b.
    """
    print("\n=== Test 3: no member loss when a duplicated key is absorbed ===")
    all_groups = [
        {"group_key": "Y", "type": "merge", "member_ids": ["a", "b"]},
        {"group_key": "Y", "type": "merge", "member_ids": ["c", "d"]},
        {"group_key": "X", "type": "merge", "member_ids": ["e"]},
    ]
    cse._dedupe_group_keys(all_groups)
    keys = [g["group_key"] for g in all_groups]
    print(f"  keys after dedupe: {keys}")
    assert keys == ["Y", "Y_2", "X"]

    # The LLM now sees distinct keys; absorb the second group into X.
    merges = [{"keep": "X", "absorb": ["Y_2"], "rationale": "same event"}]
    result = cse._apply_consolidation_merges(all_groups, merges)

    surviving = set()
    for g in result:
        surviving.update(str(m) for m in g.get("member_ids", []))
    print(f"  surviving members: {sorted(surviving)}")
    assert surviving == {"a", "b", "c", "d", "e"}, "no members should be dropped"

    # The first 'Y' group survives intact; X absorbed c,d.
    by_key = {g["group_key"]: g for g in result}
    assert set(by_key["Y"]["member_ids"]) == {"a", "b"}
    assert set(by_key["X"]["member_ids"]) == {"e", "c", "d"}
    print("✓ Test passed")


def test_assemble_output_keeps_three_same_slug_groups():
    """Three groups whose keys slugify identically must all appear in the output.

    The old `_2`-only suffix overwrote the third; the global used-set must keep
    all three as distinct entries.
    """
    print("\n=== Test 4: three same-slug groups all survive assembly ===")
    final_groups = [
        {"group_key": "oxidative stress", "type": "merge", "member_ids": ["1", "2"]},
        {"group_key": "oxidative-stress", "type": "merge", "member_ids": ["3", "4"]},
        {"group_key": "oxidative_stress", "type": "merge", "member_ids": ["5", "6"]},
    ]
    events = {str(i): f"title {i}" for i in range(1, 7)}
    out = cse.assemble_output(
        final_groups, events, processed_ids=set(events), date_str="test",
        cache_path="x", batch_size=1,
    )
    merge_keys = list(out["events_to_merge"].keys())
    print(f"  merge bucket keys: {merge_keys}")
    assert len(merge_keys) == 3, "all three groups must be present, none overwritten"
    assert len(set(merge_keys)) == 3
    # Every member id is accounted for.
    all_members = set()
    for v in out["events_to_merge"].values():
        all_members.update(v["merged_event_titles"].keys())
    assert all_members == set(events)
    print("✓ Test passed")


def run_all_tests() -> int:
    print("\n" + "=" * 68)
    print("GROUP-KEY DEDUP REGRESSION TESTS")
    print("=" * 68)
    test_dedupe_renames_collisions()
    test_dedupe_leaves_unique_keys_untouched()
    test_consolidation_keeps_all_members_with_duplicate_keys()
    test_assemble_output_keeps_three_same_slug_groups()
    print("\n" + "=" * 68)
    print("ALL TESTS PASSED ✓")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
