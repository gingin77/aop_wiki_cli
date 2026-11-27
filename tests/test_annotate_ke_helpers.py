"""Tests for the pure helpers in annotate_ke: reference masking (--force-on),
newly-annotated-field detection, comment normalization, and the off-target
process-result filter.

These encode the trickiest store semantics in the annotation workflow:
 - _mask_ref decides which stored values a --force-on run re-annotates,
 - _compute_newly_updated_fields decides what gets reported as new,
 - _flat_ref_comments / _strip_carried_suffix migrate older comment formats
   without compounding '[carried from reference]' suffixes,
 - partition_process_results keeps process terms for the resolved object and
   drops terms specific to a different variant of it.

Run directly:    python -m tests.test_annotate_ke_helpers
Under pytest:    python -m pytest tests/test_annotate_ke_helpers.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.annotate_ke import (
    _carry_manual_markers,
    _compute_newly_updated_fields,
    _flat_ref_comments,
    _manual_only_ref,
    _mask_ref,
    _strip_carried_suffix,
    _unmatched_ref_components,
    _workflow_ontology_acronyms,
    partition_process_results,
)


def _ref_ke() -> dict:
    return {
        "ke_id": "68",
        "biological_organization": "Cellular",
        "cell_term": {"term_id": "CL:1", "label": "hepatocyte", "source": "llm_recommendation"},
        "organ_term": None,
        "cellular_component": None,
        "assays": [{"id": 1, "title": "ELISA"}],
        "ec_annotations": [
            {
                "subject": "LXR activation",
                "biological_object": {"term_id": "PR:1", "label": "LXR", "source": "llm_recommendation"},
                "biological_process": None,
                "phenotype": {"rejection_reason": "no match", "source": "llm_rejection"},
                "biological_action": {"term": "increased", "source": "controlled_vocab"},
            }
        ],
    }


def test_mask_ref_top_level_field():
    masked = _mask_ref(_ref_ke(), {"cell_term"})
    assert masked["cell_term"] is None
    # Everything else untouched.
    assert masked["biological_organization"] == "Cellular"
    assert masked["assays"] == [{"id": 1, "title": "ELISA"}]
    assert masked["ec_annotations"][0]["biological_object"]["label"] == "LXR"


def test_mask_ref_ecs_field_nulls_every_subject():
    ref = _ref_ke()
    ref["ec_annotations"].append(dict(ref["ec_annotations"][0], subject="second subject"))
    masked = _mask_ref(ref, {"biological_object"})
    assert all(s["biological_object"] is None for s in masked["ec_annotations"])
    # Other ECS fields survive.
    assert masked["ec_annotations"][0]["phenotype"]["source"] == "llm_rejection"


def test_mask_ref_does_not_mutate_input():
    ref = _ref_ke()
    _mask_ref(ref, {"cell_term", "biological_object"})
    assert ref["cell_term"] is not None
    assert ref["ec_annotations"][0]["biological_object"] is not None


def test_mask_ref_assays_field():
    masked = _mask_ref(_ref_ke(), {"assays"})
    assert masked["assays"] is None


def test_unmatched_ref_components_are_detected_for_carryover():
    """A stored component whose subject the extraction reworded must be
    carried over, not silently dropped on save."""
    ref = {
        "Increased, fatty acid synthesis": {
            "subject": "Increased, fatty acid synthesis",
            "biological_object": {"term_id": "CHEBI:1", "label": "fatty acid",
                                  "source": "manual_curation"},
            "biological_process": None, "phenotype": None,
        },
        "empty one": {"subject": "empty one", "biological_object": None,
                      "biological_process": None, "phenotype": None},
    }
    carried = _unmatched_ref_components(ref, ["fatty acid synthesis"])
    # The manually curated component is carried; the empty one is not worth keeping.
    assert [c["subject"] for c in carried] == ["Increased, fatty acid synthesis"]
    # A matching subject is handled by the normal reference path, not carryover.
    assert _unmatched_ref_components(ref, ["Increased, fatty acid synthesis"]) == []


def test_unmatched_llm_components_are_not_carried():
    """Carrying LLM-sourced components would duplicate the event under both
    the old and the reworded subject phrase; only manual values are kept."""
    ref = {
        "Increased, fatty acid synthesis": {
            "subject": "Increased, fatty acid synthesis",
            "biological_object": {"term_id": "CHEBI:1", "label": "fatty acid",
                                  "source": "llm_recommendation"},
            "biological_process": {"rejection_reason": "x", "source": "llm_rejection"},
            "phenotype": None,
        },
    }
    assert _unmatched_ref_components(ref, ["fatty acid synthesis"]) == []


def test_manual_markers_survive_the_save_and_protect_force():
    """apply_ke_annotation_curations → annotate_ke save → --force: the provenance
    marker must ride through the save for the curated string value to
    survive the forced run."""
    ref = {"biological_organization": "Tissue",
           "manually_curated_fields": ["biological_organization"]}
    saved_entry = {"ke_id": "9", "biological_organization": "Tissue"}
    _carry_manual_markers(saved_entry, ref)
    assert saved_entry["manually_curated_fields"] == ["biological_organization"]
    # The marker on the saved entry is what a later --force run reads:
    kept = _manual_only_ref(saved_entry)
    assert kept["biological_organization"] == "Tissue"
    # Without a marker, nothing is carried and nothing crashes.
    plain = {"ke_id": "9"}
    _carry_manual_markers(plain, {"biological_organization": "Tissue"})
    assert "manually_curated_fields" not in plain


def test_marker_dropped_for_deliberately_reannotated_field():
    """--force-on a curated field replaces the curator's value, so its
    marker must not survive to bless the LLM's new value as manual."""
    ref = {"manually_curated_fields": ["biological_organization", "cell_term"]}
    entry = {"ke_id": "9"}
    _carry_manual_markers(entry, ref, re_annotated={"biological_organization"})
    assert entry["manually_curated_fields"] == ["cell_term"]
    # Re-annotating the only marked field drops the key entirely.
    entry2 = {"ke_id": "9"}
    _carry_manual_markers(entry2, {"manually_curated_fields": ["cell_term"]},
                          re_annotated={"cell_term"})
    assert "manually_curated_fields" not in entry2


