"""Regression tests for query_bioportal._iri_prefix.

The prefix it returns is what annotate_ke's off-target filter compares against the
requested ontology set. The old digits-only pattern returned '' for HGNC IRIs and
species-specific Protein Ontology IRIs (letter+digits local ids like PR_Q16236),
so those correct terms were silently discarded as "off-target". These cases lock
in the broader matcher.

Run directly:    python -m tests.test_iri_prefix
Under pytest:    python -m pytest tests/test_iri_prefix.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts import query_bioportal as qb

CASES = [
    # OBO PURL, numeric local id (worked before and must keep working)
    ("http://purl.obolibrary.org/obo/GO_0042921", "GO"),
    ("http://purl.obolibrary.org/obo/PR_000011170", "PR"),
    ("http://purl.obolibrary.org/obo/CL_0000057", "CL"),
    ("http://purl.obolibrary.org/obo/UBERON_0002107", "UBERON"),
    ("http://purl.obolibrary.org/obo/CHEBI_17855", "CHEBI"),
    # OBO PURL, UniProt-style local id (previously dropped -> '')
    ("http://purl.obolibrary.org/obo/PR_Q16236", "PR"),
    ("http://purl.obolibrary.org/obo/PR_O54968", "PR"),
    ("http://purl.obolibrary.org/obo/PR_Q13133", "PR"),
    # HGNC genenames IRI (previously dropped -> '')
    ("https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:7782", "HGNC"),
    ("https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:7780", "HGNC"),
    # Unresolvable
    ("http://example.org/something/else", ""),
    ("", ""),
]


def test_iri_prefix_cases():
    print("\n=== _iri_prefix across OBO, UniProt-style PR, and HGNC IRIs ===")
    failures = []
    for iri, expected in CASES:
        got = qb._iri_prefix(iri)
        status = "ok" if got == expected else "FAIL"
        print(f"  [{status}] {iri[-48:]:>48}  -> {got!r} (want {expected!r})")
        if got != expected:
            failures.append((iri, expected, got))
    assert not failures, f"{len(failures)} case(s) wrong: {failures}"
    print("✓ Test passed")


def test_species_pr_and_hgnc_no_longer_empty():
    """The two shapes that used to be silently dropped now carry a real prefix."""
    assert qb._iri_prefix("http://purl.obolibrary.org/obo/PR_Q16236") == "PR"
    assert qb._iri_prefix(
        "https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:7782"
    ) == "HGNC"


def run_all_tests() -> int:
    print("\n" + "=" * 68)
    print("IRI PREFIX REGRESSION TESTS")
    print("=" * 68)
    test_iri_prefix_cases()
    test_species_pr_and_hgnc_no_longer_empty()
    print("\n" + "=" * 68)
    print("ALL TESTS PASSED ✓")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
