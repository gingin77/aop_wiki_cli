# Run with: `uv run python -m src.parsers.parse_behl_seizure_aop_workbook`

import re

import pandas as pd
import pprint as pp

from aop_wiki_cli.parsers.parse_citations import parse_citations, process_literature_citations
from aop_wiki_cli.paths import seizure_workbook_path

TITLES_TO_FIX = {"Altered Synaptic Serotinin Release": "Altered Synaptic Serotonin Release"}
# Note: The following AOPs are listed next to harmonized KEs associated with AOP 214 and I'm not
# sure why: 
#       221, 222, 223, 225, 235, 236
HARMONIZED_AOPs = {
    'presynaptic_neuron': {
        'mie': "Activated Presynaptic Neuron",
        'combines': [215, 230]
    },
    'synaptic_serotonin': {
        'mie': "Altered Serotonin Transporter Activity",
        'combines': [214, 223] 
    }
}

# ============================================================================
# Helper functions 
# ============================================================================

def _normalize_target_family(tf):
    """Normalize a target family string using programmatic rules."""
    if pd.isna(tf):
        return tf
    tf_str = str(tf).strip()
    
    # 1. Collapse multiple spaces to single
    tf_str = re.sub(r'\s+', ' ', tf_str)
    
    # 2. Singularize trailing "Receptors" -> "Receptor", "Transporters" -> "Transporter", "Channels" -> "Channel"
    tf_str = re.sub(r'(Receptor|Transporter|Channel)s$', r'\1', tf_str)
    
    # 3. Expand trailing " R" -> " Receptor" (but not mid-word)
    tf_str = re.sub(r'\s+R$', ' Receptor', tf_str)
    
    # 4. Normalize "GABA A" -> "GABA-A" (space to hyphen)
    tf_str = re.sub(r'GABA\s+A\b', 'GABA-A', tf_str)
    
    # 5. Expand standalone "GABA-A" (without Receptor) to "GABA-A Receptor"
    if tf_str.endswith('GABA-A') and 'Receptor' not in tf_str:
        tf_str = tf_str + ' Receptor'
    
    return tf_str


def _normalize_target_family_list(tf_list):
    """Normalize a list of target family strings, removing duplicates."""
    normalized = [_normalize_target_family(tf) for tf in tf_list]
    # Remove duplicates while preserving order
    seen = set()
    result = []
    for tf in normalized:
        if tf not in seen:
            seen.add(tf)
            result.append(tf)
    return result


def _normalize_target_family_series(series):
    """Normalize a pandas Series of target family strings."""
    return series.apply(_normalize_target_family)


def _refine_df_columns(df, columns_to_keep, col_names):
    df = df[columns_to_keep]
    df = df.rename(columns=col_names)
    return df

def _refine_harmonization_df_columns(harmonization_df):
    columns_to_keep = ['AOP Wiki Terminologies', 'Standardized Term Applied for the AOP Network', 'References', 'Target Family', 'Category']
    col_names = {
        'AOP Wiki Terminologies': 'aop_wiki_terminologies', 
        'Standardized Term Applied for the AOP Network': 'harmonized_kes', 
        'Category': 'category',
        'References': 'references', 
        'Target Family': 'target_family'
    }
    harmonization_df = _refine_df_columns(harmonization_df, columns_to_keep, col_names)
    return harmonization_df

def _refine_chemicals_w_cas_df_columns(chemicals_w_cas_df):
    columns_to_keep = ['Chemical', 'CASRN', 'Positive/Negative', 'Evidence of Seizure from Literature', 'Evidence of Seizure from PubChem ']
    col_names = {
        'Chemical': 'chemical',
        'CASRN': 'casrn',
        'Positive/Negative': 'direction_of_effect',
        'Evidence of Seizure from Literature': 'literature_citation',
        'Evidence of Seizure from PubChem ': 'pubchem_evidence'
    }
    chemicals_w_cas_df = _refine_df_columns(chemicals_w_cas_df, columns_to_keep, col_names)
    return chemicals_w_cas_df

def _collect_harmonized_kes_from_df(harmonization_df):
    # Note: TITLES_TO_FIX already applied in get_seizure_dfs()
    return {
        'DROPPED' if title in {'nan', 'E'} else title
        for title in harmonization_df['harmonized_kes'].dropna()
    }

def _extract_aop_id_from_header(value_str):
    if not value_str.startswith('AOP '):
        return None

    match = re.match(r'^AOP (\d+)', value_str)
    return match.group(1) if match else None


def _is_harmonization_event_row(current_aop, value_str):
    return bool(current_aop and value_str and value_str != 'nan')


def _extract_row_values_as_str(row, columns):
    return [str(row.get(column, '')).strip() for column in columns]


def _extract_event_id_from_str(value_str):
    """Extract numerical digits from event identifier string."""
    if not value_str or value_str == 'nan':
        return None

    # Extract all digits from the string
    digits = re.search(r'\d+', str(value_str).strip())
    return digits.group(0) if digits else None