def test_unmatched_action_record_is_not_newly_annotated():
    """{"term": None, "source": "unmatched"} is absence, not an annotation."""
    stored = {
        "ec_annotations": [{
            "subject": "s",
            "biological_object": None, "biological_process": None, "phenotype": None,
            "biological_action": {"term": None, "source": "unmatched", "vocabulary": None},
        }],
    }
    assert _compute_newly_updated_fields(None, stored) == []


def test_workflow_ontology_acronyms_cover_every_scope():
    """The provenance fetch must cover every ontology the workflow queries."""
    acronyms = _workflow_ontology_acronyms()
    assert acronyms == sorted(acronyms)
    for expected in ("GO", "CL", "UBERON", "CHEBI", "PR", "HGNC",
                     "UPHENO", "HP", "MP", "OBI", "BAO", "NCBITAXON"):
        assert expected in acronyms, expected


def test_manual_only_ref_keeps_manual_values_and_drops_llm_ones():
    ref = _ref_ke()
    ref["organ_term"] = {"term_id": "UBERON:0002048", "label": "lung", "source": "manual_review"}
    ref["ec_annotations"][0]["phenotype"] = {
        "term_id": "HP:1", "label": "x", "source": "manual_curation"}
    kept = _manual_only_ref(ref)
    # Manual values survive a --force run as references...
    assert kept["organ_term"]["label"] == "lung"
    assert kept["ec_annotations"][0]["phenotype"]["source"] == "manual_curation"
    assert kept["ec_annotations"][0]["subject"] == "LXR activation"
    # ...while LLM-sourced values are dropped so they re-annotate.
    assert "cell_term" not in kept
    assert "biological_object" not in kept["ec_annotations"][0]


