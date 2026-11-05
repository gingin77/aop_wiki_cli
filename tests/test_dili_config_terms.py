"""
Unit tests for the DILI config's key event title term list.

Tests cover:
- Hepatic key event titles matching the term list
- Nuclear receptor isoform spellings (PPARalpha, LXRalpha) matching, which the
  bare acronyms do not cover because terms match on word boundaries and a Greek
  letter is a word character
- Non-hepatic titles not matching

Examples:
    Run all tests::

        $ uv run python -m pytest tests/test_dili_config_terms.py
"""
import pytest

from aop_wiki_cli.configs.dili_aops import SEARCH_PARAMS
from aop_wiki_cli.search.event_first_search import find_events_by_title_terms

TERMS = SEARCH_PARAMS["ke_title_terms"]


def _matches(title):
    """Return the terms a single title matches, or an empty list."""
    hits = find_events_by_title_terms({"1": {"title": title}}, TERMS)
    return hits.get("1", {}).get("matched_terms", [])


# Isoform-suffixed receptor titles. The bare acronym cannot match these: the
# term pattern is \bppar\b, and "α" is a word character, so there is no word
# boundary after "ppar" in "pparα". Each spelling has to be its own term, so
# none of these is redundant with "PPAR" or "LXR".
@pytest.mark.parametrize("title", [
    "Activation, PPARα",
    "Activation, PPARalpha",
    "Activation, PPAR alpha",
    "Activation, PPARγ",
    "Activation, PPARgamma",
    "Activation, LXRα",
    "Activation, LXRalpha",
])
def test_receptor_isoform_spellings_match(title):
    """An isoform-suffixed receptor title matches, not only the bare acronym."""
    assert _matches(title), (
        f"{title!r} matched no term. The isoform spellings in dili_aops.py are "
        "not duplicates of the bare acronyms -- see the comment above them."
    )


@pytest.mark.parametrize("title", [
    "PPAR activation",
    "Activation, LXR",
    "Activation, PXR",
    "Increase, Hepatic steatosis",
    "Increase, Liver steatosis",
    "Occurrence, DILI in susceptible individuals",
    "Inhibition of the bile salt export pump (BSEP)",
])
def test_hepatic_titles_match(title):
    """A hepatic key event title matches at least one term."""
    assert _matches(title), f"{title!r} matched no term"


@pytest.mark.parametrize("title", [
    "Activation, Androgen receptor",
    "Drug-induced QT prolongation",
    "Decrease, Neuronal synaptogenesis",
    "Impaired learning and memory",
])
def test_non_hepatic_titles_do_not_match(title):
    """A title with no hepatic content matches nothing."""
    assert not _matches(title), f"{title!r} unexpectedly matched {_matches(title)}"