def _collect_event_mappings_orig_to_harmonized(event_mappings_orig_to_harmonized, event_id_from_sheet, harmonized_title):
    # Now, any "E" or "nan" titles will be normalized to "DROPPED" in the mapping
    harmonized_title_for_mapping = harmonized_title
    if harmonized_title_for_mapping in {'E', 'nan'}:
        harmonized_title_for_mapping = 'DROPPED'

    if event_id_from_sheet not in event_mappings_orig_to_harmonized:
        event_mappings_orig_to_harmonized[event_id_from_sheet] = set()
    event_mappings_orig_to_harmonized[event_id_from_sheet].add(harmonized_title_for_mapping)

    return event_mappings_orig_to_harmonized

def _collapse_single_title_sets(event_mappings_orig_to_harmonized):
    for event_id, harmonized_titles in event_mappings_orig_to_harmonized.items():
        if len(harmonized_titles) > 1:
            print(f"⚠️ Validation Warning: Original event ID {event_id} maps to multiple harmonized titles:")
            for title in harmonized_titles:
                print(f"  - {title}")
            continue

        event_mappings_orig_to_harmonized[event_id] = list(harmonized_titles)[0]

    return event_mappings_orig_to_harmonized


def _collect_titles_from_event_mapping(event_mappings_orig_to_harmonized):
    harmonized_kes_in_mapping = set()

    for harmonized_titles in event_mappings_orig_to_harmonized.values():
        if isinstance(harmonized_titles, set):
            titles_to_add = harmonized_titles
        else:
            titles_to_add = [harmonized_titles]

        for title in titles_to_add:
            if title != 'nan' and title != '':
                harmonized_kes_in_mapping.add(title)

    return harmonized_kes_in_mapping


def _print_harmonized_title_discrepancy(harmonized_kes_from_df, harmonized_kes_in_mapping):
    if len(harmonized_kes_from_df) == len(harmonized_kes_in_mapping):
        return

    print('Discrepancy between harmonized titles from DF and from mapping dict:')
    diff_1 = harmonized_kes_in_mapping.difference(harmonized_kes_from_df)
    diff_2 = harmonized_kes_from_df.difference(harmonized_kes_in_mapping)
    print(diff_1)
    print(diff_2)

def _run_aeid_mappings_validation_check(aeid_mappings):
    all_valid = True
    for aeid, mapping in aeid_mappings.items():
        if len(mapping["assays"]) > 1:
            all_valid = False
            print(f"⚠️ Warning: AEID {aeid} is associated with multiple assays: {mapping['assays']}. This may indicate duplicate entries or multiple relationships for the same assay.")
        elif len(mapping["target_families"]) > 1:
            all_valid = False
            print(f"⚠️ Warning: AEID {aeid} is associated with multiple target families: {mapping['target_families']}. This may indicate duplicate entries or multiple relationships for the same assay.")

    if all_valid and aeid_mappings:
        print(f"✅ Validation Check Passed: All {len(aeid_mappings)} AEIDs are associated with a single assay and target family.")

def _identify_merged_original_events(events):
    grouped_by_title = {}
    for event in events.values():
        harmonized_title = event.get('harmonized_event')
        if not harmonized_title:
            continue

        grouped_by_title.setdefault(harmonized_title, [])
        grouped_by_title[harmonized_title].append({
            'row_index': event.get('row_index'),
            'original_event_id': event.get('original_event_id'),
            'original_event_title': event.get('original_event_title')
        })

    return {
        title: event_list
        for title, event_list in grouped_by_title.items()
        if len(event_list) > 1
    }


def _unmatched_events(source_events, reference_titles):
    return {
        key: event for key, event in source_events.items()
        if event.get('harmonized_event')
        and str(event.get('harmonized_event')).strip().lower() not in reference_titles
    }


def _limit_to_expected_extra(unmatched_events, expected_extra_count):
    if len(unmatched_events) <= expected_extra_count:
        return unmatched_events

    selected_keys = sorted(unmatched_events.keys(), key=lambda value: str(value))[0:expected_extra_count]
    return {key: unmatched_events[key] for key in selected_keys}


