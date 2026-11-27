"""
Tests for the private console-printing helpers in cli.py.

These format a stats dict to stdout and are called by the collection commands
(e.g. collect-event-integration-rankings -> _print_event_summary). They are
pure apart from the printing, so the test asserts on captured stdout.

Run with::

    $ uv run pytest tests/test_cli_helpers.py
"""

from aop_wiki_cli.cli import (
    _available_search_configs,
    _count_kers_by_key_event,
    _print_event_summary,
    _print_event_to_aop_summary,
    _print_ker_lookup_summary,
    _print_ker_statistics,
    _print_mie_ao_summary,
    _print_search_summary,
)


def test_print_event_summary_outputs_every_metric(capsys):
    summary = {
        "total_events": 523,
        "average_completion_percent": 67.45,
        "average_integration_score": 4.2,
        "events_with_methods": 310,
        "events_only_open_for_adoption": 12,
        "events_in_oecd_program": 48,
        "events_oecd_endorsed": 20,
        "events_non_oecd_non_adoption": 443,
    }
    _print_event_summary(summary)
    out = capsys.readouterr().out
    assert "EVENT INTEGRATION RANKING SUMMARY" in out
    assert "Total events: 523" in out
    assert "Average completion: 67.45%" in out
    assert "Average integration score: 4.2" in out
    assert "Events with methods: 310" in out
    assert "Events only open for adoption: 12" in out
    assert "Events in OECD AOP program: 48" in out
    assert "OECD endorsed events: 20" in out
    assert "Events (non-OECD, non-open-adoption): 443" in out


# ---------------------------------------------------------------------------
# _print_ker_statistics (collect_ker_analytics)
# ---------------------------------------------------------------------------

def test_print_ker_statistics(capsys):
    stats = {
        "total_kers": 100,
        "kers_with_tables": 40,
        "kers_without_tables": 60,
        "average_completion_score": 55.5,
        "average_completion_score_kers_with_tables": 70.0,
        "average_completion_score_kers_without_tables": 45.0,
    }
    _print_ker_statistics(stats)
    out = capsys.readouterr().out
    assert "KER ANALYTICS SUMMARY" in out
    assert "Total KERs: 100" in out
    assert "KERs with tables: 40" in out
    assert "Average completion score (all KERs): 55.5%" in out


# ---------------------------------------------------------------------------
# _count_kers_by_key_event (find_kers_for_events)
# ---------------------------------------------------------------------------

def test_count_kers_by_key_event():
    matched = {
        "10": {"roles": {"200": "upstream", "300": "downstream"}},
        "11": {"roles": {"200": "downstream"}},
    }
    assert _count_kers_by_key_event(matched) == {
        "200": {"upstream": 1, "downstream": 1},
        "300": {"upstream": 0, "downstream": 1},
    }


# ---------------------------------------------------------------------------
# _print_ker_lookup_summary (find_kers_for_events)
# ---------------------------------------------------------------------------

def test_print_ker_lookup_summary(capsys):
    summary = {
        "ke_title_terms": ["oxidative stress"],
        "key_event_ids": ["1346", "55"],
        "total_kers_searched": 500,
        "total_kers_matched": 3,
        "kers_by_key_event": {"1346": {"upstream": 2, "downstream": 0}},
    }
    matched = {
        "10": {"title": "Oxidative stress -> Cell death", "roles": {"1346": "upstream"}},
        "11": {"title": "Cell death -> Tissue injury", "roles": {"55": "upstream"}},
    }
    _print_ker_lookup_summary(summary, matched, limit=1)
    out = capsys.readouterr().out
    assert "KERS CONTAINING KEY EVENTS" in out
    assert "KE title terms: oxidative stress" in out
    assert "KE1346: upstream in 2 KERs, downstream in 0 KERs" in out
    assert "and 1 more" in out  # limit=1 with 2 matches


# ---------------------------------------------------------------------------
# _print_search_summary (search_kers_for_concordance_text)
# ---------------------------------------------------------------------------

def test_print_search_summary(capsys):
    summary = {
        "fields_searched": ["description", "weight_of_evidence"],
        "terms_searched": {"concordant": 5, "discordant": 2},
        "total_entities_with_matches": 6,
    }
    _print_search_summary(summary, entity_type="KERs", search_type="concordance")
    out = capsys.readouterr().out
    assert "CONCORDANCE SEARCH SUMMARY" in out
    assert "Fields searched: description, weight_of_evidence" in out
    assert "'concordant': found in 5 KERs" in out
    assert "Total KERs with matches: 6" in out


# ---------------------------------------------------------------------------
# _print_event_to_aop_summary (pair_mies_and_aos)
# ---------------------------------------------------------------------------

def test_print_event_to_aop_summary(capsys):
    summary = {
        "ke_title_terms": ["apoptosis"],
        "total_events_searched": 1000,
        "total_aops_searched": 500,
        "total_events_matched": 3,
        "total_aops_matched": 2,
        "event_totals_by_term": {"apoptosis": 3},
    }
    _print_event_to_aop_summary(summary, total_aop_events=12)
    out = capsys.readouterr().out
    assert "EVENT-TO-AOP ITERATIVE SEARCH SUMMARY" in out
    assert "Total Events in matched AOPs: 12" in out
    assert "'apoptosis': 3 events" in out


# ---------------------------------------------------------------------------
# _print_mie_ao_summary (pair_mies_and_aos)
# ---------------------------------------------------------------------------

def _pair_summary():
    return {
        "total_pairs": 2, "total_aops": 2, "unique_mies": 1, "unique_aos": 2,
        "aops_without_mie": 0, "aops_without_ao": 1,
    }


def test_print_mie_ao_summary_with_rows(capsys):
    rows = [
        {"aop_id": "1", "mie_id": "100", "mie_title": "MIE one", "ao_id": "300", "ao_title": "AO one"},
        {"aop_id": "2", "mie_id": "", "mie_title": "", "ao_id": "", "ao_title": ""},  # no MIE/AO
    ]
    _print_mie_ao_summary(_pair_summary(), rows, limit=1)
    out = capsys.readouterr().out
    assert "MIE / AO PAIRING SUMMARY" in out
    assert "Total MIE/AO pairs: 2" in out
    assert "AOP1: KE100 MIE one" in out
    assert "and 1 more" in out  # limit=1, 2 rows


def test_print_mie_ao_summary_no_rows_returns_early(capsys):
    _print_mie_ao_summary(_pair_summary(), [], limit=25)
    out = capsys.readouterr().out
    assert "MIE / AO PAIRING SUMMARY" in out
    assert "MIE → AO pairs" not in out  # sample section skipped


# ---------------------------------------------------------------------------
# _available_search_configs (pair_mies_and_aos error path)
# ---------------------------------------------------------------------------

def test_available_search_configs_lists_event_to_aop_configs():
    configs = _available_search_configs()
    assert isinstance(configs, list)
    assert configs == sorted(configs)
    # dili_aops is the documented example config with SEARCH_PARAMS + OUTPUT_CONFIG
    assert "dili_aops" in configs
