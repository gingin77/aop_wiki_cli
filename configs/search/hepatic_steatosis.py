"""Configuration for regulatory relevance screening."""
import datetime

today = datetime.date.today()

SEARCH_PARAMS = {
    "entities_and_fields": {
        "events": ["title"],
        "aops": ["title", "abstract", "overall_assessment_description"],
    },
    "priority_field": "title",
    "terms": [
        "liver",
        "hepatic",
        "steatosis",
        "PPAR",
    ],
    "co_occurrence_pairs": [
        # TODO: Update as needed to support hepatic steatosis search
        ["liver", "steatosis"],
        ["hepatic", "steatosis"]
    ],
    "title_exclusion_terms": [
        # TODO: Add to support hepatic steatosis search
    ],
}

OUTPUT_CONFIG = {
    "directory": "outputs/hepatic_steatosis_search",
    "filename": f"hepatic_steatosis_search_{today}.json"
}
