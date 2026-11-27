"""
Tests for parsers/completion_score.py — the AOP/Event/KER completion scoring used
across the tool (imported by cli, parsers, analysis, harmonization, data_export).

Pure dict-in/dict-out logic, so these tests build minimal entity dicts and assert
exact scores, the LOBO branches, the handbook-version conditional, and which
fields are tracked as empty.

Run with::

    $ uv run pytest tests/test_completion_score.py
"""

import pytest

from aop_wiki_cli.parsers.completion_score import (
    _has_content,
    _has_visible_content,
    event_completion_score,
    ker_completion_score,
    aop_completion_score,
    add_completion_score_to_events,
    add_completion_score_to_kers,
    add_completion_score_to_aops,
)


# ---------------------------------------------------------------------------
# content predicates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None, False),
    ("", False),
    ("   ", False),
    ("text", True),
    ([], False),
    ([1], True),
    ({}, False),
    ({"a": 1}, True),
    (0, False),       # falsy, caught by the initial `if not value`
    (1.5, True),      # truthy non-str/list/dict falls through to True
])
def test_has_content(value, expected):
    assert _has_content(value) is expected


@pytest.mark.parametrize("html_value, expected", [
    ("<p>&nbsp;</p>", False),               # markup with no visible text
    ("<p></p>", False),
    ("<p>Real text</p>", True),
    ('<p><img src="x.png"></p>', True),     # an image alone counts
    ("plain text", True),
])
def test_has_visible_content_html(html_value, expected):
    assert _has_visible_content(html_value) is expected


def test_has_visible_content_non_string_falls_back_to_has_content():
    assert _has_visible_content([1]) is True
    assert _has_visible_content([]) is False


# ---------------------------------------------------------------------------
# event_completion_score
# ---------------------------------------------------------------------------

def _full_tissue_event():
    """A Tissue event with every scored field populated → 100%."""
    return {
        "title": "t", "short_name": "s", "description": "d",
        "doa_free_text": "doa", "measurement_method": "m", "references": "r",
        "level_of_biological_organization": "Tissue",
        "organ_term": {"term": "liver"},
        "taxonomy_terms": [{"title": "Homo sapiens"}],
        "life_stage_terms": ["Adult"],
        "sex_terms": ["Male"],
        "ecs": [{"biological_process": {"term": "apoptosis"}}],
    }


def test_event_score_full_tissue_is_100():
    result = event_completion_score(_full_tissue_event())
    assert result["percent"] == 100.0
    assert result["raw_score"] == result["max_score"] == 12
    assert result["empty_free_text"] == []
    assert result["empty_structured"] == []


def test_event_score_tissue_without_organ_term_tracks_organ():
    event = _full_tissue_event()
    event["organ_term"] = {}
    result = event_completion_score(event)
    # LOBO present (+1) but organ missing: 11/12
    assert result["raw_score"] == 11
    assert result["max_score"] == 12
    assert "organ" in result["empty_structured"]


@pytest.mark.parametrize("lobo, term_field", [
    ("Cellular", "cell_term"),
    ("Molecular", "cell_term"),
])
def test_event_score_cellular_molecular_use_cell_term(lobo, term_field):
    event = {
        "title": "t",
        "level_of_biological_organization": lobo,
        term_field: {"term": "hepatocyte"},
    }
    result = event_completion_score(event)
    # title (+1) + lobo base (+1) + cell term (+1) = 3; max 12
    assert result["raw_score"] == 3
    assert "cell" not in result["empty_structured"]


def test_event_score_minimal_tracks_all_empties():
    result = event_completion_score({"title": "only a title"})
    assert result["raw_score"] == 1
    assert result["max_score"] == 11          # no LOBO → no conditional organ/cell slot
    assert result["percent"] == round(100 / 11, 2)
    assert set(result["empty_free_text"]) == {
        "short_name", "description", "doa_free_text", "measurement_method", "references",
    }
    assert result["empty_structured"] == [
        "lobo", "taxonomy_terms", "life_stage_terms", "sex_terms", "sub_events",
    ]


# ---------------------------------------------------------------------------
# ker_completion_score
# ---------------------------------------------------------------------------

def test_ker_score_empty_is_zero_and_tracks_all_fields():
    result = ker_completion_score({})
    assert result["raw_score"] == 0
    assert result["max_score"] == 17          # 9 free-text + 8 structured
    assert result["percent"] == 0
    assert "description" in result["empty_free_text"]
    assert "aop_ids" in result["empty_structured"]


def test_ker_score_counts_present_fields():
    result = ker_completion_score({"description": "d", "aop_ids": ["1"]})
    assert result["raw_score"] == 2
    assert "description" not in result["empty_free_text"]
    assert "aop_ids" not in result["empty_structured"]


# ---------------------------------------------------------------------------
# aop_completion_score
# ---------------------------------------------------------------------------

def _full_aop(handbook_version):
    return {
        "title": "t", "short_name": "s", "abstract": "a", "authors": "au",
        "background": "b", "overall_assessment_description": "o",
        "doa_free_text": "d", "ke_essentiality": "k", "woe_evidence": "w",
        "quantitative_considerations": "q", "potential_applications": "p",
        "references": "r",
        "development_strategy": "ds", "known_modulating_factors": "kmf",
        "point_of_contact": "poc", "stressors": ["s1"],
        "sex_applicability": ["Male"], "life_stage_applicability": ["Adult"],
        "taxonomy_applicability": [{"title": "Homo sapiens"}],
        "event_ids": ["100", "200", "300"],
        "kers": {"10": {}, "20": {}},
        "handbook_version": handbook_version,
    }


def test_aop_score_new_handbook_scores_conditional_fields():
    result = aop_completion_score(_full_aop(2.5))
    assert result["max_score"] == 21          # 12 free + 5 struct + 2 counts + 2 conditional
    assert result["raw_score"] == 21
    assert result["percent"] == 100.0


def test_aop_score_old_handbook_tracks_but_does_not_score_conditional():
    result = aop_completion_score(_full_aop(2.0))
    # conditional fields excluded from max_score and from raw_score, though still present
    assert result["max_score"] == 19          # 12 free + 5 struct + 2 counts
    assert result["raw_score"] == 19
    assert result["percent"] == 100.0


def test_aop_score_below_minimum_event_and_ker_counts_tracks_them():
    aop = _full_aop(2.5)
    aop["event_ids"] = ["100", "200"]          # < 3
    aop["kers"] = {"10": {}}                    # < 2
    result = aop_completion_score(aop)
    assert "event_ids" in result["empty_structured"]
    assert "kers" in result["empty_structured"]


# ---------------------------------------------------------------------------
# add_completion_score_to_* wrappers
# ---------------------------------------------------------------------------

def test_add_completion_score_to_events_attaches_score():
    events = {"100": {"title": "t"}}
    out = add_completion_score_to_events(events)
    assert out is events                        # mutates in place and returns
    assert "completion_score" in out["100"]
    assert out["100"]["completion_score"]["percent"] >= 0


def test_add_completion_score_to_kers_attaches_score():
    kers = {"10": {"description": "d"}}
    out = add_completion_score_to_kers(kers)
    assert "completion_score" in out["10"]


def test_add_completion_score_to_aops_attaches_score():
    aops = {"1": {"title": "t", "handbook_version": 2.5}}
    out = add_completion_score_to_aops(aops)
    assert "completion_score" in out["1"]
