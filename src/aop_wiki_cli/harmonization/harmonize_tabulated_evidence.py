import pprint as pp
import difflib
import re

"""
COLUMN_HARMONIZER: Mapping of various column header terms used in KER evidence tables.
- Time & duration were considered but not added because of how these concepts were combined in
  a single field, for example, "Dose/ conc. +Duration of exp."
- "effect" considered for harmonization but not added due to ambiguity in terms of upstream and
  downstream effects
- Conversion of "experimental model" > "Assay" was removed because "experimental model" was used 
  too broadly to refer to different concepts, such as an species for an in vivo model.
"""
COLUMN_HARMONIZER = {
    "ke up": "Upstream Key Event",
    "ke down": "Downstream Key Event",
    "keup": "Upstream Key Event",
    "kedown": "Downstream Key Event",
    "upstream": "Upstream Key Event",
    "downstream": "Downstream Key Event",
    "reference": "References",
    "ref": "References",
    "publication": "References",
    "citation": "References",
    "stressor": "Stressor", 
    "chemical": "Stressor",
    "compound": "Stressor",
    "species": "Species",
    "taxa": "Species",
    "speies": "Species",
    "dose": "Dose",
    "study type": "Study Type",
    "assay": "Assay",
    "method": "Assay",
    "cell type": "Biological Object",
    "note": "Comment",
    "comment": "Comment",
    "details": "Comment",
    "description": "Comment",
    "notes": "Comment",
    "comments": "Comment",
    "summary": "Comment",
    "compound class": "Stressor",
    "compound": "Stressor",
    "stressor(s)": "Stressor",
    "stressors(s)": "Stressor",
    "study type": "Study Type",
    "exposure route": "Route of Exposure"
}

"""
KE_SEMANTIC_VARIATIONS holds semantic variations and synonyms for key events, assembled by CoPilot
based on terms found in the KER Dictionary of evidence table content.

Maps normalized variations to canonical forms for better matching
"""
KE_SEMANTIC_VARIATIONS = {
    "ovarian cycle": ["disrupted ovarian cycle", "disrupted, ovarian cycle", "ovarian cycle irregularities", "irregular estrous cycles"],
    "ovarian follicle": ["follicle depletion", "follicles"],
    "reduced estrogen": ["reduced e2", "reduction plasma 17beta-estradiol", "e2 production/levels"],
    "reproductive toxicity": ["impaired fertility", "reduced fertility", "impaired spermatogenesis"],
    "testosterone": ["testosterone production/levels", "reduction testosterone", "decreased testosterone", "circulating testosterone", "intratesticular testosterone"],
    "agd": ["anogenital distance", "agd decreased"],
    "dht": ["dihydrotestosterone", "dht decrease"],
    "cryptorchidism": ["cryptorchidism", "inguinoscrotal"],
    "urethral": ["urethral tube closure", "hypospadias"],
    "aromatase": ["aromatase decrease", "aromatase activity"],
    "star": ["star protein", "star decrease"],
    "gnrh": ["gnrh", "decreased gnrh"],
    "kisspeptin": ["avpv kisspeptin", "decreased kisspeptin"],
    "gonadotropin": ["gonadotropins", "fsh", "lh"],
}


