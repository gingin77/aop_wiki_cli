"""
Unit tests for MIE/AO role capture and pairing.

Tests cover:
- Parsing an AOP's <molecular-initiating-event> and <adverse-outcome> elements
  into per-AOP mie_ids / ao_ids
- An AO with no <examples> still being flagged as an AO
- One row per MIE/AO combination, including AOPs missing one side
- Selecting the KERs that belong to a set of AOPs
- Markdown rendering of the pair table

Examples:
    Run all tests::

        $ uv run python -m pytest tests/test_pair_mies_and_aos.py
"""
import xml.etree.ElementTree as ET

from aop_wiki_cli.analysis.pair_mies_and_aos import (
    build_mie_ao_pairs,
    filter_kers_by_aop_ids,
    render_mie_ao_markdown_table,
    summarize_mie_ao_pairs,
)
from aop_wiki_cli.parsers.parse_aop_wiki_xml_data import collect_base_aop_info_from_xml

NS = '{http://www.aopkb.org/aop-xml}'

# Two AOPs shaped like the AOP-Wiki XML export. AOP 100 is complete; AOP 200
# declares an MIE and an AO with no <examples>, and shares MIE x1 with AOP 100.
MOCK_XML = """<?xml version="1.0"?>
<data xmlns="http://www.aopkb.org/aop-xml">
  <aop id="a1">
    <status><oecd-status>Under Development</oecd-status><wiki-license>Open for adoption</wiki-license></status>
    <key-events>
      <key-event key-event-id="x2"/>
    </key-events>
    <molecular-initiating-event key-event-id="x1"/>
    <adverse-outcome key-event-id="x3"><examples>Liver injury in humans</examples></adverse-outcome>
  </aop>
  <aop id="a2">
    <status><oecd-status>WPHA/WNT Endorsed</oecd-status><wiki-license>All rights reserved</wiki-license></status>
    <key-events>
      <key-event key-event-id="x4"/>
    </key-events>
    <molecular-initiating-event key-event-id="x1"/>
    <adverse-outcome key-event-id="x5"/>
  </aop>
</data>
"""

MOCK_REFS = {
    'AOP': {'a1': '100', 'a2': '200'},
    'KE': {'x1': '11', 'x2': '22', 'x3': '33', 'x4': '44', 'x5': '55'},
    'KER': {},
    'Stressor': {},
}

MOCK_EVENTS = {
    '11': {'title': 'Activation of the pregnane X receptor'},
    '22': {'title': 'Increase, Hepatic steatosis'},
    '33': {'title': 'Liver injury'},
    '44': {'title': 'Increase, Bile acid accumulation'},
    '55': {'title': 'Cholestasis'},
}


def _parse_mock_xml():
    root = ET.fromstring(MOCK_XML)
    return collect_base_aop_info_from_xml(root, NS, MOCK_REFS)


def test_mie_and_ao_ids_recorded_per_aop():
    """MIEs and AOs land in their own lists as well as in event_ids."""
    print("\n=== Test 1: MIE and AO IDs recorded per AOP ===")

    aop_base_info, _ = _parse_mock_xml()

    assert aop_base_info['100']['mie_ids'] == ['11']
    assert aop_base_info['100']['ao_ids'] == ['33']
    assert sorted(aop_base_info['100']['event_ids']) == ['11', '22', '33']

    assert aop_base_info['200']['mie_ids'] == ['11']
    assert aop_base_info['200']['ao_ids'] == ['55']
    print("✓ mie_ids and ao_ids populated, event_ids still complete")


def test_adverse_outcome_without_examples_is_still_an_ao():
    """An <adverse-outcome> with no <examples> is an AO with no regulatory text."""
    print("\n=== Test 2: AO without <examples> ===")

    _, ke_to_aop_info = _parse_mock_xml()

    assert ke_to_aop_info['55']['is_ao'] is True
    assert ke_to_aop_info['55']['regulatory_relevance'] is False
    assert ke_to_aop_info['33']['regulatory_relevance'] == 'Liver injury in humans'
    print("✓ is_ao set from the element, regulatory_relevance from <examples>")


