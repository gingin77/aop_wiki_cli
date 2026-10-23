"""
Unit tests for the within_aops module.

Tests cover:
- Selecting AOPs by ID, by title term, and by contained key event title
- Reporting requested AOP IDs that are absent from the export
- Restricting the search to the entities the selected AOPs own
- Reporting every term, including terms with no match
- Punctuation sensitivity of the word-boundary matcher
- KE and KER IDs an AOP references but the export lacks
- Case-sensitive terms, which acronyms need (iPSCs vs IPSCs)
- Term groups and record-level co-occurrence between two groups

Examples:
    Run directly::

        $ python -m pytest tests/test_within_aops.py
"""

from aop_wiki_cli.search.within_aops import (
    parse_term_groups,
    search_within_aops,
    select_aops,
)

import pytest


MOCK_AOPS = {
    "10": {
        "title": "Picrotoxin binding leading to epileptic seizures",
        "abstract": "Measured with a micro-electrode array.",
        "event_ids": ["613", "616"],
        "kers": {"630": {"type": "adjacent"}},
    },
    "281": {
        "title": "Acetylcholinesterase inhibition leading to neurodegeneration",
        "abstract": "No functional assay named here.",
        # 999 is referenced but absent from MOCK_EVENTS
        "event_ids": ["388", "999"],
        "kers": {"1857": {"type": "adjacent"}},
    },
    "402": {
        "title": "Thyroid peroxidase inhibition leads to heterotopia",
        "abstract": "Unrelated to the selected set.",
        "event_ids": ["1348"],
        "kers": {"2000": {"type": "adjacent"}},
    },
}

MOCK_EVENTS = {
    "613": {
        "title": "Occurrence, Epileptic seizure",
        "measurement_method": "Recently a technique called micro-electrode array (MEA) recording.",
    },
    "616": {
        "title": "Occurrence, A paroxysmal depolarizing shift",
        "measurement_method": "Measured in vitro using patch-clamp recording.",
    },
    "388": {
        "title": "Overactivation, NMDARs",
        "measurement_method": "Microelectrode array (MEA) recordings of network activity.",
    },
    "1348": {
        "title": "Decreased, Neuronal network function",
        "measurement_method": "Microelectrode array recordings in primary cultures.",
    },
}

MOCK_KERS = {
    "630": {
        "upstream_ke": {"id": "613", "title": "Occurrence, Epileptic seizure"},
        "downstream_ke": {"id": "616", "title": "Occurrence, A paroxysmal depolarizing shift"},
        "empirical_support": {"free_text": "Electrophysiological evidence in rodents.", "tables": []},
    },
    "1857": {
        "upstream_ke": {"id": "388", "title": "Overactivation, NMDARs"},
        "downstream_ke": {"id": "999", "title": "Neurodegeneration"},
        "quantitative_understanding": {"free_text": "No quantitative data.", "tables": []},
    },
    "2000": {
        "upstream_ke": {"id": "1348", "title": "Decreased, Neuronal network function"},
        "downstream_ke": {"id": "1349", "title": "Heterotopia"},
        "description": {"free_text": "Unrelated to the selected set.", "tables": []},
    },
}


def test_select_aops_by_id_reports_missing():
    selected, missing = select_aops(MOCK_AOPS, MOCK_EVENTS, aop_ids=["10", "4242"])

    assert list(selected) == ["10"]
    assert selected["10"]["selected_by"] == ["aop_id"]
    assert missing == ["4242"]


def test_select_aops_unions_the_three_selectors_and_records_each_reason():
    selected, missing = select_aops(
        MOCK_AOPS,
        MOCK_EVENTS,
        aop_ids=["10"],
        aop_title_terms=["neurodegeneration"],
        ke_title_terms=["seizure"],
    )

    assert sorted(selected) == ["10", "281"]
    assert selected["10"]["selected_by"] == ["aop_id", "ke_title:KE613"]
    assert selected["281"]["selected_by"] == ["aop_title:neurodegeneration"]
    assert missing == []


def test_select_aops_accepts_int_ids():
    selected, missing = select_aops(MOCK_AOPS, MOCK_EVENTS, aop_ids=[10])

    assert list(selected) == ["10"]
    assert missing == []


def test_search_is_confined_to_the_selected_aops_entities():
    result = search_within_aops(
        MOCK_AOPS, MOCK_EVENTS, MOCK_KERS, ["10"], ["micro-electrode array", "patch-clamp"]
    )

    assert result["scope"]["aops"] == ["10"]
    assert result["scope"]["events"] == ["613", "616"]
    assert result["scope"]["kers"] == ["630"]
    # KE 388 and 1348 also mention an array, but belong to AOPs not selected
    assert [hit["id"] for hit in result["findings"]["micro-electrode array"]] == ["10", "613"]
    assert [hit["id"] for hit in result["findings"]["patch-clamp"]] == ["616"]


def test_each_snippet_is_attributed_to_the_term_that_matched_it():
    result = search_within_aops(
        MOCK_AOPS, MOCK_EVENTS, MOCK_KERS, ["10"], ["micro-electrode array", "patch-clamp"]
    )

    hit = result["findings"]["patch-clamp"][0]
    assert hit["entity"] == "events"
    assert hit["label"] == "Occurrence, A paroxysmal depolarizing shift"
    assert hit["aop_ids"] == ["10"]
    assert "patch-clamp" in hit["snippets_by_field"]["measurement_method"][0]


def test_every_term_is_counted_including_terms_with_no_match():
    result = search_within_aops(
        MOCK_AOPS, MOCK_EVENTS, MOCK_KERS, ["10"], ["patch-clamp", "hiPSC"]
    )

    assert result["term_counts"]["patch-clamp"] == {"aops": 0, "events": 1, "kers": 0}
    assert result["term_counts"]["hiPSC"] == {"aops": 0, "events": 0, "kers": 0}
    assert result["terms_not_found"] == ["hiPSC"]
    assert "hiPSC" not in result["findings"]


