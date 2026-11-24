"""Regression/monitoring tests for collect_similar_events.py groupings.

These tests assert that pairings you rely on stay grouped together across runs
even as prompts, batch sizes, or the model change. Expected pairings live in
``tests/expected_ke_groupings.json`` — edit that file to add your own; no code
changes needed.

What is checked
---------------
For each expectation, every listed Event ID must appear in the SAME output group,
and (when ``expected_type`` is given) that shared group must be of that type.

Which output file
-----------------
By default the newest ``ke_similar_events_*_pass3.json`` (falling back to
``_pass2``) under ``outputs/ke_groupings`` or ``outputs_for_vc/ke_groupings`` is
used. Point at a specific run with the ``KE_GROUPINGS_FILE`` environment variable::

    KE_GROUPINGS_FILE=outputs/ke_groupings/05-07-2026/ke_similar_events_05-07-2026_pass3.json \
        python -m pytest tests/test_expected_ke_groupings.py

Run directly for a readable report::

    python -m tests.test_expected_ke_groupings
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:  # direct-run / stdlib-only environments
    _HAS_PYTEST = False

# Repo root = parent of the tests/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = Path(__file__).resolve().parent / "expected_ke_groupings.json"

# Output-bucket (top-level JSON key) -> logical group type.
BUCKET_TYPE: dict[str, str] = {
    "events_to_merge": "merge",
    "soda_events": "soda",
    "same_object_different_process_events": "same_object_different_process",
    "similar_event_different_biological_context_events": "similar_event_different_biological_context",
}
VALID_TYPES = set(BUCKET_TYPE.values())
# Reverse lookup: type -> bucket key.
TYPE_BUCKET: dict[str, str] = {v: k for k, v in BUCKET_TYPE.items()}

OUTPUT_ROOTS = ("outputs/ke_groupings", "outputs_for_vc/ke_groupings")


# ---------------------------------------------------------------------------
# Locating and loading the output snapshot
# ---------------------------------------------------------------------------

def discover_output_file() -> Path | None:
    """Return the output JSON to check, or None if none can be found.

    Priority: $KE_GROUPINGS_FILE, else the newest *_pass3.json across the known
    output roots, else the newest *_pass2.json.
    """
    env = os.environ.get("KE_GROUPINGS_FILE")
    if env:
        p = Path(env)
        return p if p.exists() else None

    for suffix in ("_pass3.json", "_pass2.json"):
        candidates: list[Path] = []
        for root in OUTPUT_ROOTS:
            root_path = REPO_ROOT / root
            if root_path.is_dir():
                candidates.extend(root_path.glob(f"**/ke_similar_events_*{suffix}"))
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_mtime)
    return None


def _member_ids(group: dict, bucket: str) -> list[str]:
    """IDs for one group entry. Merge groups key IDs under merged_event_titles;
    the other three buckets use the event_ids list."""
    if bucket == "events_to_merge":
        return list(group.get("merged_event_titles", {}).keys())
    return [str(i) for i in group.get("event_ids", [])]


def _titles(group: dict, bucket: str) -> dict[str, str]:
    if bucket == "events_to_merge":
        return group.get("merged_event_titles", {})
    return group.get("event_titles", {})


def build_index(data: dict) -> tuple[dict[str, set[tuple[str, str]]], dict[str, str], set[str]]:
    """Index one output snapshot.

    Returns:
      id_to_groups: event_id -> set of (bucket, group_key) it belongs to.
      id_to_title:  event_id -> title (from any group or the ungrouped list).
      ungrouped:    event_ids left in ungrouped_processed_events.
    """
    id_to_groups: dict[str, set[tuple[str, str]]] = {}
    id_to_title: dict[str, str] = {}

    for bucket in BUCKET_TYPE:
        for group_key, group in data.get(bucket, {}).items():
            titles = _titles(group, bucket)
            for ke_id in _member_ids(group, bucket):
                ke_id = str(ke_id)
                id_to_groups.setdefault(ke_id, set()).add((bucket, group_key))
                if ke_id not in id_to_title and titles.get(ke_id):
                    id_to_title[ke_id] = titles[ke_id]

    ungrouped: set[str] = set()
    for ke_id, title in data.get("ungrouped_processed_events", {}).items():
        ke_id = str(ke_id)
        ungrouped.add(ke_id)
        id_to_title.setdefault(ke_id, title)

    return id_to_groups, id_to_title, ungrouped


# ---------------------------------------------------------------------------
# Checking one expectation
# ---------------------------------------------------------------------------

def _describe_location(
    ke_id: str,
    id_to_groups: dict[str, set[tuple[str, str]]],
    ungrouped: set[str],
) -> str:
    groups = id_to_groups.get(ke_id)
    if groups:
        return ", ".join(f"{BUCKET_TYPE[b]}:{k}" for b, k in sorted(groups))
    if ke_id in ungrouped:
        return "UNGROUPED (processed but placed in no group)"
    return "NOT FOUND in output (filtered out, or not processed)"


def check_expectation(
    expectation: dict,
    id_to_groups: dict[str, set[tuple[str, str]]],
    id_to_title: dict[str, str],
    ungrouped: set[str],
) -> tuple[bool, str]:
    """Return (passed, message). message explains a failure in full."""
    label = expectation.get("label", "<unlabeled>")
    ids = [str(i) for i in expectation.get("event_ids", [])]
    expected_type = expectation.get("expected_type")

    if len(ids) < 2:
        return False, f"{label!r}: needs at least 2 event_ids, got {ids}."
    if expected_type is not None and expected_type not in VALID_TYPES:
        return False, (
            f"{label!r}: expected_type {expected_type!r} is not one of "
            f"{sorted(VALID_TYPES)}."
        )

    # Groups shared by ALL listed IDs.
    group_sets = [id_to_groups.get(i, set()) for i in ids]
    common = set.intersection(*group_sets) if group_sets else set()

    def _roster() -> str:
        lines = []
        for i in ids:
            title = id_to_title.get(i, "?")
            where = _describe_location(i, id_to_groups, ungrouped)
            lines.append(f"      - {i} ({title}) -> {where}")
        return "\n".join(lines)

    if not common:
        return False, (
            f"{label!r}: expected IDs {ids} in one shared group, but they are "
            f"split apart.\n{_roster()}"
        )

    if expected_type is not None:
        wanted_bucket = TYPE_BUCKET[expected_type]
        if not any(bucket == wanted_bucket for bucket, _ in common):
            shared = ", ".join(f"{BUCKET_TYPE[b]}:{k}" for b, k in sorted(common))
            return False, (
                f"{label!r}: IDs {ids} are grouped together, but not as "
                f"{expected_type!r}. Shared group(s): {shared}.\n{_roster()}"
            )

    return True, f"{label!r}: OK"


# ---------------------------------------------------------------------------
# Loading the fixture
# ---------------------------------------------------------------------------

def load_expectations() -> list[dict]:
    with open(FIXTURE_PATH) as f:
        fixture = json.load(f)
    return fixture.get("expectations", [])


# Loaded once at import so pytest can parametrize over them.
_EXPECTATIONS = load_expectations()
_OUTPUT_FILE = discover_output_file()


def _case_id(expectation: dict) -> str:
    return expectation.get("label", "unlabeled").replace(" ", "_")


if _HAS_PYTEST:
    @pytest.mark.skipif(not _EXPECTATIONS, reason="no expectations defined in expected_ke_groupings.json")
    @pytest.mark.skipif(
        _OUTPUT_FILE is None,
        reason=(
            "no ke_similar_events_*.json output found under outputs/ke_groupings or "
            "outputs_for_vc/ke_groupings; set KE_GROUPINGS_FILE to a specific run"
        ),
    )
    @pytest.mark.parametrize("expectation", _EXPECTATIONS, ids=[_case_id(e) for e in _EXPECTATIONS])
    def test_expected_grouping(expectation: dict) -> None:
        with open(_OUTPUT_FILE) as f:
            data = json.load(f)
        id_to_groups, id_to_title, ungrouped = build_index(data)
        passed, message = check_expectation(expectation, id_to_groups, id_to_title, ungrouped)
        assert passed, f"\nChecked: {_OUTPUT_FILE}\n{message}"


# ---------------------------------------------------------------------------
# Direct-run report (mirrors the style of test_search_text_by_field.py)
# ---------------------------------------------------------------------------

def run_all_tests() -> int:
    print("\n" + "=" * 68)
    print("EXPECTED KE GROUPINGS CHECK")
    print("=" * 68)

    if _OUTPUT_FILE is None:
        print("\nNo output file found. Set KE_GROUPINGS_FILE or run collect_similar_events.py.")
        return 1
    print(f"\nChecking: {_OUTPUT_FILE}")

    expectations = load_expectations()
    if not expectations:
        print("No expectations defined in expected_ke_groupings.json.")
        return 1

    with open(_OUTPUT_FILE) as f:
        data = json.load(f)
    id_to_groups, id_to_title, ungrouped = build_index(data)

    failures = 0
    for expectation in expectations:
        passed, message = check_expectation(expectation, id_to_groups, id_to_title, ungrouped)
        mark = "✓" if passed else "✗"
        print(f"\n{mark} {message}")
        if not passed:
            failures += 1

    print("\n" + "=" * 68)
    if failures:
        print(f"{failures} of {len(expectations)} expectation(s) FAILED")
    else:
        print(f"All {len(expectations)} expectation(s) passed ✓")
    print("=" * 68 + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
