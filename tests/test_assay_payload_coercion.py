"""Tests for coerce_assays — the shape gate between the assay-extraction LLM
reply and the store. A malformed reply must read as a failure (None, KE left
unstamped), never as "no assays" ([]), and must never crash the batch.

Run directly:    python -m tests.test_assay_payload_coercion
Under pytest:    python -m pytest tests/test_assay_payload_coercion.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts.assay_extraction import coerce_assays


def test_valid_payload_gets_sequential_ids():
    out = coerce_assays({"assays": [{"title": "ELISA"}, {"title": "qPCR"}]})
    assert [a["id"] for a in out] == [1, 2]


def test_empty_and_null_assay_lists_mean_no_assays():
    assert coerce_assays({"assays": []}) == []
    assert coerce_assays({"assays": None}) == []


def test_unusable_payloads_are_failures_not_empty_results():
    assert coerce_assays(None) is None
    assert coerce_assays("not json") is None
    assert coerce_assays({"assays": "ELISA"}) is None
    # A list of non-dict entries is malformed, not a report of zero assays.
    assert coerce_assays({"assays": ["ELISA", "qPCR"]}) is None


def test_non_dict_entries_are_dropped_but_valid_ones_survive():
    out = coerce_assays({"assays": ["junk", {"title": "ELISA"}]})
    assert out == [{"title": "ELISA", "id": 1}]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL TESTS PASSED ✓")
