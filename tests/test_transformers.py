"""
Tests for data_export/transformers.py — the field-transform functions that
flatten nested entity structures into CSV/Excel cells, plus the row-builders
and the name->function registry the exporters look transforms up in.

All pure value-in/value-out, so these build minimal inputs and assert the
rendered output and the None/non-matching-type fallbacks.

Run with::

    $ uv run pytest tests/test_transformers.py
"""

import pytest

from aop_wiki_cli.data_export import transformers as t


# ---------------------------------------------------------------------------
# scalar transforms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("a\n b   c", "a b c"),
    (123, "123"),
    (None, ""),
])
def test_clean_text(value, expected):
    assert t.clean_text(value) == expected


@pytest.mark.parametrize("value, expected", [
    (1.234, "1.23"),
    ("2", "2.00"),
    ("not a number", "not a number"),
    (None, ""),
])
def test_round_2(value, expected):
    assert t.round_2(value) == expected


@pytest.mark.parametrize("value, expected", [(True, "Yes"), (1, "Yes"), (False, "No"), (None, "No"), ([], "No")])
def test_yes_no(value, expected):
    assert t.yes_no(value) == expected


@pytest.mark.parametrize("value, expected", [
    (["a", "", None, "b"], "a, b"),     # None/empty filtered
    (("x", "y"), "x, y"),
    ("plain", "plain"),
    (None, ""),
])
def test_join_list(value, expected):
    assert t.join_list(value) == expected


# ---------------------------------------------------------------------------
# dict/list extractors
# ---------------------------------------------------------------------------

def test_extract_key_value_from_dicts():
    value = [{"title": "T1"}, {"title": ""}, {"nope": "x"}, "loose"]
    assert t.extract_key_value_from_dicts(value) == "T1, loose"


def test_extract_key_value_non_list_fallback():
    assert t.extract_key_value_from_dicts("solo") == "solo"
    assert t.extract_key_value_from_dicts(None) == ""


def test_extract_titles_and_sources_wrappers():
    items = [{"title": "Homo sapiens", "source": "NCBI"}]
    assert t.extract_titles_from_dicts(items) == "Homo sapiens"
    assert t.extract_sources_from_dicts(items) == "NCBI"


@pytest.mark.parametrize("value, expected", [
    ({"source": "UBERON", "term": "liver"}, "UBERON: liver"),
    ({"term": "liver"}, "liver"),
    ({}, ""),
    ("fallback", "fallback"),
])
def test_format_term_with_source(value, expected):
    assert t.format_term_with_source(value) == expected


def test_extract_ec_components():
    ecs = [
        {"biological_object": {"term": "hepatocyte"}, "biological_action": {"term": "increased"},
         "biological_process": {"term": "apoptosis"}},
        {"biological_object": {}},  # no term -> skipped
    ]
    assert t.extract_ec_objects(ecs) == "hepatocyte"
    assert t.extract_ec_actions(ecs) == "increased"
    assert t.extract_ec_processes(ecs) == "apoptosis"
    assert t.extract_ec_objects("not a list") == ""


# ---------------------------------------------------------------------------
# flatten_ordered_events
# ---------------------------------------------------------------------------

def test_flatten_ordered_events_empty_and_string_and_nondict():
    assert t.flatten_ordered_events(None) == ""
    assert t.flatten_ordered_events("orphaned event message") == "orphaned event message"
    assert t.flatten_ordered_events(42) == ""


def test_flatten_ordered_events_linear():
    ordered = {"path_to_ao": {"0": {"event_id": 1, "title": "A"}, "1": {"event_id": 2, "title": "B"}}}
    assert t.flatten_ordered_events(ordered) == "1:A → 2:B"


def test_flatten_ordered_events_branched():
    ordered = {
        "path_before_branching": {"0": {"event_id": 1, "title": "A"}},
        "divergent_branches": [
            {"events": {"0": {"event_id": 2, "title": "B"}}},
            {"events": {"0": {"event_id": 3, "title": "C"}}},
        ],
        "path_after_branching": {"0": {"event_id": 4, "title": "D"}},
    }
    assert t.flatten_ordered_events(ordered) == "1:A [BRANCHES: 2:B | 3:C] 4:D"


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def test_get_transformer_known_and_unknown():
    assert t.get_transformer("yes_no") is t.yes_no
    assert t.get_transformer("to_json_string") is not None
    assert t.get_transformer("does_not_exist") is None


