"""
Tests for data_export/export_reference_search_results.py — JSON/CSV export of
parsed-citation reference-search results.

All writers go to tmp_path and are read back. ``export_structured_json`` is
handed a stub citation parser so the module is exercised without depending on
parse_references.

Run with::

    $ uv run pytest tests/test_export_reference_search_results.py
"""

import csv
import json

from aop_wiki_cli.data_export import export_reference_search_results as er


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# export_structured_json
# ---------------------------------------------------------------------------

def test_export_structured_json_groups_by_entity_type(tmp_path):
    results = [
        {"entity_type": "KE", "entity_id": "100", "citations": ["Smith 2020", "Jones 2019"]},
        {"entity_type": "AOP", "entity_id": "1", "citations": ["Lee 2021"]},
    ]
    out = tmp_path / "structured.json"
    er.export_structured_json(results, out, parse_citation_details=lambda c: {"parsed": c})
    data = json.loads(out.read_text())
    assert data["KE"]["100"]["citation_count"] == 2
    assert data["KE"]["100"]["citations"] == [{"parsed": "Smith 2020"}, {"parsed": "Jones 2019"}]
    assert data["AOP"]["1"]["citation_count"] == 1


# ---------------------------------------------------------------------------
# export_summary
# ---------------------------------------------------------------------------

def test_export_summary(tmp_path):
    results = [
        {"entity_type": "KE", "entity_id": "100", "citation_count": 3},
        {"entity_type": "AOP", "entity_id": "1", "citation_count": 1},
    ]
    out = tmp_path / "summary.csv"
    er.export_summary(results, out)
    rows = _read(out)
    assert rows[0] == {"Entity_Type": "KE", "Entity_ID": "100", "Citation_Count": "3"}
    assert rows[1]["Entity_Type"] == "AOP"


# ---------------------------------------------------------------------------
# export_search_results_to_csv
# ---------------------------------------------------------------------------

def _citation():
    return {
        "year": "2020", "authors": ["Smith J", "Jones K"], "title": "A study",
        "journal": "J Tox", "links": {"doi": "10.1/x", "urls": ["http://example.org"]},
        "other_info": "vol 1", "raw_citation": "Smith J et al. 2020...",
    }


def test_export_search_results_to_csv_empty_writes_nothing(tmp_path):
    out = tmp_path / "none.csv"
    er.export_search_results_to_csv({}, out)
    assert not out.exists()


def test_export_search_results_to_csv_tuple_and_plain_citations(tmp_path):
    search_results = {
        "100": {
            "entity_type": "KE",
            "matched_field": "references",
            "citations": [
                (_citation(), "Smith"),   # new (citation, matched_term) tuple form
                _citation(),              # old plain-citation form
            ],
        }
    }
    out = tmp_path / "refs.csv"
    er.export_search_results_to_csv(search_results, out, term_type_map={"Smith": "author"})
    rows = _read(out)
    assert len(rows) == 2
    # tuple form: matched term + type from the map
    assert rows[0]["Matched_Term"] == "Smith"
    assert rows[0]["Term_Type"] == "author"
    assert rows[0]["Entity"] == "KE 100"
    assert rows[0]["Authors"] == "Smith J; Jones K"
    assert rows[0]["URLs"] == "http://example.org"
    assert rows[0]["DOI"] == "10.1/x"
    assert rows[0]["Citation_Index"] == "1"
    # plain form: no matched term, type falls back to the matched_field
    assert rows[1]["Matched_Term"] == "N/A"
    assert rows[1]["Term_Type"] == "references"
    assert rows[1]["Citation_Index"] == "2"