def test_punctuation_differences_do_not_match():
    result = search_within_aops(
        MOCK_AOPS, MOCK_EVENTS, MOCK_KERS, ["10"], ["microelectrode array", "patch clamp"]
    )

    assert result["findings"] == {}
    assert result["terms_not_found"] == ["microelectrode array", "patch clamp"]


def test_ker_evidence_blocks_are_searched_through_free_text():
    result = search_within_aops(MOCK_AOPS, MOCK_EVENTS, MOCK_KERS, ["10"], ["electrophysiological"])

    hit = result["findings"]["electrophysiological"][0]
    assert (hit["entity"], hit["id"]) == ("kers", "630")
    assert list(hit["snippets_by_field"]) == ["empirical_support"]
    assert hit["label"] == (
        "Occurrence, Epileptic seizure -> Occurrence, A paroxysmal depolarizing shift"
    )


def test_entities_absent_from_the_export_are_reported_as_missing():
    result = search_within_aops(MOCK_AOPS, MOCK_EVENTS, MOCK_KERS, ["281"], ["MEA"])

    assert result["scope"]["events"] == ["388"]
    assert result["scope"]["missing"]["events"] == ["999"]
    assert result["scope"]["missing"]["kers"] == []


def test_matches_record_every_selected_aop_that_owns_the_entity():
    aops = {
        "10": dict(MOCK_AOPS["10"], event_ids=["613"]),
        "281": dict(MOCK_AOPS["281"], event_ids=["613"], kers={}),
    }
    result = search_within_aops(aops, MOCK_EVENTS, MOCK_KERS, ["281", "10"], ["MEA"])

    assert result["findings"]["MEA"][0]["aop_ids"] == ["10", "281"]


MOCK_CASE_EVENTS = {
    "388": {
        "title": "Overactivation, NMDARs",
        "measurement_method": (
            "Microelectrode array (MEA) recordings of network activity. Whole-cell patch "
            "clamp was used to study inhibitory postsynaptic currents (EPSCs and IPSCs, "
            "respectively) in brain slices."
        ),
    },
    "2078": {
        "title": "Loss of drebrin",
        "references": "Synapse maturation in human iPSC-derived neurons.",
    },
}

MOCK_CASE_AOPS = {
    "900": {
        "title": "Case sensitivity fixture",
        "event_ids": ["388", "2078"],
        "kers": {},
    }
}


def test_case_insensitive_acronym_matches_the_wrong_capitalization():
    result = search_within_aops(
        MOCK_CASE_AOPS, MOCK_CASE_EVENTS, {}, ["900"], ["iPSCs"]
    )

    # IPSCs, inhibitory postsynaptic currents, is not a stem cell
    assert [hit["id"] for hit in result["findings"]["iPSCs"]] == ["388"]


def test_a_cs_prefixed_term_rejects_the_wrong_capitalization():
    result = search_within_aops(
        MOCK_CASE_AOPS, MOCK_CASE_EVENTS, {}, ["900"], ["cs:iPSCs", "cs:iPSC"]
    )

    assert "iPSCs" in result["terms_not_found"]
    assert result["term_counts"]["iPSCs"] == {"aops": 0, "events": 0, "kers": 0}
    # The same acronym in its own capitalization still matches
    assert [hit["id"] for hit in result["findings"]["iPSC"]] == ["2078"]
    assert result["case_sensitive_terms"] == ["iPSCs", "iPSC"]


def test_a_cs_prefix_inside_a_group_does_not_leak_into_the_keys():
    result = search_within_aops(
        MOCK_CASE_AOPS, MOCK_CASE_EVENTS, {}, ["900"],
        [], {"ipsc": ["cs:iPSC", "cs:iPSCs"], "mea": ["cs:MEA"]},
    )

    assert result["groups"] == {"ipsc": ["iPSC", "iPSCs"], "mea": ["MEA"]}
    assert result["group_counts"] == {"ipsc": 1, "mea": 1}
    # KE 2078 has the iPSC, KE 388 has the MEA: no record has both
    assert result["co_occurrence"][0]["groups"] == ["ipsc", "mea"]
    assert result["co_occurrence"][0]["records"] == []


def test_co_occurrence_reports_a_record_matching_both_groups():
    result = search_within_aops(
        MOCK_CASE_AOPS, MOCK_CASE_EVENTS, {}, ["900"],
        [], {"mea": ["cs:MEA"], "clamp": ["patch clamp"]},
    )

    record = result["co_occurrence"][0]["records"][0]
    assert (record["entity"], record["id"]) == ("events", "388")
    assert record["terms_by_group"] == {"mea": ["MEA"], "clamp": ["patch clamp"]}
    assert record["fields_by_group"]["mea"] == ["measurement_method"]


def test_conflicting_case_sensitivity_for_one_term_is_refused():
    with pytest.raises(ValueError, match="both case-sensitively"):
        search_within_aops(MOCK_CASE_AOPS, MOCK_CASE_EVENTS, {}, ["900"], ["MEA", "cs:MEA"])


def test_parse_term_groups_reads_name_and_spellings():
    groups = parse_term_groups(["mea=microelectrode array|MEA", "ipsc=cs:iPSC"])

    assert groups == {"mea": ["microelectrode array", "MEA"], "ipsc": ["cs:iPSC"]}


def test_parse_term_groups_refuses_a_malformed_spec():
    for spec in ["microelectrode array", "=MEA", "mea="]:
        with pytest.raises(ValueError, match="name=term"):
            parse_term_groups([spec])
