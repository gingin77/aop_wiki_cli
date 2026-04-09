"""Configuration for regulatory relevance screening."""
import datetime

today = datetime.date.today()

SEARCH_PARAMS = {
    "entity": ["aops","events"],
    "priority_field": "title",
    "fields_to_search": ["title", "abstract", "overall_assessment_description", "potential_applications"],
    "terms": [
        "lung",
        "pulmonary",
        "immune",
        "inflammation",
        "fibrosis",
        "respiratory",
        "bronchiolitis",
        "pneumonitis",
        "alveolar"
    ],
    "co_occurrence_pairs": [
        ["lung", "immune"],
        ["pulmonary", "immune"],
        ["respiratory", "immune"],
        ["inflammation", "lung"],
        ["inflammation", "pulmonary"],
        ["inflammation", "respiratory"],
        ["fibrosis", "lung"],
        ["fibrosis", "pulmonary"],
        ["fibrosis", "respiratory"],
    ],
    "title_exclusion_terms": [
        # Liver related terms
        "liver", 
        "hepatic", 
        "hepatitis",
        "hepatotoxicity",
        "MASLD",
        "NAFLD",
        "NASH",
        # Skin related terms
        "skin", 
        "dermal", 
        "dermis", 
        "cutaneous",
        # Other organ related terms
        "heart",
        "cardiac",
        "cardiovascular",
        "brain",
        "neuron",
        "neurons",
        "neural",
        "nervous",
        "neuropathy",
        "kidney",
        "renal",
        "nephrotoxicity",
        "neurological",
        "intestinal tract",
        "vascular",
        "reproductive",
        "coagulation",
        "Memory",
        "cognitive",
        "learning",
        "behavior",
        "behavioral",
        "developmental",

        # Disease areas
        "lupus",
        "obesity",
        "psoriasis",
        "cancer",
        "carcinoma",
        "tumor",
        "tumors",
        "neoplasm",
        "metastasis",
        "cardiomyopathy",
        "celiac",
        "atherosclerosis",
        "diabetes",
        "acute mortality",
        "parkinsonian",
        "alzheimer",
        "neurodegenerative",
        "inflammatory bowel disease",
        "colitis",
        "Crohn's",
        "Parkinson's",
        # Non-mammalian terms
        "amphibian",
        "colony loss",
        "Mytilus edulis",
        "Daphnia",
        "zebrafish",
        "Danio rerio",
        "Caenorhabditis elegans",
        "C. elegans",
        "Drosophila",
        "fruit fly",
        "insect",
        "nematode",
        "worm",
        "mollusk"
    ],
}

OUTPUT_CONFIG = {
    "directory": "outputs/lung_and_immune",
    "filename": f"lung_and_immune_{today}.json"
}
