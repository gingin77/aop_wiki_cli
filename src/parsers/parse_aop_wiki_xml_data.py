"""
Examples:
    Run the script to collect and parse AOP-Wiki XML data:
        $   uv run python -m scripts.parse_aop_wiki_xml_data
"""

# Needed for testing purposes
import os
import json
import pprint as pp
from datetime import date
from src.collection import collect_xml_data
from src.utilities import write_dict_to_json, generic_cache_wrapper

# Required dependencies for core functions
from src.parsers.completion_score import (
    add_completion_score_to_events,
    add_completion_score_to_kers,
    add_completion_score_to_aops,
)
from src.analysis import apply_ranking_to_events_dict
from src.parsers.xml_processing_helpers import (
    collect_ker_to_aop_mapping_from_xml,
    collect_tables_from_field,
)

# ============================================================================
# Core functions for capturing core entities from the AOP-Wiki XML and 
# applying completion scoring
# ============================================================================

def collect_events_from_xml(root, xml_namespace, refs):
    """
    Collect all event (Key Event) data from XML.
    
    Note: This function automatically adds completion scores and retention ranking
    scores to all events before returning.
    
    Args:
        root: ElementTree Element object (XML root)
        xml_namespace: XML namespace
        refs: Reference dictionaries for ID mapping
    
    Returns:
        Dictionary of events with completion scores and retention rankings
    """
    ecs_dict = collect_ecs_from_xml(root, xml_namespace)
    taxonomy_dict = collect_taxonomies_from_xml(root, xml_namespace)
    _, ke_to_aop_info = collect_base_aop_info_from_xml(root, xml_namespace, refs)
    for ke in root.findall(xml_namespace + 'key-event'):
        ke_id = refs['KE'][ke.get('id')]
        cell_source = None
        cell_term = None
        organ_source = None
        organ_term = None

        # Organ and Cell term extraction
        if ke.find(xml_namespace + 'organ-term') is not None:
            organ_source = ke.find(xml_namespace + 'organ-term').find(xml_namespace + 'source').text
            organ_term = ke.find(xml_namespace + 'organ-term').find(xml_namespace + 'name').text

        if ke.find(xml_namespace + 'cell-term') is not None:
            cell_source = ke.find(xml_namespace + 'cell-term').find(xml_namespace + 'source').text
            cell_term = ke.find(xml_namespace + 'cell-term').find(xml_namespace + 'name').text

        # ECS extraction
        ecs_from_xml = ke.find(xml_namespace + 'biological-events')
        ecs = []
        if ecs_from_xml is not None:
            for ec in ecs_from_xml.findall(xml_namespace + 'biological-event'):
                ec_dict = {
                    "biological_process": {},
                    "biological_object": {},
                    "biological_action": {}
                }
                if ec.get('process-id') is not None:
                    ec_dict["biological_process"] = ecs_dict["processes"].get(ec.get('process-id'), {})
                if ec.get('object-id') is not None:
                    ec_dict["biological_object"] = ecs_dict["objects"].get(ec.get('object-id'), {})
                if ec.get('action-id') is not None:
                    ec_dict["biological_action"] = ecs_dict["actions"].get(ec.get('action-id'), {})
                
                ecs.append(ec_dict)

        # Domain of applicability extraction
        doa_dict = collect_doa_fields(ke, xml_namespace, taxonomy_dict)
        
        aop_count = len(ke_to_aop_info[ke_id].get('aop_ids', [])) if ke_id in ke_to_aop_info else 0
        if ke_id in ke_to_aop_info:
            ke_to_aop_info[ke_id].update({
                'ke_id': ke_id,
                'title': ke.find(xml_namespace + 'title').text,
                "short_name": ke.find(xml_namespace + 'short-name').text,
                "doa_free_text": ke.find(xml_namespace + 'evidence-supporting-taxonomic-applicability').text,
                "description": ke.find(xml_namespace + 'description').text,
                "measurement_method": ke.find(xml_namespace + 'measurement-methodology').text,
                "level_of_biological_organization": ke.find(xml_namespace + 'biological-organization-level').text,
                "references": ke.find(xml_namespace + 'references').text,
                "cell_term": {
                    "source": cell_source,
                    "term": cell_term
                },
                "organ_term": {
                    "source": organ_source,
                    "term": organ_term
                },
                "ecs": ecs,
                "sex_terms": doa_dict['sex_terms'],
                "life_stage_terms": doa_dict['life_stage_terms'],
                "taxonomy_terms": doa_dict['taxonomy_terms'],
                "aop_count": aop_count
            })
        else:
            print(f"WARNING: Missing KE ID {ke_id}")

    events_with_completion_scores = add_completion_score_to_events(ke_to_aop_info)
    events_ranked = apply_ranking_to_events_dict(events_with_completion_scores)
    return events_ranked


