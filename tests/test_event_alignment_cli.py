"""
Tests for the `event-content-internal-alignment` and `event-level-llm-review`
CLI commands.

The analysis functions have their own tests; these cover what the commands add
on top: which Events they read, the files they write, and the guard that keeps
the LLM review from running over a whole snapshot by accident.

No XML snapshot is read and no request leaves the machine. Entity collection is
replaced with the three-Event fixture, outputs go to a temporary data directory,
and the LLM review is given the fake client from test_event_level_llm_review.

Run with::

    $ uv run pytest tests/test_event_alignment_cli.py
"""

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aop_wiki_cli import cli, paths
from aop_wiki_cli.analysis import event_level_llm_review
from aop_wiki_cli.analysis.event_content_internal_alignment import REPORT_COLUMNS
from tests.test_event_level_llm_review import FakeClient, verdict

FIXTURE = Path(__file__).parent / "mock_data" / "alignment_events_09-03-2026.json"
DATE = "09-03-2026"

runner = CliRunner()


@pytest.fixture
def events():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def data_dir(tmp_path, monkeypatch, events):
    """A temporary data directory, with entity collection returning the fixture.

    Returns the directory and the list of keyword arguments each collection call
    was made with.
    """
    # --data-dir pins a module-level override for the rest of the process;
    # monkeypatch restores it so later tests are not pointed at tmp_path.
    monkeypatch.setattr(paths, "_data_dir_override", None)
    calls = []

    def fake_collect(**kwargs):
        calls.append(kwargs)
        return events

    monkeypatch.setattr(cli, "collect_entity_with_cache", fake_collect)
    return tmp_path, calls


def invoke(data_dir, *args):
    return runner.invoke(cli.app, ["--data-dir", str(data_dir), *args])


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# event-content-internal-alignment
# ---------------------------------------------------------------------------

def test_alignment_writes_the_whole_snapshot_report(data_dir):
    root, calls = data_dir
    result = invoke(root, "event-content-internal-alignment", "--date", DATE)
    assert result.exit_code == 0, result.output

    out = root / "outputs" / "event_alignment" / DATE
    report = json.loads((out / f"event_alignment_{DATE}.json").read_text(encoding="utf-8"))
    assert report["summary"]["events_read"] == 3
    assert report["summary"]["events_with_flags"] == 1

    rows = read_csv(out / f"event_alignment_{DATE}.csv")
    assert list(rows[0]) == list(REPORT_COLUMNS)
    flagged = [r for r in rows if r["severity"] == "flag"]
    assert [r["ke_id"] for r in flagged] == ["1909"]
    # The row carries enough to judge the finding without opening AOP-Wiki.
    assert flagged[0]["assigned_level"] == "Individual"
    assert flagged[0]["description"]
    assert flagged[0]["url"] == "https://aopwiki.org/events/1909"

    assert "Events read: 3" in result.output
    assert "Events with at least one flag: 1" in result.output
    assert calls[0]["entity_type"] == "events"
    assert calls[0]["force_refresh"] is False


def test_alignment_subset_gets_its_own_files_and_reports_missing_ids(data_dir):
    """Screening named Events must not overwrite the whole-snapshot report."""
    root, _ = data_dir
    result = invoke(root, "event-content-internal-alignment", "--date", DATE,
                    "--ke-ids", "1909, 999999")
    assert result.exit_code == 0, result.output

    out = root / "outputs" / "event_alignment" / DATE
    assert not (out / f"event_alignment_{DATE}.json").exists()
    [json_path] = out.glob(f"event_alignment_{DATE}_subset_*.json")
    [csv_path] = out.glob(f"event_alignment_{DATE}_subset_*.csv")

    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["summary"]["events_read"] == 1
    assert report["summary"]["events_not_found"] == ["999999"]
    assert {r["ke_id"] for r in read_csv(csv_path)} == {"1909"}
    assert "Not found in the snapshot: 999999" in result.output


def test_alignment_passes_force_refresh_to_collection(data_dir):
    root, calls = data_dir
    result = invoke(root, "event-content-internal-alignment", "--date", DATE, "--force-refresh")
    assert result.exit_code == 0, result.output
    assert calls[0]["force_refresh"] is True


