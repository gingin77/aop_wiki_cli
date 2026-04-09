"""Configuration for searching AOP-Wiki references."""
import datetime

today = datetime.date.today()

GOLD_NANOPARTICLES_SEARCH = {
    "terms": {
        "author": ["Paula"],
        "title": ["Gold nanoparticles"],
        "publication_year": ["2015"]
    },
    "output_file": f"outputs/reference_search_results/paula_nanoparticles_{today}.json",
    "expected_results": {
        "entity_count": 1,
        "citation_count": 1,
        "entities": {
            "ker_ids": [3241]
        }
    },
}

PARKINSON_IPSC_SEARCH = {
    "terms": {
        "author": ["Paul"],
        "title": ["iPSC dopaminergic neuron"],
        "publication_year": ["2023"]
    },
    "output_file": f"outputs/reference_search_results/parkinson_ipsc_{today}.json",
    "expected_results": {
        "entity_count": 0,
        "citation_count": 0,
        "entities": {}
    }
}

FISH_SHORT_TERM_REPRODUCTION_ASSAY_SEARCH = {
    "terms": {
        "title": ["Fish Short Term Reproduction Assay"]
    },
    "output_file": f"outputs/reference_search_results/fish_short_term_reproduction_assay_{today}.json",
    "expected_results": {
        "entity_count": 6,
        "citation_count": 8,
        "entities": {
            "aop_ids": [23, 25, 29, 30, 289],
            "event_ids": [78]
        }
    }
}