def collect_kers_from_xml(root, xml_namespace, refs):
    """
    Collect all KER data from XML with upstream/downstream KE information.
    
    This function:
      - Extracts all KERs with their metadata (upstream/downstream KEs)
      - Associates KERs with their AOPs using KER-to-AOP mapping
      - Extracts tabulated evidence tables
      - Automatically adds completion scores to all KERs before returning
    
    Note: If you need the AOP-to-KER mapping, use collect_ker_to_aop_mapping_from_xml()
          from xml_processing_helpers separately.
    
    Args:
        root: ElementTree Element object (XML root)
        xml_namespace: XML namespace
        refs: Reference dictionaries for ID mapping
    
    Returns:
        Dictionary of KERs with completion scores, keyed by KER ID
    """
    # Collect minimal KE info internally
    ke_dict = collect_events_from_xml(root, xml_namespace, refs)
    taxonomy_dict = collect_taxonomies_from_xml(root, xml_namespace)
    
    # Build KER mapping (AOP IDs + adjacency types) from XML
    ker_to_aop_dict, _ = collect_ker_to_aop_mapping_from_xml(root, xml_namespace, refs)
    
    ker_props = {}
    for ker in root.findall(xml_namespace + 'key-event-relationship'):
        up_ke_id = refs['KE'][ker.find(xml_namespace + 'title').find(xml_namespace + 'upstream-id').text]
        down_ke_id = refs['KE'][ker.find(xml_namespace + 'title').find(xml_namespace + 'downstream-id').text]
        ker_id = refs['KER'][ker.get('id')]
        
        woe = ker.find(xml_namespace + 'weight-of-evidence')
        
        mod_in_xml = ker.find(xml_namespace + 'known-modulating-factors')
        mod_f_value = mod_in_xml.text if mod_in_xml is not None else None
        
        ref_in_xml = ker.find(xml_namespace + 'references')
        references = ref_in_xml.text if ref_in_xml is not None else None

        description_in_xml = ker.find(xml_namespace + 'description')
        description = description_in_xml.text if description_in_xml is not None else None

        doa_free_text_in_xml = ker.find(xml_namespace + 'evidence-supporting-taxonomic-applicability')
        doa_free_text = doa_free_text_in_xml.text if doa_free_text_in_xml is not None else None

        if woe is not None:
            woe_field = woe.find(xml_namespace + 'value')
            empirical_support = woe.find(xml_namespace + 'emperical-support-linkage')
            biological_plausibility = woe.find(xml_namespace + 'biological-plausibility')
            uncertainties = woe.find(xml_namespace + 'uncertainties-or-inconsistencies')
        else:
            woe_field = None
            empirical_support = None
            biological_plausibility = None
            uncertainties = None

        # Quantitative understanding extraction
        quant_und_in_xml = ker.find(xml_namespace + 'quantitative-understanding')
        if quant_und_in_xml is not None:
            quant_understanding_prop = quant_und_in_xml.find(xml_namespace + 'description')
            res_response_rel = quant_und_in_xml.find(xml_namespace + 'response-response-relationship')
            time_scale = quant_und_in_xml.find(xml_namespace + 'time-scale')
            known_loops = quant_und_in_xml.find(xml_namespace + 'feedforward-feedback-loops')
            evidence_collection_strategy = quant_und_in_xml.find(xml_namespace + 'evidence-collection-strategy')
        else:
            res_response_rel = None
            time_scale = None
            known_loops = None
            evidence_collection_strategy = None
            quant_understanding_prop = None

        # Domain of applicability extraction
        doa_dict = collect_doa_fields(ker, xml_namespace, taxonomy_dict)
        
        # Build complete evidence data structure from fields
        # Use the raw XML elements for table collection, not the extracted text values
        evidence_fields_config = [
            ('woe', woe_field),
            ('empirical_support', empirical_support),
            ('biological_plausibility', biological_plausibility),
            ('quantitative_understanding', quant_understanding_prop)  # Use element, not text value
        ]
        
        evidence_data = {}
        for key, field in evidence_fields_config:
            tables, headers = collect_tables_from_field(field)
            free_text = field.text if field is not None else None
            evidence_data[key] = {
                "free_text": free_text,
                "tables": tables,
                "headers": headers
            }
        
        # Check if any tables have values
        has_any_tables = any(evidence_data[key]['tables'] for key in evidence_data)
            
        ker_props[ker_id] = {
            "upstream_ke": {
                "id": up_ke_id,
                "title": ke_dict[up_ke_id]["title"]
            },
            "downstream_ke": {
                "title": ke_dict[down_ke_id]["title"],
                "id": down_ke_id
            },
            "has_any_tables": has_any_tables,
            "aop_ids": ker_to_aop_dict.get(ker_id, {}).get("aop_ids", []),
            "adjacency_types": ker_to_aop_dict.get(ker_id, {}).get("adjacency_types", []),
            "weight_of_evidence": evidence_data['woe'],
            "empirical_support": evidence_data['empirical_support'],
            "biological_plausibility": evidence_data['biological_plausibility'],
            "quantitative_understanding": evidence_data['quantitative_understanding'],
            "sex_terms": doa_dict['sex_terms'],
            "life_stage_terms": doa_dict['life_stage_terms'],
            "taxonomy_terms": doa_dict['taxonomy_terms'],
            "modulating_factors": mod_f_value,
            "description": description,
            "doa_free_text": doa_free_text,
            "uncertainties": uncertainties.text if uncertainties is not None else None,
            "response_relationship": res_response_rel.text if res_response_rel is not None else None,
            "time_scale": time_scale.text if time_scale is not None else None,
            "known_loops": known_loops.text if known_loops is not None else None,
            "evidence_collection_strategy": evidence_collection_strategy.text if evidence_collection_strategy is not None else None,
            "references": references
        }

    ker_props_with_completion_scores = add_completion_score_to_kers(ker_props)

    return ker_props_with_completion_scores

