"""Tests for the biological_action record shape: `source` says how the term
was derived, while `vocabulary` separately asserts membership in the AOP-Wiki
controlled vocabulary (which every derivation path guarantees for a non-null
term). Added after the two meanings were conflated in a single `source` value.

Run directly:    python -m tests.test_biological_action_record
Under pytest:    python -m pytest tests/test_biological_action_record.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.annotate_ke import (
    _action_record,
    _annotate_biological_action,
)


def test_record_separates_derivation_from_vocabulary_membership():
    rec = _action_record("increased", "llm_extraction")
    assert rec == {
        "term": "increased",
        "source": "llm_extraction",
        "vocabulary": "aop_wiki_action_terms",
    }


def test_null_term_has_null_vocabulary():
    rec = _action_record(None, "unmatched")
    assert rec["term"] is None
    assert rec["vocabulary"] is None


def test_llm_extraction_path():
    parsed = {"biological_action": "occurrence", "action_source": "llm_extraction"}
    rec = _annotate_biological_action(parsed, client=None)
    assert rec["source"] == "llm_extraction"
    assert rec["vocabulary"] == "aop_wiki_action_terms"


def test_rule_based_detection_path():
    parsed = {"biological_action": "decreased"}
    rec = _annotate_biological_action(parsed, client=None)
    assert rec["source"] == "rule_based_detection"
    assert rec["vocabulary"] == "aop_wiki_action_terms"


def test_unmatched_path_without_client():
    parsed = {"biological_action": None, "raw_direction": "weird phrasing"}
    rec = _annotate_biological_action(parsed, client=None)
    assert rec == {"term": None, "source": "unmatched", "vocabulary": None}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL TESTS PASSED ✓")
