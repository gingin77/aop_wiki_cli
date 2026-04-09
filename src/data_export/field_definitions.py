"""
Centralized field definitions for CSV exports.

This module defines the structure and configuration for all CSV exports
in the AOP-Wiki CLI system. Each field configuration includes:
- Column name
- Source key (supports dot notation for nested dicts)
- Optional transformer function
- Default value
- Documentation

Adding a new field only requires updating this file.
"""

from dataclasses import dataclass
from typing import Callable, Optional, List, Any


@dataclass
class FieldConfig:
    """Configuration for a single CSV field."""
    name: str                          # Column header name
    source_key: str                    # Key in source dict (supports dot notation)
    transformer: Optional[str] = None  # Name of transformation function
    default: Any = ''                  # Default value if missing
    description: str = ''              # Documentation


class FieldConfigSet:
    """Collection of field configurations for an entity type."""
    
    def __init__(self, name: str, fields: List[FieldConfig]):
        self.name = name
        self.fields = fields
    
    def get_field_names(self) -> List[str]:
        """Get list of column names in order."""
        return [f.name for f in self.fields]
    
    def get_source_keys(self) -> List[str]:
        """Get list of source keys in order."""
        return [f.source_key for f in self.fields]


# ============================================================================
# AOP Field Definitions
# ============================================================================

AOP_FIELDS_MIN = FieldConfigSet(
    name="aop_summary",
    fields=[
        FieldConfig('AOP ID', 'id', description='AOP identifier'),
        FieldConfig('Title', 'title', transformer='clean_text', description='AOP title'),
        FieldConfig('OECD Status', 'oecd_status', description='OECD endorsement status'),
        FieldConfig('License', 'wiki_license', description='Wiki license type'),
        FieldConfig('Handbook Version', 'handbook_version', default='', description='AOP Handbook version'),
        FieldConfig('Completion %', 'completion_score.percent', transformer='round_2', description='Completion percentage'),
        FieldConfig('Raw Score', 'completion_score.raw_score', description='Raw completion score'),
        FieldConfig('Max Score', 'completion_score.max_score', description='Maximum possible score'),
        FieldConfig('Events', 'num_events', default=0, description='Number of key events'),
        FieldConfig('KERs', 'num_kers', default=0, description='Number of KERs'),
        FieldConfig('Stressors', 'num_stressors', default=0, description='Number of stressors'),
        FieldConfig('Empty Free Text Fields', 'completion_score.empty_free_text', transformer='join_list', description='Missing free text fields'),
        FieldConfig('Empty Structured Fields', 'completion_score.empty_structured', transformer='join_list', description='Missing structured fields'),
    ]
)

AOP_DETAIL_FIELDS = FieldConfigSet(
    name="aop_detail",
    fields=[
        FieldConfig('aop_id', 'id'),
        FieldConfig('title', 'title', transformer='clean_text'),
        FieldConfig('oecd_status', 'oecd_status'),
        FieldConfig('wiki_license', 'wiki_license'),
        FieldConfig('adverse_outcomes', 'adverse_outcomes', transformer='clean_text'),
        FieldConfig('detected_as_aop_network', 'detected_as_aop_network'),
        FieldConfig('has_internal_loops', 'has_internal_loops'),
        FieldConfig('missing_mie', 'missing_mie'),
        FieldConfig('source_event_ids', 'source_event_ids'),
        FieldConfig('ordered_events_path', 'ordered_events', transformer='flatten_ordered_events'),
    ]
)

# ============================================================================
# Event/KE Field Definitions
# ============================================================================

