"""Regression tests for _parse_json_from_response in collect_similar_events.py.

Current-generation models run with thinking off sometimes append commentary
after the JSON (e.g. a `[...]` array followed by "Correction: ... Final
answer:"). A plain json.loads rejects that as "Extra data", which silently
dropped a Pass 2 consolidation call (returning groups unmerged) and could blank
Pass 3 straggler batches. These tests lock in the fix: the parser decodes the
first complete JSON value and ignores any trailing prose.

Run directly::

    python -m tests.test_parse_json_from_response

Or under pytest::

    python -m pytest tests/test_parse_json_from_response.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "annotation_scripts" / "collect_similar_events.py"


def _load_module():
    """Import collect_similar_events.py by path (annotation_scripts is not a package)."""
    spec = importlib.util.spec_from_file_location("collect_similar_events", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cse = _load_module()

# The exact Pass 2 payload observed in the logs: valid JSON then a retraction.
_LEAKED_PASS2 = (
    '[\n  {\n    "keep": "lh_secretion_increase",\n    "absorb": [],\n'
    '    "rationale": "placeholder"\n  }\n]\n\n'
    "Correction: I have no valid cross-batch merges to make. "
    "The above entry was erroneous. Final answer:\n"
)


def test_array_with_trailing_prose():
    """A JSON array followed by commentary parses to just the array."""
    print("\n=== Test: array + trailing prose ===")
    result = cse._parse_json_from_response(_LEAKED_PASS2)
    assert result == [{"keep": "lh_secretion_increase", "absorb": [], "rationale": "placeholder"}]
    print("✓ parsed the leading array, ignored the retraction prose")


def test_object_with_trailing_prose():
    """A Pass 3-shaped object followed by prose parses to the object."""
    print("\n=== Test: object + trailing prose ===")
    raw = '{"existing_group_assignments": [], "new_groups": []}\nDone — nothing to assign.'
    result = cse._parse_json_from_response(raw)
    assert result == {"existing_group_assignments": [], "new_groups": []}
    print("✓ parsed the object, ignored trailing text")


def test_fenced_json():
    """JSON inside a markdown code fence still parses."""
    print("\n=== Test: fenced JSON ===")
    raw = 'Here you go:\n```json\n[{"a": 1}]\n```\nthanks!'
    assert cse._parse_json_from_response(raw) == [{"a": 1}]
    print("✓ parsed fenced JSON")


def test_plain_json_unchanged():
    """Bare JSON with no surrounding text is unaffected by the fix."""
    print("\n=== Test: plain JSON ===")
    raw = '[{"keep": "x", "absorb": ["y"]}]'
    assert cse._parse_json_from_response(raw) == [{"keep": "x", "absorb": ["y"]}]
    print("✓ parsed plain JSON")


def test_no_json_returns_none():
    """A response with no JSON returns None (caller treats as empty)."""
    print("\n=== Test: no JSON ===")
    assert cse._parse_json_from_response("I have no merges to suggest.") is None
    print("✓ returned None")


def test_leading_prose_before_json():
    """Prose before the JSON is skipped to the first bracket."""
    print("\n=== Test: leading prose ===")
    raw = 'After review, the groups are: [{"keep": "a", "absorb": []}]'
    assert cse._parse_json_from_response(raw) == [{"keep": "a", "absorb": []}]
    print("✓ parsed JSON after leading prose")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
