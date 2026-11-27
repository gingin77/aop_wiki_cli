"""Tests for the curator-guidance wiring: _guidance_context assembles the
rank_term context, and prompts.rank_term renders that context into the prompt
the LLM actually sees. Together these lock in that prior curator comments
(summarized by review_ref_comments) reach term selection instead of being
display-only.

Run directly:    python -m tests.test_rank_term_context
Under pytest:    python -m pytest tests/test_rank_term_context.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts import prompts
from aop_wiki_cli.annotation_scripts.annotate_ke import _guidance_context

CANDIDATES = [
    {"label": "mitochondrion", "ontology": "GO", "synonyms": ["mitochondria"]},
    {"label": "mitochondrial membrane", "ontology": "GO"},
]


def test_guidance_context_shapes():
    assert _guidance_context(None) is None
    assert _guidance_context("prefer HP terms") == {"curator_guidance": "prefer HP terms"}
    assert _guidance_context(None, selected_object="LXR") == {"selected_object": "LXR"}
    assert _guidance_context("prefer HP terms", selected_object="LXR") == {
        "selected_object": "LXR",
        "curator_guidance": "prefer HP terms",
    }
    # Falsy extras are dropped, not rendered as empty context lines.
    assert _guidance_context(None, selected_object=None) is None


def test_rank_term_prompt_renders_context_lines():
    prompt = prompts.rank_term(
        "Decreased, mitochondrial function", "cellular_component", CANDIDATES,
        context={"curator_guidance": "prefer the organelle over the membrane"},
    )
    assert "Additional context:" in prompt
    assert "- curator_guidance: prefer the organelle over the membrane" in prompt
    # Candidates and component guidance still present.
    assert "1. mitochondrion [GO]" in prompt
    assert "2. mitochondrial membrane [GO]" in prompt
    assert prompts.COMPONENT_GUIDANCE["cellular_component"] in prompt


def test_rank_term_prompt_without_context_has_no_context_block():
    prompt = prompts.rank_term("Decreased, mitochondrial function", "cellular_component", CANDIDATES)
    assert "Additional context:" not in prompt


if __name__ == "__main__":
    test_guidance_context_shapes()
    test_rank_term_prompt_renders_context_lines()
    test_rank_term_prompt_without_context_has_no_context_block()
    print("ALL TESTS PASSED ✓")
