"""
Tests for the private console-printing helpers in cli.py.

These format a stats dict to stdout and are called by the collection commands
(e.g. collect-event-integration-rankings -> _print_event_summary). They are
pure apart from the printing, so the test asserts on captured stdout.

Run with::

    $ uv run pytest tests/test_cli_helpers.py
"""

from aop_wiki_cli.cli import _print_event_summary


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
