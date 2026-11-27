"""
Tests for analysis/meta_data_helpers.py — pure scoring/summary logic over event,
KER, and AOP dicts.

`apply_ranking_to_events_dict` is the integration-ranking the core XML parser
attaches to every event, so its branch logic (completion tiers, OECD status,
method, search source, open-for-adoption penalty, unbounded AOP count) is pinned
here. The module's ``__main__`` demo block is intentionally not exercised.

Run with::

    $ uv run pytest tests/test_meta_data_helpers.py
"""

import pytest

from aop_wiki_cli.analysis.meta_data_helpers import (
    apply_ranking_to_events_dict,
    calculate_event_summary_statistics,
    filter_kers_by_tables,
    get_average_completion_score,
)


def _event(percent=0, program=False, endorsed=False, only_open=False,
           method=None, source=None, aop_count=None):
    """Build a minimal event dict with just the ranked fields set."""
    event = {
        "completion_score": {"percent": percent},
        "summary_oecd_statuses": {"in_oecd_aop_program": program, "any_oecd_endorsed": endorsed},
        "summary_licenses": {"only_open_for_adoption": only_open},
    }
    if method is not None:
        event["measurement_method"] = method
    if source is not None:
        event["source"] = source
    if aop_count is not None:
        event["aop_count"] = aop_count
    return event


# ---------------------------------------------------------------------------
# get_average_completion_score
# ---------------------------------------------------------------------------

def test_average_completion_empty_is_zero():
    assert get_average_completion_score({}) == 0


def test_average_completion_rounds():
    entities = {
        "a": {"completion_score": {"percent": 100}},
        "b": {"completion_score": {"percent": 50}},
        "c": {"completion_score": {"percent": 0}},
    }
    assert get_average_completion_score(entities) == 50.0


def test_average_completion_missing_score_counts_as_zero():
    assert get_average_completion_score({"a": {}}) == 0


# ---------------------------------------------------------------------------
# apply_ranking_to_events_dict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("percent, expected", [(90, 3), (60, 2), (30, 1), (10, 0)])
def test_ranking_completion_tiers(percent, expected):
    events = {"e": _event(percent=percent)}
    out = apply_ranking_to_events_dict(events)
    # only the completion tier contributes; max = 3 (completion) + 3 (oecd) + 1 (method)
    assert out["e"]["integration_score"] == expected
    assert out["e"]["max_i_score_sans_aop_count"] == 7


@pytest.mark.parametrize("program, endorsed, expected", [
    (True, True, 3),
    (True, False, 2),
    (False, False, 0),
])
def test_ranking_oecd_branches(program, endorsed, expected):
    out = apply_ranking_to_events_dict({"e": _event(program=program, endorsed=endorsed)})
    assert out["e"]["integration_score"] == expected


def test_ranking_method_present_sets_flag_and_point():
    out = apply_ranking_to_events_dict({"e": _event(method="TUNEL assay")})
    assert out["e"]["has_method"] is True
    assert out["e"]["integration_score"] == 1


def test_ranking_blank_method_scores_nothing():
    out = apply_ranking_to_events_dict({"e": _event(method="   ")})
    assert out["e"]["has_method"] is False
    assert out["e"]["integration_score"] == 0


@pytest.mark.parametrize("source, expected_score, expected_max", [
    ("title_search", 2, 9),
    ("full_text_search", 1, 9),
    ("other", 0, 9),   # unknown source still widens max but scores nothing
])
def test_ranking_search_source(source, expected_score, expected_max):
    out = apply_ranking_to_events_dict({"e": _event(source=source)})
    assert out["e"]["integration_score"] == expected_score
    assert out["e"]["max_i_score_sans_aop_count"] == expected_max


def test_ranking_only_open_for_adoption_penalty():
    out = apply_ranking_to_events_dict({"e": _event(percent=90, only_open=True)})
    # +3 completion, -4 penalty = -1; penalty does not change max (stays 7)
    assert out["e"]["integration_score"] == -1
    assert out["e"]["max_i_score_sans_aop_count"] == 7


def test_ranking_aop_count_is_added_but_held_out_of_percent():
    out = apply_ranking_to_events_dict({"e": _event(percent=90, aop_count=5)})
    # score 3 of max 7 => 42.86% ; integration_score adds the unbounded count
    assert out["e"]["integration_score"] == 3 + 5
    assert out["e"]["percent_i_score_sans_aop_count"] == pytest.approx(3 / 7 * 100)


def test_ranking_full_house():
    event = _event(percent=90, program=True, endorsed=True, method="m",
                   source="title_search", aop_count=2)
    out = apply_ranking_to_events_dict({"e": event})
    # 3 + 3 + 1 + 2 = 9 of max 9 => 100%, plus aop_count
    assert out["e"]["max_i_score_sans_aop_count"] == 9
    assert out["e"]["percent_i_score_sans_aop_count"] == 100
    assert out["e"]["integration_score"] == 9 + 2


# ---------------------------------------------------------------------------
# filter_kers_by_tables
# ---------------------------------------------------------------------------

def test_filter_kers_by_tables():
    kers = {
        "1": {"has_any_tables": True},
        "2": {"has_any_tables": False},
        "3": {},  # missing defaults to False
    }
    assert set(filter_kers_by_tables(kers, has_tables=True)) == {"1"}
    assert set(filter_kers_by_tables(kers, has_tables=False)) == {"2", "3"}


# ---------------------------------------------------------------------------
# calculate_event_summary_statistics
# ---------------------------------------------------------------------------

def test_summary_statistics_empty():
    summary = calculate_event_summary_statistics({})
    assert summary["total_events"] == 0
    assert all(v == 0 for v in summary.values())


def test_summary_statistics_counts_and_averages():
    events = {
        "a": {"completion_score": {"percent": 100}, "integration_score": 10,
              "has_method": True,
              "summary_oecd_statuses": {"in_oecd_aop_program": True, "any_oecd_endorsed": True},
              "summary_licenses": {"only_open_for_adoption": False}},
        "b": {"completion_score": {"percent": 50}, "integration_score": 2,
              "has_method": False,
              "summary_oecd_statuses": {"in_oecd_aop_program": False, "any_oecd_endorsed": False},
              "summary_licenses": {"only_open_for_adoption": True}},
        "c": {"completion_score": {"percent": 0}, "integration_score": 0,
              "has_method": False,
              "summary_oecd_statuses": {"in_oecd_aop_program": False, "any_oecd_endorsed": False},
              "summary_licenses": {"only_open_for_adoption": False}},
    }
    summary = calculate_event_summary_statistics(events)
    assert summary == {
        "total_events": 3,
        "average_completion_percent": 50.0,
        "average_integration_score": 4.0,
        "events_with_methods": 1,
        "events_only_open_for_adoption": 1,
        "events_in_oecd_program": 1,
        "events_oecd_endorsed": 1,
        "events_non_oecd_non_adoption": 1,
    }
