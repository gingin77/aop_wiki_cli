"""
Summarizes the current state of the annotations for KEs and AOPs saved in outputs_for_vc/annotations
"""
import json
import pprint as pp

# Input files
INPUT_KE_FILE = "outputs_for_vc/annotations/ke_annotations.json"
INPUT_AOP_FILE = "outputs_for_vc/annotations/aop_based_ke_store.json"

# Output files
OUTPUT_ASSAYS = "outputs_for_vc/annotations/assays_from_wiki_kes.json"

def main():
    # Read inputs
    with open(INPUT_KE_FILE, "r") as f:
        ke_annotations = json.load(f)

    with open(INPUT_AOP_FILE, "r") as f:
        aop_annotations = json.load(f)

    kes_with_assays = {ke_id: ke for ke_id, ke in ke_annotations.items() if "assays" in ke}
    kes_without_assays = {ke_id: ke for ke_id, ke in ke_annotations.items() if "assays" not in ke}
    assay_annotations = {}
    assay_count = 0
    for ke_id, ke in kes_with_assays.items():
        for assay in ke["assays"]:
            assay_count += 1
            assay_annotations[assay_count] = {**{"ke_id": ke_id}, **assay}

    with open(OUTPUT_ASSAYS, "w") as f:
        json.dump(assay_annotations, f, indent=2)

    summary = {
        "kes": {
            "count_kes_annotated": len(ke_annotations),
            "count_kes_with_assays": len(kes_with_assays),
            "count_kes_without_assays": len(kes_without_assays),
            "kes_with_assays": ", ".join(list(kes_with_assays.keys())),
            "kes_without_assays": ", ".join(list(kes_without_assays.keys())),
            "assays_annotated": assay_count
        },
        "aops": {}
    }
    pp.pprint(summary)

if __name__ == "__main__":
    main()