def collect_aops_from_xml(root, xml_namespace, refs):
    """
    Collect comprehensive AOP data including all major fields.
    
    Note: This function automatically adds completion scores to all AOPs before returning.
    
    Args:
        root: XML root element
        xml_namespace: XML namespace string
        refs: Reference dictionaries for ID mapping
        
    Returns:
        Dictionary of AOPs with completion scores, keyed by AOP ID
    """
    aop_data, _ = collect_base_aop_info_from_xml(root, xml_namespace, refs)
    for aop in root.findall(xml_namespace + 'aop'):
        aop_id = refs['AOP'][aop.get('id')]
        
        # Basic identification
        title = safe_text(aop.find(xml_namespace + 'title'))
        short_name = safe_text(aop.find(xml_namespace + 'short-name'))
        abstract = safe_text(aop.find(xml_namespace + 'abstract'))
        
        # Authors and coaches
        authors = safe_text(aop.find(xml_namespace + 'authors'))
        coaches_elem = aop.find(xml_namespace + 'coaches')
        coaches = []
        if coaches_elem is not None:
            for coach in coaches_elem.findall(xml_namespace + 'coach'):
                if coach.text:
                    coaches.append(coach.text.strip())
        
        # Handbook version (used for conditional scoring)
        handbook_version_text = safe_text(aop.find(xml_namespace + 'handbook-version'))
        handbook_version = None
        if handbook_version_text:
            try:
                handbook_version = float(handbook_version_text)
            except ValueError:
                handbook_version = None
        
        # Background section (direct child of aop)
        background = safe_text(aop.find(xml_namespace + 'background'))
        
        # Development strategy (direct child of aop)
        development_strategy = safe_text(aop.find(xml_namespace + 'development-strategy'))
        
        # Domain of applicability (direct child of aop - structured data)
        # Collect sex, life-stage, and taxonomy terms for scoring
        taxonomy_dict = collect_taxonomies_from_xml(root, xml_namespace)
        doa_dict = collect_doa_fields(aop, xml_namespace, taxonomy_dict)
        
        # Overall assessment section contains the evidence summaries
        overall_assessment = aop.find(xml_namespace + 'overall-assessment')
        overall_assessment_description = ''
        doa_free_text = ''
        ke_essentiality = ''
        woe_evidence = ''
        quantitative_considerations = ''
        known_modulating_factors = ''
        
        if overall_assessment is not None:
            overall_assessment_description = safe_text(overall_assessment.find(xml_namespace + 'description'))
            doa_free_text = safe_text(overall_assessment.find(xml_namespace + 'applicability'))
            ke_essentiality = safe_text(overall_assessment.find(xml_namespace + 'key-event-essentiality-summary'))
            woe_evidence = safe_text(overall_assessment.find(xml_namespace + 'weight-of-evidence-summary'))
            quantitative_considerations = safe_text(overall_assessment.find(xml_namespace + 'quantitative-considerations'))
            known_modulating_factors = safe_text(overall_assessment.find(xml_namespace + 'known-modulating-factors'))
        
        # Potential applications section (direct child of aop)
        potential_applications = safe_text(aop.find(xml_namespace + 'potential-applications'))
        
        # Collect KER information
        kers = {}
        ker_section = aop.find(xml_namespace + 'key-event-relationships')
        if ker_section is not None:
            for ker in ker_section.findall(xml_namespace + 'relationship'):
                ker_xml_id = ker.get('id')
                if ker_xml_id and ker_xml_id in refs['KER']:
                    ker_id = refs['KER'][ker_xml_id]
                    adjacency_elem = ker.find(xml_namespace + 'adjacency')
                    kers[ker_id] = {
                        'type': safe_text(adjacency_elem)
                    }
        
        # Collect stressor information
        stressors = []
        stressor_section = aop.find(xml_namespace + 'aop-stressors')
        if stressor_section is not None:
            for stressor in stressor_section.findall(xml_namespace + 'aop-stressor'):
                stressor_xml_id = stressor.get('stressor-id')
                if stressor_xml_id and stressor_xml_id in refs['Stressor']:
                    stressors.append(refs['Stressor'][stressor_xml_id])
        
        event_count = len(aop_data.get(aop_id, {}).get('event_ids', []))
        references = aop.find(xml_namespace + 'references').text
        aop_data[aop_id].update({
            'title': title,
            'short_name': short_name,
            'abstract': abstract,
            'authors': authors,
            'coaches': coaches,
            'handbook_version': handbook_version,
            'background': background,
            'development_strategy': development_strategy,
            'sex_applicability': doa_dict['sex_terms'],
            'life_stage_applicability': doa_dict['life_stage_terms'],
            'taxonomy_applicability': doa_dict['taxonomy_terms'],
            'overall_assessment_description': overall_assessment_description,
            'doa_free_text': doa_free_text,
            'ke_essentiality': ke_essentiality,
            'woe_evidence': woe_evidence,
            'quantitative_considerations': quantitative_considerations,
            'known_modulating_factors': known_modulating_factors,
            'potential_applications': potential_applications,
            "references": references,
            'kers': kers,
            'stressors': stressors,
            'num_events': event_count,
            'num_kers': len(kers),
            'num_stressors': len(stressors)
        })
    
    aops_with_completion_scores = add_completion_score_to_aops(aop_data)
    return aops_with_completion_scores

