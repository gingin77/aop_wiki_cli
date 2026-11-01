"""
Tests for the `search-within-aops` CLI command.

The search and selection functions have their own tests in test_within_aops.py;
these cover what the command adds on top: the guards on its arguments, the AOP
IDs it reports as missing, and the three files it writes.

No XML snapshot is read. Entity collection is replaced with the mock AOPs, KEs
and KERs from test_within_aops, and outputs go to a temporary data directory.

Run with::

    $ uv run pytest tests/test_within_aops_cli.py
"""

import json

import pytest
from typer.testing import CliRunner

from aop_wiki_cli import cli, paths
from tests.test_within_aops import MOCK_AOPS, MOCK_EVENTS, MOCK_KERS

DATE = "09-03-2026"
ENTITIES = {"aops": MOCK_AOPS, "events": MOCK_EVENTS, "kers": MOCK_KERS}

runner = CliRunner()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A temporary data directory, with entity collection returning the mocks."""
    # --data-dir pins a module-level override for the rest of the process;
    # monkeypatch restores it so later tests are not pointed at tmp_path.
    monkeypatch.setattr(paths, "_data_dir_override", None)
    monkeypatch.setattr(cli, "collect_entity_with_cache",
                        lambda entity_type, *args, **kwargs: ENTITIES[entity_type])
    return tmp_path


def invoke(data_dir, *args):
    return runner.invoke(cli.app, ["--data-dir", str(data_dir), "search-within-aops",
                                   "--date", DATE, *args])


def out_dir(data_dir):
    return data_dir / "outputs" / "within_aop_searches" / DATE


def test_writes_the_three_files_and_reports_every_term(data_dir):
    result = invoke(data_dir, "--aop-ids", "10,281", "--term", "patch-clamp",
                    "--term", "zebrafish")
    assert result.exit_code == 0, result.output

    out = out_dir(data_dir)
    report = json.loads((out / f"within_aop_search_{DATE}.json").read_text(encoding="utf-8"))
    assert sorted(report["selected_aops"]) == ["10", "281"]
    assert list(report["findings"]) == ["patch-clamp"]
    assert report["terms_not_found"] == ["zebrafish"]
    assert (out / f"within_aop_search_{DATE}.md").exists()
    assert (out / f"within_aop_search_matches_{DATE}.csv").exists()

    assert "searched 2 AOPs" in result.output
    assert "NOT FOUND — 1 terms: 'zebrafish'" in result.output


def test_term_groups_report_records_where_both_groups_match(data_dir):
    result = invoke(data_dir, "--aop-ids", "10,281",
                    "--term-group", "mea=microelectrode array|micro-electrode array|MEA",
                    "--term-group", "seizure=seizure")
    assert result.exit_code == 0, result.output
    assert "TOGETHER IN ONE RECORD — mea + seizure: 1" in result.output
    assert "KE 613" in result.output


def test_missing_aop_ids_are_reported_but_do_not_stop_the_search(data_dir):
    result = invoke(data_dir, "--aop-ids", "10,4242", "--term", "seizure")
    assert result.exit_code == 0, result.output
    assert "AOP IDs not in the 09-03-2026 export: 4242" in result.output

    report = json.loads((out_dir(data_dir) / f"within_aop_search_{DATE}.json")
                        .read_text(encoding="utf-8"))
    assert report["summary"]["aop_ids_missing"] == ["4242"]


def test_no_term_is_an_error(data_dir):
    result = invoke(data_dir, "--aop-ids", "10")
    assert result.exit_code == 1
    assert "Provide at least one --term or --term-group" in result.output


def test_no_aop_selector_is_an_error(data_dir):
    result = invoke(data_dir, "--term", "seizure")
    assert result.exit_code == 1
    assert "Provide at least one of --aop-ids" in result.output


def test_a_malformed_term_group_is_an_error(data_dir):
    result = invoke(data_dir, "--aop-ids", "10", "--term-group", "no-equals-sign")
    assert result.exit_code == 1


def test_only_unknown_aop_ids_selects_nothing(data_dir):
    result = invoke(data_dir, "--aop-ids", "4242", "--term", "seizure")
    assert result.exit_code == 1
    assert "No AOPs selected" in result.output
    assert not out_dir(data_dir).exists()
