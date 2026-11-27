"""
Tests for harmonization/harmonize_tabulated_evidence.py — mapping the varied
column headers of KER evidence tables onto canonical names.

All pure: text normalization, semantic matching against the KE-variation groups,
the four-strategy header matcher, per-field/per-KER harmonization, the top-level
``harmonize_evidence_headers`` roll-up, and the harmonizer inversion.

Run with::

    $ uv run pytest tests/test_harmonize_tabulated_evidence.py
"""

import pytest

from aop_wiki_cli.harmonization import harmonize_tabulated_evidence as h


# A KER whose weight-of-evidence table has upstream, downstream and reference
# columns (plus a note) → harmonizable.
HARMONIZABLE_KER = {
    "upstream_ke": {"id": "1", "title": "Oxidative stress"},
    "downstream_ke": {"id": "2", "title": "Cell death"},
    "aop_ids": ["100"],
    "weight_of_evidence": {
        "headers": ["ke up", "ke down", "ref", "notes"],
        "tables": {"t1": [{"ke up": "A", "ke down": "B", "ref": "R", "notes": "n"}]},
    },
}

# A KER whose table lacks the up/down/reference trio → not harmonizable.
NON_HARMONIZABLE_KER = {
    "upstream_ke": {"id": "3", "title": "Foo"},
    "downstream_ke": {"id": "4", "title": "Bar"},
    "aop_ids": ["200"],
    "weight_of_evidence": {
        "headers": ["dose", "notes"],
        "tables": {"t1": [{"dose": "10", "notes": "n"}]},
    },
}


# ---------------------------------------------------------------------------
# normalize_text_for_matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("The Dose-Response", "dose response"),
    ("  Upstream,  KE  ", "ke"),
    ("Species (taxa)", "species taxa"),
])
def test_normalize_text_for_matching(text, expected):
    assert h.normalize_text_for_matching(text) == expected


# ---------------------------------------------------------------------------
# find_semantic_match
# ---------------------------------------------------------------------------

def test_find_semantic_match_true():
    assert h.find_semantic_match("decreased testosterone", "testosterone production/levels") is True


def test_find_semantic_match_false():
    assert h.find_semantic_match("random header", "unrelated title") is False


# ---------------------------------------------------------------------------
# _match_header_to_harmonized (the four strategies)
# ---------------------------------------------------------------------------

def test_match_header_direct_mapping():
    assert h._match_header_to_harmonized("Dose", h.COLUMN_HARMONIZER, "u", "d") == ("Dose", True)


@pytest.mark.parametrize("header, expected", [
    ("KE down: effect", "Downstream Key Event"),
    ("upstream something", "Upstream Key Event"),
])
def test_match_header_keyword(header, expected):
    assert h._match_header_to_harmonized(header, h.COLUMN_HARMONIZER, "u", "d") == (expected, True)


def test_match_header_semantic_upstream_and_downstream():
    up = h._match_header_to_harmonized(
        "decreased testosterone", h.COLUMN_HARMONIZER, "testosterone production/levels", "abc")
    assert up == ("Upstream Key Event", True)
    down = h._match_header_to_harmonized(
        "decreased testosterone", h.COLUMN_HARMONIZER, "abc", "testosterone production/levels")
    assert down == ("Downstream Key Event", True)


def test_match_header_fuzzy_upstream_and_downstream():
    assert h._match_header_to_harmonized("cell death", h.COLUMN_HARMONIZER, "cell death", "zzz") \
        == ("Upstream Key Event", True)
    assert h._match_header_to_harmonized("tissue injury", h.COLUMN_HARMONIZER, "zzz", "tissue injury") \
        == ("Downstream Key Event", True)


def test_match_header_no_match():
    assert h._match_header_to_harmonized("xyz", h.COLUMN_HARMONIZER, "abc", "def") == (None, False)


# ---------------------------------------------------------------------------
# _harmonize_tables
# ---------------------------------------------------------------------------

def test_harmonize_tables_maps_and_skips_unharmonizable_rows():
    harmonized_evidence = {
        "harmonized_headers": {"ke up": "Upstream Key Event", "ke down": "Downstream Key Event", "ref": "References"},
        "unmatched_headers": {"notes"},
    }
    tables = {"t1": [
        {"ke up": "A", "ke down": "B", "ref": "R", "notes": "n"},
        {"other": "x"},  # no harmonizable key → dropped
    ]}
    out = h._harmonize_tables(tables, "10", harmonized_evidence)
    assert out["t1"] == [{
        "Upstream Key Event": "A", "Downstream Key Event": "B", "References": "R", "notes": "n",
    }]


# ---------------------------------------------------------------------------
# _process_ker_headers
# ---------------------------------------------------------------------------

def test_process_ker_headers_harmonizable():
    record, is_harmonizable = h._process_ker_headers("10", HARMONIZABLE_KER, h.COLUMN_HARMONIZER)
    assert is_harmonizable is True
    assert record["harmonized_fields"] == ["weight_of_evidence"]
    # harmonized_headers is converted to a list of the original header names;
    # the canonical mapping lives in header_mapping
    assert "ke up" in record["harmonized_headers"]
    assert record["header_mapping"]["ke up"] == "Upstream Key Event"
    assert "weight_of_evidence" in record["harmonized_tables"]


def test_process_ker_headers_not_harmonizable():
    record, is_harmonizable = h._process_ker_headers("20", NON_HARMONIZABLE_KER, h.COLUMN_HARMONIZER)
    assert is_harmonizable is False
    assert record["harmonized_fields"] == []


# ---------------------------------------------------------------------------
# harmonize_evidence_headers (top level)
# ---------------------------------------------------------------------------

def test_harmonize_evidence_headers_rollup():
    kers = {
        "average_completion_scores": {"ignored": True},  # non-KER entry, filtered out
        "10": HARMONIZABLE_KER,
        "20": NON_HARMONIZABLE_KER,
    }
    result = h.harmonize_evidence_headers(kers)
    counts = result["summary"]["counts"]
    assert counts["Count KERs with tabulated evidence"] == 2
    assert result["summary"]["harmonizable_kers"] == ["10"]
    # per-KER records are merged into the result; the non-KER entry is gone
    assert "10" in result and "20" in result
    assert "average_completion_scores" not in result
    # AOP tracking
    assert result["summary"]["aops_harm_evi"] == ["100"]


# ---------------------------------------------------------------------------
# transform_column_harmonizer
# ---------------------------------------------------------------------------

def test_transform_column_harmonizer_inverts():
    inverted = h.transform_column_harmonizer(h.COLUMN_HARMONIZER)
    assert "ref" in inverted["References"]
    assert "reference" in inverted["References"]
    assert "ke up" in inverted["Upstream Key Event"]
