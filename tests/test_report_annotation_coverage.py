"""Tests for report_annotation_coverage.classify — the resolved/rejected/null
triage every coverage figure and worklist is built from.

Run directly:    python -m tests.test_report_annotation_coverage
Under pytest:    python -m pytest tests/test_report_annotation_coverage.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.report_annotation_coverage import classify


def test_resolved_term_with_source():
    assert classify({"term_id": "GO:1", "source": "llm_recommendation"}) == \
        ("resolved", "llm_recommendation")


def test_resolved_term_without_source_is_unknown():
    assert classify({"term_id": "GO:1"}) == ("resolved", "unknown")


def test_rejections_by_source_and_by_reason():
    assert classify({"source": "llm_rejection", "rejection_reason": "x"})[0] == "rejected"
    assert classify({"source": "manual_rejection"})[0] == "rejected"
    assert classify({"rejection_reason": "no valid term"})[0] == "rejected"


def test_null_states():
    assert classify(None) == ("null", None)
    assert classify("a bare string") == ("null", None)
    # A comment record has no term_id and no rejection — it counts as null.
    assert classify({"comment": "needs curation", "source": "manual_comment"})[0] == "null"


if __name__ == "__main__":
    test_resolved_term_with_source()
    test_resolved_term_without_source_is_unknown()
    test_rejections_by_source_and_by_reason()
    test_null_states()
    print("ALL TESTS PASSED ✓")
