"""
Unit tests for search_text_by_field module.

Tests cover:
- Basic text searching with snippet extraction
- Searching through entity dictionaries
- Content stripping functionality
- Snippet deduplication logic

Examples:
    Run all tests::
    
        $ uv run python -m tests.test_search_text_by_field
        
    Or directly::
    
        $ python -m pytest tests/test_search_text_by_field.py
"""

# Import directly from submodule since package-level import would trigger
# circular import: src.parsers <-> src.analysis
from src.search.search_text_by_field import (
    seek_search_phrase_in_field_text,
    search_entity_data,
    add_search_result
)


def test_basic_text_search():
    """Test basic text searching with snippet extraction."""
    print("\n=== Test 1: Basic Text Search ===")
    
    # Sample HTML field text
    field_text = """
    <p>This study examined dose concordance between in vitro and in vivo models.
    The results showed strong temporal concordance across species [1].</p>
    """
    
    # Search for a term
    result = seek_search_phrase_in_field_text(field_text, "dose concordance")
    
    print(f"Term: {result['term']}")
    print(f"Found: {result['found']}")
    print(f"Snippet: {result['snippet']}")
    assert result['found'] == True
    assert "dose concordance" in result['snippet'].lower()
    print("✓ Test passed")


def test_search_entity_data():
    """Test searching through entity dictionary."""
    print("\n=== Test 2: Search Entity Data ===")
    
    # Mock entity data
    mock_entities = {
        "ker_101": {
            "title": "Test KER 1",
            "empirical_support": {
                "free_text": "<p>Studies show dose concordance in multiple models.</p>"
            },
            "biological_plausibility": {
                "free_text": "<p>The mechanism is well established.</p>"
            }
        },
        "ker_102": {
            "title": "Test KER 2",
            "empirical_support": {
                "free_text": "<p>No relevant evidence here.</p>"
            },
            "biological_plausibility": {
                "free_text": "<p>Temporal concordance was observed [2].</p>"
            }
        }
    }
    
    # Search params
    search_params = {
        "fields_to_search": ["empirical_support", "biological_plausibility"],
        "terms": ["dose concordance", "temporal concordance"]
    }
    
    summary, results = search_entity_data(mock_entities, search_params)
    
    print(f"Entities searched: {len(mock_entities)}")
    print(f"Entities with matches: {summary['total_entities_with_matches']}")
    print(f"Terms found: {summary['terms_searched']}")
    print(f"Matching entity IDs: {list(results.keys())}")
    
    assert summary['total_entities_with_matches'] == 2
    assert "ker_101" in results
    assert "ker_102" in results
    print("✓ Test passed")


def test_content_stripping():
    """Test content stripping before search."""
    print("\n=== Test 3: Content Stripping To Remove Boilerplate Instructional Text ===")
    
    # Mock entities - one has boilerplate text, one doesn't
    mock_entities_with_boilerplate = {
        "ker_201": {
            "empirical_support": {
                "free_text": "Include consideration of temporal concordance here. Real content about concordance."
            }
        }
    }
    
    mock_entities_without_boilerplate = {
        "ker_201": {
            "empirical_support": {
                "free_text": "Real content about concordance without boilerplate."
            }
        }
    }
    
    search_params = {
        "fields_to_search": ["empirical_support"],
        "terms": ["temporal concordance"]
    }
    
    # With boilerplate - term is found (in the boilerplate)
    summary1, results1 = search_entity_data(mock_entities_with_boilerplate, search_params)
    print(f"With boilerplate present: {len(results1)} entities matched")
    
    # With stripping - term is removed, so no match
    content_to_drop = {
        "empirical_support": "Include consideration of temporal concordance here"
    }
    summary2, results2 = search_entity_data(mock_entities_with_boilerplate, search_params, content_to_drop)
    print(f"After stripping boilerplate: {len(results2)} entities matched")
    
    # Without boilerplate text at all - term not found
    summary3, results3 = search_entity_data(mock_entities_without_boilerplate, search_params)
    print(f"Without boilerplate text: {len(results3)} entities matched")
    
    assert len(results1) == 1  # Found in boilerplate
    assert len(results2) == 0  # Stripped away
    assert len(results3) == 0  # Never had the term
    print("✓ Test passed")


