"""Regression tests for src.utilities.helpers.insert_after.

process_manual_curations_csv.py stamps provenance paths onto the integrated output
with two chained insert_after calls: the first inserts ``llm_annotation_file``
after ``source_cache``, the second inserts ``manual_annotation_file`` after
``llm_annotation_file``. An earlier version dropped the new key whenever the
anchor key was absent, so a metadata block without ``source_cache`` (e.g. an
older grouping file) silently lost BOTH provenance paths. These tests lock in
the fix: a missing anchor appends at the end instead of dropping the value.

Run directly::

    python -m tests.test_insert_after

Or under pytest::

    python -m pytest tests/test_insert_after.py
"""

from __future__ import annotations

from aop_wiki_cli.utilities.helpers import insert_after


def test_inserts_after_existing_anchor():
    """new_key lands immediately after after_key, order otherwise preserved."""
    print("\n=== Test: insert after existing anchor ===")
    d = {"a": 1, "source_cache": 2, "z": 3}
    result = insert_after(d, "source_cache", "llm_annotation_file", "path.json")
    assert list(result.items()) == [
        ("a", 1),
        ("source_cache", 2),
        ("llm_annotation_file", "path.json"),
        ("z", 3),
    ]
    print("✓ inserted directly after the anchor")


def test_appends_when_anchor_missing():
    """A missing anchor appends at the end rather than silently dropping."""
    print("\n=== Test: anchor missing -> append ===")
    d = {"a": 1, "z": 3}
    result = insert_after(d, "source_cache", "llm_annotation_file", "path.json")
    assert result["llm_annotation_file"] == "path.json"
    assert list(result)[-1] == "llm_annotation_file"
    print("✓ appended at end, value not dropped")


def test_chained_inserts_survive_missing_first_anchor():
    """The real call pattern: both provenance keys survive even without source_cache."""
    print("\n=== Test: chained inserts, source_cache absent ===")
    metadata = {"generated_at": "2026-11-26"}  # no source_cache
    metadata = insert_after(metadata, "source_cache", "llm_annotation_file", "llm.json")
    metadata = insert_after(metadata, "llm_annotation_file", "manual_annotation_file", "manual.json")
    assert metadata["llm_annotation_file"] == "llm.json"
    assert metadata["manual_annotation_file"] == "manual.json"
    # Second insert anchors on the key the first appended, so they stay adjacent.
    keys = list(metadata)
    assert keys.index("manual_annotation_file") == keys.index("llm_annotation_file") + 1
    print("✓ both provenance paths present and adjacent")


def test_existing_new_key_is_replaced_not_kept_stale():
    """Re-stamping must take the new value: an existing new_key after the
    anchor previously overwrote the inserted value with the stale one."""
    print("\n=== Test: existing new_key replaced ===")
    d = {"a": 1, "x": "old"}
    result = insert_after(d, "a", "x", "new")
    assert result == {"a": 1, "x": "new"}
    # Also when the stale key precedes the anchor: it moves after it.
    d2 = {"x": "old", "a": 1}
    result2 = insert_after(d2, "a", "x", "new")
    assert list(result2.items()) == [("a", 1), ("x", "new")]
    print("✓ stale value replaced in both positions")


def test_does_not_mutate_input():
    """The input dict is left untouched; a new dict is returned."""
    print("\n=== Test: input not mutated ===")
    d = {"a": 1, "source_cache": 2}
    insert_after(d, "source_cache", "new", "v")
    assert "new" not in d
    print("✓ input dict unchanged")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
