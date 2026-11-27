"""
Tests for parsers/seizure_harmonization.py — the shared harmonization-sheet
core of the seizure workbook parser.

``read_behl_seizure_aop_ids`` is exercised end to end against the Behl
supplementary workbook bundled with the package; the pure row/dict helpers are
unit-tested with small fixtures (no Excel).

Run with::

    $ uv run pytest tests/test_seizure_harmonization.py
"""

import pandas as pd
import pytest

from aop_wiki_cli.parsers import seizure_harmonization as sh
from aop_wiki_cli.paths import seizure_workbook_path


# ---------------------------------------------------------------------------
# read_behl_seizure_aop_ids (integration, against the bundled workbook)
# ---------------------------------------------------------------------------

def test_read_behl_seizure_aop_ids_from_bundled_workbook():
    ids = sh.read_behl_seizure_aop_ids(seizure_workbook_path())
    # Every AOP header on the harmonization sheet, sorted numerically. This is
    # the exact set search-within-aops injects for --behl-seizure-aops.
    assert ids == ['10', '214', '215', '223', '230', '231', '281']
    assert all(isinstance(i, str) for i in ids)


def test_get_seizure_dfs_reads_all_three_sheets():
    # The full seizure runner uses this; it must read the harmonization, assay
    # and chemical sheets (read_behl_seizure_aop_ids reads only the first).
    import pandas as pd
    harmonization_df, assays_df, chemicals_df = sh.get_seizure_dfs(
        pd.ExcelFile(seizure_workbook_path())
    )
    assert "aop_wiki_terminologies" in harmonization_df.columns
    assert "casrn" in chemicals_df.columns          # chemicals columns refined
    assert not assays_df.empty


# ---------------------------------------------------------------------------
# _extract_aop_id_from_header
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("AOP 214", "214"),
    ("AOP 10: serotonin", "10"),
    ("Altered Serotonin", None),   # not an AOP header
    ("AOP network", None),         # "AOP " prefix but no number
])
def test_extract_aop_id_from_header(value, expected):
    assert sh._extract_aop_id_from_header(value) == expected


# ---------------------------------------------------------------------------
# _is_harmonization_event_row / _extract_event_id_from_str / _extract_row_values_as_str
# ---------------------------------------------------------------------------

def test_is_harmonization_event_row():
    assert sh._is_harmonization_event_row("AOP 10", "Some KE") is True
    assert sh._is_harmonization_event_row(None, "Some KE") is False
    assert sh._is_harmonization_event_row("AOP 10", "nan") is False


@pytest.mark.parametrize("value,expected", [
    ("KE 386", "386"),
    ("nan", None),
    ("", None),
    ("no digits", None),
])
def test_extract_event_id_from_str(value, expected):
    assert sh._extract_event_id_from_str(value) == expected


def test_extract_row_values_as_str():
    row = {"category": "KE 386", "harmonized_kes": "Title"}
    assert sh._extract_row_values_as_str(row, ["category", "harmonized_kes", "missing"]) == \
        ["KE 386", "Title", ""]


# ---------------------------------------------------------------------------
# _collect_event_mappings_orig_to_harmonized / _collapse_single_title_sets
# ---------------------------------------------------------------------------

def test_collect_and_collapse_event_mappings():
    mappings = {}
    mappings = sh._collect_event_mappings_orig_to_harmonized(mappings, "386", "Title A")
    mappings = sh._collect_event_mappings_orig_to_harmonized(mappings, "386", "Title A")  # dup
    mappings = sh._collect_event_mappings_orig_to_harmonized(mappings, "999", "E")        # -> DROPPED
    collapsed = sh._collapse_single_title_sets(mappings)
    assert collapsed["386"] == "Title A"   # single title collapsed out of its set
    assert collapsed["999"] == "DROPPED"


def test_collapse_keeps_multi_title_sets_and_warns(caplog):
    mappings = {"386": {"Title A", "Title B"}}
    with caplog.at_level("WARNING", logger=sh.__name__):
        collapsed = sh._collapse_single_title_sets(mappings)
    assert collapsed["386"] == {"Title A", "Title B"}  # ambiguous set left intact
    assert "maps to multiple harmonized titles" in caplog.text


# ---------------------------------------------------------------------------
# _collect_titles_from_event_mapping / _log_harmonized_title_discrepancy
# ---------------------------------------------------------------------------

def test_collect_titles_from_event_mapping_handles_sets_and_scalars():
    mapping = {"1": "Title A", "2": {"Title B", "nan"}, "3": ""}
    titles = sh._collect_titles_from_event_mapping(mapping)
    assert titles == {"Title A", "Title B"}  # 'nan' and '' dropped


def test_log_harmonized_title_discrepancy(caplog):
    with caplog.at_level("WARNING", logger=sh.__name__):
        sh._log_harmonized_title_discrepancy({"a", "b"}, {"a"})
    assert "Discrepancy" in caplog.text
    # equal sizes -> silent
    caplog.clear()
    with caplog.at_level("WARNING", logger=sh.__name__):
        sh._log_harmonized_title_discrepancy({"a"}, {"b"})
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# parse_harmonization_df / extract_harmonized_aops (small DataFrame)
# ---------------------------------------------------------------------------

def test_parse_and_extract_from_small_frame():
    df = pd.DataFrame({
        "aop_wiki_terminologies": ["AOP 10", "Upstream KE", "AOP 20", "Downstream KE"],
        "category": ["", "KE 100", "", "KE 200"],
        "harmonized_kes": ["", "Harmonized Up", "", "E"],  # AOP 20's only KE is excluded
        "references": ["", "r1", "", "r2"],
        "target_family": ["", "tf1", "", "tf2"],
    })
    harmonization_dict, mappings, harmonized_kes = sh.parse_harmonization_df(df)
    aop_to_events = sh.extract_harmonized_aops(harmonization_dict)
    # AOP 10 keeps its harmonized event; AOP 20's only event is 'E' (excluded)
    assert list(aop_to_events["10"].values())[0]["harmonized_event"] == "Harmonized Up"
    assert aop_to_events["20"] == {}


def test_collect_harmonized_kes_from_df_marks_dropped():
    df = pd.DataFrame({"harmonized_kes": ["Title A", "E", "nan", None]})
    assert sh._collect_harmonized_kes_from_df(df) == {"Title A", "DROPPED"}