def test_snippet_deduplication():
    """Test that duplicate snippets are not stored."""
    print("\n=== Test 4: Snippet Deduplication ===")
    
    search_results = {}
    
    # Add exact duplicate snippet
    add_search_result("ker_301", "concordance", "field1", 
                     "This shows concordance.", search_results)
    add_search_result("ker_301", "concordance", "field1", 
                     "This shows concordance.", search_results)
    
    # Add snippet that's a substring of existing
    add_search_result("ker_301", "concordance", "field1", 
                     "This shows concordance. Additional text here.", search_results)
    
    # Add completely different snippet
    add_search_result("ker_301", "concordance", "field1", 
                     "Different snippet about concordance.", search_results)
    
    # Should only store 2 unique snippets:
    # - "This shows concordance." (duplicate removed)
    # - "This shows concordance. Additional text here." (contains first as substring, so first is skipped)
    # - "Different snippet about concordance." (unique)
    # Actually only 2 because the first is a substring of the second
    num_snippets = len(search_results["ker_301"]["snippets_by_field"]["field1"])
    print(f"Unique snippets stored: {num_snippets}")
    
    # The function detects substring overlap, so "This shows concordance." 
    # is not stored if "This shows concordance. Additional text here." already exists
    assert num_snippets == 2  # The longer one and the different one
    print("✓ Test passed")

