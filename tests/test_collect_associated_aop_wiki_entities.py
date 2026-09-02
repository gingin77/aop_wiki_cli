"""
Unit tests for collect_events_from_matched_aops.

Tests cover:
- Event info lookup when events_dict is keyed by strings
- Event info lookup when events_dict is keyed by ints
- Non-numeric event IDs falling back to an empty record instead of raising
- Provenance accumulation when an event appears in several matched AOPs

Examples:
    Run all tests::

        $ uv run python -m tests.test_collect_associated_aop_wiki_entities

    Or directly::

        $ uv run pytest tests/test_collect_associated_aop_wiki_entities.py
"""

from aop_wiki_cli.collection.collect_associated_aop_wiki_entities import (
    collect_events_from_matched_aops,
)


# Matched AOPs in event_to_aop format: event_ids live under "aop_info"
MOCK_MATCHED_AOPS = {
    "281": {"aop_info": {"event_ids": ["1346", "55"]}},
    "237": {"aop_info": {"event_ids": ["55", "88"]}},
}


def test_lookup_with_string_keyed_events():
    """Test that events keyed by strings are found and enriched."""
    print("\n=== Test 1: String-Keyed Events ===")

    events_dict = {
        "1346": {"title": "Increase, Oxidative stress"},
        "55": {"title": "Cell death"},
        "88": {"title": "Tissue injury"},
    }

    results = collect_events_from_matched_aops(MOCK_MATCHED_AOPS, events_dict)

    print(f"Events collected: {sorted(results.keys())}")

    assert sorted(results.keys()) == ["1346", "55", "88"]
    assert results["1346"]["title"] == "Increase, Oxidative stress"
    assert results["88"]["event_info"] == {"title": "Tissue injury"}
    print("✓ Test passed")


def test_lookup_with_int_keyed_events():
    """Test that events keyed by ints are still found for string event IDs."""
    print("\n=== Test 2: Int-Keyed Events ===")

    # Some collection paths hand back a dict keyed by int, so the string ID
    # from the AOP record has to fall back to the int key
    events_dict = {
        1346: {"title": "Increase, Oxidative stress"},
        55: {"title": "Cell death"},
        88: {"title": "Tissue injury"},
    }

    results = collect_events_from_matched_aops(MOCK_MATCHED_AOPS, events_dict)

    print(f"Titles resolved: {[results[k]['title'] for k in sorted(results)]}")

    # Keys of the result are always strings, whatever events_dict used
    assert sorted(results.keys()) == ["1346", "55", "88"]
    assert results["1346"]["title"] == "Increase, Oxidative stress"
    assert results["55"]["title"] == "Cell death"
    print("✓ Test passed")


def test_non_numeric_event_id_does_not_raise():
    """Test that a non-numeric event ID yields an empty record rather than raising."""
    print("\n=== Test 3: Non-Numeric Event ID ===")

    matched_aops = {"281": {"aop_info": {"event_ids": ["KE-1346", "1346"]}}}
    events_dict = {"1346": {"title": "Increase, Oxidative stress"}}

    # Casting every ID to int would raise ValueError on "KE-1346"
    results = collect_events_from_matched_aops(matched_aops, events_dict)

    print(f"Unmatched ID resolved to: {results['KE-1346']}")

    assert results["KE-1346"]["event_info"] == {}
    assert results["KE-1346"]["title"] == "Unknown"
    # The numeric ID alongside it still resolves
    assert results["1346"]["title"] == "Increase, Oxidative stress"
    print("✓ Test passed")


def test_missing_event_and_shared_provenance():
    """Test that unknown IDs are recorded and shared events list every AOP."""
    print("\n=== Test 4: Missing Events and Provenance ===")

    events_dict = {"1346": {"title": "Increase, Oxidative stress"}}

    results = collect_events_from_matched_aops(MOCK_MATCHED_AOPS, events_dict)

    print(f"found_in_aops for KE55: {results['55']['found_in_aops']}")

    # KE 55 belongs to both matched AOPs, so both are recorded once each
    assert results["55"]["found_in_aops"] == ["281", "237"]
    assert results["1346"]["found_in_aops"] == ["281"]
    # Events absent from events_dict are still collected, with a placeholder title
    assert results["55"]["title"] == "Unknown"
    assert results["88"]["event_info"] == {}
    print("✓ Test passed")


def test_search_results_format_uses_aops_dict():
    """Test that search-results-shaped input reads event_ids from aops_dict."""
    print("\n=== Test 5: Search Results Format ===")

    matched_aops = {"281": {"entity_id": "281", "title": "Acetylcholinesterase Inhibition"}}
    aops_dict = {"281": {"event_ids": [1346, 55]}}
    events_dict = {"1346": {"title": "Increase, Oxidative stress"}, "55": {"title": "Cell death"}}

    results = collect_events_from_matched_aops(matched_aops, events_dict, aops_dict=aops_dict)

    print(f"Events collected: {sorted(results.keys())}")

    # aops_dict stores int event IDs; results are still keyed by string
    assert sorted(results.keys()) == ["1346", "55"]
    assert results["55"]["title"] == "Cell death"
    print("✓ Test passed")


def run_all_tests():
    """Run all test functions."""
    print("\n" + "=" * 60)
    print("RUNNING COLLECT ASSOCIATED ENTITIES TESTS")
    print("=" * 60)

    test_lookup_with_string_keyed_events()
    test_lookup_with_int_keyed_events()
    test_non_numeric_event_id_does_not_raise()
    test_missing_event_and_shared_provenance()
    test_search_results_format_uses_aops_dict()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_all_tests()
