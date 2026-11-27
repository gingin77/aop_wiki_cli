"""
Annotate liver microphysiological system data with bio-ontology terms.

Annotates:
  1. Cell types in experiment_setup.biological_context.cell_types using Cell Ontology (CL)
  2. Biological objects in event observations using molecular ontologies (ChEBI, PR preferred; UBERON, CL as fallback)

Usage:
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_liver_microphys_data --input inputs/liver_microphys.json --output outputs/liver_microphys_annotated.json

    # Force re-annotation of all terms
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_liver_microphys_data --input inputs/liver_microphys.json --force

    # Annotate only cell types
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_liver_microphys_data --input inputs/liver_microphys.json --cells-only

    # Annotate only biological objects
    uv run python -m aop_wiki_cli.annotation_scripts.annotate_liver_microphys_data --input inputs/liver_microphys.json --objects-only
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from aop_wiki_cli.annotation_scripts.annotate_term_helpers import annotate_term, is_rejection
from aop_wiki_cli.annotation_scripts.llm import make_client

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Cell types use only Cell Ontology
CELL_TYPE_ONTOLOGIES = "CL"

# Biological objects: prefer molecular ontologies (CHEBI, PR) over structural (UBERON, CL)
# Order matters: preferred ontologies listed first
BIOLOGICAL_OBJECT_ONTOLOGIES = "CHEBI,PR"


def annotate_cell_types(data: dict, api_key: str, force: bool = False) -> dict:
    """
    Annotate cell types in experiment_setup.biological_context.cell_types.
    
    Args:
        data: The input JSON data
        api_key: BioPortal API key
        force: If True, re-annotate even if annotations exist
        
    Returns:
        Updated data dict with cell type annotations
    """
    client = make_client()
    
    cell_types = data.get("experiment_setup", {}).get("biological_context", {}).get("cell_types", [])
    
    if not cell_types:
        logger.warning("No cell_types found in experiment_setup.biological_context")
        return data
    
    # Initialize annotations structure if needed
    if "experiment_setup" not in data:
        data["experiment_setup"] = {}
    if "biological_context" not in data["experiment_setup"]:
        data["experiment_setup"]["biological_context"] = {}
    if "cell_type_annotations" not in data["experiment_setup"]["biological_context"]:
        data["experiment_setup"]["biological_context"]["cell_type_annotations"] = []
    
    annotations = data["experiment_setup"]["biological_context"]["cell_type_annotations"]
    
    # Build index of existing annotations
    existing = {ann.get("cell_type"): ann for ann in annotations if isinstance(ann, dict)}
    
    updated_annotations = []
    
    for cell_type in cell_types:
        print(f"\n{'=' * 60}")
        print(f"CELL TYPE: {cell_type}")
        print('=' * 60)
        
        # Check if already annotated
        if cell_type in existing and not force:
            print(f"  Already annotated — skipping (use --force to re-annotate)")
            updated_annotations.append(existing[cell_type])
            continue
        
        # Annotate using Cell Ontology
        annotation = {
            "cell_type": cell_type,
            "ontology_term": None,
        }
        
        term = annotate_term(
            phrase=cell_type,
            ontologies=CELL_TYPE_ONTOLOGIES,
            component="cell_term",
            title=f"Cell type: {cell_type}",
            api_key=api_key,
            client=client,
        )
        
        if term and not is_rejection(term):
            annotation["ontology_term"] = term
            print(f"  ✓ Annotated: [{term.get('ontology')}] {term.get('label')}")
        elif term and is_rejection(term):
            annotation["ontology_term"] = term
            print(f"  ⚠ Rejected: {term.get('rejection_reason')}")
        else:
            print(f"  ⚠ No annotation selected")
        
        updated_annotations.append(annotation)
    
    data["experiment_setup"]["biological_context"]["cell_type_annotations"] = updated_annotations
    
    return data


def annotate_biological_objects(data: dict, api_key: str, force: bool = False) -> dict:
    """
    Annotate biological_object fields in event observations.
    
    Args:
        data: The input JSON data
        api_key: BioPortal API key
        force: If True, re-annotate even if annotations exist
        
    Returns:
        Updated data dict with biological object annotations
    """
    client = make_client()
    
    events = data.get("events", {})
    
    if not events:
        logger.warning("No events found in data")
        return data
    
    for event_key, event_data in events.items():
        if not isinstance(event_data, dict):
            continue
        
        observations = event_data.get("observations", [])
        
        if not observations:
            continue
        
        print(f"\n{'=' * 60}")
        print(f"EVENT: {event_key} — {event_data.get('title', 'Unknown')}")
        print('=' * 60)
        
        # Initialize annotations list if needed
        if "biological_object_annotations" not in event_data:
            event_data["biological_object_annotations"] = []
        
        existing_annotations = event_data["biological_object_annotations"]
        existing = {
            ann.get("biological_object"): ann 
            for ann in existing_annotations 
            if isinstance(ann, dict)
        }
        
        updated_annotations = []
        
        # Collect unique biological objects from observations
        biological_objects = set()
        for obs in observations:
            if isinstance(obs, dict) and "biological_object" in obs:
                biological_objects.add(obs["biological_object"])
        
        for bio_obj in sorted(biological_objects):
            print(f"\n--- Biological Object: {bio_obj} ---")
            
            # Check if already annotated
            if bio_obj in existing and not force:
                print(f"  Already annotated — skipping (use --force to re-annotate)")
                updated_annotations.append(existing[bio_obj])
                continue
            
            # Annotate using biological object ontologies
            annotation = {
                "biological_object": bio_obj,
                "ontology_term": None,
            }
            
            term = annotate_term(
                phrase=bio_obj,
                ontologies=BIOLOGICAL_OBJECT_ONTOLOGIES,
                component="biological_object",
                title=f"{event_data.get('title', '')} - {bio_obj}",
                api_key=api_key,
                client=client,
            )
            
            if term and not is_rejection(term):
                annotation["ontology_term"] = term
                print(f"  ✓ Annotated: [{term.get('ontology')}] {term.get('label')}")
            elif term and is_rejection(term):
                annotation["ontology_term"] = term
                print(f"  ⚠ Rejected: {term.get('rejection_reason')}")
            else:
                print(f"  ⚠ No annotation selected")
            
            updated_annotations.append(annotation)
        
        event_data["biological_object_annotations"] = updated_annotations
    
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Annotate liver microphysiological system data with bio-ontology terms"
    )
    parser.add_argument(
        "--input",
        default="inputs/liver_microphys.json",
        help="Input JSON file path (default: inputs/liver_microphys.json)",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file path (default: <input>_annotated.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-annotate all terms, even if annotations exist",
    )
    parser.add_argument(
        "--cells-only",
        action="store_true",
        help="Annotate only cell types",
    )
    parser.add_argument(
        "--objects-only",
        action="store_true",
        help="Annotate only biological objects",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    # Check for BioPortal API key
    api_key = os.environ.get("BIOPORTAL_API_KEY")
    if not api_key:
        logger.error("BIOPORTAL_API_KEY environment variable not set")
        sys.exit(1)
    
    # Load input data
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    print(f"Loading data from {input_path}")
    with open(input_path) as f:
        data = json.load(f)
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_annotated.json"
    
    # Run annotations
    annotate_cells = not args.objects_only
    annotate_objects = not args.cells_only
    
    if annotate_cells:
        print("\n" + "=" * 60)
        print("ANNOTATING CELL TYPES")
        print("=" * 60)
        data = annotate_cell_types(data, api_key, force=args.force)
    
    if annotate_objects:
        print("\n" + "=" * 60)
        print("ANNOTATING BIOLOGICAL OBJECTS")
        print("=" * 60)
        data = annotate_biological_objects(data, api_key, force=args.force)
    
    # Save annotated data
    print(f"\n{'=' * 60}")
    print(f"Saving annotated data to {output_path}")
    print('=' * 60)
    
    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n✓ Annotation complete. Output saved to: {output_path}")
    
    # Print summary
    print(f"\n{'=' * 60}")
    print("ANNOTATION SUMMARY")
    print('=' * 60)
    
    if annotate_cells:
        cell_annotations = data.get("experiment_setup", {}).get("biological_context", {}).get("cell_type_annotations", [])
        annotated_count = sum(
            1 for ann in cell_annotations 
            if ann.get("ontology_term") and not is_rejection(ann.get("ontology_term"))
        )
        print(f"Cell types: {annotated_count}/{len(cell_annotations)} annotated")
    
    if annotate_objects:
        total_objects = 0
        annotated_objects = 0
        for event_data in data.get("events", {}).values():
            if isinstance(event_data, dict):
                obj_annotations = event_data.get("biological_object_annotations", [])
                total_objects += len(obj_annotations)
                annotated_objects += sum(
                    1 for ann in obj_annotations 
                    if ann.get("ontology_term") and not is_rejection(ann.get("ontology_term"))
                )
        print(f"Biological objects: {annotated_objects}/{total_objects} annotated")
    
    print('=' * 60)


if __name__ == "__main__":
    main()
