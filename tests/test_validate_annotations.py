"""Tests for the pure parts of validate_annotations: IRI→CURIE conversion,
store traversal, and the field rules. The OAK-backed checks themselves need
the optional `validation` dependency group and are exercised manually.

Run directly:    python -m tests.test_validate_annotations
Under pytest:    python -m pytest tests/test_validate_annotations.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.validate_annotations import (
    FIELD_RULES,
    iri_to_curie,
    iter_term_records,
)
from aop_wiki_cli.annotation_scripts.annotate_term_helpers import FIELD_ONTOLOGIES


def test_iri_to_curie_obo_purls():
    assert iri_to_curie("http://purl.obolibrary.org/obo/GO_0005739") == "GO:0005739"
    assert iri_to_curie("http://purl.obolibrary.org/obo/PR_Q16236") == "PR:Q16236"
    assert iri_to_curie("http://purl.obolibrary.org/obo/UBERON_0002107") == "UBERON:0002107"


def test_iri_to_curie_curie_tails_and_passthrough():
    assert iri_to_curie(
        "https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:7782"
    ) == "HGNC:7782"
    assert iri_to_curie("HGNC:7782") == "HGNC:7782"


def test_iri_to_curie_unrecognized():
    assert iri_to_curie("") is None
    assert iri_to_curie("http://example.org/something/else") is None


def _store() -> dict:
    term = lambda curie, label: {  # noqa: E731
        "term_id": f"http://purl.obolibrary.org/obo/{curie.replace(':', '_')}",
        "label": label, "ontology": curie.split(":")[0], "source": "llm_recommendation",
    }
    return {
        "68": {
            "cell_term": term("CL:0000182", "hepatocyte"),
            "organ_term": None,
            "cellular_component": {"rejection_reason": "none fit", "source": "llm_rejection"},
            "ec_annotations": [
                {
                    "subject": "LXR activation",
                    "biological_object": term("PR:000011170", "LXR"),
                    "biological_process": None,
                    "phenotype": {"comment": "needs curation", "source": "manual_comment"},
                }
            ],
            "assays": [
                {
                    "id": 1,
                    "assay_type": term("OBI:0000070", "assay"),
                    "objects": [term("CHEBI:17855", "triglyceride"), {"label": "unresolved"}],
                    "processes": [],
                    "taxon_terms": [term("NCBITaxon:9606", "Homo sapiens")],
                }
            ],
        }
    }


def test_iter_term_records_yields_only_resolvable_records():
    records = list(iter_term_records(_store()))
    fields = [(loc, field) for _, loc, field, _ in records]
    assert ("cell_term", "cell_term") in fields
    assert ("ec['LXR activation'].biological_object", "biological_object") in fields
    assert ("assay[1].assay_type", "assay_type") in fields
    assert ("assay[1].objects", "biological_object") in fields
    assert ("assay[1].taxon_terms", "taxon_term") in fields
    # Nulls, rejections, comments, and label-only entries are not yielded.
    assert len(records) == 5
    assert all(rec.get("term_id") for _, _, _, rec in records)


def test_field_rules_cover_the_annotators_ontology_scopes():
    """Every field the annotator can assign has a validation rule, and the
    rule's prefixes match the BioPortal search scope."""
    for field, ontologies in FIELD_ONTOLOGIES.items():
        assert field in FIELD_RULES, field
        scope = {o.strip().upper() for o in ontologies.split(",")}
        # GO is additionally allowed for phenotype (UPHENO-incorporated terms).
        assert scope <= FIELD_RULES[field].prefixes, field


def test_closure_roots_are_within_allowed_prefixes():
    for field, rule in FIELD_RULES.items():
        for prefix, root in rule.roots.items():
            assert prefix in rule.prefixes, (field, prefix)
            assert root.split(":")[0] == prefix, (field, root)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL TESTS PASSED ✓")
