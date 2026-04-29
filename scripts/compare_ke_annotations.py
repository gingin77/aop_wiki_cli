"""
Compare KE annotations in outputs_for_vc/aop_based_ke_annotations/ke_annotations.json
against existing annotations in the AOP-Wiki cache.

Writes a CSV with one row per KE:
  - ke_id, title
  - divergent_field_count   : fields where both files have a value but they differ
  - new_only_fields         : fields populated in the annotation but blank in the cache

Usage:
    uv run python scripts/compare_ke_annotations.py
    uv run python scripts/compare_ke_annotations.py \
        --annotations outputs_for_vc/aop_based_ke_annotations/ke_annotations.json \
        --cache outputs/cache/04-28-2026/all_events_04-28-2026.json \
        --output outputs/ke_annotation_comparison.csv
"""

import argparse
import csv
import json
from pathlib import Path

ANNOTATIONS_FILE = "outputs_for_vc/aop_based_ke_annotations/ke_annotations.json"
CACHE_FILE = "outputs/cache/04-28-2026/all_events_04-28-2026.json"
OUTPUT_FILE = "outputs/ke_annotation_comparison.csv"

COLUMNS = [
    "ke_id",
    "title",
    "new_over_null_count",
    "new_over_null_fields",
    "divergent_content_count",
    "divergent_content_fields",
]

DIVERGENT_COLUMNS = [
    "ke_id",
    "title",
    "divergent_field",
    "cached_value",
    "annotation_value",
]


def _label(term_dict: dict | None) -> str:
    if not term_dict:
        return ""
    return term_dict.get("label") or term_dict.get("term") or ""


def _compare_field(new_val: str, existing_val: str) -> str:
    """Return 'divergent', 'new_only', 'match', or 'both_null'."""
    new_val = (new_val or "").strip()
    existing_val = (existing_val or "").strip()
    if not new_val and not existing_val:
        return "both_null"
    if new_val and not existing_val:
        return "new_only"
    if not new_val and existing_val:
        return "existing_only"
    return "match" if new_val.lower() == existing_val.lower() else "divergent"


def compare(annotations_path: str, cache_path: str, output_path: str) -> None:
    with open(annotations_path) as f:
        annotations: dict = json.load(f)
    with open(cache_path) as f:
        cache: dict = json.load(f)

    rows: list[dict] = []
    divergent_rows: list[dict] = []

    for ke_id, ann in annotations.items():
        title = ann.get("title", "")
        cached = cache.get(ke_id, {})

        divergent: list[str] = []
        new_over_null: list[str] = []

        def check(field_name: str, new_val: str, existing_val: str) -> None:
            result = _compare_field(new_val, existing_val)
            if result == "divergent":
                divergent.append(field_name)
                divergent_rows.append({
                    "ke_id": ke_id,
                    "title": title,
                    "divergent_field": field_name,
                    "cached_value": existing_val,
                    "annotation_value": new_val,
                })
            elif result == "new_only":
                new_over_null.append(field_name)

        # biological_organization
        check(
            "biological_organization",
            ann.get("biological_organization") or "",
            cached.get("level_of_biological_organization") or "",
        )

        # cell_term
        check("cell_term", _label(ann.get("cell_term")), _label(cached.get("cell_term")))

        # organ_term
        check("organ_term", _label(ann.get("organ_term")), _label(cached.get("organ_term")))

        # EC annotations — matched by position
        new_ecs = ann.get("ec_annotations") or ann.get("ecs_annotations") or []
        cached_ecs = cached.get("ecs") or []
        cached_by_index = {i: ec for i, ec in enumerate(cached_ecs)}

        for i, ec in enumerate(new_ecs):
            cached_ec = cached_by_index.get(i, {})
            prefix = f"ec_{i}" if len(new_ecs) > 1 else "ec"

            check(
                f"{prefix}.biological_object",
                _label(ec.get("biological_object")),
                _label(cached_ec.get("biological_object")),
            )
            check(
                f"{prefix}.biological_process",
                _label(ec.get("biological_process")),
                _label(cached_ec.get("biological_process")),
            )
            check(
                f"{prefix}.biological_action",
                _label(ec.get("biological_action")),
                _label(cached_ec.get("biological_action")),
            )

        rows.append({
            "ke_id": ke_id,
            "title": title,
            "new_over_null_count": len(new_over_null),
            "new_over_null_fields": "; ".join(new_over_null),
            "divergent_content_count": len(divergent),
            "divergent_content_fields": "; ".join(divergent),
        })

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")

    divergent_out = out.with_stem(out.stem + "_divergent_detail")
    with open(divergent_out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DIVERGENT_COLUMNS)
        writer.writeheader()
        writer.writerows(divergent_rows)
    print(f"Wrote {len(divergent_rows)} rows to {divergent_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", default=ANNOTATIONS_FILE)
    parser.add_argument("--cache", default=CACHE_FILE)
    parser.add_argument("--output", default=OUTPUT_FILE)
    args = parser.parse_args()
    compare(args.annotations, args.cache, args.output)


if __name__ == "__main__":
    main()