EVENT_FIELDS_MIN = FieldConfigSet(
    name="event_summary",
    fields=[
        FieldConfig('Event ID', 'ke_id', description='Key event identifier'),
        FieldConfig('Title', 'title', transformer='clean_text', description='Event title'),
        FieldConfig('Retention Score', 'retention_score', default=0, description='Integration ranking score'),
        FieldConfig('Completion %', 'completion_score.percent', transformer='round_2', description='Completion percentage'),
        FieldConfig('AOP Count', 'aop_count', default=0, description='Number of associated AOPs'),
        FieldConfig('Has Method', 'has_method', transformer='yes_no', description='Has measurement method'),
        FieldConfig('OECD Endorsed', 'summary_oecd_statuses.any_oecd_endorsed', transformer='yes_no', description='In OECD endorsed AOP'),
        FieldConfig('In OECD Program', 'summary_oecd_statuses.in_oecd_aop_program', transformer='yes_no', description='In OECD AOP program'),
        FieldConfig('Only Open for Adoption', 'summary_licenses.only_open_for_adoption', transformer='yes_no', description='Only in open-for-adoption AOPs'),
    ]
)

EVENT_DETAIL_FIELDS = FieldConfigSet(
    name="event_detail",
    fields=[
        FieldConfig('ke_id', 'ke_id'),
        FieldConfig('title', 'title', transformer='clean_text'),
        FieldConfig('retention_score', 'retention_score', default=0),
        FieldConfig('source', 'source'),
        FieldConfig('completion_score', 'completion_score.percent', transformer='round_2'),
        FieldConfig('any_open_for_adoption', 'summary_licenses.any_open_for_adoption'),
        FieldConfig('any_all_rights_reserved', 'summary_licenses.any_all_rights_reserved'),
        FieldConfig('aop_count', 'aop_count', default=0),
        FieldConfig('aops', 'aops'),
        FieldConfig('fields_with_input_term', 'fields_with_input_term', transformer='join_list'),
        FieldConfig('higher_priority_field', 'higher_priority_field'),
        FieldConfig('summary_oecd_statuses', 'summary_oecd_statuses.statuses', transformer='join_list'),
        FieldConfig('level_of_biological_organization', 'level_of_biological_organization'),
        FieldConfig('cell_term', 'cell_term', transformer='format_term_with_source'),
        FieldConfig('organ_term', 'organ_term', transformer='format_term_with_source'),
        FieldConfig('ec_objects', 'ecs', transformer='extract_ec_objects'),
        FieldConfig('ec_actions', 'ecs', transformer='extract_ec_actions'),
        FieldConfig('ec_processes', 'ecs', transformer='extract_ec_processes'),
        FieldConfig('description', 'description', transformer='clean_text'),
    ]
)

# ============================================================================
# Concordance KER Fields
# ============================================================================

CONCORDANCE_KER_FIELDS = FieldConfigSet(
    name="concordance_ker",
    fields=[
        FieldConfig('KER ID', 'ker_id', description='KER identifier'),
        FieldConfig('Upstream KE', 'upstream_ke', description='Upstream key event title'),
        FieldConfig('Downstream KE', 'downstream_ke', description='Downstream key event title'),
        FieldConfig('AOPs', 'aops', transformer='join_list', description='Associated AOP IDs'),
        FieldConfig('Search Terms Found', 'terms_found', transformer='join_list', description='All concordance terms found'),
        FieldConfig('Field Searched', 'field', description='Field where match was found'),
        FieldConfig('Snippet', 'snippet', description='Text snippet showing match'),
    ]
)

# ============================================================================
# Search Results Fields - AOPs with Co-occurrences
# ============================================================================

