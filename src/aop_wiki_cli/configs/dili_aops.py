"""Configuration for collecting drug-induced liver injury (DILI) AOPs.

Uses the ``event_to_aop`` search mode: key event titles are matched against the
term list below, then every AOP containing one of those key events is collected,
along with all of that AOP's other key events. This is deliberately
"event-first" rather than "AOP-title-first" -- a liver AOP whose title never
says "liver" is still collected as long as one of its key events is hepatic.

Run with::

    aop-wiki-cli search-with-config dili_aops          # AOPs + key events
    aop-wiki-cli pair-mies-and-aos dili_aops           # the same, plus KERs
                                                       # and the MIE/AO table
"""
import datetime

today = datetime.date.today()

SEARCH_PARAMS = {
    "search_mode": "event_to_aop",
    # Matched against key event titles. Terms are liver-specific on purpose:
    # generic injury words ("necrosis", "fibrosis", "apoptosis", "inflammation")
    # are left out because they pull in every organ, and they are picked up
    # anyway once the AOP they belong to is collected through a hepatic KE.
    "ke_title_terms": [
        # Organ and cell types
        "liver",
        "hepatic",
        "hepatocyte",
        "hepatocytes",
        "hepatocellular",
        "hepatotoxicity",
        "hepatoxicity",
        "hepatitis",
        "hepatobiliary",
        "hepatotoxicant",
        "kupffer",
        "stellate cell",
        "cholangiocyte",
        "cholangiocytes",
        "sinusoidal",
        # Hepatic adverse outcomes and disease states
        "steatosis",
        "steatohepatitis",
        "cholestasis",
        "cholestatic",
        "cirrhosis",
        "NAFLD",
        "NASH",
        "MASLD",
        "MASH",
        "fatty liver",
        # Hepatic processes and transporters
        "bile",
        "bile acid",
        "bile salt",
        "biliary",
        "BSEP",
        "bile salt export pump",
        "bile duct",
        "LXR",
        "liver X receptor",
        "FXR",
        "farnesoid X receptor",
        "PXR",
        "pregnane X receptor",
        "constitutive androstane receptor",
    ],
    # Left empty so the collection stays inclusive, which is what "all AOPs
    # covering DILI" asks for. To narrow the set -- e.g. to drop ecotoxicology
    # AOPs that reach the liver in fish or invertebrates -- add terms here,
    # for example: "fish", "zebrafish", "Danio rerio", "Daphnia", "mollusk",
    # "amphibian", "Oryzias", "fathead minnow", "vitellogenin".
    "aop_title_exclusion_terms": [],
}

# "directory" is a name under the resolved outputs directory, not a path
OUTPUT_CONFIG = {
    "directory": "dili_aops",
    "filename": f"dili_aops_{today}.json"
}