def collect_ecs_from_xml(root, xml_namespace):
    ec_dict = {
        "processes": {},
        "objects": {},
        "actions": {}
    }
    for process in root.findall(xml_namespace + 'biological-process'):
        ec_dict["processes"][process.get('id')] = {
            "source": process.find(xml_namespace + "source").text,
            "source_id": process.find(xml_namespace + "source-id").text,
            "term": process.find(xml_namespace + "name").text,
        }
    for object in root.findall(xml_namespace + 'biological-object'):
        ec_dict["objects"][object.get('id')] = {
            "source": object.find(xml_namespace + "source").text,
            "source_id": object.find(xml_namespace + "source-id").text,
            "term": object.find(xml_namespace + "name").text,
        }
        
    for action in root.findall(xml_namespace + 'biological-action'):
        ec_dict["actions"][action.get('id')] = {
            "source_id": action.find(xml_namespace + "source-id").text,
            "term": action.find(xml_namespace + "name").text,
        }

    return ec_dict

def collect_references_from_aops_kers_and_events(root, xml_namespace, refs):
    """
    Aggregate references for AOPs, KEs, and KERs from XML data.
    
    Args:
        root: ElementTree Element object (XML root)
        xml_namespace: XML namespace
        refs: Reference dictionaries for ID mapping 
    Returns:
        Dictionary with references aggregated for AOPs, KEs, and KERs
    """
    references_for_core_entities = {
        "AOP": {},
        "KE": {},
        "KER": {}
    }

    # Aggregate references for AOPs
    for aop in root.findall(xml_namespace + 'aop'):
        aop_id = refs['AOP'][aop.get('id')]
        ref_elem = aop.find(xml_namespace + 'references').text

        references_for_core_entities["AOP"][aop_id] = ref_elem

    # Aggregate references for KEs
    for ke in root.findall(xml_namespace + 'key-event'):
        ke_id = refs['KE'][ke.get('id')]
        ref_elem = ke.find(xml_namespace + 'references').text

        references_for_core_entities["KE"][ke_id] = ref_elem

    # Aggregate references for KERs
    for ker in root.findall(xml_namespace + 'key-event-relationship'):
        ker_id = refs['KER'][ker.get('id')]
        ref_elem = ker.find(xml_namespace + 'references').text

        references_for_core_entities["KER"][ker_id] = ref_elem

    return references_for_core_entities

