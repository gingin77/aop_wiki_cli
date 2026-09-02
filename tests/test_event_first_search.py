"""
Unit tests for event_first_search module.

Tests cover:
- Finding KERs that have a given key event as an endpoint
- Upstream vs. downstream role assignment for matched events
- ID normalization between int and string event IDs
- Malformed KER records with missing endpoints
- Chaining KE title search into KER lookup

Examples:
    Run all tests::

        $ uv run python -m tests.test_event_first_search

    Or directly::

        $ python -m pytest tests/test_event_first_search.py
"""

# Import directly from submodule since package-level import would trigger
# circular import: src.parsers <-> src.analysis
from aop_wiki_cli.search.event_first_search import (
    find_kers_containing_events,
    find_events_by_title_terms,
)


# Mock KER set shaped like collect_kers_from_xml output. The chain is
# 1346 -> 55 -> 88, with KER 12 as a non-adjacent shortcut 1346 -> 88.
MOCK_KERS = {
    "10": {
        "upstream_ke": {"id": "1346", "title": "Increase, Oxidative stress"},
        "downstream_ke": {"id": "55", "title": "Cell death"},
        "description": "Oxidative stress drives cell death.",
    },
    "11": {
        "upstream_ke": {"id": "55", "title": "Cell death"},
        "downstream_ke": {"id": "88", "title": "Tissue injury"},
        "description": "Cell death accumulates into tissue injury.",
    },
    "12": {
        # Endpoint ID stored as an int, as some records arrive from XML
        "upstream_ke": {"id": 1346, "title": "Increase, Oxidative stress"},
        "downstream_ke": {"id": "88", "title": "Tissue injury"},
        "description": "Non-adjacent shortcut.",
    },
    "13": {
        "upstream_ke": {"id": "900", "title": "Thyroid hormone decrease"},
        "downstream_ke": {"id": "901", "title": "Impaired development"},
        "description": "Unrelated pathway.",
    },
}


def test_find_kers_by_single_event():
    """Test that a KE is found in every KER it is an endpoint of."""
    print("\n=== Test 1: Find KERs by Single Event ===")

    results = find_kers_containing_events(MOCK_KERS, ["1346"])

    print(f"KERs matched: {sorted(results.keys())}")

    # KE 1346 is the upstream of KER 10 and KER 12, and absent from 11 and 13
    assert sorted(results.keys()) == ["10", "12"]
    assert "11" not in results
    assert "13" not in results

    # The full KER record travels with the match
    assert results["10"]["ker_info"]["description"] == "Oxidative stress drives cell death."
    assert results["10"]["title"] == "Increase, Oxidative stress -> Cell death"
    assert results["10"]["upstream_ke_id"] == "1346"
    assert results["10"]["downstream_ke_id"] == "55"
    print(f"✓ KER 10 label: {results['10']['title']}")
    print("✓ Test passed")


def test_upstream_and_downstream_roles():
    """Test that a KE is labeled upstream or downstream per KER."""
    print("\n=== Test 2: Upstream and Downstream Roles ===")

    # KE 55 sits downstream in KER 10 and upstream in KER 11
    results = find_kers_containing_events(MOCK_KERS, ["55"])

    print(f"Roles by KER: {({k: v['roles'] for k, v in results.items()})}")

    assert sorted(results.keys()) == ["10", "11"]
    assert results["10"]["roles"] == {"55": "downstream"}
    assert results["11"]["roles"] == {"55": "upstream"}

    # source_events mirrors the roles keys
    assert results["10"]["source_events"] == ["55"]
    assert results["11"]["source_events"] == ["55"]

    print("✓ KE 55 is downstream of KER 10 and upstream of KER 11")
    print("✓ Test passed")


def test_both_endpoints_matched():
    """Test that a KER matching on both endpoints reports both roles."""
    print("\n=== Test 3: Both Endpoints Matched ===")

    # Searching a connected run of KEs matches KER 10 on both sides
    results = find_kers_containing_events(MOCK_KERS, ["1346", "55"])

    print(f"KERs matched: {sorted(results.keys())}")
    print(f"KER 10 roles: {results['10']['roles']}")

    assert results["10"]["roles"] == {"1346": "upstream", "55": "downstream"}
    assert sorted(results["10"]["source_events"]) == ["1346", "55"]

    # KER 11 and 12 each match on one endpoint only
    assert results["11"]["roles"] == {"55": "upstream"}
    assert results["12"]["roles"] == {"1346": "upstream"}

    print("✓ Test passed")


