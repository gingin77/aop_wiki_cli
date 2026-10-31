"""
Unit tests for the role of each Key Event within an AOP.

The XML lists an AOP's Key Events in three places: key-events, then
molecular-initiating-event and adverse-outcome. collect_base_aop_info_from_xml
keeps every id in event_ids and records which place it came from in event_roles.

Examples:
    $ uv run pytest tests/test_aop_event_roles.py
"""

import xml.etree.ElementTree as ET

from aop_wiki_cli.parsers.parse_aop_wiki_xml_data import collect_base_aop_info_from_xml

NS = "{http://www.aopkb.org/aop-xml}"

XML = """<data xmlns="http://www.aopkb.org/aop-xml">
  <aop id="a1">
    <status><oecd-status/><wiki-license>BY-SA</wiki-license></status>
    <molecular-initiating-event key-event-id="k1"/>
    <adverse-outcome key-event-id="k3"><examples>yes</examples></adverse-outcome>
    <key-events>
      <key-event key-event-id="k2"/>
      {listed_again}
    </key-events>
  </aop>
</data>"""

REFS = {"AOP": {"a1": "587"}, "KE": {"k1": "1542", "k2": "177", "k3": "896"}}


def collect(listed_again=""):
    root = ET.fromstring(XML.format(listed_again=listed_again))
    aops, _ = collect_base_aop_info_from_xml(root, NS, REFS)
    return aops["587"]


def test_each_event_has_its_role():
    aop = collect()
    assert aop["event_roles"] == {
        "1542": "MolecularInitiatingEvent",
        "177": "KeyEvent",
        "896": "AdverseOutcome",
    }


def test_event_ids_are_unchanged():
    assert sorted(collect()["event_ids"]) == ["1542", "177", "896"]


def test_an_mie_listed_again_among_the_key_events_stays_an_mie():
    aop = collect('<key-event key-event-id="k1"/>')
    assert aop["event_roles"]["1542"] == "MolecularInitiatingEvent"