def test_key_event_is_mie_flag():
    """A KE used as an MIE is flagged; a plain KE is not."""
    print("\n=== Test 3: is_mie flag ===")

    _, ke_to_aop_info = _parse_mock_xml()

    assert ke_to_aop_info['11']['is_mie'] is True
    assert ke_to_aop_info['22']['is_mie'] is False
    assert ke_to_aop_info['11']['aop_ids'] == ['100', '200']
    print("✓ is_mie tracks the MIE, and the shared MIE lists both AOPs")


def test_build_pairs_one_row_per_combination():
    """Each AOP contributes one row per MIE/AO combination."""
    print("\n=== Test 4: One row per MIE/AO combination ===")

    aops = {
        '100': {'title': 'PXR to liver injury', 'mie_ids': ['11'], 'ao_ids': ['33'],
                'event_ids': ['11', '22', '33'], 'oecd_status': 'Under Development'},
        '200': {'title': 'Two AOs', 'mie_ids': ['11'], 'ao_ids': ['33', '55'],
                'event_ids': ['11', '44', '33', '55'], 'oecd_status': ''},
    }

    rows = build_mie_ao_pairs(aops, MOCK_EVENTS, matched_event_ids=['33'])

    assert len(rows) == 3
    assert rows[0]['aop_id'] == '100'
    assert rows[0]['mie_title'] == 'Activation of the pregnane X receptor'
    assert rows[0]['ao_title'] == 'Liver injury'
    assert rows[0]['ao_matched_search_term'] is True
    assert rows[0]['mie_matched_search_term'] is False
    assert {(r['aop_id'], r['ao_id']) for r in rows} == {('100', '33'), ('200', '33'), ('200', '55')}
    print(f"✓ {len(rows)} pair rows built across 2 AOPs")


def test_aop_missing_one_side_still_gets_a_row():
    """An AOP with no MIE or no AO keeps a row with that side blank."""
    print("\n=== Test 5: AOP missing an MIE or an AO ===")

    aops = {
        '300': {'title': 'No MIE declared', 'mie_ids': [], 'ao_ids': ['33'], 'event_ids': ['22', '33']},
        '400': {'title': 'No AO declared', 'mie_ids': ['11'], 'ao_ids': [], 'event_ids': ['11', '22']},
        '500': {'title': 'Neither', 'mie_ids': [], 'ao_ids': [], 'event_ids': ['22']},
    }

    rows = build_mie_ao_pairs(aops, MOCK_EVENTS)
    summary = summarize_mie_ao_pairs(rows)

    assert len(rows) == 3
    assert summary['aops_without_mie'] == 2
    assert summary['aops_without_ao'] == 2
    by_aop = {row['aop_id']: row for row in rows}
    assert by_aop['300']['mie_id'] == '' and by_aop['300']['mie_title'] == ''
    assert by_aop['400']['ao_id'] == '' and by_aop['400']['ao_title'] == ''
    print("✓ gaps stay visible instead of dropping the AOP")


def test_filter_kers_by_aop_ids():
    """KERs are selected by the AOPs they name, across str/int ID types."""
    print("\n=== Test 6: Filter KERs by AOP ===")

    kers = {
        '1': {'aop_ids': ['100', '999']},
        '2': {'aop_ids': [200]},
        '3': {'aop_ids': ['999']},
        '4': {'aop_ids': []},
    }

    selected = filter_kers_by_aop_ids(kers, ['100', '200'])

    assert set(selected) == {'1', '2'}
    print(f"✓ {len(selected)} of {len(kers)} KERs belong to the collected AOPs")


def test_markdown_table_renders_and_escapes_pipes():
    """The markdown table has a header, a divider, and one line per row."""
    print("\n=== Test 7: Markdown rendering ===")

    aops = {'100': {'title': 'A | B', 'mie_ids': ['11'], 'ao_ids': ['33'], 'event_ids': ['11', '33']}}
    table = render_mie_ao_markdown_table(build_mie_ao_pairs(aops, MOCK_EVENTS))
    lines = table.splitlines()

    assert lines[0].startswith('| AOP |')
    assert set(lines[1].replace('|', '').replace('-', '').strip()) == set()
    assert len(lines) == 3
    assert 'A \\| B' in lines[2]
    print("✓ table renders with the pipe in an AOP title escaped")