def _parse_string_for_kes_and_aops(rel_str):
    """Parse relationship strings to extract AOP IDs and KE descriptions.

    Handles formats like:
    - "AOP 789", "AOPs 789", "AOP: 789", "AOP:789"
    - "AOPs 214 and 223" (multiple IDs with conjunctions)
    - "MIE <description>" and "KE <description>" patterns
    """
    # Handle empty/null values
    if pd.isna(rel_str) or not rel_str or str(rel_str).strip() == '':
        return {
            'aop_ids': [],
            'ke_descriptions': []
        }

    rel_str = str(rel_str).strip()

    aop_ids = []
    ke_descriptions = []

    # Pattern 1: Look for "AOP" or "AOPs" followed by digits, handling multiple IDs
    aop_prefix_match = re.search(r'AOPs?[:\s]+', rel_str, re.IGNORECASE)
    if aop_prefix_match:
        # Get the substring starting from the AOP prefix
        aop_section = rel_str[aop_prefix_match.start():]
        # Extract all numbers that appear after AOPs (handles "214 and 223")
        aop_nums = re.findall(r'\b(\d+)\b', aop_section[:100])  # Limit search to next 100 chars
        if aop_nums:
            aop_ids.extend(aop_nums)

    # Pattern 2: Extract KE/MIE descriptions
    if not aop_ids:
        # Matches "MIE <description>" or "KE <description>" patterns
        ke_pattern = r'(?:MIE|KEs?)\s+(?:the\s+)?([^,]+?)(?=\s+and\s+(?:MIE|KE)|$)'
        ke_description_matches = re.finditer(ke_pattern, rel_str, re.IGNORECASE)

        for match in ke_description_matches:
            description = match.group(1).strip()
            if description:
                ke_descriptions.append(description)

    # Remove duplicates while preserving order
    aop_ids = [int(aop_id) for aop_id in aop_ids]  # Convert to integers
    ke_descriptions = list(dict.fromkeys(ke_descriptions))

    result = {
        'aop_ids': aop_ids,
        'ke_descriptions': ke_descriptions
    }

    return result


def _parse_aop_network_relationship_columns(assays_df):
    # Add 2 new columns to the DF for parsed relationship info
    assays_df['aop_ids'] = None
    assays_df['ke_descriptions'] = None

    # Apply string parsing to each row
    parsed_data = assays_df['relationship_to_ke_in_aop_network'].apply(_parse_string_for_kes_and_aops)

    # Extract components into separate columns
    assays_df['aop_ids'] = parsed_data.apply(lambda x: x['aop_ids'])
    assays_df['ke_descriptions'] = parsed_data.apply(lambda x: x['ke_descriptions'])

    return assays_df


def _add_assay_and_tf_to_mapping(mapping, key, endpoint_name, target_family):
    """Helper to add assay and target family to a mapping dictionary."""
    if key not in mapping:
        mapping[key] = {'assays': [], 'target_families': set()}
    mapping[key]['assays'].append(endpoint_name)
    if pd.notna(target_family):
        mapping[key]['target_families'].add(target_family)

    return mapping

# ===============================================================================
# Core functions called by orchestration function, parse_seizure_aop_workbook()
# ===============================================================================

def get_seizure_dfs(excel_file):
    sheet_names = {
        "network": "Suppl1_Biovista Vizit",
        "harmonization": "Suppl2_KEs AOP Harmonization",
        "assays": "Suppl6_ICE Assays",
        "chemicals_w_cas": "Suppl4_Compiled Compounds"
    }

    # network_df = pd.read_excel(excel_file, sheet_name=sheet_names["network"])
    harmonization_df = pd.read_excel(excel_file, sheet_name=sheet_names["harmonization"], skiprows=1)
    harmonization_df = _refine_harmonization_df_columns(harmonization_df)
    
    # Apply title fixes early: strip whitespace and correct typos in harmonized_kes column
    harmonization_df['harmonized_kes'] = harmonization_df['harmonized_kes'].apply(
        lambda x: TITLES_TO_FIX.get(x.strip(), x.strip()) if pd.notna(x) else x
    )
    
    assays_df = pd.read_excel(excel_file, sheet_name=sheet_names["assays"], skiprows=1)

    chemicals_w_cas_df = pd.read_excel(excel_file, sheet_name=sheet_names["chemicals_w_cas"], skiprows=1)
    chemicals_w_cas_df = _refine_chemicals_w_cas_df_columns(chemicals_w_cas_df)
    # chemicals_w_cas_df.to_csv('chemicals_w_cas_after_df.csv', index=False)

    return harmonization_df, assays_df, chemicals_w_cas_df

