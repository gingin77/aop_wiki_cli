"""Configuration for collecting related AOP entities (AOPs, KEs, KERs) for specific event IDs."""
import datetime

today = datetime.date.today()

# Example config for depression events
DEPRESSION_CONFIG = {
    "input_term": "depression",
    "event_title_filter": [1346, 2392],
    "event_ft_filter": [1944, 389, 388, 618, 2078, 875, 2098, 2371, 195, 201, 757],
    "output_config": {
        "ke_file_name": f"depression_aops/depression_events_{today}.json",
        "aop_file_name": f"depression_aops/depression_aops_{today}.json",
        "logger_name": "analyze_depression_aops"
    }
}

# Example config for Parkinson's events
PARKINSON_CONFIG = {
    "input_term": "parkinson",
    "event_title_filter": [896],
    "event_ft_filter": None,
    "output_config": {
        "ke_file_name": f"parkinson_aops/parkinson_events_{today}.json",
        "aop_file_name": f"parkinson_aops/parkinson_aops_{today}.json",
        "logger_name": "analyze_parkinson_aops"
    }
}
