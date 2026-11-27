"""Tests for the BioPortal subtree restriction: parameter construction and
the per-field subtree-root lookup.

BioPortal's subtree search (`subtree_root_id`) requires the singular
`ontology` parameter and exactly one ontology — sending `ontologies`
alongside it is a 400 — so these tests lock in both the param shapes and
the guard that disables the restriction for multi-ontology scopes.

Run directly:    python -m tests.test_subtree_search
Under pytest:    python -m pytest tests/test_subtree_search.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.annotate_term_helpers import (
    FIELD_ONTOLOGIES,
    FIELD_SUBTREE_ROOTS,
    field_subtree_root,
)
from aop_wiki_cli.annotation_scripts.query_bioportal import _search_params

GO_CC = "http://purl.obolibrary.org/obo/GO_0005575"


def test_plain_search_uses_ontologies_param():
    params = _search_params("membrane", "GO", "key")
    assert params["ontologies"] == "GO"
    assert "ontology" not in params
    assert "subtree_root_id" not in params


def test_subtree_search_uses_singular_ontology_param():
    params = _search_params("membrane", "GO", "key", subtree_root_iri=GO_CC)
    assert params["ontology"] == "GO"
    assert params["subtree_root_id"] == GO_CC
    # `ontologies` next to subtree_root_id is a BioPortal 400.
    assert "ontologies" not in params


def test_cellular_component_gets_the_go_cc_root():
    assert field_subtree_root("cellular_component", FIELD_ONTOLOGIES["cellular_component"]) == GO_CC


def test_unrestricted_fields_get_no_root():
    for field in ("biological_process", "cell_term", "organ_term"):
        assert field_subtree_root(field, FIELD_ONTOLOGIES[field]) is None


def test_multi_ontology_scope_disables_the_restriction():
    # Even if a root were configured, a comma-separated scope cannot use it.
    assert field_subtree_root("cellular_component", "GO,CL") is None


def test_every_configured_root_has_a_single_ontology_scope():
    for field in FIELD_SUBTREE_ROOTS:
        assert field in FIELD_ONTOLOGIES, field
        assert "," not in FIELD_ONTOLOGIES[field], (
            f"{field}: subtree roots require a single-ontology scope"
        )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL TESTS PASSED ✓")