# ---------------------------------------------------------------------------
# prepare_concordance_results_for_export
# ---------------------------------------------------------------------------

def test_prepare_concordance_enriches_and_sorts_sets():
    search_results = {
        "10": {
            "snippets_by_field": {"desc": {"b", "a"}},
            "terms_found": {"y", "x"},
            "matched_fields": {"f2", "f1"},
            "co_occurrences": {("b", "a")},
            "co_occurrence_fields": {"g2", "g1"},
        }
    }
    all_kers = {"10": {"upstream_ke": {"title": "U"}, "downstream_ke": {"title": "D"}, "aop_ids": ["1"]}}
    out = t.prepare_concordance_results_for_export(search_results, all_kers)
    r = out["10"]
    assert (r["upstream_ke"], r["downstream_ke"], r["aops"]) == ("U", "D", ["1"])
    assert r["snippets_by_field"]["desc"] == ["a", "b"]
    assert r["terms_found"] == ["x", "y"]
    assert r["matched_fields"] == ["f1", "f2"]
    # each pair keeps its internal order; only the outer list of pairs is sorted
    assert r["co_occurrences"] == [["b", "a"]]
    assert r["co_occurrence_fields"] == ["g1", "g2"]


def test_prepare_concordance_missing_ker_uses_na():
    search_results = {"99": {}}
    out = t.prepare_concordance_results_for_export(search_results, {})
    assert out["99"]["upstream_ke"] == "N/A"
    assert out["99"]["aops"] == []


# ---------------------------------------------------------------------------
# mapping / row builders
# ---------------------------------------------------------------------------

def test_build_aop_to_ker_mapping_skips_empty():
    aop_info = {"1": {"kers": {"123": {}, "456": {}}}, "2": {"kers": {}}, "3": {}}
    assert t.build_aop_to_ker_mapping(aop_info) == {"1": ["123", "456"]}


def test_build_submitted_title_by_event_id_filters_and_stringifies():
    entries = [
        {"event_id": 1, "submitted_title": "Title one"},
        {"event_id": 2, "submitted_title": ""},        # empty title dropped
        {"event_id": None, "submitted_title": "x"},    # missing id dropped
    ]
    assert t.build_submitted_title_by_event_id(entries) == {"1": "Title one"}


def test_build_seizure_extracted_rows():
    curations = {"1": {"0": {"event_id": "100", "title": "T", "event_match": True}}}
    rows = t.build_seizure_extracted_rows(curations)
    assert rows[0]["aop_id"] == "1"
    assert rows[0]["event_id"] == "100"
    assert rows[0]["event_match"] is True
    assert rows[0]["event_index"] == "0"  # falls back to the dict key


def test_build_seizure_ke_desc_mapping_rows():
    mappings = {"desc": {"assays": ["a1"], "target_families": {"TF1"}}}
    rows = t.build_seizure_ke_desc_mapping_rows(mappings)
    assert rows[0]["ke_description"] == "desc"
    assert rows[0]["assays"] == ["a1"]
    assert rows[0]["target_families"] == ["TF1"]


def test_build_seizure_summary_rows():
    summary = {"harmonized_kes": {"H1": {"total_events": 2, "lobos": ["Tissue"]}}}
    rows = t.build_seizure_summary_rows(summary)
    assert rows[0]["harmonized_title"] == "H1"
    assert rows[0]["total_events"] == 2
    assert rows[0]["lobos"] == ["Tissue"]


def test_build_seizure_ke_desc_to_harmonized_rows():
    reviewed = [{"input_term": "d", "matched_term": "H", "match_score": 0.9, "human_verified": True}]
    rows = t.build_seizure_ke_desc_to_harmonized_rows(reviewed)
    assert rows[0] == {
        "ke_description": "d",
        "harmonized_ke_match": "H",
        "match_score": 0.9,
        "human_verified": True,
        "suggested_match": "",
    }


def test_flatten_harmonized_events():
    harmonized = {"H1": {"100": {"0": {"aop_id": "1", "title": "T", "lobo": "Tissue"}}}}
    rows = t.flatten_harmonized_events(harmonized)
    assert rows[0]["harmonized_title"] == "H1"
    assert rows[0]["event_id"] == "100"
    assert rows[0]["row_index"] == "0"
    assert rows[0]["aop_id"] == "1"
    assert rows[0]["lobo"] == "Tissue"
