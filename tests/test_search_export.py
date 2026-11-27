"""
Tests for data_export/search_export.py — JSON/CSV export for config-based
searches.

Filename assembly is pure; the writers go through the real write_csv/json into
tmp_path and the output is read back with csv.DictReader / json.

Run with::

    $ uv run pytest tests/test_search_export.py
"""

import csv
import json

from aop_wiki_cli.data_export import search_export as se


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# generate_search_results_filename
# ---------------------------------------------------------------------------

def test_filename_default():
    assert se.generate_search_results_filename("cfg", "02-15-2026") == "cfg_results_02-15-2026.csv"


def test_filename_co_occurrence_only():
    assert se.generate_search_results_filename("cfg", "02-15-2026", co_occurrence_only=True) \
        == "cfg_results_co_occurrence_only_02-15-2026.csv"


def test_filename_priority_field_only_and_extension():
    name = se.generate_search_results_filename(
        "cfg", "02-15-2026", search_params={"priority_field": "title"}, extension="json"
    )
    assert name == "cfg_results_priority_field_only_02-15-2026.json"


def test_filename_priority_field_with_fields_to_search_has_no_suffix():
    name = se.generate_search_results_filename(
        "cfg", "02-15-2026", search_params={"priority_field": "title", "fields_to_search": ["x"]}
    )
    assert name == "cfg_results_02-15-2026.csv"


# ---------------------------------------------------------------------------
# export_search_results_to_json
# ---------------------------------------------------------------------------

def test_export_search_results_to_json(tmp_path):
    out = tmp_path / "r.json"
    se.export_search_results_to_json(
        {"1": {"title": "A"}}, {"total": 1}, out, "cfg", "02-15-2026", co_occurrence_only=True
    )
    data = json.loads(out.read_text())
    assert data["config"] == "cfg"
    assert data["co_occurrence_only"] is True
    assert data["results"] == {"1": {"title": "A"}}


# ---------------------------------------------------------------------------
# write_search_results_csv — the three entity branches
# ---------------------------------------------------------------------------

def test_write_search_results_csv_aops_sorted_priority_first(tmp_path):
    results = {
        "1": {"entity_id": "1", "title": "AOP one", "has_priority_co_occurrence": True,
              "snippets_by_field": {"abstract": ["s"]}, "co_occurrences": [["a", "b"]]},
        "2": {"entity_id": "2", "title": "AOP two", "has_priority_co_occurrence": False,
              "snippets_by_field": {"abstract": ["s1", "s2", "s3", "s4", "s5"]}},
    }
    entity_dict = {"1": {"sex_applicability": ["Male"], "taxonomy_applicability": [{"title": "Homo sapiens"}]}}
    out = tmp_path / "aops.csv"
    se.write_search_results_csv(results, out, "aops", entity_dict)
    rows = _read(out)
    # priority co-occurrence AOP ranks first despite fewer snippets
    assert [r["entity_id"] for r in rows] == ["1", "2"]
    assert rows[0]["co_occurrences"] == "a + b"
    assert rows[0]["taxonomy_applicability"] == "Homo sapiens"


def test_write_search_results_csv_kers_titled_by_ke_pair(tmp_path):
    results = {"10": {"entity_id": "10", "snippets_by_field": {"desc": ["s"]}, "terms_found": ["t"]}}
    entity_dict = {"10": {"upstream_ke": {"title": "U"}, "downstream_ke": {"title": "D"},
                          "has_any_tables": True, "completion_score": {"percent": 50}}}
    out = tmp_path / "kers.csv"
    se.write_search_results_csv(results, out, "kers", entity_dict)
    row = _read(out)[0]
    assert row["title"] == "U -> D"
    assert row["has_any_tables"] == "Yes"


def test_write_search_results_csv_events(tmp_path):
    results = {"100": {"entity_id": "100", "title": "E", "snippets_by_field": {"desc": ["s1", "s2"]}}}
    entity_dict = {"100": {"integration_score": 5, "has_method": True, "aop_count": 2,
                           "completion_score": {"percent": 80}}}
    out = tmp_path / "events.csv"
    se.write_search_results_csv(results, out, "events", entity_dict)
    row = _read(out)[0]
    assert row["entity_id"] == "100"
    assert row["snippet_count"] == "2"
    assert row["has_method"] == "Yes"


# ---------------------------------------------------------------------------
# write_combined_search_events_csv
# ---------------------------------------------------------------------------

def test_write_combined_search_events_csv_merges_and_flags(tmp_path):
    event_results = {
        "100": {"entity_id": "100", "title": "E100", "terms_found": ["t"],
                "matched_fields": ["title"], "snippets_by_field": {"title": ["s"]}},
    }
    aop_events = {
        "100": {"event_info": {"title": "E100"}},      # also found through AOPs
        "200": {"event_info": {"title": "E200"}},      # only found through AOPs
    }
    entity_dict = {"100": {"integration_score": 3}, "200": {"integration_score": 1}}
    out = tmp_path / "combined.csv"
    se.write_combined_search_events_csv(event_results, aop_events, entity_dict, out)
    rows = {r["entity_id"]: r for r in _read(out)}
    assert set(rows) == {"100", "200"}
    assert rows["100"]["Found in Event Search"] == "Yes"
    assert rows["100"]["Found Through AOPs"] == "Yes"
    assert rows["200"]["Found in Event Search"] == "No"
    assert rows["200"]["Found Through AOPs"] == "Yes"