# Helper used to support collection of AOPs, KERs, and Events
def collect_taxonomies_from_xml(root, xml_namespace):
    tax_dict = {}
    for tax in root.findall(xml_namespace + 'taxonomy'):
        tax_dict[tax.get('id')] = {}
        tax_dict[tax.get('id')]['source'] = tax.find(xml_namespace + 'source').text
        tax_dict[tax.get('id')]['source-id'] = tax.find(xml_namespace + 'source-id').text
        tax_dict[tax.get('id')]['title'] = tax.find(xml_namespace + 'name').text

    return tax_dict


def collect_doa_fields(element, xml_namespace, taxonomy_dict):
    """Extract domain of applicability fields (sex, life stage, taxonomy) from XML element.
    
    Args:
        element: XML element containing 'applicability' children
        xml_namespace: XML namespace string
        taxonomy_dict: Dictionary of taxonomy data keyed by taxonomy ID
        
    Returns:
        Dictionary with 'sex_terms', 'life_stage_terms', 'taxonomy_terms' lists
    """
    doa_dict = {
        "sex_terms": [],
        "life_stage_terms": [],
        "taxonomy_terms": []
    }
    
    for appl in element.findall(xml_namespace + 'applicability'):
        # Extract sex terms
        for sex in appl.findall(xml_namespace + 'sex'):
            sex_elem = sex.find(xml_namespace + 'sex')
            if sex_elem is not None and sex_elem.text:
                sex_text = sex_elem.text.strip()
                if sex_text:
                    doa_dict["sex_terms"].append(sex_text)
        
        # Extract life stage terms
        for life in appl.findall(xml_namespace + 'life-stage'):
            life_elem = life.find(xml_namespace + 'life-stage')
            if life_elem is not None and life_elem.text:
                life_text = life_elem.text.strip()
                if life_text:
                    doa_dict["life_stage_terms"].append(life_text)
        
        # Extract taxonomy terms
        for tax in appl.findall(xml_namespace + 'taxonomy'):
            tax_id = tax.get('taxonomy-id')
            if tax_id and tax_id in taxonomy_dict:
                doa_dict["taxonomy_terms"].append(taxonomy_dict[tax_id])
    
    return doa_dict

