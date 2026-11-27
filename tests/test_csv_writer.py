"""
Tests for data_export/csv_writer.py — the unified CSV writer: nested-value
lookup, row transformation via field configs, the generic ``write_csv`` (dict or
list input, sorting, empty handling), the simple key/value stats writer, and the
entity-specific wrappers that flatten nested structures before writing.

Everything writes into ``tmp_path`` and is read back with ``csv.DictReader``.

Run with::

    $ uv run pytest tests/test_csv_writer.py
"""

import csv

import pytest

from aop_wiki_cli.data_export import csv_writer as cw
from aop_wiki_cli.data_export.field_definitions import FieldConfig, FieldConfigSet


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# get_nested_value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key_path, expected", [
    ("title", "T"),
    ("score.percent", 90),
    ("score.missing", "DEF"),       # missing leaf -> default
    ("missing.deep", "DEF"),        # missing branch -> default
    ("title.deeper", "DEF"),        # descend into a non-dict -> default
])
def test_get_nested_value(key_path, expected):
    data = {"title": "T", "score": {"percent": 90}}
    assert cw.get_nested_value(data, key_path, "DEF") == expected


def test_get_nested_value_none_becomes_default():
    assert cw.get_nested_value({"k": None}, "k", "DEF") == "DEF"


# ---------------------------------------------------------------------------
# _transform_row
# ---------------------------------------------------------------------------

def test_transform_row_applies_sources_and_transformers():
    config = FieldConfigSet("t", [
        FieldConfig("Plain", "title"),
        FieldConfig("Nested", "score.percent", transformer="round_2"),
        FieldConfig("Callable", "flag", transformer=lambda v: "YEP" if v else "NOPE"),
        FieldConfig("Named", "flag", transformer="yes_no"),
        FieldConfig("Unknown", "title", transformer="does_not_exist"),
        FieldConfig("Default", "absent", default="fallback"),
    ])
    row = cw._transform_row({"title": "T", "score": {"percent": 1.2}, "flag": True}, config)
    assert row == {
        "Plain": "T",
        "Nested": "1.20",
        "Callable": "YEP",
        "Named": "Yes",
        "Unknown": "T",       # unknown transformer name -> value passes through
        "Default": "fallback",
    }


# ---------------------------------------------------------------------------
# write_csv
# ---------------------------------------------------------------------------

_SIMPLE = FieldConfigSet("simple", [
    FieldConfig("ID", "id"),
    FieldConfig("Pct", "score.percent", transformer="round_2"),
])


def test_write_csv_from_dict_sorts_by_nested_key(tmp_path):
    data = {
        "a": {"id": "a", "score": {"percent": 10}},
        "b": {"id": "b", "score": {"percent": 90}},
    }
    out = tmp_path / "out.csv"
    cw.write_csv(data, _SIMPLE, out, sort_key="score.percent")  # reverse by default
    rows = _read(out)
    assert [r["ID"] for r in rows] == ["b", "a"]
    assert rows[0]["Pct"] == "90.00"


def test_write_csv_from_list_ascending(tmp_path):
    data = [{"id": "a", "score": {"percent": 10}}, {"id": "b", "score": {"percent": 90}}]
    out = tmp_path / "out.csv"
    cw.write_csv(data, _SIMPLE, out, sort_key="score.percent", reverse_sort=False)
    assert [r["ID"] for r in _read(out)] == ["a", "b"]


def test_write_csv_empty_prints_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "out.csv"
    cw.write_csv({}, _SIMPLE, out)
    assert "No data to write" in capsys.readouterr().out
    assert not out.exists()


def test_write_csv_unsortable_warns_but_still_writes(tmp_path, capsys):
    # mixed str/int under the sort key -> TypeError, caught and reported
    data = [{"id": "a", "k": "abc"}, {"id": "b", "k": 5}]
    config = FieldConfigSet("c", [FieldConfig("ID", "id")])
    out = tmp_path / "out.csv"
    cw.write_csv(data, config, out, sort_key="k")
    assert "Could not sort" in capsys.readouterr().out
    assert len(_read(out)) == 2