SEARCH_RESULTS_AOP_FIELDS = FieldConfigSet(
    name="search_results_aop",
    fields=[
        FieldConfig('entity_id', 'entity_id', description='AOP ID'),
        FieldConfig('title', 'title', description='AOP title'),
        FieldConfig('snippet_count', 'snippet_count', description='Total number of snippets'),
        FieldConfig('has_priority_term_match', 'has_priority_term_match', transformer='yes_no', description='Search term in priority field'),
        FieldConfig('has_priority_co_occurrence', 'has_priority_co_occurrence', transformer='yes_no', description='Co-occurrence in priority field'),
        FieldConfig('sex_applicability', 'sex_applicability', transformer='join_list', description='Sex applicability'),
        FieldConfig('life_stage_applicability', 'life_stage_applicability', transformer='join_list', description='Life stage applicability'),
        FieldConfig('taxonomy_applicability', 'taxonomy_applicability', transformer='extract_titles_from_dicts', description='Taxonomy applicability'),
        FieldConfig('co_occurrences', 'co_occurrences_str', description='Co-occurring term pairs'),
        FieldConfig('co_occurrence_fields', 'co_occurrence_fields', transformer='join_list', description='Fields with co-occurrences'),
        FieldConfig('terms_found', 'terms_found', transformer='join_list', description='Individual terms found'),
        FieldConfig('matched_fields', 'matched_fields', transformer='join_list', description='All fields with matches'),
    ]
)

# ============================================================================
# Search Results Fields - Events (regulatory/methods)
# ============================================================================

SEARCH_RESULTS_EVENT_FIELDS = FieldConfigSet(
    name="search_results_event",
    fields=[
        FieldConfig('entity_id', 'entity_id', description='Event ID'),
        FieldConfig('title', 'title', description='Event title'),
        FieldConfig('terms_found', 'terms_found', transformer='join_list', description='Search terms found'),
        FieldConfig('matched_fields', 'matched_fields', transformer='join_list', description='Fields with matches'),
        FieldConfig('snippet_count', 'snippet_count', description='Total number of snippets'),
    ]
)

# ============================================================================
# Seizure AOP Event Fields
# ============================================================================

SEIZURE_AOP_EVENT_FIELDS = FieldConfigSet(
    name="seizure_aop_event",
    fields=[
        FieldConfig('AOP ID', 'aop_id', description='AOP identifier'),
        FieldConfig('Event Index', 'event_index', description='Event position in AOP'),
        FieldConfig('Row Index', 'row_index', description='Row number from Excel sheet'),
        FieldConfig('Event ID', 'event_id', description='Event ID parsed from workbook'),
        FieldConfig('Title from Wiki', 'title_from_wiki', description='Event title from AOP-Wiki XML'),
        FieldConfig('Harmonized Name', 'harmonized_event', description='Harmonized event name'),
        FieldConfig('Event Match', 'event_match', transformer='yes_no', description='Event found in AOP-Wiki'),
        FieldConfig('References', 'references', description='References from workbook'),
        FieldConfig('Target Family', 'target_family', description='Target family from workbook'),
    ]
)
HARMONIZED_SEIZURE_AOP_EVENT_FIELDS = FieldConfigSet(
    name="harmonized_seizure_aop_event",
    fields=[
        FieldConfig('Harmonized Title', 'harmonized_title', description='Harmonized event name grouping'),
        FieldConfig('AOP ID', 'aop_id', description='AOP identifier'),
        FieldConfig('Event ID', 'event_id', description='Event ID from AOP-Wiki'),
        FieldConfig('Row Index', 'row_index', description='Row number from Excel sheet'),
        FieldConfig('Event Index', 'event_index', description='Event position in source AOP'),
        FieldConfig('Title from Wiki', 'title_from_wiki', description='Event title from AOP-Wiki XML'),
        FieldConfig('LOBO', 'lobo', description='Level of biological organization'),
        FieldConfig('Event Match', 'event_match', transformer='yes_no', description='Event found in AOP-Wiki'),
        FieldConfig('References', 'references', description='References from workbook'),
        FieldConfig('Target Family', 'target_family', description='Target family from workbook'),
    ]
)

