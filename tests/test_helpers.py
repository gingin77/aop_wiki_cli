"""
Tests for utilities/helpers.py — the shared file-I/O, JSON-serialization,
caching, and small formatting helpers used across the package.

Most are pure or filesystem-local (driven with ``tmp_path``); ``download_with_retry``
is exercised by monkeypatching ``subprocess.run`` and ``time.sleep``.

Run with::

    $ uv run pytest tests/test_helpers.py
"""

import json
import logging
import subprocess
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from aop_wiki_cli.utilities import helpers


# ---------------------------------------------------------------------------
# get_dated_cache_dir
# ---------------------------------------------------------------------------

def test_get_dated_cache_dir(tmp_path):
    result = helpers.get_dated_cache_dir(tmp_path, date(2024, 1, 2))
    assert result == tmp_path / "01-02-2024"


# ---------------------------------------------------------------------------
# to_json_serializable
# ---------------------------------------------------------------------------

def test_to_json_serializable_primitives_and_none():
    assert helpers.to_json_serializable("s") == "s"
    assert helpers.to_json_serializable(3) == 3
    assert helpers.to_json_serializable(None) is None


def test_to_json_serializable_datetime_and_date():
    assert helpers.to_json_serializable(date(2024, 1, 2)) == "2024-01-02"
    assert helpers.to_json_serializable(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05"


def test_to_json_serializable_sets_are_sorted_tuples_keep_order():
    assert helpers.to_json_serializable({3, 1, 2}) == [1, 2, 3]
    assert helpers.to_json_serializable((3, 1, 2)) == [3, 1, 2]


def test_to_json_serializable_nested_and_nonstring_keys():
    out = helpers.to_json_serializable({1: {"inner": {2, 1}}, (0, 1): "k"})
    assert out == {1: {"inner": [1, 2]}, "(0, 1)": "k"}


def test_to_json_serializable_object_with_dict():
    obj = SimpleNamespace(a=1, b=[date(2024, 1, 2)])
    assert helpers.to_json_serializable(obj) == {"a": 1, "b": ["2024-01-02"]}


def test_to_json_serializable_handles_cycles():
    node = SimpleNamespace(name="n")
    node.self_ref = node  # cycle
    out = helpers.to_json_serializable(node)
    assert out["name"] == "n"
    assert isinstance(out["self_ref"], str)  # cycle broken via str()


# ---------------------------------------------------------------------------
# to_json_string
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("empty", [None, [], {}])
def test_to_json_string_empty_is_blank(empty):
    assert helpers.to_json_string(empty) == ""


def test_to_json_string_serializes():
    assert helpers.to_json_string({"b": 1, "a": 2}) == '{"b": 1, "a": 2}'
    assert helpers.to_json_string([1, 2]) == "[1, 2]"


# ---------------------------------------------------------------------------
# write / read JSON + YAML
# ---------------------------------------------------------------------------

def test_write_dict_to_json_roundtrip(tmp_path, capsys):
    helpers.write_dict_to_json({"x": {1, 2}}, tmp_path, "out.json")
    written = json.loads((tmp_path / "out.json").read_text())
    assert written == {"x": [1, 2]}
    assert "JSON written" in capsys.readouterr().out


def test_get_dict_from_json_present_and_missing(tmp_path):
    path = tmp_path / "d.json"
    path.write_text('{"k": 1}')
    assert helpers.get_dict_from_json(str(path)) == {"k": 1}
    assert helpers.get_dict_from_json(str(tmp_path / "nope.json")) is None


def test_get_dict_from_tsv_present_and_missing(tmp_path):
    logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None)
    path = tmp_path / "d.json"
    path.write_text('{"k": 1}')
    assert helpers.get_dict_from_tsv(str(path), logger) == {"k": 1}
    assert helpers.get_dict_from_tsv(str(tmp_path / "missing.json"), logger) is None


def test_load_yaml_file(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("a: 1\nb:\n  - x\n  - y\n")
    assert helpers.load_yaml_file(str(path)) == {"a": 1, "b": ["x", "y"]}


# ---------------------------------------------------------------------------
# generic_cache_wrapper
# ---------------------------------------------------------------------------

def test_cache_wrapper_miss_collects_and_writes(tmp_path):
    result = helpers.generic_cache_wrapper("k", str(tmp_path), lambda: {"fresh": 1})
    assert result == {"fresh": 1}
    assert (tmp_path / "k.json").exists()


def test_cache_wrapper_hit_skips_collector(tmp_path):
    (tmp_path / "k.json").write_text('{"cached": 1}')

    def boom():
        raise AssertionError("collector should not run on a cache hit")

    assert helpers.generic_cache_wrapper("k", str(tmp_path), boom) == {"cached": 1}


def test_cache_wrapper_force_refresh_ignores_cache(tmp_path):
    (tmp_path / "k.json").write_text('{"cached": 1}')
    result = helpers.generic_cache_wrapper(
        "k", str(tmp_path), lambda: {"fresh": 1}, force_refresh=True
    )
    assert result == {"fresh": 1}


# ---------------------------------------------------------------------------
# download_with_retry
# ---------------------------------------------------------------------------

def test_download_with_retry_succeeds_first_try(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(1))
    logger = SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None)
    assert helpers.download_with_retry("http://x", logger, "/tmp/f") is True
    assert len(calls) == 1


def test_download_with_retry_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(helpers.time, "sleep", lambda *_: None)
    attempts = {"n": 0}

    def flaky(*a, **k):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise subprocess.CalledProcessError(1, "curl", stderr="boom")

    monkeypatch.setattr(subprocess, "run", flaky)
    logger = SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None)
    assert helpers.download_with_retry("http://x", logger, "/tmp/f", max_retries=3) is True
    assert attempts["n"] == 3


def test_download_with_retry_raises_after_exhausting(monkeypatch):
    monkeypatch.setattr(helpers.time, "sleep", lambda *_: None)

    def always_fail(*a, **k):
        raise subprocess.CalledProcessError(1, "curl", stderr="boom")

    monkeypatch.setattr(subprocess, "run", always_fail)
    logger = SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None)
    with pytest.raises(subprocess.CalledProcessError):
        helpers.download_with_retry("http://x", logger, "/tmp/f", max_retries=2)


# ---------------------------------------------------------------------------
# URL builders + formatting
# ---------------------------------------------------------------------------

def test_get_single_aopwiki_url_with_and_without_anchor():
    assert helpers.get_single_aopwiki_url(5, "aops") == "https://aopwiki.org/aops/5"
    assert helpers.get_single_aopwiki_url(5, "aops", "ke") == "https://aopwiki.org/aops/5/#ke"


def test_get_aopwiki_urls_maps_every_id():
    assert helpers.get_aopwiki_urls([1, 2], "events") == {
        1: "https://aopwiki.org/events/1",
        2: "https://aopwiki.org/events/2",
    }


def test_format_elapsed():
    assert helpers.format_elapsed(3661.5) == "01:01:01.500"
    assert helpers.format_elapsed(0) == "00:00:00.000"


def test_set_up_logger(tmp_path):
    log_file = tmp_path / "logs" / "run.log"
    logger = helpers.set_up_logger("test_logger", log_file=log_file)
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_logger"
    assert log_file.parent.is_dir()
