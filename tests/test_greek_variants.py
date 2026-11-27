"""Regression tests for query_bioportal._greek_variants and its wiring.

KE titles use Greek letters for receptor/cytokine names ("PPARα", "LXRβ",
"TNFα"). Those return zero BioPortal hits because ontology labels spell the
letter out or fold it into a Latin gene suffix, so the object resolved to null
(see KE 227 "PPARα"). _greek_variants produces Latin transliterations to retry.

Order matters: the single Latin letter attached to the stem (α→"a", giving
"PPARa") must come first, because it surfaces the correct gene/receptor
(PPARA [HGNC] and the PR alpha-receptor), whereas the spelled-out,
space-separated form ("PPAR alpha") tends to surface the wrong paralog.

Run directly:    python -m tests.test_greek_variants
Under pytest:    python -m pytest tests/test_greek_variants.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts import query_bioportal as qb

# (phrase, expected ordered variants)
CASES = [
    # The motivating case: single-letter form first, spelled-out second.
    ("PPARα", ["PPARa", "PPARalpha"]),
    ("LXRβ", ["LXRb", "LXRbeta"]),
    ("TNFα", ["TNFa", "TNFalpha"]),
    ("TGFβ", ["TGFb", "TGFbeta"]),
    # Uppercase Greek folds onto the same transliterations.
    ("PPARΑ", ["PPARa", "PPARalpha"]),
    # Multi-letter transliteration (θ→"th"/"theta").
    ("CD8θ", ["CD8th", "CD8theta"]),
    # No Greek letters -> no variants (fallback is a no-op).
    ("liver X receptor alpha", []),
    ("NRF2", []),
    ("", []),
]


def test_greek_variants_cases():
    print("\n=== _greek_variants transliterations ===")
    failures = []
    for phrase, expected in CASES:
        got = qb._greek_variants(phrase)
        status = "ok" if got == expected else "FAIL"
        print(f"  [{status}] {phrase!r:>24}  -> {got} (want {expected})")
        if got != expected:
            failures.append((phrase, expected, got))
    assert not failures, f"{len(failures)} case(s) wrong: {failures}"
    print("✓ Test passed")


def test_single_letter_form_is_first():
    """The attached single-letter form must precede the spelled-out word."""
    variants = qb._greek_variants("PPARα")
    assert variants, "expected transliterations for a Greek-letter phrase"
    assert variants[0] == "PPARa", f"single-letter form should be first, got {variants}"
    assert "PPARalpha" in variants
    assert variants.index("PPARa") < variants.index("PPARalpha")


def test_original_phrase_never_returned():
    """A variant is never identical to the input phrase."""
    for phrase, _ in CASES:
        assert phrase not in qb._greek_variants(phrase)


def run_all_tests() -> int:
    print("\n" + "=" * 68)
    print("GREEK VARIANT REGRESSION TESTS")
    print("=" * 68)
    test_greek_variants_cases()
    test_single_letter_form_is_first()
    test_original_phrase_never_returned()
    print("\n" + "=" * 68)
    print("ALL TESTS PASSED ✓")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
