"""
Summarizes the current state of the annotations for KEs and AOPs saved in outputs_for_vc/annotations
"""
import json
import pprint as pp

SELECTED_AOPS = [14, 39, 173, 277, 302]

# Input files
INPUT_KE_FILE = "outputs_for_vc/annotations/ke_annotations.json"
INPUT_AOP_FILE = "outputs_for_vc/annotations/aop_ke_index.json"

# Output files
OUTPUT_ASSAYS = "outputs_for_vc/annotations/assays_from_wiki_kes.json"

def main():
    # Read inputs
    with open(INPUT_KE_FILE, "r") as f:
        ke_annotations = json.load(f)

    with open(INPUT_AOP_FILE, "r") as f:
        aop_annotations = json.load(f)

    # Sort every KE into exactly one assay-annotation bucket.
    kes_with_assays: dict = {}
    kes_without_assays: dict = {}
    kes_needing_assay_annotation: dict = {}
    for ke_id, ke in ke_annotations.items():
        if "assays" not in ke:
            kes_needing_assay_annotation[ke_id] = ke
        elif ke["assays"]:
            kes_with_assays[ke_id] = ke
        else:
            kes_without_assays[ke_id] = ke
    count_submitted_for_assay_annotation = len(kes_with_assays) + len(kes_without_assays)

    ke_to_aops = {}
    for aop_id, ke_ids in aop_annotations.items():
        for ke_id in ke_ids:
            ke_to_aops.setdefault(ke_id, []).append(aop_id)

    assay_annotations = {}
    assay_count = 0
    for ke_id, ke in kes_with_assays.items():
        for assay in ke["assays"]:
            assay_count += 1
            assay_annotations[assay_count] = {**{"ke_id": ke_id, "aop_ids": ke_to_aops.get(ke_id, [])}, **assay}

    with open(OUTPUT_ASSAYS, "w") as f:
        json.dump(assay_annotations, f, indent=2)

    summary = {
        "kes": {
            "count_kes_annotated": len(ke_annotations),
            "kes_submitted_for_assay_annotation": {
                "count": count_submitted_for_assay_annotation,
                "count_annotated_kes_with_assays": len(kes_with_assays),
                "count_annotated_kes_without_assays": len(kes_without_assays),
                "kes_with_assays": ", ".join(list(kes_with_assays.keys())),
                "kes_without_assays": ", ".join(list(kes_without_assays.keys())),
            },
            "kes_not_yet_submitted_for_assay_annotation": {
                "count_kes_needing_assay_annotations": len(kes_needing_assay_annotation),
                "kes_needing_assay_annotations": ", ".join(list(kes_needing_assay_annotation.keys())),
            },
            "assays_annotated": assay_count
        },
        "aops": {}
    }

    aop_coverage = {}
    aops_with_greater_than_70_pct_assay_coverage = []
    for aop_id, ke_ids in aop_annotations.items():
        if int(aop_id) not in SELECTED_AOPS:
            continue

        total = len(ke_ids)
        with_assays = [ke_id for ke_id in ke_ids if ke_id in kes_with_assays]
        without_assays = [ke_id for ke_id in ke_ids if ke_id in kes_without_assays]
        not_submitted = [ke_id for ke_id in ke_ids if ke_id in kes_needing_assay_annotation]
        pct = len(with_assays) / total * 100 if total else 0
        has_all_kes_annotated = len(with_assays) == total
        percent_ke_assay_coverage = f"{pct:.1f}%"
        if pct > 70:
            aops_with_greater_than_70_pct_assay_coverage.append(aop_id)
        
        aop_coverage[aop_id] = {
            "percent_ke_assay_coverage": percent_ke_assay_coverage,
            "has_all_kes_annotated": has_all_kes_annotated,
            "kes_with_assays": len(with_assays),
            "kes_without_assays": len(without_assays),
            "kes_not_yet_submitted": len(not_submitted),
            "ke_details": {
                "ke_ids_with_assays": ", ".join(with_assays),
                "ke_ids_not_submitted": ", ".join(not_submitted),
            }
        }
    summary["aops"] = {
        "assay_coverage_greater_than_70_percent": aops_with_greater_than_70_pct_assay_coverage,
        "aop_coverage": aop_coverage,
    }
    pp.pprint(summary)

if __name__ == "__main__":
    main()