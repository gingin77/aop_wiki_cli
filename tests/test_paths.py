"""
Tests for paths.py — lazy resolution of every filesystem root the CLI uses.

It is the most widely imported module in the package, so its precedence rules
(``--data-dir`` override > ``AOP_WIKI_CLI_DATA_DIR`` env var > cwd) and the
packaged-vs-user-copy fallback are worth pinning down. Everything resolves at
call time, so the tests drive it with ``monkeypatch``/``tmp_path``.

Run with::

    $ uv run pytest tests/test_paths.py
"""

from pathlib import Path

import pytest

from aop_wiki_cli import paths


@pytest.fixture(autouse=True)
def reset_override():
    """paths keeps a module-level data-dir override; isolate every test."""
    saved = paths._data_dir_override
    paths._data_dir_override = None
    yield
    paths._data_dir_override = saved


# ---------------------------------------------------------------------------
# data-dir precedence
# ---------------------------------------------------------------------------

def test_set_data_dir_resolves_and_pins(tmp_path):
    returned = paths.set_data_dir(tmp_path)
    assert returned == tmp_path.resolve()
    # once pinned, get_data_dir returns it regardless of env/cwd
    assert paths.get_data_dir() == tmp_path.resolve()


def test_get_data_dir_override_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "from_env"))
    paths.set_data_dir(tmp_path / "override")
    assert paths.get_data_dir() == (tmp_path / "override").resolve()


def test_get_data_dir_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.get_data_dir() == tmp_path.expanduser().resolve()


def test_get_data_dir_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.get_data_dir() == Path.cwd()


# ---------------------------------------------------------------------------
# directory helpers (all relative to the data dir)
# ---------------------------------------------------------------------------

def test_subdir_helpers(tmp_path):
    paths.set_data_dir(tmp_path)
    assert paths.data_subdir("a", "b") == tmp_path.resolve() / "a" / "b"
    assert paths.outputs_dir("r.csv") == tmp_path.resolve() / "outputs" / "r.csv"
    assert paths.cache_root() == tmp_path.resolve() / "outputs" / "cache"
    assert paths.logs_dir() == tmp_path.resolve() / "logs"
    assert paths.xml_inputs_dir() == tmp_path.resolve() / "xml_inputs"
    assert paths.inputs_dir("in.json") == tmp_path.resolve() / "inputs" / "in.json"
    assert paths.curated_dir("c.json") == tmp_path.resolve() / "curated" / "c.json"


def test_ensure_dir_creates_and_returns(tmp_path):
    target = tmp_path / "nested" / "deep"
    result = paths.ensure_dir(target)
    assert result == target
    assert target.is_dir()


# ---------------------------------------------------------------------------
# packaged data + user-copy fallback
# ---------------------------------------------------------------------------

def test_package_data_path_points_inside_the_package():
    p = paths.package_data_path("curated", "x.json")
    assert isinstance(p, Path)
    assert p.parts[-3:] == ("data", "curated", "x.json")


def test_bundled_input_prefers_existing_user_copy(tmp_path):
    user_copy = tmp_path / "mine.xlsx"
    user_copy.write_text("data")
    assert paths.bundled_input(user_copy, "seizure_aops", "mine.xlsx") == user_copy


def test_bundled_input_falls_back_to_packaged(tmp_path):
    missing = tmp_path / "absent.json"
    result = paths.bundled_input(missing, "curated", "absent.json")
    # falls through to the packaged copy under aop_wiki_cli/data/
    assert result == paths.package_data_path("curated", "absent.json")


def test_seizure_and_curated_paths_resolve(tmp_path):
    paths.set_data_dir(tmp_path)  # no user copies exist → packaged fallback
    assert paths.seizure_workbook_path().name == "behl_seizure_supp_data.xlsx"
    assert paths.curated_input_path("map.json").name == "map.json"
