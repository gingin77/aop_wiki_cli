"""
Tests for analysis/collect_event_rankings.py — collect events (via cache), attach
summary statistics, sort by integration score, and write the combined rankings
JSON.

``collect_entity_with_cache`` is monkeypatched so the test supplies events
directly; everything else (sorting, summary, the written file) is real.

Run with::

    $ uv run pytest tests/test_collect_event_rankings.py
"""

import json
from datetime import date
from types import SimpleNamespace

from aop_wiki_cli.analysis import collect_event_rankings as cer


def test_collect_and_rank_events_sorts_and_writes(tmp_path, monkeypatch):
    events = {
        "low": {"integration_score": 1, "completion_score": {"percent": 10}},
        "high": {"integration_score": 9, "completion_score": {"percent": 90}},
        "mid": {"integration_score": 5, "completion_score": {"percent": 50}},
    }
    monkeypatch.setattr(cer, "collect_entity_with_cache", lambda **kwargs: events)
    logger = SimpleNamespace(info=lambda *a, **k: None)

    event_dict, summary = cer.collect_and_rank_events(
        work_date=date(2024, 3, 4),
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
        logger=logger,
    )

    # sorted by integration_score descending
    assert list(event_dict) == ["high", "mid", "low"]
    assert summary["total_events"] == 3

    # combined rankings file written with the expected envelope
    out_file = tmp_path / "out" / "event_rankings_03-04-2024.json"
    assert out_file.exists()
    written = json.loads(out_file.read_text())
    assert written["collection_date"] == "03-04-2024"
    assert written["summary"]["total_events"] == 3
    assert list(written["events"]) == ["high", "mid", "low"]