def test_manual_only_ref_preserves_comments_for_forced_runs():
    """Comments must survive --force so ranking guidance still sees them."""
    ref = _ref_ke()
    ref["comments"] = {"carried": [], "new": ["prefer the CL hepatocyte term"]}
    kept = _manual_only_ref(ref)
    assert kept["comments"]["new"] == ["prefer the CL hepatocyte term"]


def test_manual_only_ref_keeps_curated_biological_organization():
    """A string field has no source marker; manually_curated_fields carries
    its provenance so --force cannot discard the curated level."""
    ref = _ref_ke()
    ref["manually_curated_fields"] = ["biological_organization"]
    kept = _manual_only_ref(ref)
    assert kept["biological_organization"] == "Cellular"
    # Without the provenance marker, the LLM-set level is re-detected.
    assert "biological_organization" not in (_manual_only_ref(_ref_ke()) or {})


def test_manual_only_ref_returns_none_when_nothing_is_manual():
    assert _manual_only_ref(_ref_ke()) is None


def test_newly_updated_fields_against_empty_ref():
    stored = _ref_ke()
    new = _compute_newly_updated_fields(None, stored)
    assert "biological_organization" in new
    assert "cell_term" in new
    assert "assays" in new
    assert "ec_annotations['LXR activation'].biological_object" in new
    assert "ec_annotations['LXR activation'].biological_action" in new
    # Null and rejected slots are not "newly annotated".
    assert "organ_term" not in new
    assert not any("phenotype" in f for f in new)


def test_newly_updated_fields_ignores_values_already_in_ref():
    stored = _ref_ke()
    assert _compute_newly_updated_fields(stored, stored) == []


def test_newly_updated_fields_detects_single_fill():
    ref = _ref_ke()
    stored = _mask_ref(ref, set())  # deep copy
    stored["organ_term"] = {"term_id": "UBERON:1", "label": "liver", "source": "llm_recommendation"}
    assert _compute_newly_updated_fields(ref, stored) == ["organ_term"]


def test_flat_ref_comments_handles_all_storage_formats():
    assert _flat_ref_comments(None) == []
    assert _flat_ref_comments([]) == []
    assert _flat_ref_comments(["a", "b"]) == ["a", "b"]
    assert _flat_ref_comments({"carried": ["a"], "new": ["b"]}) == ["a", "b"]
    # Nested lists inside buckets are flattened (legacy format).
    assert _flat_ref_comments({"carried": [["a", "b"]], "new": ["c"]}) == ["a", "b", "c"]


def test_strip_carried_suffix_removes_repeats():
    s = "check the organ term [carried from reference] [carried from reference]"
    assert _strip_carried_suffix(s) == "check the organ term"
    # Only trailing suffixes are stripped.
    assert _strip_carried_suffix("no suffix here") == "no suffix here"
    assert _strip_carried_suffix("[carried from reference] leading stays") == \
        "[carried from reference] leading stays"


def test_partition_process_results_filters_other_variants():
    results = [
        {"label": "fatty acid beta-oxidation", "ontology": "GO"},
        {"label": "PPAR gamma signaling", "ontology": "GO"},
        {"label": "PPAR alpha signaling", "ontology": "GO"},
        {"label": "signal transduction", "ontology": "GO"},
    ]
    kept, filtered_out = partition_process_results(results, "PPAR alpha")
    kept_labels = [r["label"] for r in kept]
    # Generic terms (no object word) and exact-object terms are kept...
    assert "fatty acid beta-oxidation" in kept_labels
    assert "signal transduction" in kept_labels
    assert "PPAR alpha signaling" in kept_labels
    # ...terms naming a different variant of the object are filtered out.
    assert [r["label"] for r in filtered_out] == ["PPAR gamma signaling"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL TESTS PASSED ✓")