def parse_harmonization_df(harmonization_df):
    # harmonized_kes_from_df is used for validation purposes to ensure we are capturing all harmonized KEs 
    # from the DF in our mapping dict, and to identify any discrepancies in the titles (after applying fixes)
    # that may indicate issues in parsing or mapping
    harmonized_kes_from_df = _collect_harmonized_kes_from_df(harmonization_df)

    event_mappings_orig_to_harmonized = {}
    harmonization_dict = {}
    current_aop = None
    current_aop_id = None
    event_index = -1

    for idx, row in harmonization_df.iterrows():
        value_str = str(row['aop_wiki_terminologies']).strip()

        aop_id = _extract_aop_id_from_header(value_str)
        if aop_id:
            current_aop = value_str
            current_aop_id = aop_id
            event_index = 0
            harmonization_dict[current_aop_id] = {}
            continue

        if _is_harmonization_event_row(current_aop, value_str):
            cols_to_extract = ['category', 'harmonized_kes', 'references', 'target_family']
            cat_col_str, harmonized_title, references, target_family = _extract_row_values_as_str(row, cols_to_extract)
            # Note: TITLES_TO_FIX already applied in get_seizure_dfs()
            event_id_from_sheet = _extract_event_id_from_str(cat_col_str)

            # Populate the harmonization_dict with enriched event data
            harmonization_dict[current_aop_id][event_id_from_sheet] = {
                'row_index': idx,
                'event_index': event_index,
                'event_id': event_id_from_sheet,
                'aop_id': current_aop_id,
                'title': value_str,
                'harmonized_event': harmonized_title,
                'references': references,
                'target_family': target_family
            }

            # Build mapping of original event IDs to harmonized titles allowing for multiple harmonized
            # titles per original event if needed (e.g. if the same KE is listed under multiple AOPs with
            # slightly different harmonized titles)
            event_mappings_orig_to_harmonized = _collect_event_mappings_orig_to_harmonized(
                event_mappings_orig_to_harmonized, 
                event_id_from_sheet, 
                harmonized_title
            )

            event_index += 1

            if value_str.upper() == "N/A, NEURODEGENERATION":
                break
    
    # Perform validation and cleanup on the event_mappings_orig_to_harmonized to ensure we have a clean mapping of 
    # each original event ID to a single harmonized title, and to reveal any discrepancies that might have been present
    # in the input data.
    event_mappings_orig_to_harmonized = _collapse_single_title_sets(event_mappings_orig_to_harmonized)
    harmonized_kes_in_mapping = _collect_titles_from_event_mapping(event_mappings_orig_to_harmonized)
    _print_harmonized_title_discrepancy(harmonized_kes_from_df, harmonized_kes_in_mapping)

    return harmonization_dict, event_mappings_orig_to_harmonized, harmonized_kes_from_df

def extract_harmonized_aops(harmonization_dict):
    aop_to_harmonized_events_dict = {}
    for aop_id, aop_data in harmonization_dict.items():
        aop_to_harmonized_events_dict[aop_id] = {}
        for event_id, event_data in aop_data.items():
            row_index = event_data.get('row_index')
            harmonized_title = event_data.get('harmonized_event')

            # Only include events that have a valid harmonized title (exclude empty, 'nan', or 'E' which indicates excluded)
            if harmonized_title and harmonized_title != 'nan' and harmonized_title != 'E':
                aop_to_harmonized_events_dict[aop_id][row_index] = {
                    'row_index': event_data.get('row_index'),
                    'harmonized_event': harmonized_title,
                    'original_event_id': event_id,
                    'original_event_title': event_data.get('title')
                }
    
    return aop_to_harmonized_events_dict

