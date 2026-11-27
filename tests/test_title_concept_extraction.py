"""Tests for coerce_title_concepts — the gate between the holistic LLM
title-extraction call and the annotation workflow. The extraction is
LLM-first by design, so this coercion is what guarantees the workflow only
ever sees a vocabulary-valid action, non-empty subject phrases, and cleaned
hint phrases, falling back to the rule-based parse otherwise.

Run directly:    python -m tests.test_title_concept_extraction
Under pytest:    python -m pytest tests/test_title_concept_extraction.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.annotate_ke import coerce_title_concepts
from aop_wiki_cli.annotation_scripts.ke_title_parser import WIKI_ACTION_WORDS


def test_valid_payload_is_normalized():
    raw = {
        "biological_action": "decreased",
        "cellular_component": " mitochondrion ",
        "event_components": [
            {
                "subject": "mitochondrial fatty acid beta-oxidation",
                "biological_object": "fatty acid",
                "biological_process": "fatty acid beta-oxidation",
                "phenotype": None,
            }
        ],
    }
    out = coerce_title_concepts(raw, WIKI_ACTION_WORDS)
    assert out["biological_action"] == "decreased"
    assert out["cellular_component"] == "mitochondrion"
    assert out["event_components"] == [{
        "subject": "mitochondrial fatty acid beta-oxidation",
        "biological_object": "fatty acid",
        "biological_process": "fatty acid beta-oxidation",
        "phenotype": None,
    }]


def test_action_outside_vocabulary_becomes_none_without_failing():
    raw = {
        "biological_action": "upregulated",  # not a controlled-vocab term
        "event_components": [{"subject": "LXR activation"}],
    }
    out = coerce_title_concepts(raw, WIKI_ACTION_WORDS)
    assert out is not None
    assert out["biological_action"] is None
    assert out["event_components"][0]["subject"] == "LXR activation"


def test_empty_or_blank_phrases_become_none():
    raw = {
        "event_components": [{
            "subject": "hepatocyte proliferation",
            "biological_object": "  ",
            "biological_process": "",
            "phenotype": 42,  # wrong type
        }],
    }
    out = coerce_title_concepts(raw, WIKI_ACTION_WORDS)
    comp = out["event_components"][0]
    assert comp["biological_object"] is None
    assert comp["biological_process"] is None
    assert comp["phenotype"] is None


def test_unusable_payloads_return_none():
    assert coerce_title_concepts(None, WIKI_ACTION_WORDS) is None
    assert coerce_title_concepts("not json", WIKI_ACTION_WORDS) is None
    assert coerce_title_concepts({}, WIKI_ACTION_WORDS) is None
    # Components without a subject phrase are dropped; none left → unusable.
    assert coerce_title_concepts(
        {"event_components": [{"biological_object": "LXR"}, "junk"]},
        WIKI_ACTION_WORDS,
    ) is None


def test_components_without_subject_are_dropped_but_rest_survive():
    raw = {
        "event_components": [
            {"subject": ""},
            {"subject": "collagen accumulation", "phenotype": "collagen accumulation"},
        ],
    }
    out = coerce_title_concepts(raw, WIKI_ACTION_WORDS)
    assert [c["subject"] for c in out["event_components"]] == ["collagen accumulation"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL TESTS PASSED ✓")