# Helper function to safely extract text
def safe_text(element, default=''):
    return element.text if element is not None and element.text else default

def update_ke_and_aop_mappings(ke, refs, aop_id, aop_base_info, ke_to_aop_info, reg_field=None):
    ke_id = refs['KE'][ke.get('key-event-id')]
    if ke_id not in ke_to_aop_info:
        ke_to_aop_info[ke_id] = {"aop_ids": []}
        ke_to_aop_info[ke_id]["is_ao"] = False
        ke_to_aop_info[ke_id]["regulatory_relevance"] = False
        
    if reg_field is not None:
        ke_to_aop_info[ke_id]["is_ao"] = True
        ke_to_aop_info[ke_id]["regulatory_relevance"] = reg_field

    ke_to_aop_info[ke_id]["aop_ids"].append(aop_id)
    aop_base_info[aop_id]["event_ids"].append(ke_id)

    return aop_base_info, ke_to_aop_info

def add_aop_status_info_to_kes(ke_to_aop_info, aop_base_info):
    # Enrich KEs with OECD and license summary info from associated AOPs
    for ke_id, ke_info in ke_to_aop_info.items():
        aop_ids = ke_info.get('aop_ids', [])
        
        # Collect OECD statuses and licenses from all associated AOPs
        oecd_statuses = []
        aops_to_oecd = {}
        aops_to_license = {}
        
        for aop_id in aop_ids:
            if aop_id in aop_base_info:
                aop_status = aop_base_info[aop_id].get('oecd_status', None)
                aop_license = aop_base_info[aop_id].get('wiki_license', None)
                oecd_statuses.append(aop_status)
                aops_to_oecd[aop_id] = aop_status
                aops_to_license[aop_id] = aop_license
        
        # Build summary OECD statuses
        oecd_statuses_clean = [status for status in oecd_statuses if status is not None]
        in_oecd_aop_program = any(item is not None and item != '' for item in oecd_statuses_clean)
        any_endorsed = any(status == 'WPHA/WNT Endorsed' for status in oecd_statuses_clean)
        
        ke_to_aop_info[ke_id]['summary_oecd_statuses'] = {
            "statuses": oecd_statuses_clean,
            'any_oecd_endorsed': any_endorsed,
            'in_oecd_aop_program': in_oecd_aop_program
        }
        
        # Build summary licenses
        licenses = list(set(aops_to_license.values()))
        licenses_clean = [lic for lic in licenses if lic is not None]
        
        ke_to_aop_info[ke_id]['summary_licenses'] = {
            "licenses": licenses_clean,
            "only_all_rights_reserved": all(lic == "All rights reserved" for lic in licenses_clean) if licenses_clean else False,
            "only_open_for_adoption": all(lic == "Open for adoption" for lic in licenses_clean) if licenses_clean else False,
            "any_open_for_adoption": any(lic == "Open for adoption" for lic in licenses_clean),
            "any_all_rights_reserved": any(lic == "All rights reserved" for lic in licenses_clean)
        }
        
        # Store AOP metadata for later use
        ke_to_aop_info[ke_id]['aops'] = ", ".join([str(aop_id) for aop_id in aop_ids])
        ke_to_aop_info[ke_id]['aops_to_oecd'] = aops_to_oecd
        ke_to_aop_info[ke_id]['aops_to_license'] = aops_to_license

    return ke_to_aop_info

