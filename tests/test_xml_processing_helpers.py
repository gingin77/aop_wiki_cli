"""
Tests for parsers/xml_processing_helpers.py.

`parse_evidence_tables` and `collect_tables_from_field` are pure (HTML string /
stub object in), and `collect_ker_to_aop_mapping_from_xml` runs against the shared
mini AOP-Wiki XML fixture.

Run with::

    $ uv run pytest tests/test_xml_processing_helpers.py
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from aop_wiki_cli.collection.get_aop_wiki_xml_data import collect_refs
from aop_wiki_cli.parsers.xml_processing_helpers import (
    collect_ker_to_aop_mapping_from_xml,
    collect_tables_from_field,
    parse_evidence_tables,
)

NS = "{http://www.aopkb.org/aop-xml}"
FIXTURE = Path(__file__).parent / "mock_data" / "mini_aop_wiki.xml"


@pytest.fixture(scope="module")
def root_and_refs():
    root = ET.parse(FIXTURE).getroot()
    return root, collect_refs(root, NS)


# ---------------------------------------------------------------------------
# parse_evidence_tables
# ---------------------------------------------------------------------------

def test_parse_evidence_tables_with_header_row():
    html = ("<table><tr><th>Dose</th><th>Response</th></tr>"
            "<tr><td>Low</td><td>Weak</td></tr>"
            "<tr><td>High</td><td>Strong</td></tr></table>")
    tables, headers = parse_evidence_tables(html)
    assert set(headers) == {"Dose", "Response"}
    assert tables[0] == [
        {"Dose": "Low", "Response": "Weak"},
        {"Dose": "High", "Response": "Strong"},
    ]


def test_parse_evidence_tables_without_th_uses_first_row_as_headers():
    html = ("<table><tr><td>H1</td><td>H2</td></tr>"
            "<tr><td>a</td><td>b</td></tr></table>")
    tables, headers = parse_evidence_tables(html)
    assert set(headers) == {"H1", "H2"}
    assert tables[0] == [{"H1": "a", "H2": "b"}]


def test_parse_evidence_tables_pads_short_rows():
    html = ("<table><tr><th>H1</th><th>H2</th></tr>"
            "<tr><td>only</td></tr></table>")
    tables, _ = parse_evidence_tables(html)
    assert tables[0] == [{"H1": "only", "H2": ""}]


def test_parse_evidence_tables_truncates_long_rows():
    html = ("<table><tr><th>H1</th><th>H2</th></tr>"
            "<tr><td>a</td><td>b</td><td>extra</td></tr></table>")
    tables, _ = parse_evidence_tables(html)
    assert tables[0] == [{"H1": "a", "H2": "b"}]


def test_parse_evidence_tables_handles_entity_encoded_html():
    # The real export stores tables HTML-entity-encoded; the parser unescapes first.
    html = "&lt;table&gt;&lt;tr&gt;&lt;th&gt;Col&lt;/th&gt;&lt;/tr&gt;&lt;tr&gt;&lt;td&gt;v&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;"
    tables, headers = parse_evidence_tables(html)
    assert headers == ["Col"]
    assert tables[0] == [{"Col": "v"}]


# ---------------------------------------------------------------------------
# collect_tables_from_field
# ---------------------------------------------------------------------------

def test_collect_tables_from_field_with_table_text():
    field = SimpleNamespace(text="<table><tr><th>C</th></tr><tr><td>x</td></tr></table>")
    tables, headers = collect_tables_from_field(field)
    assert headers == ["C"]
    assert tables[0] == [{"C": "x"}]


@pytest.mark.parametrize("field", [
    None,
    SimpleNamespace(text=None),
    SimpleNamespace(text="just prose, no markup"),
])
def test_collect_tables_from_field_returns_empty_without_a_table(field):
    assert collect_tables_from_field(field) == ({}, [])


# ---------------------------------------------------------------------------
# collect_ker_to_aop_mapping_from_xml
# ---------------------------------------------------------------------------

def test_collect_ker_to_aop_mapping(root_and_refs):
    root, refs = root_and_refs
    ker_to_aop, aop_to_kers = collect_ker_to_aop_mapping_from_xml(root, NS, refs)

    assert ker_to_aop["10"]["aop_ids"] == ["1"]
    assert ker_to_aop["10"]["adjacency_types"] == ["adjacent"]
    assert ker_to_aop["10"]["aop_to_adjacency_type_pairs"] == {"1": "adjacent"}
    assert ker_to_aop["20"]["adjacency_types"] == ["non-adjacent"]
    assert sorted(aop_to_kers["1"]) == ["10", "20"]
