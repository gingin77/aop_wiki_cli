"""
Exports assays from outputs_for_vc/annotations/assays_from_wiki_kes.json to a CSV.
One row per assay.
"""
import csv
import json

INPUT_FILE = "outputs_for_vc/annotations/assays_from_wiki_kes.json"
OUTPUT_FILE = "outputs_for_vc/annotations/assays_from_wiki_kes.csv"

COLUMNS = [
    "assay_id",
    "ke_id",
    "aop_ids",
    "title",
    "description",
    "effect_specificity",
    "assay_type_label",
    "assay_type_ontology",
    "assay_type_term_id",
    "objects",
    "processes",
    "taxon_terms",
    "citations",
]


def format_list_of_labels(items: list) -> str:
    """Render a list of dicts with a 'label' key as a bullet list."""
    if not items:
        return ""
    return "\n".join(f"- {item.get('label', '')}" for item in items)


def format_citations(citations: list) -> str:
    """Render each citation as a flattened bullet entry."""
    if not citations:
        return ""
    lines = []
    for c in citations:
        def _str(val):
            if isinstance(val, list):
                return ", ".join(str(v) for v in val)
            return str(val) if val else ""

        parts = [
            _str(c.get("authors")),
            _str(c.get("year")),
            _str(c.get("title")),
            _str(c.get("journal")),
            f"doi:{c['doi']}" if c.get("doi") else "",
            f"pmid:{c['pmid']}" if c.get("pmid") else "",
        ]
        concatenated = [p for p in parts if p]
        lines.append("- " + " | ".join(concatenated))
    return "\n".join(lines)


def main():
    with open(INPUT_FILE, "r") as f:
        assays = json.load(f)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()

        for assay_id, assay in assays.items():
            assay_type = assay.get("assay_type") or {}
            writer.writerow({
                "assay_id": assay_id,
                "ke_id": assay.get("ke_id", ""),
                "aop_ids": (", ").join(assay.get("aop_ids")),
                "title": assay.get("title", ""),
                "description": assay.get("description", ""),
                "effect_specificity": assay.get("effect_specificity") or "",
                "assay_type_label": assay_type.get("label", ""),
                "assay_type_ontology": assay_type.get("ontology", ""),
                "assay_type_term_id": assay_type.get("term_id", ""),
                "objects": format_list_of_labels(assay.get("objects", [])),
                "processes": format_list_of_labels(assay.get("processes", [])),
                "taxon_terms": format_list_of_labels(assay.get("taxon_terms", [])),
                "citations": format_citations(assay.get("citations", [])),
            })

    print(f"Wrote {len(assays)} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