def test_write_csv_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "deep" / "out.csv"
    cw.write_csv([{"id": "a", "score": {"percent": 1}}], _SIMPLE, out)
    assert out.exists()


# ---------------------------------------------------------------------------
# write_summary_stats_csv
# ---------------------------------------------------------------------------

def test_write_summary_stats_csv(tmp_path):
    out = tmp_path / "stats.csv"
    cw.write_summary_stats_csv({"total": 5, "avg": 67.456, "label": "x"}, out)
    rows = _read(out)
    assert rows[0] == {"Metric": "total", "Value": "5"}
    assert rows[1]["Value"] == "67.46"   # float rounded to 2dp
    assert rows[2] == {"Metric": "label", "Value": "x"}


def test_write_summary_stats_csv_custom_labels(tmp_path):
    out = tmp_path / "stats.csv"
    cw.write_summary_stats_csv({"a": 1}, out, metric_label="Name", value_label="Count")
    with open(out, encoding="utf-8") as f:
        header = f.readline().strip()
    assert header == "Name,Count"


# ---------------------------------------------------------------------------
# entity-specific wrappers
# ---------------------------------------------------------------------------

def test_write_concordance_csv_one_row_per_snippet(tmp_path):
    concordance = {
        "10": {
            "snippets_by_field": {"description": ["snip one", "snip two"]},
            "terms_found": ["term1"],
            "upstream_ke": "U",
            "downstream_ke": "D",
            "aops": ["1", "2"],
        }
    }
    out = tmp_path / "concordance.csv"
    cw.write_concordance_csv(concordance, out)
    rows = _read(out)
    assert len(rows) == 2
    assert rows[0]["KER ID"] == "10"
    assert rows[0]["AOPs"] == "1, 2"
    assert {r["Snippet"] for r in rows} == {"snip one", "snip two"}


def test_write_seizure_aop_csv(tmp_path):
    curations = {"1": {"0": {"event_id": "100", "title": "T", "event_match": True,
                             "title_from_wiki": "W", "references": "R", "target_family": "TF",
                             "row_index": 2, "event_index": 0}}}
    out = tmp_path / "seizure.csv"
    cw.write_seizure_aop_csv(curations, out)
    rows = _read(out)
    assert rows[0]["AOP ID"] == "1"
    assert rows[0]["Event ID"] == "100"
    assert rows[0]["Event Match"] == "Yes"


def test_write_harmonized_seizure_aop_csv(tmp_path):
    harmonized = {"H1": {"100": {"0": {"aop_id": "1", "title_from_wiki": "W", "lobo": "Tissue",
                                       "event_match": True, "references": "R", "target_family": "TF",
                                       "event_index": 0}}}}
    out = tmp_path / "harmonized.csv"
    cw.write_harmonized_seizure_aop_csv(harmonized, out)
    rows = _read(out)
    assert rows[0]["Harmonized Title"] == "H1"
    assert rows[0]["LOBO"] == "Tissue"
    assert rows[0]["Event Match"] == "Yes"


def test_write_summary_harmonized_seizure_aop_csv(tmp_path):
    summary = {"harmonized_kes": {"H1": {"total_events": 2, "lobo_count": 1,
                                         "lobos": ["Tissue"], "event_ids": ["100"],
                                         "aop_ids": ["1"], "references": ["R"],
                                         "target_families": ["TF"]}}}
    out = tmp_path / "summary.csv"
    cw.write_summary_harmonized_seizure_aop_csv(summary, out)
    rows = _read(out)
    assert rows[0]["Harmonized Title"] == "H1"
    assert rows[0]["Total Events"] == "2"
    assert rows[0]["LOBOs"] == "Tissue"


def test_write_ke_description_to_harmonized_mapping_csv(tmp_path):
    mapping = {
        "low": {"harmonized_ke_match": "H1", "match_score": 0.2},
        "high": {"harmonized_ke_match": "H2", "match_score": 0.9},
    }
    out = tmp_path / "mapping.csv"
    cw.write_ke_description_to_harmonized_mapping_csv(mapping, out)
    rows = _read(out)
    # sorted by match_score descending
    assert [r["KE Description"] for r in rows] == ["high", "low"]
    assert rows[0]["Harmonized KE Match"] == "H2"
