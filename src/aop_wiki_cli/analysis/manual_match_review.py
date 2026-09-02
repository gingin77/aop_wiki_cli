"""
Interactive manual review of term matches.

Core functions for reviewing fuzzy matches or other automated matching results,
usable both from CLI and programmatically within workflows.
"""

from typing import Dict, List, Any, Optional, Tuple

# ANSI color codes
GREY = "\033[90m"
RESET = "\033[0m"


class ReviewExit(Exception):
    """Signal to exit review loop early."""
    pass


def review_single_match(
    input_term: str,
    matched_term: Optional[str],
    match_score: Optional[float],
    data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Interactively review a single match and return updated data with human verification.
    
    Args:
        input_term: The source term being matched
        matched_term: The matched term (may be None)
        match_score: The match score (may be None)
        data: Original data dict to copy and augment
        
    Returns:
        Copy of data with 'human_verified' and optionally 'suggested_match' added.
        
    Raises:
        ReviewExit: If user enters 'q' to quit the review session.
    """
    result = data.copy()
    
    print(f"\nReviewing match for input term: '{input_term}'")
    print(f"Matched term: '{matched_term}' with score {match_score:.2f}" if match_score is not None else f"Matched term: '{matched_term}'")
    user_input = input("Accept this match? (y/n/q to quit): ").strip().lower()
    
    if user_input == 'q':
        raise ReviewExit()
    elif user_input == 'y':
        result['human_verified'] = True
        result['suggested_match'] = None
        print("Match accepted.")
    else:
        result['human_verified'] = False
        suggest = input("Would you like to suggest a better match? (y/n): ").strip().lower()
        if suggest == 'y':
            suggested_match = input("Enter your suggested match: ").strip()
            result['suggested_match'] = suggested_match
        else:
            result['suggested_match'] = None
    
    return result


def review_matches(
    matches: Dict[str, Dict[str, Any]],
    score_threshold: float = 0.0,
    input_term_field: str = 'input_term',
    matched_term_field: str = 'matched_term',
    score_field: str = 'match_score'
) -> List[Dict[str, Any]]:
    """
    Review multiple matches interactively.
    
    Args:
        matches: Dict mapping keys to match data dicts
        score_threshold: Only review matches with score < threshold (0.0 = review all)
        input_term_field: Field name for input term in data
        matched_term_field: Field name for matched term in data
        score_field: Field name for match score in data
        
    Returns:
        List of reviewed match dicts with human_verified fields added.
        If user quits early, remaining items are marked with human_verified=None.
    """
    results = []
    match_items = list(matches.values())
    exited_early = False
    processed_count = 0
    
    for data in match_items:
        if exited_early:
            # Mark remaining items as unreviewed
            data_to_pass = data.copy()
            data_to_pass['human_verified'] = None
            data_to_pass['suggested_match'] = None
            results.append(data_to_pass)
            continue
            
        data_to_pass = data.copy()
        input_term = data.get(input_term_field)
        matched_term = data.get(matched_term_field)
        match_score = data.get(score_field)
        
        # Determine if this match needs review
        needs_review = (
            match_score is not None and 
            (score_threshold == 0.0 or match_score < score_threshold)
        )
        
        if needs_review:
            try:
                data_to_pass = review_single_match(input_term, matched_term, match_score, data)
                processed_count += 1
            except ReviewExit:
                print(f"\nExiting review early. Reviewed {processed_count} items, {len(match_items) - processed_count} remaining.")
                exited_early = True
                data_to_pass['human_verified'] = None
                data_to_pass['suggested_match'] = None
        else:
            print(f"{GREY}\nSkipping: '{input_term}' → '{matched_term}' (score {match_score}){RESET}")
            data_to_pass['human_verified'] = None
            data_to_pass['suggested_match'] = None
        
        results.append(data_to_pass)
    
    return results


def calculate_review_summary(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Calculate summary metrics from reviewed results.
    
    Args:
        results: List of reviewed match dicts
        
    Returns:
        Dict with total, reviewed, skipped, accepted, rejected, suggested counts.
    """
    return {
        'total': len(results),
        'reviewed': sum(1 for r in results if r.get('human_verified') is not None),
        'skipped': sum(1 for r in results if r.get('human_verified') is None),
        'accepted': sum(1 for r in results if r.get('human_verified') is True),
        'rejected': sum(1 for r in results if r.get('human_verified') is False),
        'suggested': sum(1 for r in results if r.get('suggested_match'))
    }


def get_matches_and_scores_from_json(input_json: Dict[str, Dict], match_threshold: float) -> List[Tuple[str, Optional[str], Optional[float]]]:
    """
    Extract input terms, matched terms, and scores from the enhanced mapping JSON.
    
    Args:
        input_json: Dictionary with source terms as keys, each containing 'matched_term' and 'match_score'.
        
    Returns:
        List of tuples: (input_term, matched_term, match_score).
    """
    results = []
    for data in input_json.values():
        input_term = data.get('input_term')
        matched_term = data.get('matched_term')
        match_score = data.get('match_score')
        results.append((input_term, matched_term, match_score))
    return results