HARMONIZED_SEIZURE_AOP_SUMMARY_FIELDS = FieldConfigSet(
    name="harmonized_seizure_aop_summary",
    fields=[
        FieldConfig('Harmonized Title', 'harmonized_title', description='Harmonized event name grouping'),
        FieldConfig('Total Events', 'total_events', description='Total number of event occurrences'),
        FieldConfig('LOBO Count', 'lobo_count', description='Number of unique biological organization levels'),
        FieldConfig('LOBOs', 'lobos', transformer='join_list', description='List of unique biological organization levels'),
        FieldConfig('Event IDs', 'event_ids', transformer='join_list', description='List of unique event IDs'),
        FieldConfig('AOP IDs', 'aop_ids', transformer='join_list', description='List of unique AOP IDs'),
        FieldConfig('References', 'references', transformer='join_list', description='Aggregated unique references from all events'),
        FieldConfig('Target Families', 'target_families', transformer='join_list', description='Aggregated unique target families from all events'),
    ]
)

# ============================================================================
# Seizure AOP Assay Fields
# ============================================================================

SEIZURE_ASSAY_FIELDS = FieldConfigSet(
    name="seizure_assays",
    fields=[
        FieldConfig('AEID', 'aeid', description='Assay endpoint ID'),
        FieldConfig('Endpoint Name', 'endpoint_name', description='Assay endpoint name'),
        FieldConfig('Mode of Action', 'moa', description='Mode of action'),
        FieldConfig('Mechanistic Target', 'mechanistic_target', description='Mechanistic target'),
        FieldConfig('MT NCIm Term', 'mt_ncim_term', description='NCI Metathesaurus term'),
        FieldConfig('MT NCIm Term ID', 'mt_ncim_term_id', description='NCI Metathesaurus term ID'),
        FieldConfig('Target Families', 'target_families_general', description='General target families'),
        FieldConfig('Assay Component Desc', 'assay_component_desc', description='Assay component description'),
        FieldConfig('Assay Component Target Desc', 'assay_component_target_desc', description='Assay component target description'),
        FieldConfig('Relationship to KE', 'relationship_to_ke_in_aop_network', description='Relationship to key event in AOP network'),
        FieldConfig('Species', 'species', description='Species'),
        FieldConfig('AOP IDs', 'aop_ids', transformer='join_list', description='AOP IDs mentioned in relationship'),
        FieldConfig('KE Descriptions', 'ke_descriptions', transformer='join_list', description='KE descriptions mentioned in relationship'),
    ]
)

SEIZURE_TARGET_FAMILIES_SUMMARY_FIELDS = FieldConfigSet(
    name="target_families_summary",
    fields=[
        FieldConfig('Category', 'category', description='Target family category'),
        FieldConfig('Target Families', 'target_families', transformer='join_list', description='Target family names'),
    ]
)

SEIZURE_TF_TO_EVENTS_ASSAYS_FIELDS = FieldConfigSet(
    name="tf_to_events_assays",
    fields=[
        FieldConfig('Target Family', 'target_family', description='Target family name'),
        FieldConfig('Harmonized Events', 'h_events', transformer='join_list', description='Harmonized event IDs'),
        FieldConfig('Assays', 'assays', transformer='join_list', description='Associated assay endpoint names'),
    ]
)

SEIZURE_AOP_ID_MAPPING_FIELDS = FieldConfigSet(
    name="aop_id_mapping",
    fields=[
        FieldConfig('AOP ID', 'aop_id', description='AOP identifier'),
        FieldConfig('Assays', 'assays', transformer='join_list', description='Associated assay endpoint names'),
        FieldConfig('Target Families', 'target_families', transformer='join_list', description='Associated target families'),
    ]
)

SEIZURE_KE_DESC_MAPPING_FIELDS = FieldConfigSet(
    name="ke_description_mapping",
    fields=[
        FieldConfig('KE Description', 'ke_description', description='Key event description'),
        FieldConfig('Assays', 'assays', transformer='join_list', description='Associated assay endpoint names'),
        FieldConfig('Target Families', 'target_families', transformer='join_list', description='Associated target families'),
    ]
)

SEIZURE_TF_ASSAYS_KE_MAPPING_FIELDS = FieldConfigSet(
    name="tf_assays_ke_mapping",
    fields=[
        FieldConfig('Target Family', 'target_family', description='Target family name'),
        FieldConfig('Assays', 'assays', transformer='join_list', description='Associated assay endpoint names'),
        FieldConfig('KE Descriptions', 'ke_descriptions', transformer='join_list', description='Associated KE descriptions'),
    ]
)