def validate_harmonized_aops(aop_to_harmonized_events_dict):
    """
    Perform validation checks on the harmonized Events in the harmonized AOPs
    """
    # Validation step to check for any missing or empty harmonized event titles
    validated_aop_to_harmonized_events_dict = {}

    for details in HARMONIZED_AOPs.values():
        mie_title = details['mie']
        aops_to_combine = details['combines']
        aop_one_id = aops_to_combine[0]       
        aop_two_id = aops_to_combine[1]

        aop_one_events = aop_to_harmonized_events_dict.get(str(aop_one_id), {})
        aop_two_events = aop_to_harmonized_events_dict.get(str(aop_two_id), {})

        # Duplicate harmonized-title check - highlights multiple original events mapping to the same harmonized title
        aop_one_merged_events = _identify_merged_original_events(aop_one_events)
        aop_two_merged_events = _identify_merged_original_events(aop_two_events)
        if aop_one_merged_events:
            validated_aop_to_harmonized_events_dict.setdefault('merged_original_events', {})
            validated_aop_to_harmonized_events_dict['merged_original_events'][aop_one_id] = aop_one_merged_events
            print(f"‼️ Validation Alert: AOP {aop_one_id} has 2 different source events:")
            for title, events in aop_one_merged_events.items():
                print(f"  - '{title}' mapped from {len(events)} original events:")
                for ev in events:
                    print(f"      Event ID {ev['original_event_id']}: {ev['original_event_title']}")
                if title == 'Activated/Inactivated 5-HT R':
                    print(f"This harmonized title has been noted for combining 2 5-HT receptor activity Events.")
        if aop_two_merged_events:
            validated_aop_to_harmonized_events_dict.setdefault('merged_original_events', {})
            validated_aop_to_harmonized_events_dict['merged_original_events'][aop_two_id] = aop_two_merged_events
            print(f"‼️ Validation Alert: AOP {aop_two_id} has 2 different source events:")
            for title, events in aop_two_merged_events.items():
                print(f"  - '{title}' mapped from {len(events)} original events:")
                for ev in events:
                    print(f"      Event ID {ev['original_event_id']}")

        # MIE title check - verify expected MIE title exists in each AOP's harmonized event list
        mie_title_normalized = mie_title.strip().lower()
        aop_one_titles_normalized = {str(event.get('harmonized_event')).strip().lower() for event in aop_one_events.values() if event.get('harmonized_event')}
        aop_two_titles_normalized = {str(event.get('harmonized_event')).strip().lower() for event in aop_two_events.values() if event.get('harmonized_event')}
        
        if not aop_one_events or not aop_two_events:
            print(f"⚠️ Validation Warning: Harmonized events are missing for one or both AOPs, {aop_one_id} and {aop_two_id}.")
        else:
            aop_one_has_mie = mie_title_normalized in aop_one_titles_normalized
            aop_two_has_mie = mie_title_normalized in aop_two_titles_normalized

            if aop_one_has_mie and aop_two_has_mie:
                print(f"✅ Validation Successful: MIE title '{mie_title}' is present in both AOP {aop_one_id} and AOP {aop_two_id}.")
            else:
                if not aop_one_has_mie:
                    print(f"⚠️ Validation Warning: Expected MIE title '{mie_title}' was not found in AOP {aop_one_id} harmonized events.")
                if not aop_two_has_mie:
                    print(f"⚠️ Validation Warning: Expected MIE title '{mie_title}' was not found in AOP {aop_two_id} harmonized events.")


        # Length check - ensure both AOPs have the same number of events
        if len(aop_one_titles_normalized) != len(aop_two_titles_normalized):
            print(f"⚠️ Validation Warning: AOP {aop_one_id} has {len(aop_one_titles_normalized)} events, while AOP {aop_two_id} has {len(aop_two_titles_normalized)} events.")
            validated_aop_to_harmonized_events_dict.setdefault('unique_event_mismatches', {})
            validated_aop_to_harmonized_events_dict['unique_event_mismatches'][f"{aop_one_id} vs {aop_two_id}"] = {
                'aop_one_event_count': len(aop_one_titles_normalized),
                'aop_two_event_count': len(aop_two_titles_normalized)
            }

        # Only evaluate "extra" events on the longer side
        if len(aop_one_events) > len(aop_two_events):
            longer_id, shorter_id = aop_one_id, aop_two_id
            longer_events = aop_one_events
            shorter_titles = aop_two_titles_normalized
        elif len(aop_two_events) > len(aop_one_events):
            longer_id, shorter_id = aop_two_id, aop_one_id
            longer_events = aop_two_events
            shorter_titles = aop_one_titles_normalized
        else:
            continue
        
        expected_extra_count = abs(len(aop_one_events) - len(aop_two_events))
        unmatched_in_longer = _unmatched_events(longer_events, shorter_titles)
        extra_events = _limit_to_expected_extra(unmatched_in_longer, expected_extra_count)

        if extra_events:
            validated_aop_to_harmonized_events_dict.setdefault('extra_events', {})
            validated_aop_to_harmonized_events_dict['extra_events'][longer_id] = extra_events
            print(f"⚠️ Validation Warning: AOP {longer_id} contains harmonized events not found in AOP {shorter_id}.")
            print('The extra events are:')
            for event in extra_events.values():
                print(f"  - {event.get('harmonized_event')} (original event ID: {event.get('original_event_id')}, original title: {event.get('original_event_title')})")

    return validated_aop_to_harmonized_events_dict


def parse_assay_df(assays_df):
    # Collect list from sheet, separate from DF content before dropping columns and renaming for easier parsing and mapping
    raw_target_families = assays_df['Summary of Target Families'].dropna().unique().tolist()[0:27]
    target_families = _normalize_target_family_list(raw_target_families)

    all_columns = assays_df.columns.tolist()
    columns_to_keep = all_columns[0:11]
    col_names = {
        'aeid': "aeid",
        'AssayEndpointName': "endpoint_name",
        'ModeofAction': "moa",
        'MechanisticTarget': "mechanistic_target",
        'MT_NCIm_term': "mt_ncim_term",
        'MT_NCIm_term_ID': "mt_ncim_term_id",
        'Target Families (General)': "target_families_general",
        'assay_component_desc': "assay_component_desc",
        'assay_component_target_desc': "assay_component_target_desc",
        'Relationship to KE in AOP network': "relationship_to_ke_in_aop_network",
        'Species': "species"
    }
    assays_df = assays_df[columns_to_keep]
    assays_df = assays_df.rename(columns=col_names)

    assays_df['target_families_general'] = _normalize_target_family_series(assays_df['target_families_general'])

    assays_df = _parse_aop_network_relationship_columns(assays_df)

    return assays_df, target_families