def normalize_text_for_matching(text):
    """
    Normalize text by removing common prefixes, punctuation, and extra whitespace.
    """
    text = text.lower().strip()
    # Remove common prefixes
    text = re.sub(r'^(ke:|keup|kedown|upstream|downstream|the\s+|a\s+)', '', text)
    # Remove punctuation except spaces
    text = re.sub(r'[,\-;:()]+', ' ', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def find_semantic_match(header_text, ke_title):
    """
    Check if header_text semantically matches the ke_title by comparing against
    known variations.
    
    Returns True if a semantic match is found, False otherwise.
    """
    normalized_header = normalize_text_for_matching(header_text)
    normalized_ke = normalize_text_for_matching(ke_title)
    
    # Check each semantic group
    for canonical_form, variations in KE_SEMANTIC_VARIATIONS.items():
        # Check if both header and KE match this semantic group
        header_matches_group = any(
            canonical_form in normalized_header or 
            normalize_text_for_matching(var) in normalized_header
            for var in variations + [canonical_form]
        )
        ke_matches_group = any(
            canonical_form in normalized_ke or 
            normalize_text_for_matching(var) in normalized_ke
            for var in variations + [canonical_form]
        )
        
        if header_matches_group and ke_matches_group:
            return True
    
    return False

def _harmonize_tables(tables_dict, ker_id, harmonized_evidence, table_type=""):
    """
    Helper function to harmonize tables using the harmonized_headers mapping.
    
    Args:
        tables_dict: Dictionary of table_id -> rows
        ker_id: KER identifier for logging
        harmonized_evidence: The harmonized evidence dict for this KER
        table_type: String description of table type for logging (e.g., "weight_of_evidence")
    
    Returns:
        Dictionary of harmonized tables
    """
    harmonized_tables = {}
    for table_id, rows in tables_dict.items():
        harmonized_tables[table_id] = []
        for row in rows:
            harmonizable_keys_in_row = [key for key in row.keys() if key in harmonized_evidence["harmonized_headers"]]
            if harmonizable_keys_in_row:
                harmonized_row = {}
                for header, value in row.items():
                    if header in harmonized_evidence["harmonized_headers"]:
                        harmonized_header = harmonized_evidence["harmonized_headers"][header]
                        harmonized_row[harmonized_header] = value
                    if header in harmonized_evidence["unmatched_headers"]:
                        harmonized_row[header] = value
                harmonized_tables[table_id].append(harmonized_row)
            # else:
                # print(f"Cannot harmonize row for KER {ker_id}, {table_type} table {table_id} because no headers in row are harmonizable")
    return harmonized_tables

def _match_header_to_harmonized(header, column_harmonizer, upstream_ke_title, downstream_ke_title):
    """
    Match a single header to a harmonized form using multiple strategies.
    
    Tries (in order):
    1. Direct mapping from column_harmonizer
    2. Keyword matching (ke up/down, upstream/downstream)
    3. Semantic matching via KE variations
    4. Fuzzy matching via difflib
    
    Args:
        header: Raw header string from table
        column_harmonizer: Dict mapping variations to canonical forms
        upstream_ke_title: Title of upstream KE
        downstream_ke_title: Title of downstream KE
        
    Returns:
        Tuple of (harmonized_header or None, is_matched: bool)
    """
    header_lower = header.lower().strip().replace("ke:", "").strip()
    
    # 1. Direct mapping
    if header_lower in column_harmonizer:
        return column_harmonizer[header_lower], True
    
    # 2. Keyword matching
    if "ke down" in header_lower or "downstream" in header_lower:
        return "Downstream Key Event", True
    if "ke up" in header_lower or "upstream" in header_lower:
        return "Upstream Key Event", True
    
    # 3. Semantic matching
    if find_semantic_match(header, upstream_ke_title):
        return "Upstream Key Event", True
    if find_semantic_match(header, downstream_ke_title):
        return "Downstream Key Event", True
    
    # 4. Fuzzy matching (using higher threshold to avoid false positives)
    upstream_ratio = difflib.SequenceMatcher(None, header_lower, upstream_ke_title.lower()).ratio()
    downstream_ratio = difflib.SequenceMatcher(None, header_lower, downstream_ke_title.lower()).ratio()
    
    if upstream_ratio > 0.7:
        return "Upstream Key Event", True
    if downstream_ratio > 0.7:
        return "Downstream Key Event", True
    
    return None, False


def _process_ker_headers(ker_id, ker_data, column_harmonizer):
    """
    Process and harmonize headers for a single KER.
    
    Only includes harmonized headers from fields that have both upstream and downstream KEs.
    
    Args:
        ker_id: KER identifier
        ker_data: KER data dictionary
        column_harmonizer: Header mapping dict
        
    Returns:
        Tuple of (harmonized_evidence dict, is_harmonizable: bool)
    """
    upstream_ke = ker_data['upstream_ke']
    downstream_ke = ker_data['downstream_ke']
    
    # Initialize harmonization record
    harmonized_record = {
        "upstream_ke": upstream_ke,
        "downstream_ke": downstream_ke,
        "aops": ker_data.get("aop_ids", []),
        "harmonized_fields": [],
        "harmonized_tables": {},
        "original_headers": set(),
        "harmonized_headers": {},
        "unmatched_headers": set(),
    }
    
    # Map evidence fields and process per-field harmonization
    evidence_fields = {
        'weight_of_evidence': ker_data.get("weight_of_evidence", {}),
        'empirical_support': ker_data.get("empirical_support", {}),
        'biological_plausibility': ker_data.get("biological_plausibility", {}),
        'quantitative_understanding': ker_data.get("quantitative_understanding", {})
    }
    
    field_harmonizability = {}
    
    for field_name, field_data in evidence_fields.items():
        field_headers = field_data.get("headers", []) if isinstance(field_data, dict) else []
        field_tables = field_data.get("tables", {}) if isinstance(field_data, dict) else {}
        
        # Skip fields with no headers or no tables (we only harmonize tabulated evidence)
        if not field_headers or not field_tables:
            field_harmonizability[field_name] = False
            continue
        
        # Match headers for this specific field
        field_harmonized_headers = {}
        field_unmatched_headers = set()
        
        for header in field_headers:
            harmonized_header, matched = _match_header_to_harmonized(
                header, column_harmonizer, upstream_ke['title'], downstream_ke['title']
            )
            
            if matched:
                field_harmonized_headers[header] = harmonized_header
            else:
                field_unmatched_headers.add(header)

        # Check if this field is harmonizable (has both upstream and downstream KEs)
        field_harmonized_values = set(field_harmonized_headers.values())
        field_is_harmonizable = (
            "Upstream Key Event" in field_harmonized_values and 
            "Downstream Key Event" in field_harmonized_values and 
            "References" in field_harmonized_values
        )
        field_harmonizability[field_name] = field_is_harmonizable
        
        # Only add to global harmonized_headers if field is harmonizable
        if field_is_harmonizable:
            harmonized_record["harmonized_fields"].append(field_name)
            harmonized_record["harmonized_headers"].update(field_harmonized_headers)
            # Track unmatched headers from harmonizable fields too
            harmonized_record["unmatched_headers"].update(field_unmatched_headers)
            
            # Process tables for harmonizable fields
            harmonized_record["harmonized_tables"][field_name] = _harmonize_tables(
                field_tables, ker_id, harmonized_record, field_name
            )
        else:
            # Still track unmatched headers even from non-harmonizable fields
            harmonized_record["unmatched_headers"].update(field_unmatched_headers)
            
        # Track all original headers
        harmonized_record["original_headers"].update(field_headers)
    
    # KER is harmonizable if at least one evidence field is harmonizable
    is_harmonizable = any(field_harmonizability.values())
    
    # Create header mapping dictionary (original -> harmonized)
    header_mapping = dict(harmonized_record["harmonized_headers"])
    # Add unmatched headers that map to themselves
    for unmatched in harmonized_record["unmatched_headers"]:
        header_mapping[unmatched] = unmatched
    
    # Convert sets to lists for JSON serialization
    harmonized_record["original_headers"] = list(harmonized_record["original_headers"])
    harmonized_record["unmatched_headers"] = list(harmonized_record["unmatched_headers"])
    harmonized_record["harmonized_headers"] = list(harmonized_record["harmonized_headers"])
    harmonized_record["header_mapping"] = header_mapping
    
    return harmonized_record, is_harmonizable


def _create_harmonization_summary(harmonized_evidence, harmonizable_kers, aops_with_evidence, aops_with_harmonizable):
    """
    Create summary statistics for the harmonization process.
    
    Args:
        harmonized_evidence: Dict of all KER harmonization records
        harmonizable_kers: List of KER IDs that could be harmonized
        aops_with_evidence: Set of AOPs that have any tabulated evidence
        aops_with_harmonizable: Set of AOPs with harmonizable evidence
        
    Returns:
        Dict with summary statistics
    """
    # Collect all headers across all KERs
    all_harmonized = set()
    all_unmatched = set()
    for record in harmonized_evidence.values():
        # harmonized_headers is a list of header names
        all_harmonized.update(record['harmonized_headers'])
        all_unmatched.update(record['unmatched_headers'])
    
    all_original = set()
    for record in harmonized_evidence.values():
        all_original.update(record['original_headers'])
    
    return {
        "summary": {
            "counts": {
                'Count KERs with tabulated evidence': len(harmonized_evidence),
                'Count KERs with harmonizable evidence tables': len(harmonizable_kers),
                'Count Harmonized headers': len(all_harmonized),
                'Count Unmatched headers': len(all_unmatched),
                'Count All KER Evidence table headers': len(all_original),
                'Count AOPs with any KER evidence tables': len(aops_with_evidence),
                'Count AOPs with harmonizable KER evidence tables': len(aops_with_harmonizable)
            },
            'harmonizable_kers': harmonizable_kers,
            'all_evidence_headers': sorted(list(all_original)),
            'all_harmonized_headers': sorted(list(all_harmonized)),
            'all_unmatched_headers': sorted(list(all_unmatched)),
            'aops_tab_evi': sorted(list(aops_with_evidence)),
            'aops_harm_evi': sorted(list(aops_with_harmonizable)),
        }
    }


def harmonize_evidence_headers(kers_and_evidence, column_harmonizer=COLUMN_HARMONIZER):
    """
    Harmonize headers used in evidence tables using the term mappings defined in column_harmonizer.

    Args:
        kers_and_evidence (dict): Dictionary of KER IDs mapped to their evidence tables
        column_harmonizer: Dict mapping header variations to canonical forms
        
    Returns:
        dict: Harmonized evidence with summary statistics
    """
    # Filter out non-KER entries
    kers = {k: v for k, v in kers_and_evidence.items() if k != "average_completion_scores"}
    
    harmonized_evidence = {}
    harmonizable_kers = []
    aops_with_evidence = set()
    aops_with_harmonizable = set()
    
    # Process each KER
    for ker_id, ker_data in kers.items():
        harmonized_record, is_harmonizable = _process_ker_headers(ker_id, ker_data, column_harmonizer)
        harmonized_evidence[ker_id] = harmonized_record
        
        # Track AOP associations
        aop_ids = ker_data.get("aop_ids", [])
        aops_with_evidence.update(aop_ids)
        
        if is_harmonizable:
            harmonizable_kers.append(ker_id)
            aops_with_harmonizable.update(aop_ids)
    
    # Build summary and return
    summary = _create_harmonization_summary(
        harmonized_evidence, harmonizable_kers, aops_with_evidence, aops_with_harmonizable
    )
    summary.update(harmonized_evidence)
    
    return summary

def transform_column_harmonizer(column_harmonizer):
    harmonized_columns = {}
    for k,v in column_harmonizer.items():
        if v not in harmonized_columns:
            harmonized_columns[v] = []
        harmonized_columns[v].append(k)

    return harmonized_columns
