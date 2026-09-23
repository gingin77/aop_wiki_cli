"""
Tests for event_content_internal_alignment.

Uses three Events from the 09-03-2026 AOP-Wiki snapshot, trimmed to the fields the
checks read (tests/mock_data/alignment_events_09-03-2026.json). Each expectation
was set by reading the Event's text, not by running the checks:

- KE 1908 Cilia Beat Frequency, Decreased (Cellular): consistent on every check.
- KE 1909 Mucociliary Clearance, Decreased (Individual): the description is about
  tracheal and small-airway clearance and has no individual-level content, so
  the level should be flagged.
- KE 1250 Decrease, Lung function (Individual): the level is right. Its taxa and
  life-stage mismatches are covered by the commented-out tests below.

Run with::

    $ uv run pytest tests/test_event_content_internal_alignment.py
"""

import json
from pathlib import Path

import pytest

from aop_wiki_cli.analysis.event_content_internal_alignment import (
    FLAG,
    NOTE,
    UNCHECKED,
    SUPPLEMENTARY_LEVEL_CUES,
    check_event,
    check_events,
    check_level,
    enum_values,
    level_cues,
)

FIXTURE = Path(__file__).parent / "mock_data" / "alignment_events_09-03-2026.json"


@pytest.fixture(scope="module")
def events():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def flags(findings, check=None):
    return [f for f in findings if f["severity"] == FLAG and (check is None or f["check"] == check)]


# --- schema ---------------------------------------------------------------

def test_level_cues_come_from_the_schema_definitions():
    """Every level has cue words, derived from that level's definition in the schema."""
    levels = enum_values("BiologicalOrganizationEnum")
    cues = level_cues()
    assert set(cues) == set(levels)
    for level in levels:
        assert cues[level], f"{level} has no cue words; is its definition missing?"


def test_level_cue_words_track_the_definition_text():
    """A word in a level's definition is searched for; one absent from it is not."""
    cues = level_cues()
    assert any("fibrosis" in p for p in cues["Tissue"])
    assert not any("fibrosis" in p for p in cues["Individual"])
    assert any("survival" in p for p in cues["Individual"])
    # Words that appear only inside a definition's quoted examples are not cues:
    # "Increase, Mortality" illustrates the Individual level without defining it.
    assert not any("mortality" in p for p in cues["Individual"])


def test_no_local_cue_words_are_needed():
    """Cue words belong in the schema definitions, not in this module."""
    assert SUPPLEMENTARY_LEVEL_CUES == {}


# def test_schema_enums_hold_the_all_covering_values():
#     assert {"Mixed", "Unspecific"} <= set(enum_values("SexTermEnum"))
#     assert {"All life stages", "Not Otherwise Specified"} <= set(enum_values("LifeStageTermEnum"))


# --- level ----------------------------------------------------------------

def test_ke1909_level_is_flagged(events):
    found = flags(check_level("1909", events["1909"]))
    assert len(found) == 1
    assert "Individual" in found[0]["message"]
    # Cues for other levels, and the schema's definition of the assigned one.
    assert found[0]["evidence"]
    assert "whole organism" in (found[0]["definition"] or "")


def test_ke1250_level_passes(events):
    assert flags(check_level("1250", events["1250"])) == []


def test_ke1908_level_passes(events):
    assert flags(check_level("1908", events["1908"])) == []


def test_empty_description_is_unchecked_not_noted():
    """An Event with no description is separated from one whose text lacks cue words."""
    found = check_level("x", {"level_of_biological_organization": "Cellular",
                              "description": "<p>&nbsp;</p>"})
    assert [f["severity"] for f in found] == [UNCHECKED]
    assert "no description" in found[0]["message"]


def test_text_without_cue_words_is_a_note():
    found = check_level("x", {"level_of_biological_organization": "Cellular",
                              "description": "<p>An observation was recorded.</p>"})
    assert [f["severity"] for f in found] == [NOTE]
    assert "no level cue words" in found[0]["message"]


def test_unknown_level_value_is_flagged():
    found = check_level("x", {"level_of_biological_organization": "Organism", "description": ""})
    assert flags(found) and "not a value" in found[0]["message"]


# --- taxa, sex and life stage - COMMENTED OUT --------------------------------
#
# These passed before the prototype was narrowed to the level check. They come
# back with the checks they cover; see the note in the module.
#
# # --- taxa -----------------------------------------------------------------
#
# def test_ke1250_taxa_flags_unlisted_species_in_applicability_text(events):
#     found = flags(check_taxa("1250", events["1250"]))
#     assert len(found) == 1
#     assert found[0]["field"] == "doa_free_text"
#     assert set(found[0]["evidence"]) == {"rabbit", "pig", "horse", "dog", "cat", "rodents"}
#
#
# def test_guinea_pig_is_not_read_as_pig(events):
#     """KE 1908 names guinea pigs and lists Cavia porcellus but not Sus scrofa."""
#     assert flags(check_taxa("1908", events["1908"])) == []
#
#
# def test_bullfrog_synonyms_map_to_one_species(events):
#     """KE 1908 lists Lithobates catesbeianus and KE 1909 Rana catesbeiana."""
#     for ke in ("1908", "1909"):
#         unmapped = [f for f in check_taxa(ke, events[ke]) if "cannot map" in f["message"]]
#         assert unmapped == []
#
#
# # --- sex and life stage ---------------------------------------------------
#
# def test_ke1250_life_stage_is_flagged(events):
#     found = flags(check_life_stage("1250", events["1250"]))
#     assert len(found) == 1
#     assert "Adult" in found[0]["message"]
#
#
# def test_ke1250_sex_passes_because_mixed_covers_all(events):
#     assert flags(check_sex("1250", events["1250"])) == []
#
#
# @pytest.mark.parametrize("ke", ["1908", "1909"])
# def test_sex_and_life_stage_pass(events, ke):
#     assert flags(check_sex(ke, events[ke])) == []
#     assert flags(check_life_stage(ke, events[ke])) == []
#
#
# def test_restricted_sex_contradicted_by_text_is_flagged():
#     event = {"sex_terms": ["Male"],
#              "doa_free_text": "<p>Observed in both sexes of every species tested.</p>"}
#     assert flags(check_sex("x", event))
#
#
# def test_sex_value_outside_schema_is_flagged():
#     assert flags(check_sex("x", {"sex_terms": ["Both"]}))


# --- entry points ---------------------------------------------------------

def test_expected_flags_per_event(events):
    """Only KE 1909 is flagged: its assigned level contradicts its description.

    KE 1250's flags were for taxa and life stage, so with those checks commented
    out it passes here; its level is right.
    """
    got = {ke: sorted({f["check"] for f in flags(check_event(ke, events[ke]))}) for ke in events}
    assert got == {"1908": [], "1909": ["level"], "1250": []}


def test_check_events_summary(events):
    result = check_events(events, ke_ids=["1908", "1909", "1250", "999999"])
    summary = result["summary"]
    assert summary["events_read"] == 3
    assert summary["events_not_found"] == ["999999"]
    assert summary["events_with_flags"] == 1
    # All three fixture Events carry a description, so none is unchecked.
    assert summary["events_unchecked"] == 0
    assert summary["findings_by_check"]["level"]["unchecked"] == 0