def test_co_occurrence_term_search():
    """Test that co-occurrence terms are correctly identified in the same field text."""
    print("\n=== Test 5: Co-occurrence Term Search ===")
    
    # Mock AOP entities with different term combinations
    mock_aops = {
        "aop_401": {
            "title": "Suppression of immune system contributes to impaired development and leads to colony loss/failure"
        },
        "aop_402": {
            "title": "Substance interaction with the pulmonary resident cell membrane components leading to fibrosis"
        },
        "aop_403": {
            "title": "Inflammation in lung tissue leading to chronic respiratory disease"
        },
        "aop_404": {
            "title": "Cardiac hypertrophy leading to heart failure"  # No matching terms
        }
    }
    
    search_params = {
        "fields_to_search": ["title"],
        "terms": ["lung", "pulmonary", "immune", "inflammation", "fibrosis"],
        "co_occurrence_pairs": [
            ["pulmonary", "fibrosis"],   # Should match aop_402
            ["inflammation", "lung"],     # Should match aop_403
            ["lung", "immune"],           # Should NOT match (different AOPs)
        ]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total entities with matches: {summary['total_entities_with_matches']}")
    print(f"Matching entity IDs: {list(results.keys())}")
    
    # Check individual term matches
    # aop_401 has "immune", aop_402 has "pulmonary" and "fibrosis", aop_403 has "inflammation" and "lung"
    assert summary['total_entities_with_matches'] >= 3
    
    # Check co-occurrence results structure
    assert 'co_occurrence_matches' in summary
    print(f"Co-occurrence summary: {summary['co_occurrence_matches']}")
    
    # Verify co-occurrence summary has the new structure
    for pair_key, counts in summary['co_occurrence_matches'].items():
        assert 'total_instances' in counts
        assert 'unique_entities' in counts
        print(f"  {pair_key}: {counts['unique_entities']} unique entities, {counts['total_instances']} instances")
    
    # aop_402 should match ["pulmonary", "fibrosis"]
    assert "aop_402" in results
    result_402 = results["aop_402"]
    assert 'entity_id' in result_402
    assert result_402['entity_id'] == "aop_402"
    assert 'title' in result_402
    assert 'co_occurrences' in result_402
    assert ('fibrosis', 'pulmonary') in result_402['co_occurrences'] or ('pulmonary', 'fibrosis') in result_402['co_occurrences']
    print(f"✓ aop_402 ({result_402['title']})")
    print(f"  co-occurrences: {result_402['co_occurrences']}")
    
    # aop_403 should match ["inflammation", "lung"]
    assert "aop_403" in results
    result_403 = results["aop_403"]
    assert 'entity_id' in result_403
    assert result_403['entity_id'] == "aop_403"
    assert 'title' in result_403
    assert 'co_occurrences' in result_403
    assert ('inflammation', 'lung') in result_403['co_occurrences'] or ('lung', 'inflammation') in result_403['co_occurrences']
    print(f"✓ aop_403 ({result_403['title']})")
    print(f"  co-occurrences: {result_403['co_occurrences']}")
    
    # aop_401 has only "immune" (no co-occurrence match)
    if "aop_401" in results:
        result_401 = results["aop_401"]
        assert len(result_401['co_occurrences']) == 0
        print(f"✓ aop_401 has no co-occurrences: {result_401['co_occurrences']}")
    
    print("✓ Test passed")

def test_priority_field_ranking():
    """Test that priority field is correctly identified for co-occurrence matches."""
    print("\n=== Test 6: Priority Field Ranking ===")
    
    # Mock AOP entities with co-occurrences in different fields
    mock_aops = {
        "aop_501": {
            "title": "Inflammation in lung tissue and pulmonary fibrosis",
            "abstract": "This AOP describes various pathways."
        },
        "aop_502": {
            "title": "Cardiac dysfunction in heart tissue",
            "abstract": "Inflammation in lung tissue is a key feature of respiratory disease."
        },
        "aop_503": {
            "title": "Neurological effects",
            "abstract": "The immune response involves lung inflammation."
        }
    }
    
    search_params = {
        "priority_field": "title",
        "fields_to_search": ["title", "abstract"],
        "terms": ["inflammation", "lung", "pulmonary", "immune"],
        "co_occurrence_pairs": [
            ["inflammation", "lung"],
        ]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total entities with matches: {summary['total_entities_with_matches']}")
    print(f"Matching entity IDs: {list(results.keys())}")
    
    # aop_501 should have co-occurrence in title (priority field)
    if "aop_501" in results:
        result_501 = results["aop_501"]
        assert result_501.get("has_priority_co_occurrence") == True
        assert "title" in result_501.get("co_occurrence_fields", set())
        print(f"✓ aop_501 has priority field co-occurrence: {result_501.get('has_priority_co_occurrence')}")
        print(f"  co_occurrence_fields: {result_501.get('co_occurrence_fields', set())}")
    
    # aop_502 should have co-occurrence only in abstract (not priority field)
    if "aop_502" in results:
        result_502 = results["aop_502"]
        assert result_502.get("has_priority_co_occurrence") == False
        assert "abstract" in result_502.get("co_occurrence_fields", set())
        print(f"✓ aop_502 has no priority field co-occurrence: {result_502.get('has_priority_co_occurrence')}")
        print(f"  co_occurrence_fields: {result_502.get('co_occurrence_fields', set())}")
    
    # aop_503 should have co-occurrence only in abstract (not priority field)
    if "aop_503" in results:
        result_503 = results["aop_503"]
        assert result_503.get("has_priority_co_occurrence") == False
        print(f"✓ aop_503 has no priority field co-occurrence: {result_503.get('has_priority_co_occurrence')}")
    
    print("✓ Test passed")

def test_priority_field_as_fallback():
    """Test that priority_field is used as fields_to_search when not explicitly provided."""
    print("\n=== Test 7: Priority Field as Fallback ===")
    
    # Mock AOP entities
    mock_aops = {
        "aop_601": {
            "title": "Inflammation in lung tissue",
            "abstract": "This is about heart disease, not lung."
        },
        "aop_602": {
            "title": "Cardiac dysfunction",
            "abstract": "Inflammation in lung tissue is discussed here."
        }
    }
    
    # Config WITHOUT fields_to_search, only priority_field
    search_params = {
        "priority_field": "title",  # Should default to searching only title
        "terms": ["inflammation", "lung"],
        "co_occurrence_pairs": [
            ["inflammation", "lung"],
        ]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Fields searched: {summary['fields_searched']}")
    assert summary['fields_searched'] == ["title"], "Should use priority_field as fields_to_search"
    
    # aop_601 should match (has both terms in title)
    assert "aop_601" in results
    assert len(results["aop_601"]["co_occurrences"]) > 0
    print(f"✓ aop_601 matched in title")
    
    # aop_602 should NOT match co-occurrence (terms are in abstract, not title)
    # But "abstract" is not being searched since we only search priority_field
    if "aop_602" in results:
        # It might appear if individual terms match, but no co-occurrence in title
        assert len(results["aop_602"]["co_occurrences"]) == 0
        print(f"✓ aop_602 has no co-occurrence matches (abstract not searched)")
    else:
        print(f"✓ aop_602 not in results (no title matches)")
    
    print("✓ Test passed")

def test_priority_field_error_handling():
    """Test that an error is raised when neither fields_to_search nor priority_field is provided."""
    print("\n=== Test 8: Priority Field Error Handling ===")
    
    mock_aops = {"aop_701": {"title": "Test"}}
    
    # Config with NEITHER fields_to_search NOR priority_field
    search_params = {
        "terms": ["test"],
    }
    
    try:
        summary, results = search_entity_data(mock_aops, search_params)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "fields_to_search" in str(e) or "priority_field" in str(e)
        print(f"✓ Correctly raised ValueError: {e}")
    
    print("✓ Test passed")

def test_exclusion_terms_basic():
    """Test that exclusion_terms filter out matching entities."""
    print("\n=== Test 9: Basic Exclusion Terms ===")
    
    mock_aops = {
        "aop_801": {
            "title": "Female fertility impairment in rodents",
            "abstract": "This AOP describes ovarian dysfunction."
        },
        "aop_802": {
            "title": "Male fertility impairment in fish",
            "abstract": "This AOP describes testicular damage."
        },
        "aop_803": {
            "title": "Reproductive toxicity in females",
            "abstract": "Effects on ovarian development."
        },
        "aop_804": {
            "title": "Sperm count reduction leading to male infertility",
            "abstract": "Effects on spermatogenesis."
        }
    }
    
    # Search for fertility terms but EXCLUDE male-related terms
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["fertility", "reproductive"],
        "exclusion_terms": ["male", "sperm", "testicular", "spermatogenesis"]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total AOPs with matches before exclusion: 4")
    print(f"Total AOPs after exclusion: {len(results)}")
    
    # Should have filtered out aop_802 (male) and aop_804 (sperm, male)
    assert "aop_801" in results, "aop_801 (female) should remain"
    assert "aop_802" not in results, "aop_802 (male) should be excluded"
    assert "aop_803" in results, "aop_803 (females) should remain"
    assert "aop_804" not in results, "aop_804 (sperm, male) should be excluded"
    
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"
    print("✓ Correctly filtered out 2 male-related AOPs")
    print("✓ Test passed")


def test_exclusion_terms_with_co_occurrences():
    """Test that exclusion_terms work correctly with co-occurrence searches."""
    print("\n=== Test 10: Exclusion Terms with Co-occurrences ===")
    
    mock_aops = {
        "aop_901": {
            "title": "Ovarian follicle development",
            "abstract": "This describes follicle growth in ovaries."
        },
        "aop_902": {
            "title": "Male reproductive tract development",
            "abstract": "This describes follicle development in males."
        }
    }
    
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["follicle", "development", "reproductive", "ovarian"],
        "co_occurrence_pairs": [
            ["follicle", "development"]
        ],
        "exclusion_terms": ["male"]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total AOPs after exclusion: {len(results)}")
    
    # aop_901 has co-occurrence and no male terms
    assert "aop_901" in results, "aop_901 should remain (female-related)"
    
    # aop_902 has co-occurrence BUT contains "male" exclusion term
    assert "aop_902" not in results, "aop_902 should be excluded (contains 'male')"
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    print("✓ Correctly excluded AOP with co-occurrence but containing exclusion term")
    print("✓ Test passed")


def test_exclusion_terms_case_insensitive():
    """Test that exclusion_terms are case-insensitive."""
    print("\n=== Test 11: Exclusion Terms Case Insensitivity ===")
    
    mock_aops = {
        "aop_1001": {
            "title": "Effects on Male fertility",
            "abstract": "MALE reproductive issues"
        },
        "aop_1002": {
            "title": "Female fertility effects",
            "abstract": "female reproductive issues"
        }
    }
    
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["fertility"],
        "exclusion_terms": ["male"]  # lowercase
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    # Should exclude aop_1001 even though "Male" is capitalized
    assert "aop_1001" not in results, "Should exclude 'Male' (capital M)"
    assert "aop_1002" in results, "Should keep female-related AOP"
    
    print("✓ Correctly handled case variations of exclusion terms")
    print("✓ Test passed")


def test_exclusion_terms_empty_list():
    """Test that empty exclusion_terms list doesn't affect results."""
    print("\n=== Test 12: Empty Exclusion Terms List ===")
    
    mock_aops = {
        "aop_1101": {"title": "Test AOP 1"},
        "aop_1102": {"title": "Test AOP 2"}
    }
    
    search_params = {
        "fields_to_search": ["title"],
        "terms": ["Test"],
        "exclusion_terms": []  # Empty list
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    assert len(results) == 2, "Empty exclusion list should not filter anything"
    print("✓ Empty exclusion_terms list handled correctly")
    print("✓ Test passed")


def test_title_exclusion_basic():
    """Test that title_exclusion_terms filter out AOPs with matching terms in title only."""
    print("\n=== Test 13: Basic Title Exclusion ===")
    
    mock_aops = {
        "aop_38": {
            "title": "Protein Alkylation leading to Liver Fibrosis",
            "abstract": "This AOP describes mechanisms of fibrosis development."
        },
        "aop_39": {
            "title": "Ovarian follicle damage leading to fertility reduction",
            "abstract": "Effects on liver metabolism were also observed."
        },
        "aop_40": {
            "title": "Cardiac hypertrophy leading to heart failure",
            "abstract": "This AOP focuses on cardiac tissue."
        }
    }
    
    # Search for fibrosis but EXCLUDE AOPs with "liver" in title
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["fibrosis", "fertility", "cardiac"],
        "title_exclusion_terms": ["liver"]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total AOPs with matches: {len(results)}")
    print(f"Filtered out: {set(mock_aops.keys()) - set(results.keys())}")
    
    # Should exclude aop_38 (has "liver" in title)
    # Should KEEP aop_39 (has "liver" in abstract but NOT in title)
    # Should keep aop_40 (no "liver" anywhere)
    assert "aop_38" not in results, "aop_38 should be excluded ('liver' in title)"
    assert "aop_39" in results, "aop_39 should remain ('liver' only in abstract, not title)"
    assert "aop_40" in results, "aop_40 should remain (no 'liver')"
    
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"
    print("✓ Correctly excluded AOP with 'liver' in title only")
    print("✓ Test passed")


def test_title_exclusion_word_boundaries():
    """Test that title exclusion respects word boundaries."""
    print("\n=== Test 14: Title Exclusion Word Boundaries ===")
    
    mock_aops = {
        "aop_50": {
            "title": "Delivery of toxicants to target tissue",
            "abstract": "Mechanisms of substance delivery."
        },
        "aop_51": {
            "title": "Liver dysfunction leading to organ failure",
            "abstract": "Focus on hepatic impairment."
        }
    }
    
    # Search for "delivery" but exclude "liver"
    # "delivery" contains "liver" as substring, but shouldn't be excluded
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["delivery", "dysfunction"],
        "title_exclusion_terms": ["liver"]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total AOPs with matches: {len(results)}")
    
    # Should keep aop_50 ("liver" is only substring of "delivery", not a word)
    # Should exclude aop_51 ("liver" is a standalone word in title)
    assert "aop_50" in results, "aop_50 should remain ('liver' only in 'delivery' substring)"
    assert "aop_51" not in results, "aop_51 should be excluded ('liver' as standalone word)"
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    print("✓ Word boundaries respected - 'liver' in 'delivery' not excluded")
    print("✓ Test passed")


def test_title_exclusion_case_insensitive():
    """Test that title exclusion is case insensitive."""
    print("\n=== Test 15: Title Exclusion Case Insensitive ===")
    
    mock_aops = {
        "aop_60": {
            "title": "Kidney damage from toxicant exposure",
            "abstract": "Effects on renal function."
        },
        "aop_61": {
            "title": "KIDNEY failure and metabolic dysfunction",
            "abstract": "Severe renal impairment."
        },
        "aop_62": {
            "title": "Ovarian damage from chemical exposure",
            "abstract": "Effects on kidney were also noted."
        }
    }
    
    # Exclude "kidney" (lowercase) - should match "Kidney" and "KIDNEY"
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["damage", "failure"],
        "title_exclusion_terms": ["kidney"]
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total AOPs with matches: {len(results)}")
    
    # Should exclude both aop_60 (Kidney) and aop_61 (KIDNEY) from title
    # Should keep aop_62 ("kidney" only in abstract, not title)
    assert "aop_60" not in results, "aop_60 should be excluded ('Kidney' in title)"
    assert "aop_61" not in results, "aop_61 should be excluded ('KIDNEY' in title)"
    assert "aop_62" in results, "aop_62 should remain ('kidney' only in abstract)"
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    print("✓ Case-insensitive exclusion working correctly")
    print("✓ Test passed")


def test_title_exclusion_combined_with_regular_exclusion():
    """Test that title_exclusion_terms work alongside regular exclusion_terms."""
    print("\n=== Test 16: Title Exclusion Combined with Regular Exclusion ===")
    
    mock_aops = {
        "aop_70": {
            "title": "Liver toxicity in rodents",
            "abstract": "Effects on hepatic function."
        },
        "aop_71": {
            "title": "Ovarian damage in fish",
            "abstract": "Reproductive effects in male fish also observed."
        },
        "aop_72": {
            "title": "Cardiac dysfunction in mammals",
            "abstract": "Focus on heart function and liver metabolism."
        }
    }
    
    # Exclude "male" from all fields, and "liver" only from title
    search_params = {
        "fields_to_search": ["title", "abstract"],
        "terms": ["toxicity", "damage", "dysfunction"],
        "exclusion_terms": ["male"],  # Search all fields
        "title_exclusion_terms": ["liver"]  # Only check title
    }
    
    summary, results = search_entity_data(mock_aops, search_params)
    
    print(f"Total AOPs with matches: {len(results)}")
    
    # Should exclude aop_70 (has "liver" in title)
    # Should exclude aop_71 (has "male" in abstract)
    # Should keep aop_72 (has "liver" only in abstract, not title)
    assert "aop_70" not in results, "aop_70 should be excluded ('liver' in title)"
    assert "aop_71" not in results, "aop_71 should be excluded ('male' in abstract)"
    assert "aop_72" in results, "aop_72 should remain ('liver' only in abstract)"
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    print("✓ Both exclusion types working together correctly")
    print("✓ Test passed")


def run_all_tests():
    """Run all test functions."""
    print("\n" + "="*60)
    print("RUNNING SEARCH TEXT BY FIELD TESTS")
    print("="*60)
    
    test_basic_text_search()
    test_search_entity_data()
    test_content_stripping()
    test_snippet_deduplication()
    test_co_occurrence_term_search()
    test_priority_field_ranking()
    test_priority_field_as_fallback()
    test_priority_field_error_handling()
    test_exclusion_terms_basic()
    test_exclusion_terms_with_co_occurrences()
    test_exclusion_terms_case_insensitive()
    test_exclusion_terms_empty_list()
    test_title_exclusion_basic()
    test_title_exclusion_word_boundaries()
    test_title_exclusion_case_insensitive()
    test_title_exclusion_combined_with_regular_exclusion()
    
    print("\n" + "="*60)
    print("ALL TESTS PASSED ✓")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_all_tests()
