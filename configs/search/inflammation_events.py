"""Configuration for collecting events with inflammation in the title."""
import datetime

today = datetime.date.today()

SEARCH_PARAMS = {
    "entities_and_fields": {
        "events": ["title"],
    },
    "priority_field": "title",
    "terms": [
        "inflammation",
    ],
    "co_occurrence_pairs": [],
    "title_exclusion_terms": [],
}

OUTPUT_CONFIG = {
    "directory": "outputs/inflammation_events",
    "filename": f"inflammation_events_{today}.json"
}
