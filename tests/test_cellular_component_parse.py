"""Regression tests for ke_title_parser subcellular-location extraction.

KE titles qualify a process by subcellular location ("Mitochondrial fatty acid
beta-oxidation"). The location is an adjective embedded in a process phrase, so
querying the whole subject for a GO cellular_component returns the process/
complex, not the organelle. parse_ke_title extracts the location word and
normalizes it to the organelle NOUN, which the annotation workflow then queries
directly (resolving "mitochondrion" -> GO:0005739).

The detector is deliberately conservative: "nuclear" and "membrane" are NOT
treated as locations because they are frequently part of protein names
("nuclear receptor", "nuclear factor") — those must stay None so the object
annotation is not corrupted.

Run directly:    python -m tests.test_cellular_component_parse
Under pytest:    python -m pytest tests/test_cellular_component_parse.py
"""

from __future__ import annotations

from aop_wiki_cli.annotation_scripts import ke_title_parser as parser

# (title, expected cellular_component)
CASES = [
    # Positive: a subcellular location modifies the process.
    ("Inhibition, Mitochondrial fatty acid beta-oxidation", "mitochondrion"),
    ("Increased, peroxisomal beta-oxidation", "peroxisome"),
    ("Decreased, lysosomal degradation", "lysosome"),
    ("Decreased, endoplasmic reticulum stress", "endoplasmic reticulum"),
    ("Increased, cytosolic calcium", "cytosol"),
    ("Altered, cytoplasmic transport", "cytoplasm"),
    ("Disrupted, Golgi apparatus function", "Golgi apparatus"),
    ("Increased, mitochondria biogenesis", "mitochondrion"),
    # Negative: no location word, or a word that is part of a protein name.
    ("Activation, nuclear receptor", None),      # "nuclear" is protein-name context
    ("NFE2/Nrf2 repression", None),
    ("Activation, NRF2", None),
    ("Increase, Liver steatosis", None),
    ("Decreased, fatty acid beta-oxidation", None),  # no location qualifier
    ("", None),
]


def test_cellular_component_cases():
    print("\n=== cellular_component extraction from KE titles ===")
    failures = []
    for title, expected in CASES:
        got = parser.parse_ke_title(title)["cellular_component"]
        status = "ok" if got == expected else "FAIL"
        print(f"  [{status}] {str(got)!r:<22} <- {title!r}")
        if got != expected:
            failures.append((title, expected, got))
    assert not failures, f"{len(failures)} case(s) wrong: {failures}"
    print("✓ Test passed")


def test_nuclear_and_membrane_are_not_locations():
    """Guard the false-positive exclusions that protect object annotation."""
    for title in ("Activation, nuclear receptor", "Inhibition, plasma membrane transport",
                  "Repression, nuclear factor kappa B"):
        assert parser.parse_ke_title(title)["cellular_component"] is None, title


def test_longest_phrase_wins():
    """'endoplasmic reticulum' must not be shadowed by a shorter single word."""
    assert parser.parse_ke_title("X, endoplasmic reticulum stress")["cellular_component"] == \
        "endoplasmic reticulum"


def run_all_tests() -> int:
    print("\n" + "=" * 68)
    print("CELLULAR_COMPONENT PARSE REGRESSION TESTS")
    print("=" * 68)
    test_cellular_component_cases()
    test_nuclear_and_membrane_are_not_locations()
    test_longest_phrase_wins()
    print("\n" + "=" * 68)
    print("ALL TESTS PASSED ✓")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
