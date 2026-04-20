"""Configuration for method of measurement screening."""
import datetime

today = datetime.date.today()

SEARCH_PARAMS = {
    "entities_and_fields": {
        "events": ["measurement_method"],
    },
    "terms": [
        "induced pluripotent stem cell", 
        "ipsc", 
        "organoid",
        "microphysiological", 
        "microphysiological system", 
        "mps", 
        "3d culture",
        "toxcast",
        "tox21",
        "air-liquid interface",
        "ali",
        "organ-on-a-chip",
        "ELISA",
        "western blot",
        "PCR",
        "qPCR",
        "rtPCR",
        "next generation sequencing",
        "NGS",
        "high content imaging",
        "HCI",
        "mass spectrometry",
        "flow cytometry",
        "immunohistochemistry",
        "IHC",
        "transcriptomics",
        "proteomics",
        "metabolomics",
        "lipidomics",
        "epigenomics"
    ]
}

OUTPUT_CONFIG = {
    "directory": "outputs/nams_methods",
    "filename": f"nams_methods_results_{today}.json"
}