SEIZURE_KE_DESC_TO_HARMONIZED_FIELDS = FieldConfigSet(
    name="ke_description_to_harmonized",
    fields=[
        FieldConfig('KE Description', 'ke_description', description='KE description from assays sheet'),
        FieldConfig('Harmonized KE Match', 'harmonized_ke_match', description='Matched harmonized KE title'),
        FieldConfig('Match Score', 'match_score', description='Similarity score (0.0-1.0)'),
    ]
)

SEIZURE_READY_LIST_FIELDS = FieldConfigSet(
    name="seizure_ready_list",
    fields=[
        FieldConfig('Value', 'value', description='Value ready for EMOD upload'),
    ]
)

SEIZURE_EVENT_TO_HARMONIZED_FIELDS = FieldConfigSet(
    name="seizure_event_to_harmonized",
    fields=[
        FieldConfig('Event ID', 'event_id', description='Original event ID from worksheet category field'),
        FieldConfig('Harmonized Event', 'harmonized_event', description='Mapped harmonized KE title'),
    ]
)

SEIZURE_AOP_TO_HARMONIZED_FIELDS = FieldConfigSet(
    name="seizure_aop_to_harmonized",
    fields=[
        FieldConfig('AOP ID', 'aop_id', description='AOP identifier from harmonization grouping'),
        FieldConfig('Row Index', 'row_index', description='Row number from harmonization worksheet'),
        FieldConfig('Harmonized Event', 'harmonized_event', description='Mapped harmonized KE title'),
        FieldConfig('Original Event ID', 'original_event_id', description='Original event ID from worksheet category field'),
    ]
)

SEIZURE_AOP_VALIDATION_FIELDS = FieldConfigSet(
    name="seizure_aop_validation",
    fields=[
        FieldConfig('Validation Type', 'validation_type', description='Type of validation finding'),
        FieldConfig('AOP Pair', 'aop_pair', description='AOP pair identifier when applicable'),
        FieldConfig('AOP ID', 'aop_id', description='AOP identifier when applicable'),
        FieldConfig('Harmonized Event', 'harmonized_event', description='Harmonized event title when applicable'),
        FieldConfig('Row Index', 'row_index', description='Row index when applicable'),
        FieldConfig('Original Event ID', 'original_event_id', description='Original event ID when applicable'),
        FieldConfig('Original Event Title', 'original_event_title', description='Original event title when applicable'),
        FieldConfig('AOP One Event Count', 'aop_one_event_count', description='Event count for first AOP in pair'),
        FieldConfig('AOP Two Event Count', 'aop_two_event_count', description='Event count for second AOP in pair'),
    ]
)

SEIZURE_ASSAYS_BY_AEID_FIELDS = FieldConfigSet(
    name="seizure_assays_by_aeid",
    fields=[
        FieldConfig('AEID', 'aeid', description='Assay endpoint identifier'),
        FieldConfig('Assays', 'assays', transformer='join_list', description='Assay endpoint names associated with the AEID'),
        FieldConfig('Target Families', 'target_families', transformer='join_list', description='Target families associated with the AEID'),
    ]
)

SEIZURE_CHEMICALS_BY_CASRN_FIELDS = FieldConfigSet(
    name="seizure_chemicals_by_casrn",
    fields=[
        FieldConfig('CASRN', 'casrn', description='Chemical Abstracts Registry Number'),
        FieldConfig('Chemical', 'chemical', description='Chemical name'),
        FieldConfig('Direction of Effect', 'direction_of_effect', description='Positive or Negative effect'),
        FieldConfig('PubChem Evidence', 'pubchem_evidence', description='Evidence of seizure from PubChem'),
        FieldConfig('Parsed Citations', 'parsed_citations', transformer='to_json_string', description='Parsed literature citations'),
    ]
)