def collect_base_aop_info_from_xml(root, xml_namespace, refs):
    aop_base_info = {}
    ke_to_aop_info = {}
    for aop in root.findall(xml_namespace + 'aop'):
        aop_id = refs['AOP'][aop.get('id')]
        aop_base_info[aop_id] = { 
            'id': aop_id,
            "event_ids": [] 
        }
        
        # Status information for AOPs
        status_elem = aop.find(xml_namespace + 'status')
        if status_elem is not None:
            aop_base_info[aop_id]["oecd_status"] = safe_text(status_elem.find(xml_namespace + 'oecd-status'))
            aop_base_info[aop_id]["wiki_license"] = safe_text(status_elem.find(xml_namespace + 'wiki-license'))
        
        # Event Information - KEs, MIEs, AOs
        if aop.find(xml_namespace + 'key-events') is not None:
            for key_event in aop.find(xml_namespace + 'key-events').findall(xml_namespace + 'key-event'):
                aop_base_info, ke_to_aop_info = update_ke_and_aop_mappings(key_event, refs, aop_id, aop_base_info, ke_to_aop_info)
        for mie in aop.findall(xml_namespace + 'molecular-initiating-event'):
            aop_base_info, ke_to_aop_info = update_ke_and_aop_mappings(mie, refs, aop_id, aop_base_info, ke_to_aop_info)
        for ao in aop.findall(xml_namespace + 'adverse-outcome'):
            reg_field = ao.find(xml_namespace + 'examples').text if ao.find(xml_namespace + 'examples') is not None else None
            aop_base_info, ke_to_aop_info = update_ke_and_aop_mappings(ao, refs, aop_id, aop_base_info, ke_to_aop_info, reg_field)

    ke_to_aop_info = add_aop_status_info_to_kes(ke_to_aop_info, aop_base_info)

    return aop_base_info, ke_to_aop_info


# ============================================================================
# Caching Wrappers for Entity Collections
# ============================================================================

def collect_entity_with_cache(entity_type, collection_function, work_date, output_dir, force_refresh=False, logger=None):
    """
    Caching wrapper for XML entity collection functions.
    
    This is a specialized wrapper that handles XML-specific entity collection
    (events, KERs, AOPs) using the generic caching logic.
    
    Args:
        entity_type: Type of entity ('kers', 'events', 'aops')
        collection_function: Function that takes (root, xml_namespace, refs) and returns entities dict
        work_date: Date object for the data collection
        output_dir: Directory to store cached files
        force_refresh: If True, ignore cache and collect fresh data
        logger: Optional logger instance for status messages
        
    Returns:
        Dictionary of entities with completion scores
    """
    work_date_str = work_date.strftime('%m-%d-%Y')
    cache_key = f'all_{entity_type}_{work_date_str}'
    
    return generic_cache_wrapper(
        cache_key, 
        output_dir, 
        lambda: collection_function(*collect_xml_data(work_date)),
        force_refresh, 
        logger
    )

# ============================================================================
# Demo/Testing
# ============================================================================

if __name__ == '__main__':
    # Example usage for testing collection functions with caching
    today = date.today()
    today_str = today.strftime('%m-%d-%Y')
    output_dir = f'outputs/test_collections/{today_str}'
    
    print("\n" + "="*60)
    print("TESTING ENTITY COLLECTION WITH CACHING")
    print("="*60)
    
    # Test 1: Collect events with caching (first call - from XML)
    print("\n[Test 1] Collecting events with caching...")
    events = collect_entity_with_cache('events', collect_events_from_xml, today, output_dir)
    print(f"  → Collected {len(events)} events")
    
    # Test 2: Collect events again (should load from cache)
    print("\n[Test 2] Collecting events again (should use cache)...")
    events_cached = collect_entity_with_cache('events', collect_events_from_xml, today, output_dir)
    print(f"  → Retrieved {len(events_cached)} events")
    print(f"  → Cache working: {events is not events_cached and events == events_cached}")
    
    # Test 3: Collect KERs with caching
    print("\n[Test 3] Collecting KERs with caching...")
    kers = collect_entity_with_cache('kers', collect_kers_from_xml, today, output_dir)
    print(f"  → Collected {len(kers)} KERs")
    
    # Test 4: Collect AOPs with caching
    print("\n[Test 4] Collecting AOPs with caching...")
    aops = collect_entity_with_cache('aops', collect_aops_from_xml, today, output_dir)
    print(f"  → Collected {len(aops)} AOPs")
    
    # Test 5: Force refresh (ignore cache)
    print("\n[Test 5] Force refresh events (ignore cache)...")
    events_refreshed = collect_entity_with_cache('events', collect_events_from_xml, today, output_dir, force_refresh=True)
    print(f"  → Refreshed {len(events_refreshed)} events from XML")
    
    print("\n" + "="*60)
    print("✓ All caching tests completed successfully")
    print(f"✓ Test outputs saved to {output_dir}/")
    print("="*60 + "\n")