def test_event_id_normalization():
    """Test that int and string event IDs match interchangeably."""
    print("\n=== Test 4: Event ID Normalization ===")

    from_strings = find_kers_containing_events(MOCK_KERS, ["1346"])
    from_ints = find_kers_containing_events(MOCK_KERS, [1346])

    print(f"String input matched: {sorted(from_strings.keys())}")
    print(f"Int input matched:    {sorted(from_ints.keys())}")

    # KER 12 stores its upstream ID as an int, KER 10 as a string; both are
    # found regardless of how the caller supplies the search ID
    assert sorted(from_strings.keys()) == sorted(from_ints.keys()) == ["10", "12"]

    # Returned role keys are always strings
    assert from_ints["12"]["roles"] == {"1346": "upstream"}
    assert from_ints["12"]["upstream_ke_id"] == "1346"

    print("✓ Test passed")


def test_no_matches_and_empty_input():
    """Test that unmatched and empty searches return an empty dict."""
    print("\n=== Test 5: No Matches and Empty Input ===")

    assert find_kers_containing_events(MOCK_KERS, ["99999"]) == {}
    assert find_kers_containing_events(MOCK_KERS, []) == {}
    assert find_kers_containing_events({}, ["1346"]) == {}

    print("✓ Unmatched ID, empty ID list, and empty KER dict all return {}")
    print("✓ Test passed")


def test_malformed_ker_never_matches():
    """Test that KERs missing an endpoint are not matched by an empty ID."""
    print("\n=== Test 6: Malformed KER Records ===")

    malformed_kers = {
        "20": {},  # No endpoints at all
        "21": {"upstream_ke": {}, "downstream_ke": {}},  # Endpoints with no IDs
        "22": {
            "upstream_ke": {"id": "1346", "title": "Increase, Oxidative stress"},
            "downstream_ke": {},  # One usable endpoint
        },
    }

    # An empty-string search ID must not match the empty endpoint IDs
    results = find_kers_containing_events(malformed_kers, [""])
    print(f"Empty-string search matched: {sorted(results.keys())}")
    assert results == {}

    # The usable endpoint on a partially malformed record still matches
    results = find_kers_containing_events(malformed_kers, ["1346"])
    print(f"KE 1346 matched: {sorted(results.keys())}")
    assert sorted(results.keys()) == ["22"]
    assert results["22"]["roles"] == {"1346": "upstream"}
    assert results["22"]["downstream_ke_id"] == ""
    assert results["22"]["title"] == "Increase, Oxidative stress -> ?"

    print("✓ Test passed")


def test_chaining_title_search_to_kers():
    """Test the event-first flow: KE title terms -> KE IDs -> KERs."""
    print("\n=== Test 7: Chaining KE Title Search into KER Lookup ===")

    mock_events = {
        "1346": {"title": "Increase, Oxidative stress"},
        "55": {"title": "Cell death"},
        "900": {"title": "Thyroid hormone decrease"},
    }

    matched_events = find_events_by_title_terms(mock_events, ["oxidative stress"])
    print(f"Events matched by title: {sorted(matched_events.keys())}")
    assert sorted(matched_events.keys()) == ["1346"]

    # The event IDs from the title search feed straight into the KER lookup,
    # the same way they feed find_aops_containing_events
    results = find_kers_containing_events(MOCK_KERS, matched_events.keys())
    print(f"KERs reached from those events: {sorted(results.keys())}")

    assert sorted(results.keys()) == ["10", "12"]
    print("✓ Test passed")


def run_all_tests():
    """Run all test functions."""
    print("\n" + "=" * 60)
    print("RUNNING EVENT FIRST SEARCH TESTS")
    print("=" * 60)

    test_find_kers_by_single_event()
    test_upstream_and_downstream_roles()
    test_both_endpoints_matched()
    test_event_id_normalization()
    test_no_matches_and_empty_input()
    test_malformed_ker_never_matches()
    test_chaining_title_search_to_kers()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_all_tests()
