"""Downstream consumers of the AOP event list and the per-AOP KER mapping.

These are the functions that break, or silently change answers, when
`parse_aop_wiki_xml_data.py` is changed to:

- keep `<evidence>` and `<quantitative-understanding-value>` beside `<adjacency>`
  on each AOP's copy of a Key Event Relationship, and
- record a Key Event's role (MIE, KE, AO) per AOP instead of setting `is_ao`
  on the Key Event itself.

Nothing in `src/` reads `is_ao` today, so the risk of those changes sits in the
consumers of the three structures that do get read: `aop['kers']`,
`aop['event_ids']` and the `regulatory_relevance` field on an event. Each test
below pins one of those so a parser change that alters them is caught here
rather than in an output file.

`is_mie` and `is_ao` are now read from the role the AOP gives a Key Event, so
the tests for those pass. The last test is still `xfail(strict=True)`: it
states the behaviour the remaining fix should produce, recording the role per
AOP rather than per Key Event. When that lands it starts passing, the strict
marker turns that into a failure, and the marker has to be removed
deliberately.

Examples:
    Run all tests::

        $ python -m pytest tests/test_aop_event_and_ker_mappings.py
"""

# Imported from submodules rather than the package, matching the other test
# modules: a package-level import pulls in parsers <-> analysis circularly.
import xml.etree.ElementTree as ET

import pytest

from aop_wiki_cli.data_export.transformers import build_aop_to_ker_mapping
from aop_wiki_cli.parsers.completion_score import aop_completion_score
from aop_wiki_cli.parsers.parse_aop_wiki_xml_data import (
    add_aop_status_info_to_kes,
    update_ke_and_aop_mappings,
)
from aop_wiki_cli.parsers.xml_processing_helpers import collect_ker_to_aop_mapping_from_xml
from aop_wiki_cli.search.event_first_search import find_aops_containing_events
from aop_wiki_cli.search.search_text_by_field import search_entity_data

# The export identifies entities by UUID; refs maps those to AOP-Wiki ids.
REFS = {
    "AOP": {"aop-x": "344", "aop-y": "307", "aop-z": "26"},
    "KE": {"ke-a": "26", "ke-b": "1614", "ke-c": "1786"},
    "KER": {"ker-1": "2130", "ker-2": "2124"},
}


def key_event_element(uuid):
    """The element shape `update_ke_and_aop_mappings` is handed by its callers."""
    return ET.fromstring(f'<key-event key-event-id="{uuid}"/>')


def aop_xml(*aops):
    """A namespace-free export fragment, so tests pass '' as the namespace."""
    return ET.fromstring("<data>" + "".join(aops) + "</data>")


