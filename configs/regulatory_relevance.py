"""Configuration for regulatory relevance screening."""
import datetime

today = datetime.date.today()

SEARCH_PARAMS = {
    "entity": ["events"],
    "fields_to_search": ["measurement_method", "regulatory_relevance"],
    "terms": [
        "test guideline",
        "test guidelines",
        "test method",
        "test methods",
        "endpoint",
        "TG",
        "TGs",
        "OECD",
        "OECD Test Guidelines",
        "OCSPP",
        "Interagency Coordinating Committee on the Validation of Alternative Methods",
        "ICCVAM",
        "ECVAM",
        "JaCVAM",
        "KoCVAM",
        "Health Canada",
        "NIH",
        "NICEATM",
        "NTP",
        "Korean Center for the Validation of Alternative Methods",
        "Japanese Center for the Validation of Alternative Methods",
        "European Center for the Validation of Alternative Methods",
        "EPA",
        "FDA",
        "EPA Guideline",
        "regulatory acceptance",
        "ECHA",
        "REACH",
        "EFSA",
        "developmental neurotoxicity",
        "DNT"
    ]
}

OUTPUT_CONFIG = {
    "directory": "outputs/regulatory_relevance_screening",
    "filename": f"test_guideline_term_search_results_{today}.json"
}