def extract_mappings_from_assays_df(assays_df):
    """Create mappings for AOP IDs and KE descriptions to assays and target families."""
    aeid_mappings = {}
    aop_id_mapping = {}
    ke_description_mapping = {}
    
    for _, row in assays_df.iterrows():
        endpoint_name = row['endpoint_name']
        target_family = row['target_families_general']
        ke_description = row['ke_descriptions']
        aeid = row['aeid']

        # Map by AEID (unique assay identifier) - this will be the most direct way to link to Comptox data, which also uses AEIDs
        if aeid not in aeid_mappings:
            aeid_mappings[aeid] = {'assays': [], 'target_families': set()}

        aeid_mappings[aeid]['assays'].append(endpoint_name)
        if pd.notna(target_family):
            aeid_mappings[aeid]['target_families'].add(target_family)

        # Map by AOP ID
        for aop_id in row['aop_ids']:
            aop_id_mapping = _add_assay_and_tf_to_mapping(aop_id_mapping, aop_id, endpoint_name, target_family)
        
        # Map by KE description
        for ke_desc in ke_description:
            ke_description_mapping = _add_assay_and_tf_to_mapping(ke_description_mapping, ke_desc, endpoint_name, target_family)
    
    _run_aeid_mappings_validation_check(aeid_mappings)
    return aeid_mappings, aop_id_mapping, ke_description_mapping

def extract_target_family_lists(target_families, harmonization_df, assays_df):
    """
    Comprehensive set analysis for Target Families across three sources:
    1) Standalone list from Behl workbook
    2) Assays DF (target_families_general column)
    3) Harmonization DF (target_family column)
    """
    # ==========================================================================
    # BASE SETS - one for each source (normalized via TARGET_FAMILIES_TO_FIX)
    # ==========================================================================
    standalone_set = set(_normalize_target_family_list(target_families))
    assays_set = set(_normalize_target_family_series(assays_df['target_families_general']).dropna().unique())
    harmonization_set = set(_normalize_target_family_series(harmonization_df['target_family']).dropna().unique())

    # ==========================================================================
    # UNION SETS - combinations across sources
    # ==========================================================================
    all_sources_union = standalone_set | assays_set | harmonization_set
    both_dfs_union = assays_set | harmonization_set

    # ==========================================================================
    # INTERSECTION SETS - items appearing in multiple sources
    # ==========================================================================
    in_all_three = standalone_set & assays_set & harmonization_set
    in_standalone_and_assays = standalone_set & assays_set
    in_standalone_and_harmonization = standalone_set & harmonization_set
    in_assays_and_harmonization = assays_set & harmonization_set

    # ==========================================================================
    # EXCLUSIVE SETS - items appearing in ONLY one source
    # ==========================================================================
    only_in_standalone = standalone_set - assays_set - harmonization_set
    only_in_assays = assays_set - standalone_set - harmonization_set
    only_in_harmonization = harmonization_set - standalone_set - assays_set

    # ==========================================================================
    # COVERAGE / GAP ANALYSIS - what's missing from each source
    # ==========================================================================
    standalone_not_in_assays_or_harmonization = standalone_set - both_dfs_union
    standalone_not_in_assays = standalone_set - assays_set
    standalone_not_in_harmonization = standalone_set - harmonization_set
    assays_not_in_standalone = assays_set - standalone_set
    harmonization_not_in_standalone = harmonization_set - standalone_set

    # ==========================================================================
    # PRINT SUMMARY
    # ==========================================================================
    print("\n Target Family Set Analysis:")
    print("  BASE COUNTS:")
    print(f"    - Standalone list: {len(standalone_set)}")
    print(f"    - Assays DF: {len(assays_set)}")
    print(f"    - Harmonization DF: {len(harmonization_set)}")
    print(f"    - All sources combined: {len(all_sources_union)}")
    print("  INTERSECTIONS:")
    print(f"    - In all three sources: {len(in_all_three)}")
    print(f"    - In standalone & assays: {len(in_standalone_and_assays)}")
    print(f"    - In standalone & harmonization: {len(in_standalone_and_harmonization)}")
    print(f"    - In assays & harmonization: {len(in_assays_and_harmonization)}")
    print("  EXCLUSIVE TO ONE SOURCE:")
    print(f"    - Only in standalone: {len(only_in_standalone)}")
    print(f"    - Only in assays: {len(only_in_assays)}")
    print(f"    - Only in harmonization: {len(only_in_harmonization)}")
    print("  COVERAGE GAPS:")
    print(f"    - In standalone but not in assays or harmonization: {len(standalone_not_in_assays_or_harmonization)}")
    print(f"    - In assays but not in standalone: {len(assays_not_in_standalone)}")
    print(f"    - In harmonization but not in standalone: {len(harmonization_not_in_standalone)}")
    print("\n  All Target Families collected across all three sources:")
    for tf in all_sources_union:
        print(f"    - {tf}")

    print("\n  Target Families ONLY in standalone list:")
    for tf in only_in_standalone:
        print(f"    - {tf}")

    return {
        # Base sets
        "standalone_set": list(standalone_set),
        "assays_set": list(assays_set),
        "harmonization_set": list(harmonization_set),
        # Unions
        "all_sources_union": list(all_sources_union),
        "both_dfs_union": list(both_dfs_union),
        # Intersections
        "in_all_three": list(in_all_three),
        "in_standalone_and_assays": list(in_standalone_and_assays),
        "in_standalone_and_harmonization": list(in_standalone_and_harmonization),
        "in_assays_and_harmonization": list(in_assays_and_harmonization),
        # Exclusive to one source
        "only_in_standalone": list(only_in_standalone),
        "only_in_assays": list(only_in_assays),
        "only_in_harmonization": list(only_in_harmonization),
        # Coverage gaps
        "standalone_not_in_assays": list(standalone_not_in_assays),
        "standalone_not_in_harmonization": list(standalone_not_in_harmonization),
        "assays_not_in_standalone": list(assays_not_in_standalone),
        "harmonization_not_in_standalone": list(harmonization_not_in_standalone),
    }