# ---------------------------------------------------------------------------
# event-level-llm-review
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_client(monkeypatch):
    """Replace the Anthropic client with one that disagrees with every level."""
    client = FakeClient(verdict(fits=False, best="Organ", quotes=["first quote", "second quote"]))
    monkeypatch.setattr(event_level_llm_review, "_default_client", lambda: client)
    return client


def llm_outputs(root):
    out = root / "outputs" / "event_level_llm_review" / DATE
    [json_path] = out.glob(f"event_level_llm_review_{DATE}_*.json")
    [csv_path] = out.glob(f"event_level_llm_review_{DATE}_*.csv")
    return json.loads(json_path.read_text(encoding="utf-8")), read_csv(csv_path)


def test_llm_review_refuses_to_run_without_ke_ids_or_limit(data_dir, fake_client):
    """A whole-snapshot run costs one request per Event, so it is never the default."""
    root, calls = data_dir
    result = invoke(root, "event-level-llm-review", "--date", DATE)
    assert result.exit_code != 0
    assert "--ke-ids" in result.output and "--limit" in result.output
    assert fake_client.messages.calls == []
    assert calls == []


def test_llm_review_limit_takes_the_first_events_in_snapshot_order(data_dir, fake_client):
    root, _ = data_dir
    result = invoke(root, "event-level-llm-review", "--date", DATE, "--limit", "2")
    assert result.exit_code == 0, result.output
    assert "Reviewing 2 Event(s)" in result.output

    sent = [c["messages"][0]["content"] for c in fake_client.messages.calls]
    assert len(sent) == 2
    assert "Key Event 1908" in sent[0] and "Key Event 1909" in sent[1]

    report, rows = llm_outputs(root)
    assert report["summary"]["events_read"] == 2
    assert [r["ke_id"] for r in rows] == ["1908", "1909"]


def test_llm_review_limit_also_caps_named_ke_ids(data_dir, fake_client):
    root, _ = data_dir
    result = invoke(root, "event-level-llm-review", "--date", DATE,
                    "--ke-ids", "1250,1909,1908", "--limit", "1")
    assert result.exit_code == 0, result.output
    assert len(fake_client.messages.calls) == 1
    assert "Key Event 1250" in fake_client.messages.calls[0]["messages"][0]["content"]


def test_llm_review_csv_flattens_evidence_and_records_the_model(data_dir, fake_client):
    root, _ = data_dir
    result = invoke(root, "event-level-llm-review", "--date", DATE,
                    "--ke-ids", "1909", "--model", "test-model")
    assert result.exit_code == 0, result.output
    assert fake_client.messages.calls[0]["model"] == "test-model"

    report, [row] = llm_outputs(root)
    assert report["summary"]["model"] == "test-model"
    assert row["severity"] == "flag"
    assert row["best_fit_level"] == "Organ"
    assert row["evidence"] == "first quote; second quote"
    assert row["model"] == "test-model"
    assert row["definitions_digest"] == report["summary"]["definitions_digest"]


def test_llm_review_failed_request_is_reported_not_raised(data_dir, monkeypatch):
    root, _ = data_dir
    client = FakeClient(error=RuntimeError("no credentials"))
    monkeypatch.setattr(event_level_llm_review, "_default_client", lambda: client)

    result = invoke(root, "event-level-llm-review", "--date", DATE, "--ke-ids", "1909")
    assert result.exit_code == 0, result.output
    assert "Failed requests: 1" in result.output

    _, [row] = llm_outputs(root)
    assert row["severity"] == "error"
    assert "no credentials" in row["message"]


@pytest.mark.parametrize("args", [
    ["--limit", "0"],
    ["--limit", "-1"],
    ["--ke-ids", " , "],
])
def test_llm_review_refuses_a_selection_that_names_no_events(data_dir, fake_client, args):
    """An empty selection must not fall through to reviewing the whole snapshot."""
    root, _ = data_dir
    result = invoke(root, "event-level-llm-review", "--date", DATE, *args)
    assert result.exit_code != 0
    assert fake_client.messages.calls == []
