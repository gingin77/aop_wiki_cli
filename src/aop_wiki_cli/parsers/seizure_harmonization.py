"""Shared parsing of the Behl seizure workbook's harmonization sheet.

This is the small, reusable core of the seizure workbook parser that the
library still needs: ``read_behl_seizure_aop_ids`` lets the general
``search-within-aops`` command add the Behl seizure AOP IDs via its
``--behl-seizure-aops`` flag without pulling in the full single-use seizure
pipeline (assays, target families, chemicals, citations), which lives in the
standalone seizure runner outside the package.

The full seizure runner imports ``get_seizure_dfs``, ``parse_harmonization_df``
and ``extract_harmonized_aops`` from here too, so the harmonization-sheet
parsing has a single home. See issue #28.
"""

import re

import pandas as pd

TITLES_TO_FIX = {"Altered Synaptic Serotinin Release": "Altered Synaptic Serotonin Release"}


# ---------------------------------------------------------------------------
# Column refinement
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Harmonization-row helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Sheet readers and harmonization parse
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public helper for the general search-within-aops command
# ---------------------------------------------------------------------------

def read_behl_seizure_aop_ids(workbook_path):
    """Return the Behl seizure AOP IDs as a sorted list of strings.

    Reads only the harmonization sheet of the Behl supplementary workbook and
    returns the AOP IDs that have at least one harmonized key event — the same
    IDs the full seizure pipeline exposes as
    ``['ready_for_emod']['data']['aop_to_harmonized_events_dict']`` — without
    parsing the assay, target-family or chemical sheets.
    """
    excel_file = pd.ExcelFile(workbook_path)
    harmonization_df, _assays_df, _chemicals_df = get_seizure_dfs(excel_file)
    harmonization_dict, _mappings, _harmonized_kes = parse_harmonization_df(harmonization_df)
    aop_to_harmonized_events_dict = extract_harmonized_aops(harmonization_dict)
    return sorted(aop_to_harmonized_events_dict, key=int)