def relationship(ker_uuid, adjacency=None, evidence=None):
    """One AOP's copy of a relationship, with the fields the export puts there."""
    parts = [f'<relationship id="{ker_uuid}">']
    if adjacency is not None:
        parts.append(f"<adjacency>{adjacency}</adjacency>")
    if evidence is not None:
        parts.append(f"<evidence>{evidence}</evidence>")
    parts.append("</relationship>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Consumers of aop['kers'], whose inner dict gains two fields
# ---------------------------------------------------------------------------


def test_aop_to_ker_mapping_reads_only_the_keys():
    """Adding fields inside the per-KER dict must not change the KER list.

    `build_aop_to_ker_mapping` takes `.keys()`, so it should be indifferent to
    the inner shape. This is the test that lets the parser change go in.
    """
    before = {"344": {"kers": {"2130": {"type": "adjacent"}, "2124": {"type": "adjacent"}}}}
    after = {
        "344": {
            "kers": {
                "2130": {"type": "adjacent", "evidence": "High", "quantitative_understanding": "Not Specified"},
                "2124": {"type": "adjacent", "evidence": "High", "quantitative_understanding": "Not Specified"},
            }
        }
    }
    assert build_aop_to_ker_mapping(before) == {"344": ["2130", "2124"]}
    assert build_aop_to_ker_mapping(after) == build_aop_to_ker_mapping(before)


def test_aop_to_ker_mapping_omits_an_aop_with_no_relationships():
    """An AOP with an empty kers dict is left out rather than mapped to []."""
    mapping = build_aop_to_ker_mapping({"344": {"kers": {}}, "307": {"kers": {"2124": {}}}})
    assert mapping == {"307": ["2124"]}


def test_completion_score_is_unmoved_by_richer_ker_entries():
    """`kers` is scored for emptiness only, so the inner fields cannot shift it.

    `aop_completion_score` lists 'kers' among the structured fields it checks.
    If it ever looked inside, adding evidence fields would silently move every
    AOP's percentage, which is published in reports.
    """
    thin = {"title": "An AOP", "kers": {"2130": {"type": "adjacent"}}}
    rich = {"title": "An AOP", "kers": {"2130": {"type": "adjacent", "evidence": "High"}}}
    assert aop_completion_score(rich) == aop_completion_score(thin)
    assert "kers" not in aop_completion_score(thin)["empty_structured"]


def test_completion_score_is_unmoved_by_a_new_top_level_field():
    """Recording roles as a new AOP field must not change the denominator.

    The score's max is built from two fixed field lists. A new field such as
    `event_roles` is not in either, so the percentage has to stay put until
    someone adds it on purpose.
    """
    without = {"title": "An AOP", "kers": {"2130": {"type": "adjacent"}}, "event_ids": ["26"]}
    with_roles = dict(without, event_roles={"26": "MIE"})
    assert aop_completion_score(with_roles) == aop_completion_score(without)
    assert aop_completion_score(without)["max_score"] == 17


# ---------------------------------------------------------------------------
# collect_ker_to_aop_mapping_from_xml: the second place adjacency is parsed
# ---------------------------------------------------------------------------


def test_adjacency_is_already_recorded_per_aop_here():
    """This function already keys adjacency by AOP, which `aop['kers']` duplicates.

    One relationship can be adjacent in one AOP and non-adjacent in another, and
    this mapping keeps both. It is the natural home for the per-AOP evidence
    value too, rather than a third representation.
    """
    root = aop_xml(
        f'<aop id="aop-x"><key-event-relationships>{relationship("ker-1", "adjacent")}'
        "</key-event-relationships></aop>",
        f'<aop id="aop-y"><key-event-relationships>{relationship("ker-1", "non-adjacent")}'
        "</key-event-relationships></aop>",
    )
    ker_to_aop, aop_to_kers = collect_ker_to_aop_mapping_from_xml(root, "", REFS)
    assert ker_to_aop["2130"]["aop_ids"] == ["307", "344"]
    assert ker_to_aop["2130"]["adjacency_types"] == ["adjacent", "non-adjacent"]
    assert ker_to_aop["2130"]["aop_to_adjacency_type_pairs"] == {
        "307": "non-adjacent",
        "344": "adjacent",
    }
    assert aop_to_kers == {"344": ["2130"], "307": ["2130"]}


def test_a_relationship_with_no_adjacency_still_records_its_aop():
    """A missing or empty adjacency drops out of the pairs but keeps the AOP link."""
    root = aop_xml(
        '<aop id="aop-x"><key-event-relationships>'
        + relationship("ker-1")
        + relationship("ker-2", "")
        + "</key-event-relationships></aop>"
    )
    ker_to_aop, _ = collect_ker_to_aop_mapping_from_xml(root, "", REFS)
    for ker_id in ("2130", "2124"):
        assert ker_to_aop[ker_id]["aop_ids"] == ["344"]
        assert ker_to_aop[ker_id]["adjacency_types"] == []
        assert ker_to_aop[ker_id]["aop_to_adjacency_type_pairs"] == {}


def test_an_unmapped_relationship_id_raises_here_but_is_skipped_elsewhere():
    """The two adjacency parsers guard the refs lookup differently.

    `collect_aops_from_xml` tests `ker_xml_id in refs['KER']` and skips quietly;
    this function subscripts and raises. No relationship in the 2026-10-03
    export is unmapped, so the difference is latent, but the two should agree
    before a third caller depends on either.
    """
    root = aop_xml(
        '<aop id="aop-x"><key-event-relationships>'
        + relationship("ker-unknown", "adjacent")
        + "</key-event-relationships></aop>"
    )
    with pytest.raises(KeyError):
        collect_ker_to_aop_mapping_from_xml(root, "", REFS)


# ---------------------------------------------------------------------------
# Consumers of aop['event_ids'], which must stay a flat list of ids
# ---------------------------------------------------------------------------


def test_find_aops_containing_events_matches_on_the_event_id_list():
    """The AOP search reads `event_ids`, so roles must be recorded alongside it."""
    aops = {"344": {"event_ids": ["26", "1614", "1786"]}, "307": {"event_ids": ["1614", "286"]}}
    matched = find_aops_containing_events(aops, ["26"])
    assert set(matched) == {"344"}
    assert matched["344"]["source_events"] == ["26"]
    assert matched["344"]["total_events"] == 3


def test_find_aops_containing_events_normalizes_id_types():
    """Ids arrive as ints from some callers and strings from others."""
    aops = {"344": {"event_ids": [26, 1614]}}
    assert set(find_aops_containing_events(aops, ["26"])) == {"344"}
    assert set(find_aops_containing_events({"344": {"event_ids": ["26"]}}, [26])) == {"344"}


def test_a_new_roles_field_changes_no_match_but_is_echoed_into_the_result():
    """Adding `event_roles` beside `event_ids` must not change which AOPs match.

    This is the regression guard for recording roles: replacing `event_ids`
    with a role-keyed dict would break this function and four other callers,
    whereas adding a parallel field does not.

    It does change the payload, though. The whole AOP dict is copied into
    `aop_info` on every match, so a new parser field travels into search
    results and into anything serialized from them. That is worth knowing
    before the field is added, which is why it is asserted rather than
    glossed over.
    """
    plain = {"344": {"event_ids": ["26", "1614"]}}
    roles = {"26": "MIE", "1614": "KE"}
    with_roles = {"344": {"event_ids": ["26", "1614"], "event_roles": roles}}

    matched_plain = find_aops_containing_events(plain, ["26"])
    matched_roles = find_aops_containing_events(with_roles, ["26"])

    # What the search decides is identical.
    assert set(matched_plain) == set(matched_roles) == {"344"}
    for key in ("source_events", "num_matching_events", "total_events", "title"):
        assert matched_roles["344"][key] == matched_plain["344"][key]

    # What it hands on is not: the new field rides along inside aop_info.
    assert "event_roles" not in matched_plain["344"]["aop_info"]
    assert matched_roles["344"]["aop_info"]["event_roles"] == roles


# ---------------------------------------------------------------------------
# add_aop_status_info_to_kes, which reads the AOP base info the parser builds
# ---------------------------------------------------------------------------


def test_status_summary_is_built_from_every_associated_aop():
    ke_to_aop = {"1614": {"aop_ids": ["344", "307"]}}
    aop_base = {
        "344": {"oecd_status": "Under Development", "wiki_license": "BY-SA"},
        "307": {"oecd_status": "WPHA/WNT Endorsed", "wiki_license": "All rights reserved"},
    }
    enriched = add_aop_status_info_to_kes(ke_to_aop, aop_base)["1614"]
    assert enriched["summary_oecd_statuses"]["any_oecd_endorsed"] is True
    assert enriched["summary_oecd_statuses"]["in_oecd_aop_program"] is True
    assert enriched["aops_to_oecd"] == {"344": "Under Development", "307": "WPHA/WNT Endorsed"}
    assert sorted(enriched["summary_licenses"]["licenses"]) == ["All rights reserved", "BY-SA"]
    assert enriched["summary_licenses"]["any_all_rights_reserved"] is True
    assert enriched["summary_licenses"]["only_all_rights_reserved"] is False


def test_a_blank_oecd_status_is_not_counted_as_being_in_the_programme():
    """450-odd AOPs carry an empty status; empty must not read as participation."""
    enriched = add_aop_status_info_to_kes(
        {"1614": {"aop_ids": ["344"]}}, {"344": {"oecd_status": "", "wiki_license": "BY-SA"}}
    )["1614"]
    assert enriched["summary_oecd_statuses"]["in_oecd_aop_program"] is False
    assert enriched["summary_oecd_statuses"]["any_oecd_endorsed"] is False


def test_a_repeated_aop_id_duplicates_the_status_list():
    """`aop_ids` is appended to once per role, so a double role would double it.

    No AOP in the 2026-10-03 export lists the same Key Event twice, so this is
    latent. Recording roles means touching that append, and this pins what
    happens if the de-duplication is not added at the same time.
    """
    enriched = add_aop_status_info_to_kes(
        {"1786": {"aop_ids": ["344", "344"]}},
        {"344": {"oecd_status": "Under Development", "wiki_license": "BY-SA"}},
    )["1786"]
    assert enriched["summary_oecd_statuses"]["statuses"] == [
        "Under Development",
        "Under Development",
    ]
    assert enriched["aops"] == "344, 344"
    assert enriched["summary_licenses"]["licenses"] == ["BY-SA"]


# ---------------------------------------------------------------------------
# regulatory_relevance, the one field the is_ao logic actually writes
# ---------------------------------------------------------------------------


def test_a_false_regulatory_relevance_is_skipped_by_the_search():
    """`regulatory_relevance` is False or a string, and False is never searched.

    `_perform_entity_search` drops any falsy field value, so the shipped
    `regulatory_relevance` config screens only the events whose adverse-outcome
    entry happened to carry `<examples>` text. In the 2026-10-03 export that is
    69 of 1602 events; the other 1533 hold False and are passed over in silence.
    """
    entities = {
        "185": {"title": "Increase, Mutations", "regulatory_relevance": False},
        "406": {"title": "decreased, Fertility", "regulatory_relevance": "OECD TG 443 endpoint"},
    }
    params = {"fields_to_search": ["regulatory_relevance"], "terms": ["OECD"]}
    _, results = search_entity_data(entities, params)
    assert set(results) == {"406"}
    assert params["fields_to_search"] == ["regulatory_relevance"]


def test_a_string_regulatory_relevance_is_searched_normally():
    entities = {"406": {"title": "decreased, Fertility", "regulatory_relevance": "OECD TG 443"}}
    summary, results = search_entity_data(
        entities, {"fields_to_search": ["regulatory_relevance"], "terms": ["TG 443"]}
    )
    assert summary["terms_searched"]["TG 443"] == 1
    assert "406" in results


# ---------------------------------------------------------------------------
# The two bugs, stated as the behaviour the fix should produce
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# is_mie and is_ao, now read from the role the AOP gives the Key Event
# ---------------------------------------------------------------------------


def test_an_adverse_outcome_with_no_examples_text_is_still_an_adverse_outcome():
    """The flag follows the role, not the presence of regulatory-relevance text.

    `<examples>` is empty on 325 of the 656 adverse-outcome entries in the
    2026-10-03 export. While `is_ao` was derived from that text, 172 of the 241
    Key Events that are an adverse outcome somewhere were left False.
    """
    aop_base = {"344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(
        key_event_element("ke-c"), REFS, "344", aop_base, ke_to_aop,
        reg_field=None, event_type="AO",
    )
    assert ke_to_aop["1786"]["is_ao"] is True
    assert ke_to_aop["1786"]["is_mie"] is False
    # No examples text means no regulatory relevance, which is a separate fact.
    assert ke_to_aop["1786"]["regulatory_relevance"] is False


def test_regulatory_relevance_is_kept_when_the_text_is_there():
    aop_base = {"344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(
        key_event_element("ke-c"), REFS, "344", aop_base, ke_to_aop,
        reg_field="OECD TG 443 endpoint", event_type="AO",
    )
    assert ke_to_aop["1786"]["is_ao"] is True
    assert ke_to_aop["1786"]["regulatory_relevance"] == "OECD TG 443 endpoint"


def test_a_molecular_initiating_event_is_flagged():
    """`is_mie` had no equivalent at all; the role was read and discarded."""
    aop_base = {"344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(
        key_event_element("ke-a"), REFS, "344", aop_base, ke_to_aop, event_type="MIE"
    )
    assert ke_to_aop["26"]["is_mie"] is True
    assert ke_to_aop["26"]["is_ao"] is False


def test_an_intermediate_key_event_is_flagged_as_neither():
    aop_base = {"344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(
        key_event_element("ke-b"), REFS, "344", aop_base, ke_to_aop, event_type="KE"
    )
    assert ke_to_aop["1614"]["is_mie"] is False
    assert ke_to_aop["1614"]["is_ao"] is False


def test_the_default_role_is_an_intermediate_key_event():
    """A caller that names no role must not create an initiating event."""
    aop_base = {"344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(key_event_element("ke-b"), REFS, "344", aop_base, ke_to_aop)
    assert ke_to_aop["1614"]["is_mie"] is False
    assert ke_to_aop["1614"]["is_ao"] is False


def test_a_flag_set_by_one_aop_survives_another_aop():
    """Both flags mean "ever", so a second AOP must not clear the first.

    KE1065 is an adverse outcome in two AOPs and a Molecular Initiating Event
    in eight, and ends up with both flags set. That is the limit of a
    Key-Event-level flag, and the reason the per-AOP role is still wanted.
    """
    aop_base = {"26": {"id": "26", "event_ids": []}, "344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(
        key_event_element("ke-c"), REFS, "26", aop_base, ke_to_aop, event_type="AO"
    )
    update_ke_and_aop_mappings(
        key_event_element("ke-c"), REFS, "344", aop_base, ke_to_aop, event_type="MIE"
    )
    assert ke_to_aop["1786"]["is_ao"] is True
    assert ke_to_aop["1786"]["is_mie"] is True
    assert ke_to_aop["1786"]["aop_ids"] == ["26", "344"]


@pytest.mark.xfail(
    strict=True,
    reason="role is stored on the Key Event, not on the (Key Event, AOP) pair, "
    "so a Key Event that is an adverse outcome in one AOP and an "
    "intermediate event in another cannot be represented. 111 of 1602 "
    "events hold more than one role; 59 mix adverse outcome with another.",
)
def test_a_key_event_can_hold_a_different_role_in_each_aop():
    aop_base = {"26": {"id": "26", "event_ids": []}, "344": {"id": "344", "event_ids": []}}
    ke_to_aop = {}
    update_ke_and_aop_mappings(
        key_event_element("ke-c"), REFS, "26", aop_base, ke_to_aop, event_type="AO"
    )
    update_ke_and_aop_mappings(
        key_event_element("ke-c"), REFS, "344", aop_base, ke_to_aop, event_type="KE"
    )
    assert ke_to_aop["1786"]["roles"] == {"26": "AO", "344": "KE"}