def map_target_families(target_families, harmonization_df, assays_df):
    """
    Create a mapping of events to target families by cross-referencing the harmonization and assay data.

    Returns:
    {
        <target_family>: {
            'h_events': [list of event IDs from harmonization_df associated with this family],
            'assays': [list of assay endpoint names from assays_df associated with this family]
        },
    }
    """
    tf_to_events_mapping = {}
    for tf in target_families:
        tf_to_events_mapping[tf] = {
            'h_events': [],
            'assays': []
        }
        # Capture events from harmonization_df that match this target family
        harmonized_event_mappings = harmonization_df[harmonization_df['target_family'].str.lower() == tf.lower()]['harmonized_kes'].dropna().unique().tolist()
        tf_to_events_mapping[tf]['h_events'] = harmonized_event_mappings

        # Find all assays under assays_df["endpoint_name"] that match this target family
        matching_assays = assays_df[assays_df['target_families_general'].str.lower() == tf.lower()]['endpoint_name'].tolist()
        tf_to_events_mapping[tf]['assays'] = matching_assays

    return tf_to_events_mapping

def normalize_chemicals_df(chemicals_df):
    """
    Normalize chemical data and parse literature citations.
    
    Each chemical gets:
    - Normalized direction_of_effect
    - Parsed_citations: list of citation dicts as returned by parse_citations(...),
      typically including keys like 'citation_type' and 'page' when available.
    """
    chemicals_list_of_dicts = chemicals_df.to_dict(orient='records')
    print(f"Normalizing chemical data for {len(chemicals_list_of_dicts)} chemicals with CASRNs...")
    chemicals_by_casrn = {}
    literature_cited_set = set()  # For summary analysis
    
    for chem in chemicals_list_of_dicts:
        refined_chem = chem.copy()
        casrn = chem.get('casrn')
        
        # Normalize direction_of_effect
        direction = chem.get('direction_of_effect')
        if isinstance(direction, str) and direction.lower() in {'positive', 'negative'}:
            refined_chem['direction_of_effect'] = direction.strip()
        elif isinstance(direction, str) and direction.lower() not in {'positive', 'negative'}:
            print(f"⚠️ Warning: Found unexpected value in 'direction_of_effect' column: {direction} for CASRN: {casrn}")
        else:
            print(f"⚠️ Warning: Missing or invalid 'direction_of_effect' for chemical with CASRN {casrn}. Value: {direction}")

        # Parse literature citation into structured format (may be multiple citations)
        cited_literature_string = chem.get('literature_citation', None)
        if isinstance(cited_literature_string, str):
            literature_cited_set.add(cited_literature_string.strip())
            refined_chem['parsed_citations'] = parse_citations(cited_literature_string)
        else:
            print(f"⚠️ Warning: Missing or invalid 'literature_citation' for chemical with CASRN {casrn}. Value: {cited_literature_string}")
            refined_chem['parsed_citations'] = []
        refined_chem.pop('literature_citation', None)  # Remove original string to avoid confusion

        # Normalize the data from pubchem_evidence, Evidence of Seizure from PubChem 
        pubchem_evidence_raw = chem.get('pubchem_evidence')
        normalized_pubchem = None
        if isinstance(pubchem_evidence_raw, str):
            normalized_pubchem = pubchem_evidence_raw.strip().upper()
        if normalized_pubchem and "Y" in normalized_pubchem:
            refined_chem['pubchem_evidence'] = "Yes"
        elif normalized_pubchem in {"N", "NO"}:
            refined_chem['pubchem_evidence'] = "No"
        else:
            # Reserve 'Unknown' for missing, blank, or unparseable values
            refined_chem['pubchem_evidence'] = "Unknown"
        
        if casrn in chemicals_by_casrn:
            print(f"⚠️ Warning: Duplicate CASRN found in chemicals data: {casrn}. Overwriting previous entry.")
        chemicals_by_casrn[casrn] = refined_chem
    
    print("\n" + "="*60)
    print("Summary of WIP literature citation analysis using citations from chemicals data:")
    print("="*60)

    # Call function to summarize citation patterns. Used during development to understand 
    # the diversity of citation formats and sources, and to identify any common patterns.
    process_literature_citations(literature_cited_set)

    return chemicals_by_casrn


