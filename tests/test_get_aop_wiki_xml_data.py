"""
Tests for collection/get_aop_wiki_xml_data.py — the XML ingestion layer.

The network download path is out of scope; these cover the pure validators and
the local filesystem/parse helpers: structure and entity-count validation, the
gzip extractor, XML parsing (including the empty/invalid guards), the
already-downloaded short-circuit in check_for_aopwikixml, and the in-session
cache hit in collect_xml_data.

Run with::

    $ uv run pytest tests/test_get_aop_wiki_xml_data.py
"""

import gzip
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from aop_wiki_cli import paths
from aop_wiki_cli.collection import get_aop_wiki_xml_data as gx

NS = "{http://www.aopkb.org/aop-xml}"
FIXTURE = Path(__file__).parent / "mock_data" / "mini_aop_wiki.xml"


@pytest.fixture
def logger():
    class _L:
        def __init__(self):
            self.messages = {"info": [], "warning": [], "error": []}

        def info(self, m):
            self.messages["info"].append(m)

        def warning(self, m):
            self.messages["warning"].append(m)

        def error(self, m):
            self.messages["error"].append(m)

    return _L()


@pytest.fixture
def root():
    return ET.parse(FIXTURE).getroot()


@pytest.fixture(autouse=True)
def reset_data_dir(monkeypatch):
    # Start every test with no override (so leakage from earlier tests can't
    # matter); monkeypatch restores the original value afterwards.
    monkeypatch.setattr(paths, "_data_dir_override", None)


# ---------------------------------------------------------------------------
# validate_xml_structure
# ---------------------------------------------------------------------------

def test_validate_xml_structure_valid(root, logger):
    assert gx.validate_xml_structure(root, NS, logger) is True
    assert any("validation passed" in m for m in logger.messages["info"])


def test_validate_xml_structure_none_raises(logger):
    with pytest.raises(ValueError, match="XML root is None"):
        gx.validate_xml_structure(None, NS, logger)


def test_validate_xml_structure_unexpected_tag_warns_but_passes(logger):
    el = ET.fromstring(f'<notdata xmlns="{NS[1:-1]}"><vendor-specific/></notdata>')
    assert gx.validate_xml_structure(el, NS, logger) is True
    assert logger.messages["warning"]  # warned about the root tag


def test_validate_xml_structure_missing_vendor_section_raises(logger):
    el = ET.fromstring(f'<data xmlns="{NS[1:-1]}"></data>')
    with pytest.raises(ValueError, match="vendor-specific"):
        gx.validate_xml_structure(el, NS, logger)


# ---------------------------------------------------------------------------
# validate_entity_counts
# ---------------------------------------------------------------------------

def test_validate_entity_counts_all_present(logger):
    refs = {"AOP": {"a": "1"}, "KE": {"k": "1"}, "KER": {"r": "1"}, "Stressor": {"s": "1"}}
    assert gx.validate_entity_counts(refs, logger) is True
    assert not logger.messages["warning"]


def test_validate_entity_counts_low_counts_warn(logger):
    assert gx.validate_entity_counts({}, logger) is True
    # every entity type is below its minimum
    assert len(logger.messages["warning"]) == 4


# ---------------------------------------------------------------------------
# collect_refs
# ---------------------------------------------------------------------------

def test_collect_refs(root):
    refs = gx.collect_refs(root, NS)
    assert refs["AOP"] == {"aopa": "1", "aopb": "2"}
    assert refs["KE"]["kea"] == "100"
    assert refs["KER"]["kera"] == "10"
    assert refs["Stressor"]["str-1"] == "500"


# ---------------------------------------------------------------------------
# extract_gzipped_xml
# ---------------------------------------------------------------------------

def test_extract_gzipped_xml_success(tmp_path, logger):
    name = "aop-wiki-xml-2024-01-01"
    base = str(tmp_path) + os.sep
    with gzip.open(base + name + ".gz", "wb") as f:
        f.write(b"<data/>")
    gx.extract_gzipped_xml(name, base, logger)
    assert (tmp_path / name).read_bytes() == b"<data/>"
    assert any("Successfully extracted" in m for m in logger.messages["info"])


def test_extract_gzipped_xml_missing_file_logs_error(tmp_path, logger):
    gx.extract_gzipped_xml("absent", str(tmp_path) + os.sep, logger)
    assert logger.messages["error"]
    assert not (tmp_path / "absent").exists()


# ---------------------------------------------------------------------------
# parse_xml
# ---------------------------------------------------------------------------

def test_parse_xml_valid(logger):
    root, ns = gx.parse_xml(str(FIXTURE), logger)
    assert ns == NS
    assert len(root) > 0


def test_parse_xml_empty_root_raises_systemexit(tmp_path, logger):
    empty = tmp_path / "empty.xml"
    empty.write_text(f'<data xmlns="{NS[1:-1]}"></data>')
    with pytest.raises(SystemExit):
        gx.parse_xml(str(empty), logger)


def test_parse_xml_malformed_raises_systemexit(tmp_path, logger):
    bad = tmp_path / "bad.xml"
    bad.write_text("<data>")  # unclosed
    with pytest.raises(SystemExit):
        gx.parse_xml(str(bad), logger)


# ---------------------------------------------------------------------------
# validate_xml
# ---------------------------------------------------------------------------

def test_validate_xml_valid(root, logger):
    refs = gx.collect_refs(root, NS)
    assert gx.validate_xml(root, NS, refs, logger) is None  # no raise


def test_validate_xml_structure_failure_exits(logger):
    with pytest.raises(SystemExit):
        gx.validate_xml(None, NS, {}, logger)


# ---------------------------------------------------------------------------
# check_for_aopwikixml — already-present short-circuit (no download)
# ---------------------------------------------------------------------------

def test_check_for_aopwikixml_returns_existing_file(tmp_path, logger):
    paths.set_data_dir(tmp_path)
    existing = paths.xml_inputs_dir()
    existing.mkdir(parents=True, exist_ok=True)
    full = existing / "aop-wiki-xml-2024-01-01"
    full.write_text("<data/>")

    result_path, is_fresh = gx.check_for_aopwikixml("2024-01-01", logger)
    assert Path(result_path) == full
    assert is_fresh is False


# ---------------------------------------------------------------------------
# collect_xml_data — in-session cache hit (no download/parse)
# ---------------------------------------------------------------------------

def test_collect_xml_data_cache_hit():
    sentinel = ("ROOT", NS, {"AOP": {}})
    key = "2099-12-31"
    gx._XML_CACHE[key] = sentinel
    try:
        assert gx.collect_xml_data(key) is sentinel
    finally:
        gx._XML_CACHE.pop(key, None)
