"""Tests for the pure resolution helpers in apply_manual_curations:
CURIE → IRI expansion, spec → stored-record resolution (no network), and
subject selection for per-subject curations.

Run directly:    python -m tests.test_apply_manual_curations
Under pytest:    python -m pytest tests/test_apply_manual_curations.py
"""

from __future__ import annotations

import pytest

from aop_wiki_cli.annotation_scripts.apply_manual_curations import (
    _curie_to_iri,
    _pick_subject,
    _resolve_string,
    _resolve_term,
)


def test_curie_to_iri_obo_prefix_becomes_purl():
    assert _curie_to_iri("GO:0005739") == ("http://purl.obolibrary.org/obo/GO_0005739", "GO")
    assert _curie_to_iri("cl:0000182") == ("http://purl.obolibrary.org/obo/CL_0000182", "CL")


def test_curie_to_iri_non_obo_keeps_curie():
    # HGNC is not an OBO prefix: the CURIE itself stays the id.
    assert _curie_to_iri("HGNC:7782") == ("HGNC:7782", "HGNC")
    assert _curie_to_iri("FOO:123") == ("FOO:123", "FOO")


def test_curie_to_iri_rejects_non_curie():
    with pytest.raises(ValueError):
        _curie_to_iri("not a curie")


def test_resolve_term_no_term_spec_builds_rejection_record():
    rec = _resolve_term("cell_term", {"no_term": True, "reason": "molecular-level KE"}, None)
    assert rec["term_id"] is None
    assert rec["source"] == "manual_rejection"
    assert rec["rejection_reason"] == "molecular-level KE"


def test_resolve_term_curie_spec_builds_term_record():
    rec = _resolve_term("cellular_component", {"curie": "GO:0005739", "label": "mitochondrion"}, None)
    assert rec == {
        "term_id": "http://purl.obolibrary.org/obo/GO_0005739",
        "label": "mitochondrion",
        "ontology": "GO",
        "source": "manual_curation",
        "curie": "GO:0005739",
    }


def test_resolve_term_requires_a_known_spec_key():
    with pytest.raises(ValueError):
        _resolve_term("cell_term", {}, None)
    with pytest.raises(ValueError):
        _resolve_term("cell_term", "hepatocyte", None)  # not a mapping


def test_resolve_term_query_without_key_fails_cleanly():
    with pytest.raises(ValueError):
        _resolve_term("cell_term", {"query": "hepatocyte"}, None)  # no BIOPORTAL_API_KEY


def test_resolve_string():
    assert _resolve_string("biological_organization", {"value": "Cellular"}) == "Cellular"
    assert _resolve_string("biological_organization", "Tissue") == "Tissue"
    with pytest.raises(ValueError):
        _resolve_string("biological_organization", {})


def test_pick_subject_single_subject_is_implicit():
    assert _pick_subject("phenotype", {}, ["only subject"], "68") == "only subject"


def test_pick_subject_requested_subject_wins():
    assert _pick_subject("phenotype", {"subject": "b"}, ["a", "b"], "68") == "b"


def test_pick_subject_multiple_subjects_require_explicit_choice():
    with pytest.raises(ValueError):
        _pick_subject("phenotype", {}, ["a", "b"], "68")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
