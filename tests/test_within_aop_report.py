"""
Unit tests for the within-AOP search report writers.

Tests cover:
- One CSV row per (term, record, field, snippet)
- No CSV when nothing matched
- Markdown leading with the terms that matched, each with its records and quotes
- The per-term tally omitting zeros and agreeing in number
- Terms that matched nothing reported as an absence, with the scope stated
- Pipe characters in an AOP title not breaking the scope table

Examples:
    Run directly::

        $ python -m pytest tests/test_within_aop_report.py
"""

from aop_wiki_cli.data_export.within_aop_report import (
    match_rows,
    tally,
    render_within_aop_markdown,
    write_within_aop_matches_csv,
)

import csv


RESULT = {
    "scope": {
        "aops": ["10"],
        "events": ["613", "616"],
        "kers": ["630"],
        "missing": {"aops": [], "events": ["999"], "kers": []},
    },
    "term_counts": {
        "patch-clamp": {"aops": 0, "events": 1, "kers": 0},
        "hiPSC": {"aops": 0, "events": 0, "kers": 0},
    },
    "findings": {
        "patch-clamp": [
            {
                "entity": "events",
                "id": "616",
                "label": "Occurrence, A paroxysmal depolarizing shift",
                "aop_ids": ["10"],
                "snippets_by_field": {
                    "measurement_method": ["Measured using patch-clamp recording."],
                    "description": ["A patch-clamp study.", "Another patch-clamp study."],
                },
            }
        ]
    },
    "terms_not_found": ["hiPSC"],
}

SUMMARY = {
    "collection_date": "10-03-2026",
    "terms": ["patch-clamp", "hiPSC"],
    "fields_searched": {
        "aops": ["title", "abstract"],
        "events": ["title", "measurement_method", "description"],
        "kers": ["description"],
    },
}

SELECTED_AOPS = {
    "10": {"title": "Picrotoxin binding leading to epileptic seizures", "selected_by": ["aop_id"]}
}


def test_one_row_per_snippet_sorted_by_field():
    rows = match_rows(RESULT)

    assert [(row["field"], row["snippet"]) for row in rows] == [
        ("description", "A patch-clamp study."),
        ("description", "Another patch-clamp study."),
        ("measurement_method", "Measured using patch-clamp recording."),
    ]
    assert all(row["term"] == "patch-clamp" for row in rows)
    assert rows[0]["entity"] == "KE"
    assert rows[0]["id"] == "616"
    assert rows[0]["aop_ids"] == "10"


def test_csv_is_written_with_a_header_and_every_snippet(tmp_path):
    path = write_within_aop_matches_csv(RESULT, tmp_path / "matches.csv")

    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 3
    assert rows[0]["term"] == "patch-clamp"
    assert rows[0]["label"] == "Occurrence, A paroxysmal depolarizing shift"


def test_no_csv_is_written_when_nothing_matched(tmp_path):
    empty = dict(RESULT, findings={}, terms_not_found=["patch-clamp", "hiPSC"])

    assert write_within_aop_matches_csv(empty, tmp_path / "matches.csv") is None
    assert not (tmp_path / "matches.csv").exists()


def test_markdown_leads_with_what_was_found():
    report = render_within_aop_markdown(RESULT, SUMMARY, SELECTED_AOPS)

    assert "Searched **1 AOPs**, **2 key events** and **1 KERs** for **2 terms**" in report
    assert report.index("## Found") < report.index("## Not found") < report.index("## Scope searched")
    assert "### 'patch-clamp' — 1 KE field" in report
    assert "- **KE 616** Occurrence, A paroxysmal depolarizing shift (AOP 10)" in report
    assert "    > Measured using patch-clamp recording." in report


def test_markdown_states_the_absences_and_the_scope_behind_them():
    report = render_within_aop_markdown(RESULT, SUMMARY, SELECTED_AOPS)

    assert "- 'hiPSC'" in report
    assert "punctuation differences do not match" in report
    assert "- Key events searched: 613, 616" in report
    assert "KE IDs referenced by these AOPs but absent from the export: 999" in report
    assert "- KE: title, measurement_method, description" in report


def test_markdown_omits_the_found_section_when_nothing_matched():
    empty = dict(RESULT, findings={}, terms_not_found=["patch-clamp", "hiPSC"])

    report = render_within_aop_markdown(empty, SUMMARY, SELECTED_AOPS)

    assert "## Found" not in report
    assert "## Not found" in report


def test_a_pipe_in_an_aop_title_is_escaped_in_the_scope_table():
    selected = {"10": {"title": "GABA | picrotoxin site", "selected_by": ["aop_id"]}}

    report = render_within_aop_markdown(RESULT, SUMMARY, selected)

    assert "| 10 | GABA \\| picrotoxin site | aop_id |" in report


def test_tally_omits_zeros_and_agrees_in_number():
    assert tally({"aops": 3, "events": 1, "kers": 0}) == "3 AOP fields, 1 KE field"
    assert tally({"aops": 0, "events": 0, "kers": 2}) == "2 KER fields"


# A result that also carries co-occurrence groups (one pair matched together,
# one pair present separately but never in the same record) and a case-sensitive
# term, to exercise the co-occurrence and case-sensitive sections of the report.
CO_OCCURRENCE_RESULT = dict(
    RESULT,
    group_counts={"Group A": 1, "Group B": 1},
    groups={"Group A": ["patch-clamp"], "Group B": ["hiPSC", "iPSC"]},
    co_occurrence=[
        {
            "groups": ("Group A", "Group B"),
            "records": [
                {
                    "entity": "events", "id": "616", "label": "A key event",
                    "aop_ids": ["10"],
                    "terms_by_group": {"Group A": ["patch-clamp"], "Group B": ["iPSC"]},
                    "fields_by_group": {"Group A": ["description"], "Group B": ["title"]},
                }
            ],
        },
        {"groups": ("Group A", "Group B"), "records": []},  # present apart, never together
    ],
    case_sensitive_terms=["hiPSC"],
)


def test_markdown_reports_co_occurrence_groups_and_case_sensitivity():
    report = render_within_aop_markdown(CO_OCCURRENCE_RESULT, SUMMARY, SELECTED_AOPS)

    assert "## Term groups together in one record" in report
    # the pair that matched together
    assert "### Group A + Group B — 1 records" in report
    # the pair that matched apart, with the "each present, never together" note
    assert "No AOP, key event or KER in scope matched both *Group A*" in report
    assert "Each group is present in scope, but never in the same record." in report
    # group-membership rollup and the case-sensitive footnote
    assert "### Group membership" in report
    assert "Matched case-sensitively: 'hiPSC'." in report
