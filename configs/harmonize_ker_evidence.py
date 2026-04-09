"""Configuration for harmonizing KER tabulated evidence."""
import datetime

today = datetime.date.today()

OUTPUT_DIR = 'outputs/tabulated_ker_evidence/'

KERS_TO_SKIP = {
    "2820": {
        "reason": "Multiple tables with different structures in empirical_support"
    },
}

AOPS_SELECTED_FOR_HARMONIZED_KERS_WORKBOOKS = {
    281: "Acetylcholinesterase Inhibition Leading to Neurodegeneration",
    237: "Substance interaction with lung resident cell membrane components leading to atherosclerosis",
    3: "Inhibition of the mitochondrial complex I of nigro-striatal neurons leads to parkinsonian motor deficits",
    307: "Decreased testosterone synthesis leading to short anogenital distance (AGD) in male (mammalian) offspring",
    392: "Decreased fibrinolysis and activated bradykinin system leading to hyperinflammation",
}

CONCORDANCE_SEARCH_PARAMS = {
    "content_to_drop_by_field": {
        "empirical_support": "Include consideration of temporal concordance here",
        "quantitative_understanding": "",
        'weight_of_evidence': "",
        'biological_plausibility': "",
    },
    "terms_to_search": ['dose concordance', 'temporal concordance', 'incidence concordance']
}
