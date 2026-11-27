"""
Tests for parsers/parse_aop_wiki_xml_data.py — the core AOP-Wiki XML → entity
parsing that nearly every command depends on.

The collect_*_from_xml functions are exercised against a small, structurally-real
XML fixture (tests/mock_data/mini_aop_wiki.xml); the dict-level helpers
(add_aop_status_info_to_kes, safe_text, update_ke_and_aop_mappings) are tested
directly.

Run with::

    $ uv run pytest tests/test_parse_aop_wiki_xml_data.py
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from aop_wiki_cli.collection.get_aop_wiki_xml_data import collect_refs
from aop_wiki_cli.parsers.parse_aop_wiki_xml_data import (
    add_aop_status_info_to_kes,
    collect_aops_from_xml,
    collect_base_aop_info_from_xml,
    collect_doa_fields,
    collect_ecs_from_xml,
    collect_events_from_xml,
    collect_kers_from_xml,
    collect_references_from_aops_kers_and_events,
    collect_taxonomies_from_xml,
    safe_text,
    update_ke_and_aop_mappings,
)

NS = "{http://www.aopkb.org/aop-xml}"
FIXTURE = Path(__file__).parent / "mock_data" / "mini_aop_wiki.xml"


@pytest.fixture(scope="module")
def root():
    return ET.parse(FIXTURE).getroot()


@pytest.fixture(scope="module")
def refs(root):
    return collect_refs(root, NS)


# ---------------------------------------------------------------------------
# collect_events_from_xml
# ---------------------------------------------------------------------------

def test_collect_events_ids_and_scores(root, refs):
    events = collect_events_from_xml(root, NS, refs)
    assert sorted(events) == ["100", "200", "300"]
    # every event gets a completion score and an integration ranking score
    for event in events.values():
        assert "completion_score" in event
        assert "integration_score" in event


def test_collect_events_tissue_event_fields(root, refs):
    events = collect_events_from_xml(root, NS, refs)
    ke = events["200"]
    assert ke["title"] == "Increased, apoptosis"
    assert ke["level_of_biological_organization"] == "Tissue"
    assert ke["organ_term"] == {"source": "UBERON", "term": "liver"}
    assert ke["sex_terms"] == ["Male"]
    assert ke["life_stage_terms"] == ["Adult"]
    assert ke["taxonomy_terms"][0]["title"] == "Homo sapiens"
    ec = ke["ecs"][0]
    assert ec["biological_process"]["term"] == "apoptotic process"
    assert ec["biological_object"]["term"] == "hepatocyte"
    assert ec["biological_action"]["term"] == "increased"
    assert ke["completion_score"]["percent"] == 100.0


def test_collect_events_molecular_event_uses_cell_term(root, refs):
    events = collect_events_from_xml(root, NS, refs)
    mie = events["100"]
    assert mie["level_of_biological_organization"] == "Molecular"
    assert mie["cell_term"] == {"source": "CL", "term": "hepatocyte"}
    assert mie["serves_as_mie"] is True


def test_collect_events_multi_role_outcome(root, refs):
    events = collect_events_from_xml(root, NS, refs)
    ao = events["300"]
    assert ao["serves_as_ao"] is True
    # KE 300 is the adverse outcome of AOP 1 but a plain key event in AOP 2
    assert ao["role_in_aop"] == {"1": "AdverseOutcome", "2": "KeyEvent"}
    assert ao["aops"] == "1, 2"
    assert ao["regulatory_relevance"] == "Hepatocellular carcinoma in humans."


# ---------------------------------------------------------------------------
# collect_ecs_from_xml / collect_taxonomies_from_xml
# ---------------------------------------------------------------------------

def test_collect_ecs(root):
    ecs = collect_ecs_from_xml(root, NS)
    assert ecs["processes"]["proc-1"]["term"] == "apoptotic process"
    assert ecs["processes"]["proc-1"]["source"] == "GO"
    assert ecs["objects"]["obj-1"]["term"] == "hepatocyte"
    assert ecs["actions"]["act-1"]["term"] == "increased"
    # actions carry source-id but not source
    assert "source" not in ecs["actions"]["act-1"]


def test_collect_taxonomies(root):
    tax = collect_taxonomies_from_xml(root, NS)
    assert tax["tax-1"] == {"source": "NCBI", "source-id": "9606", "title": "Homo sapiens"}


# ---------------------------------------------------------------------------
# collect_kers_from_xml
# ---------------------------------------------------------------------------

def test_collect_kers_upstream_downstream_and_tables(root, refs):
    kers = collect_kers_from_xml(root, NS, refs)
    assert sorted(kers) == ["10", "20"]
    ker = kers["10"]
    assert ker["upstream_ke"] == {"id": "100", "title": "Molecular initiating event, receptor activation"}
    assert ker["downstream_ke"] == {"id": "200", "title": "Increased, apoptosis"}
    assert ker["has_any_tables"] is True
    assert ker["adjacency_types"] == ["adjacent"]
    assert ker["aop_ids"] == ["1"]
    # the weight-of-evidence value carried an HTML table → parsed into rows
    assert ker["weight_of_evidence"]["tables"][0][0]["Dose"] == "Low"


def test_collect_kers_minimal_ker_has_none_fields(root, refs):
    kers = collect_kers_from_xml(root, NS, refs)
    ker = kers["20"]
    assert ker["has_any_tables"] is False
    assert ker["weight_of_evidence"]["free_text"] is None
    assert ker["time_scale"] is None
    assert ker["modulating_factors"] is None


# ---------------------------------------------------------------------------
# collect_aops_from_xml
# ---------------------------------------------------------------------------

def test_collect_aops_fields(root, refs):
    aops = collect_aops_from_xml(root, NS, refs)
    assert sorted(aops) == ["1", "2"]
    aop = aops["1"]
    assert aop["title"] == "Receptor activation leading to liver cancer"
    assert aop["handbook_version"] == 2.5
    assert aop["num_events"] == 3
    assert aop["stressors"] == ["500"]
    assert aop["coaches"] == ["Coach One"]
    assert set(aop["kers"]) == {"10", "20"}
    assert "completion_score" in aop


def test_collect_aops_old_handbook_parsed_as_float(root, refs):
    aops = collect_aops_from_xml(root, NS, refs)
    assert aops["2"]["handbook_version"] == 2.0


# ---------------------------------------------------------------------------
# collect_base_aop_info_from_xml
# ---------------------------------------------------------------------------

def test_collect_base_aop_info_roles(root, refs):
    aop_base_info, ke_to_aop_info = collect_base_aop_info_from_xml(root, NS, refs)
    assert aop_base_info["1"]["mie_ids"] == ["100"]
    assert aop_base_info["1"]["ao_ids"] == ["300"]
    assert set(aop_base_info["1"]["event_ids"]) == {"100", "200", "300"}
    # status/license propagate onto the KEs
    assert ke_to_aop_info["100"]["summary_oecd_statuses"]["any_oecd_endorsed"] is True


# ---------------------------------------------------------------------------
# collect_references_from_aops_kers_and_events
# ---------------------------------------------------------------------------

def test_collect_references(root, refs):
    references = collect_references_from_aops_kers_and_events(root, NS, refs)
    assert references["AOP"]["2"] == "Lee 2021"
    assert references["KE"]["100"] == "Smith 2020"
    assert references["KER"]["10"] == "Smith 2020; Jones 2019"


# ---------------------------------------------------------------------------
# dict-level helpers (no XML)
# ---------------------------------------------------------------------------

def test_add_aop_status_info_to_kes_summaries():
    ke_to_aop_info = {"100": {"aop_ids": ["1", "2"]}}
    aop_base_info = {
        "1": {"oecd_status": "WPHA/WNT Endorsed", "wiki_license": "Open for adoption"},
        "2": {"oecd_status": "", "wiki_license": "All rights reserved"},
    }
    out = add_aop_status_info_to_kes(ke_to_aop_info, aop_base_info)
    ke = out["100"]
    assert ke["summary_oecd_statuses"]["any_oecd_endorsed"] is True
    assert ke["summary_oecd_statuses"]["in_oecd_aop_program"] is True
    assert ke["summary_licenses"]["any_open_for_adoption"] is True
    assert ke["summary_licenses"]["any_all_rights_reserved"] is True
    assert ke["summary_licenses"]["only_open_for_adoption"] is False
    assert ke["aops"] == "1, 2"


@pytest.mark.parametrize("xml, default, expected", [
    ("<a>hi</a>", "", "hi"),
    ("<a></a>", "", ""),
    ("<a></a>", "fallback", "fallback"),
])
def test_safe_text(xml, default, expected):
    assert safe_text(ET.fromstring(xml), default) == expected


def test_safe_text_none_element_returns_default():
    assert safe_text(None) == ""
    assert safe_text(None, "x") == "x"


def test_update_ke_and_aop_mappings_rejects_unknown_event_type():
    ke = ET.fromstring('<x key-event-id="kea"/>')
    with pytest.raises(ValueError, match="event_type must be one of"):
        update_ke_and_aop_mappings(
            ke, {"KE": {"kea": "100"}}, "1",
            {"1": {"event_ids": [], "mie_ids": [], "ao_ids": []}}, {},
            event_type="BOGUS",
        )


def test_collect_doa_fields_without_applicability_is_empty():
    element = ET.fromstring('<ke xmlns="http://www.aopkb.org/aop-xml"/>')
    doa = collect_doa_fields(element, NS, {})
    assert doa == {"sex_terms": [], "life_stage_terms": [], "taxonomy_terms": []}