# ============================================================================
# Main orchestration function 
# ============================================================================

def parse_seizure_aop_workbook(seizure_workbook_path):
    """
    Main function to parse the seizure AOP workbook and extract relevant mappings and data.
    
    Goal is to create harmonized lists of KEs, AOPs, assays, and target families that are mapped
    to each other as much as possible, to enable analysis of KE coverage by assays and linking of 
    chemical test results to KEs and AOPs.

    Direct mappings from assays to events or aops:
    1) KEs mentioned in the assays_df[relationship_to_ke_in_aop_network] -> `ke_description_mapping`
    2) AOP IDs mentioned in the assays_df[relationship_to_ke_in_aop_network] -> `aop_id_mapping`
        - This only includes 2 AOPs and one biological target family, Monoamine Oxidase. The
        direct link between the 2 open for adoption serotonin-seizure PWs is not clear to be at the
        KE level, even though a number of papers on MOAs and serotonin are available.

    Indirect mappings between assays and events or AOPs via target families:
    3) Target families mentioned in the harmonization_df and assays_df -> `events_to_target_family_mapping`,
    ...
    """
    excel_file = pd.ExcelFile(seizure_workbook_path)
    harmonization_df, raw_assays_df, chemicals_w_cas_df = get_seizure_dfs(excel_file)

    chemicals_by_casrn = normalize_chemicals_df(chemicals_w_cas_df)
    
    harmonized_kes = [x for x in harmonization_df['harmonized_kes'].dropna().unique().tolist() if x != "E"]  # Exclude "E" which indicates excluded KEs in the harmonization sheet

    print("\n" + "="*60)
    print("EXTRACTING HARMONIZED KEs AND AOPs:")
    print("="*60)
    harmonization_dict, event_mappings_orig_to_harmonized, harmonized_kes_from_df = parse_harmonization_df(harmonization_df)
    aop_to_harmonized_events_dict = extract_harmonized_aops(harmonization_dict)
    validated_aop_to_harmonized_events_dict = validate_harmonized_aops(aop_to_harmonized_events_dict)
    harmonized_kes = [x for x in harmonized_kes_from_df if x != 'DROPPED']

    print("\n" + "="*60)
    print("EXTRACTING ASSAYS, TARGET FAMILIES, AND EVENT DESCRIPTIONS:")
    print("="*60)
    # Assays DF + biological target family list from Behl
    assays_df, stand_alone_target_families = parse_assay_df(raw_assays_df)
    list_of_assay_dicts = assays_df.to_dict(orient='records')

    # Direct mappings between aops or event > assays & biological target families +
    # From target families to assays & events
    aeid_mappings, aop_id_to_assays_and_target_families, ke_description_to_assays_and_target_families = extract_mappings_from_assays_df(assays_df)

    dict_of_target_family_lists = extract_target_family_lists(stand_alone_target_families, harmonization_df, assays_df)
    target_families_to_h_events_and_assays = map_target_families(stand_alone_target_families, harmonization_df, assays_df)

    
    return {
        'ready_for_emod': {
            'data': {
                'biological_target_families': stand_alone_target_families,
                'harmonized_kes': harmonized_kes,
                'event_mappings_orig_to_harmonized': event_mappings_orig_to_harmonized,
                'aop_to_harmonized_events_dict': aop_to_harmonized_events_dict,
                'assays_by_aeid': aeid_mappings,
                'chemicals_by_casrn_with_seizure_details': chemicals_by_casrn
            },
            'export_types': ['json','xlsx']
        },
        'for_xlsx_export_only': {
            'data': {
                'harmonized_aop_validation_results': validated_aop_to_harmonized_events_dict
            },
            'export_types': ['xlsx']
        },
        'mappings_generated': {
            'data': {
                'ke_description_mappings_from_assays_df': ke_description_to_assays_and_target_families,     # Fuzzy match KE descriptions to harmonized KE titles
                'aop_id_to_assays_and_target_families': aop_id_to_assays_and_target_families,
                'dict_of_target_family_lists': dict_of_target_family_lists,
            },
            'export_types': []
        },
        'to_analyze': {
            'data': {
                'harmonization_dict': harmonization_dict,       # Enriched with content from AOP-Wiki XML
                'assays': list_of_assay_dicts,                  # Could be compared against Comptox data, if time allows
                'target_families_to_h_events_and_assays': target_families_to_h_events_and_assays,
            },
            'export_types': []
        },
        'enriched': {
            'data': {},
            'export_types': ['json','xlsx']
        },
    }



# ============================================================================
# Demo/Testing
# ============================================================================

if __name__ == '__main__':
    workbook_path = seizure_workbook_path()
    seizure_content = parse_seizure_aop_workbook(workbook_path)
