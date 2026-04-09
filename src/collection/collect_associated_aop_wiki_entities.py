import logging
import os
from datetime import date
import pprint as pp

from src.collection import collect_xml_data
from src.parsers import collect_events_from_xml, collect_aops_from_xml
from src.utilities import write_dict_to_json, set_up_logger
from src.visualization import (
    TraversalContext,
    traverse_path,
    _restructure_with_convergence,
    create_ordered_events_visual
)
from src.data_export import write_csv, AOP_DETAIL_FIELDS, EVENT_DETAIL_FIELDS

TODAY = date.today()
OUTPUT_DIR = 'outputs'
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================================
# DATA COLLECTION FUNCTIONS - Filtering and gathering entities
# ============================================================================


def identify_skipped_ke_ids(event_title_filter, event_ft_filter, ke_dict):
    """Identify KE IDs from input filters that are not present in the KE data."""
    title_set = set(event_title_filter) if event_title_filter else set()
    ft_set = set(event_ft_filter) if event_ft_filter else set()
    all_ke_ids = title_set | ft_set
    skipped_ke_ids = []
    for ke_id in all_ke_ids:
        if str(ke_id) not in ke_dict:
            skipped_ke_ids.append(ke_id)
            print(f"Warning: KE ID {ke_id} not found in collected KE data.")
    return skipped_ke_ids

def collect_filtered_events(event_title_filter, event_ft_filter, associated_event_ids, ke_dict, input_term):
    """Filter key events based on title, full-text search, and associated events criteria."""
    print(f"Count associated_event_ids: {len(associated_event_ids)}")
    event_title_filter = event_title_filter or []
    event_ft_filter = event_ft_filter or []
    filtered_ke_dict = {}
    
    for ke_id, ke_info in ke_dict.items():
        # Determine if this event should be included
        ke_id_int = int(ke_id)
        is_title_match = ke_id_int in event_title_filter
        is_ft_match = ke_id_int in event_ft_filter
        is_associated = ke_id_int in associated_event_ids
        
        # Skip events that don't match any criteria
        if not (is_title_match or is_ft_match or is_associated):
            continue
        
        # Create event dict with appropriate source
        init_dict = ke_info.copy()
        if is_title_match:
            init_dict["source"] = "title_search"
        elif is_ft_match:
            init_dict["source"] = "full_text_search"
        elif is_associated:
            init_dict["source"] = "associated_event"
        else:
            init_dict["source"] = "not_selected"
        
        # Add fields_with_input_term for input events
        if (is_title_match or is_ft_match) and input_term is not None:
            fields_with_input_term = []
            for field, value in ke_info.items():
                if isinstance(value, str) and input_term.lower() in value.lower():
                    fields_with_input_term.append(field)
            init_dict['fields_with_input_term'] = fields_with_input_term
        
        filtered_ke_dict[ke_id] = init_dict

    return filtered_ke_dict

def collect_aops_for_input_event_ids(input_event_ids, events_from_xml):
    """Get AOPs associated with the given event IDs."""
    aop_ids = set()
    for event_id in input_event_ids:
        event = events_from_xml.get(str(event_id))
        if event is None:
            print(f"Warning: Event ID {event_id} not found in collected event data.")
        else:
            aop_ids.update(event.get('aop_ids', []))
    return list(aop_ids)

def add_event(connected_events, all_events, target_event_ids, event_id, title=None, ker_id=None, ker_adjacency_types=None):
    """Add or update event in connected_events with optional KER linkage.
    
    Args:
        connected_events: Dict accumulator mapping event_id -> event record.
        all_events: Full event metadata dict from XML parsing.
        target_event_ids: Set of input event IDs (used to flag is_input_event).
        event_id: The event ID to add or update.
        title: Optional title (falls back to all_events lookup).
        ker_id: Optional KER ID to link.
        ker_adjacency_types: Optional list of adjacency types from the KER.
    
    Returns:
        The mutated connected_events dict.
    """
    event_id = str(event_id).strip()
    if not event_id:
        return connected_events

    resolved_title = title or all_events.get(event_id, {}).get("title")
    if not resolved_title:
        return connected_events

    if event_id not in connected_events:
        connected_events[event_id] = {
            "event_id": event_id,
            "title": resolved_title,
            "is_input_event": event_id in target_event_ids,
            "linked_ker_ids": set(),
            "linked_ker_adjacency_types": set(),
        }

    if ker_id is not None:
        connected_events[event_id]["linked_ker_ids"].add(str(ker_id))
    if ker_adjacency_types:
        connected_events[event_id]["linked_ker_adjacency_types"].update(
            str(adj).strip() for adj in ker_adjacency_types if str(adj).strip()
        )

    return connected_events

def collect_events_from_ker_pairs_for_input_event_id(event_ids_for_ker_pairs, all_kers, all_events, preference_for_events_in_ker=None):
    """Collect event records connected to input event IDs through KER pairs.

    For each input event ID, it finds KER-linked upstream/downstream events and
    returns enriched event records including:
    - event_id
    - title (full event title)

    Notes:
    - `linked_ker_adjacency_types` is sourced from `all_kers[ker_id]['adjacency_types']`,
      which is parsed from AOP relationship adjacency metadata in XML.
    - Output is sorted to prioritize adjacent KER-linked events.
    """
    # -------------------------------------------------------------------------
    # Step 1: Initialize target event IDs and accumulator
    # -------------------------------------------------------------------------
    target_event_ids = {
        str(event_id).strip()
        for event_id in (event_ids_for_ker_pairs or [])
        if str(event_id).strip()
    }

    # Accumulator: event_id -> enriched event dict (uses sets for deduplication)
    connected_events = {}

    # -------------------------------------------------------------------------
    # Step 2: For each input event, find all KERs where it appears as
    #         upstream or downstream, and collect endpoints based on preference
    # -------------------------------------------------------------------------
    for event_id in target_event_ids:
        event_data = all_events.get(event_id)
        # Include the input event itself in the output, even if it has no KER links
        connected_events = add_event(
            connected_events, all_events, target_event_ids,
            event_id, title=event_data.get("title") if event_data else None
        )

        for ker_id, ker_data in all_kers.items():
            upstream_ke = ker_data.get("upstream_ke", {})
            downstream_ke = ker_data.get("downstream_ke", {})
            ker_adjacency_types = ker_data.get("adjacency_types", [])

            upstream_id = str(upstream_ke.get("id", "")).strip()
            downstream_id = str(downstream_ke.get("id", "")).strip()

            input_is_upstream_in_ker = (event_id == upstream_id)
            input_is_downstream_in_ker = (event_id == downstream_id)

            if not (input_is_upstream_in_ker or input_is_downstream_in_ker):
                continue

            # Decide which connected events to collect based on preference:
            #   - "upstream": collect events upstream of input (input must be downstream in KER)
            #   - "downstream": collect events downstream of input (input must be upstream in KER)
            #   - None: collect both directions
            collect_upstream = (
                preference_for_events_in_ker is None or
                (preference_for_events_in_ker == "upstream" and input_is_downstream_in_ker)
            )
            collect_downstream = (
                preference_for_events_in_ker is None or
                (preference_for_events_in_ker == "downstream" and input_is_upstream_in_ker)
            )

            # Always update input event's KER linkage metadata
            connected_events = add_event(
                connected_events, all_events, target_event_ids,
                event_id, ker_id=ker_id, ker_adjacency_types=ker_adjacency_types
            )
            
            if collect_upstream and not input_is_upstream_in_ker:
                connected_events = add_event(
                    connected_events, all_events, target_event_ids,
                    upstream_id, title=upstream_ke.get("title"), ker_id=ker_id, ker_adjacency_types=ker_adjacency_types
                )

            if collect_downstream and not input_is_downstream_in_ker:
                connected_events = add_event(
                    connected_events, all_events, target_event_ids,
                    downstream_id, title=downstream_ke.get("title"), ker_id=ker_id, ker_adjacency_types=ker_adjacency_types
                )

    # -------------------------------------------------------------------------
    # Step 3: Convert sets to sorted lists and sort output for downstream use
    # -------------------------------------------------------------------------
    def _adjacency_priority(event):
        """Sort key: adjacent=0, non-adjacent=1, unknown=2."""
        adjacency_values = {adj.lower() for adj in event.get("linked_ker_adjacency_types", [])}
        if "adjacent" in adjacency_values:
            return 0
        if "non-adjacent" in adjacency_values:
            return 1
        return 2

    output = []
    for event in connected_events.values():
        output.append({
            **event,
            "linked_ker_ids": sorted(event["linked_ker_ids"]),
            "linked_ker_adjacency_types": sorted(event["linked_ker_adjacency_types"]),
        })

    # Sort: adjacent first, then by number of KER links (descending), then by event ID
    return sorted(
        output,
        key=lambda x: (
            _adjacency_priority(x),
            -len(x.get("linked_ker_ids", [])),
            int(x["event_id"]) if str(x["event_id"]).isdigit() else str(x["event_id"]),
        ),
    )

def filter_aop_dict_by_aop_ids(aop_dict_from_xml, aop_ids_from_xml, input_event_ids):
    """Keep only AOPs that are in aop_ids_from_xml"""
    filtered_aop_dict_from_xml = {}
    for aop_id, aop_info in aop_dict_from_xml.items():
        if aop_id in aop_ids_from_xml:
            filtered_aop_dict_from_xml[aop_id] = {
                **aop_info,
                "detected_as_aop_network": False,
                "has_internal_loops": False,
                "missing_mie": False,
                "source_event_ids": ', '.join(input_event_ids),
            }
    print(f"Filtered AOPs to {len(filtered_aop_dict_from_xml)} based on input event IDs.")
   
    return filtered_aop_dict_from_xml

def get_associated_events(aop_ids, events_by_aop_dict):
    associated_event_ids = set()
    for aop_id in aop_ids:
        if str(aop_id) in events_by_aop_dict:
            events = events_by_aop_dict[str(aop_id)]
            aop_associated_event_ids = [ev["event"] for ev in events]
            associated_event_ids.update(aop_associated_event_ids)

    return list(associated_event_ids)

def get_aops_from_filtered_kes(ke_ids, events_by_event_dict, aop_dict_from_xml):
    """Get AOPs that contain the filtered key events."""
    aop_ids_from_events = set()
    aops_and_source_events = {}
    for ke_id in ke_ids:
        if ke_id in events_by_event_dict:
            for event in events_by_event_dict[ke_id]:
                aop_ids_from_events.add(event['aop'])
                if event['aop'] not in aops_and_source_events:
                    aops_and_source_events[event['aop']] = []
                aops_and_source_events[event['aop']].append(ke_id)
    
    aop_ids_from_events = [str(aop_id) for aop_id in aop_ids_from_events]
    filtered_aop_dict_from_xml = {}
    for aop_id in aop_ids_from_events:
        if aop_id in aop_dict_from_xml:
            filtered_aop_dict_from_xml[aop_id] = {
                "detected_as_aop_network": False,
                "has_internal_loops": False,
                "missing_mie": False,
                "source_event_ids": ', '.join(aops_and_source_events[int(aop_id)]),
                **aop_dict_from_xml[aop_id]
            }
            
    return filtered_aop_dict_from_xml

def add_aop_info_to_events(events_by_event_dict, aop_dict_from_xml):
    """Add OECD status info from AOPs to input events."""
    new_events_dict = {}
    for event_id, event_list in events_by_event_dict.items():
        new_events_dict[event_id] = {}
        new_events_dict[event_id]["oecd_statuses"] = set()
        new_events_dict[event_id]["aops"] = []
        for event in event_list:
            event_to_pass = event.copy()
            aop_id = str(event['aop'])
            oecd_status = None
            license = None
            if aop_id in aop_dict_from_xml:
                oecd_status = aop_dict_from_xml[aop_id].get('oecd_status', None)
                license = aop_dict_from_xml[aop_id].get('wiki_license', None)
            new_events_dict[event_id]["oecd_statuses"].add(oecd_status)
            event_to_pass['aop_oecd_status'] = oecd_status
            event_to_pass['aop_wiki_license'] = license
            new_events_dict[event_id]["aops"].append(event_to_pass)

    return new_events_dict


def add_event_and_ker_details_to_aops(filtered_aop_dict_from_xml, event_dict, kers_dict):
    for aop_id, aop_info in filtered_aop_dict_from_xml.items():
        filtered_aop_dict_from_xml[str(aop_id)]['events'] = {}
        
        # Add event details
        for ke_id in aop_info['event_ids']:
            events = event_dict[str(ke_id)]
            for event in events:
                if event['aop'] == int(aop_id):
                    event_type = event.get('event_type', 'unknown')
                    event_title = event.get('event_title', 'unknown')
                    filtered_aop_dict_from_xml[aop_id]['events'][ke_id] = {
                        'event_id': int(ke_id),
                        'type': event_type,
                        'title': event_title
                    }
        
        # Add KER details (upstream/downstream relationships)
        for ker_id in aop_info['kers']:
            for ker_from_dict in kers_dict[ker_id]:
                if ker_from_dict["aop"] == int(aop_id):
                    filtered_aop_dict_from_xml[aop_id]['kers'][ker_id]['upstream_event'] = ker_from_dict['upstream_event']
                    filtered_aop_dict_from_xml[aop_id]['kers'][ker_id]['downstream_event'] = ker_from_dict['downstream_event']
    
    
    return filtered_aop_dict_from_xml

# ============================================================================
# GRAPH STRUCTURE FUNCTIONS - Building and analyzing event relationships
# ============================================================================

def collect_kes_from_kers(ker_dict):
    """Build adjacency dictionary from KER relationships."""
    events_from_kers = {}

    for _, ker_info in ker_dict.items():
        upstream_event_id = ker_info.get('upstream_event')
        downstream_event_id = ker_info.get('downstream_event')
        type_of_ker = ker_info.get('type')

        if upstream_event_id not in events_from_kers:
            events_from_kers[upstream_event_id] = { type_of_ker: [downstream_event_id] }
        elif type_of_ker not in events_from_kers[upstream_event_id]:
            events_from_kers[upstream_event_id][type_of_ker] = [downstream_event_id]
        else:
            events_from_kers[upstream_event_id][type_of_ker].append(downstream_event_id)
    
    return events_from_kers


def capture_mies_and_aos(events):
    """Identify and categorize Molecular Initiating Events and Adverse Outcomes."""
    mies_and_aos = {
        'mies': {},
        'aos': {},
        "mie_count": 0,
        "ao_count": 0
    }
    for ke_id, event_info in events.items():
        event_info_to_pass = {
            'ke_id': ke_id,
            'title': event_info['title'],
            "type": event_info['type']
        }
        if event_info['type'] == "MolecularInitiatingEvent":
            mies_and_aos['mies'][ke_id] = event_info_to_pass
            mies_and_aos["mie_count"] += 1
        elif event_info['type'] == "AdverseOutcome":
            mies_and_aos['aos'][ke_id] = event_info_to_pass
            mies_and_aos["ao_count"] += 1
    return mies_and_aos


def detect_cycles(adjacency_dict):
    """Detect cycles in a directed graph using DFS. Returns list of cycles found."""
    cycles = []
    visited = set()
    rec_stack = set()
    
    def dfs(node, path):
        if node in rec_stack:
            # Found a cycle - extract it from the path
            cycle_start = path.index(node)
            cycle = path[cycle_start:]
            cycles.append(cycle)
            return True
        
        if node in visited:
            return False
        
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        # Visit all adjacent nodes
        neighbors = adjacency_dict.get(node, {}).get('adjacent', [])
        for neighbor in neighbors:
            dfs(neighbor, path[:])
        
        rec_stack.remove(node)
        return False
    
    # Check all nodes as potential starting points
    for node in adjacency_dict.keys():
        if node not in visited:
            dfs(node, [])
    
    return cycles


def aop_network_check_based_on_mies_aos(mies_and_aos):
    """Check if AOP appears to be a network (multiple MIEs or AOs)."""
    if mies_and_aos['mie_count'] > 2 or mies_and_aos['ao_count'] > 2:
        return True
    return False


# ============================================================================
# EVENT ORDERING FUNCTIONS - Creating sequential event order
# ============================================================================

def get_ordered_events_for_single_mie_aop(events, up_to_down_events_from_kers, mies_and_aos):
    """Traverse from MIE to AO, creating ordered sequence of events with branch support."""
    mie_id = list(mies_and_aos['mies'].keys())[0]
    current_event_id = int(mie_id)
    
    ordered_event_dict = {
        "linear_path": {},
        "branches": []
    }
    
    # Create traversal context
    context = TraversalContext(events, up_to_down_events_from_kers, ordered_event_dict, mies_and_aos)
    
    # Start traversal from MIE
    traverse_path(current_event_id, 0, context, is_branch=False, branch_dict=None, branch_path_ids=None)
    
    # Post-process to identify convergence points and restructure output
    _restructure_with_convergence(ordered_event_dict)
    
    return ordered_event_dict


def get_ordered_events_from_kers(events, up_to_down_events_from_kers, mies_and_aos):
    """Coordinate event ordering, detect cycles, and route to appropriate ordering function."""
    ordered_event_dict = {}
    has_internal_loops = False

    # Detect cycles in the graph
    cycles = detect_cycles(up_to_down_events_from_kers)
    
    if cycles:
        print(f"Warning: Detected {len(cycles)} cycle(s) in the event graph:")
        has_internal_loops = True
        for i, cycle in enumerate(cycles, 1):
            print(f"  Cycle {i}: {' → '.join(map(str, cycle))} → {cycle[0]}")
    
    if mies_and_aos['mie_count'] == 1:
        ordered_event_dict = get_ordered_events_for_single_mie_aop(events, up_to_down_events_from_kers, mies_and_aos)

    # TODO: Handle cases with multiple MIEs or AOs
    return ordered_event_dict, has_internal_loops


def collect_ordered_events_and_detect_networks(filtered_aop_dict_from_xml):
    """Process each AOP to add ordered events and detect network structures."""
    network_aops_detected = 0
    for aop_id, aop_info in filtered_aop_dict_from_xml.items():
        # if int(aop_id) != 13:
        #     continue
        print(f"\nProcessing AOP ID: {aop_id}")
        events = aop_info.get('events', {})
        kers = aop_info['kers']

        # Check if all events are represented in KERs
        event_ids_in_aop = set(events.keys())
        event_ids_in_kers = set()
        for ker_info in kers.values():
            event_ids_in_kers.add(str(ker_info.get('upstream_event')))
            event_ids_in_kers.add(str(ker_info.get('downstream_event')))
        
        orphaned_events = event_ids_in_aop - event_ids_in_kers
        
        if orphaned_events:
            print(f"AOP ID {aop_id}: Events {orphaned_events} are not in any KERs. Skipping ordered_events generation.")
            mies_and_aos = capture_mies_and_aos(events)
            aos_as_string = '; '.join([f"{ao['ke_id']}: {ao['title']}" for ao in mies_and_aos.get('aos', {}).values()])
            filtered_aop_dict_from_xml[aop_id]['missing_mie'] = mies_and_aos['mie_count'] == 0
            filtered_aop_dict_from_xml[aop_id]['ordered_events'] = "Orphaned events present; ordered events not generated."
            filtered_aop_dict_from_xml[aop_id]['detected_as_aop_network'] = False
            filtered_aop_dict_from_xml[aop_id]['has_internal_loops'] = False
            filtered_aop_dict_from_xml[aop_id]['has_orphaned_events'] = True
            filtered_aop_dict_from_xml[aop_id]['orphaned_event_ids'] = ', '.join(orphaned_events)
            filtered_aop_dict_from_xml[aop_id]['adverse_outcomes'] = aos_as_string
            continue

        up_to_down_events_from_kers = collect_kes_from_kers(kers)
        mies_and_aos = capture_mies_and_aos(events)
        detected_as_aop_network = aop_network_check_based_on_mies_aos(mies_and_aos)

        if detected_as_aop_network:
            network_aops_detected += 1
            print(f"AOP ID {aop_id}: Multiple MIEs or AOs detected; likely incorrectly entered as a network.")
            ordered_event_dict = {}
            has_internal_loops = False
        else:
            ordered_event_dict, has_internal_loops = get_ordered_events_from_kers(events, up_to_down_events_from_kers, mies_and_aos)

        filtered_aop_dict_from_xml[aop_id]['missing_mie'] = mies_and_aos['mie_count'] == 0
        filtered_aop_dict_from_xml[aop_id]['ordered_events'] = ordered_event_dict
        filtered_aop_dict_from_xml[aop_id]['detected_as_aop_network'] = detected_as_aop_network
        filtered_aop_dict_from_xml[aop_id]['has_internal_loops'] = has_internal_loops
        filtered_aop_dict_from_xml[aop_id]['has_orphaned_events'] = False
        filtered_aop_dict_from_xml[aop_id]['orphaned_event_ids'] = ''
        aos_as_string = '; '.join([f"{ao['ke_id']}: {ao['title']}" for ao in mies_and_aos.get('aos', {}).values()])
        filtered_aop_dict_from_xml[aop_id]['adverse_outcomes'] = aos_as_string

    return filtered_aop_dict_from_xml

def combine_all_input_event_ids(event_title_filter, event_ft_filter, events_from_xml):
    skipped_ke_ids = identify_skipped_ke_ids(event_title_filter, event_ft_filter, events_from_xml)
    if event_ft_filter is None:
        input_event_ids = list(set(event_title_filter) - set(skipped_ke_ids))
    else:
        input_event_ids = list(set(event_title_filter) | set(event_ft_filter) - set(skipped_ke_ids))
    
    input_event_ids = [str(eid) for eid in input_event_ids]

    return input_event_ids, skipped_ke_ids

def collect_event_ids_from_aops(filtered_aop_dict_from_xml):
    """Collect all event IDs from the filtered AOPs."""
    associated_event_ids = set()
    for aop_info in filtered_aop_dict_from_xml.values():
        event_ids = aop_info.get('event_ids', [])
        event_ids = [int(eid) for eid in event_ids]
        associated_event_ids.update(event_ids)
    
    return list(associated_event_ids)

# ============================================================================
# MAIN ORCHESTRATION FUNCTION
# ============================================================================

def capture_related_entities_for_event_ids(logger_name, event_title_filter, event_ft_filter, ke_file_name, aop_file_name, input_term):
    """
    Main workflow function that - TODO
    """
    logger = set_up_logger(logger_name, level=logging.INFO)
    
    # Collect Event and AOP data from XML
    root, xml_namespace, refs = collect_xml_data(TODAY)
    events_from_xml = collect_events_from_xml(root, xml_namespace, refs)
    aop_dict_from_xml = collect_aops_from_xml(root, xml_namespace, refs)
    
    # Organize input Event IDs for filtering
    input_event_ids, skipped_ke_ids = combine_all_input_event_ids(event_title_filter, event_ft_filter, events_from_xml)

    # Capture AOPs associated with input Event IDs and filter AOP dictionary accordingly
    aop_ids_from_xml = collect_aops_for_input_event_ids(input_event_ids, events_from_xml)
    filtered_aop_dict_from_xml = filter_aop_dict_by_aop_ids(aop_dict_from_xml, aop_ids_from_xml, input_event_ids)
    
    # Capture associated Event IDs
    associated_event_ids = collect_event_ids_from_aops(filtered_aop_dict_from_xml)

    # Apply Event filters to aggregate associated Key Event and original input Events used as filters
    filtered_ke_dict = collect_filtered_events(event_title_filter, event_ft_filter, associated_event_ids, events_from_xml, input_term)
    filtered_ke_dict = dict(sorted(filtered_ke_dict.items(), key=lambda item: item[1]['retention_score'], reverse=True))
    
    event_summary = {
        "total_input_events": len(input_event_ids),
        "input_event_title_count": len(event_title_filter) if event_title_filter else 0,
        "input_event_full_text_count": len(event_ft_filter) if event_ft_filter else 0,
        "skipped_input_event_count": len(skipped_ke_ids),
        "associated_event_count": len(associated_event_ids)
    }
    filtered_ke_dict = { "summary": event_summary, "key_events": filtered_ke_dict }
    output_path = os.path.join(OUTPUT_DIR, ke_file_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_dict_to_json(filtered_ke_dict, OUTPUT_DIR, ke_file_name)
    logger.info(f"Filtered KE dictionary written to {ke_file_name} in {OUTPUT_DIR}")

    # Step 4: Enrich AOPs with detailed Key Event and KER information
    # filtered_aop_dict_from_xml = add_event_and_ker_details_to_aops(
    #     filtered_aop_dict_from_xml, events_by_event_dict, kers_by_ker_dict)
    
    # Step 5: Order Key Events within each AOP based on KERs and detect cycles/networks
    filtered_aop_dict_from_xml = collect_ordered_events_and_detect_networks(filtered_aop_dict_from_xml)

    # Step 6: Create visual for ordered events within each AOP
    viz_output_dir = os.path.join(OUTPUT_DIR, "aop_visualizations")
    os.makedirs(viz_output_dir, exist_ok=True)
    rendered_aop_count, skipped_aop_count = create_ordered_events_visual(filtered_aop_dict_from_xml, viz_output_dir, f"ordered_events_{TODAY}.png")

    # Step 7: Collect and integrate summary information
    summary = {
        "summary": {
            "input_event_title_count": len(event_title_filter) if event_title_filter else 0,
            "input_event_full_text_count": len(event_ft_filter) if event_ft_filter else 0,
            "skipped_input_event_count": len(skipped_ke_ids),
            "total_aops_retrieved": len(filtered_aop_dict_from_xml),
            "network_aop_count": sum(1 for aop_info in filtered_aop_dict_from_xml.values() if aop_info.get('detected_as_aop_network', False)),
            "total_events_retrieved": sum(len(aop_info.get('events', {})) for aop_info in filtered_aop_dict_from_xml.values()),
            "total_kers_retrieved": sum(len(aop_info.get('kers', {})) for aop_info in filtered_aop_dict_from_xml.values()),
            "skipped_input_event_ids": skipped_ke_ids,
            "network_aop_ids": [aop_id for aop_id, aop_info in filtered_aop_dict_from_xml.items() if aop_info.get('detected_as_aop_network', False)],
            "aops_with_visualization_created": rendered_aop_count,
            "aops_skipped_for_visualization": skipped_aop_count
        }
    }
    filtered_aop_dict_from_xml = summary | { "aops": filtered_aop_dict_from_xml }

    # Step 8: Save final results as json file
    output_path = os.path.join(OUTPUT_DIR, aop_file_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_dict_to_json(filtered_aop_dict_from_xml, OUTPUT_DIR, aop_file_name)
    logger.info(f"Filtered AOP dictionary written to {aop_file_name} in {OUTPUT_DIR}")

    # Step 9: Write AOP and Event results to a CSV file for SME review
    aop_csv_file_name = aop_file_name.replace('.json', '.csv')
    aop_csv_path = os.path.join(OUTPUT_DIR, aop_csv_file_name)
    
    write_csv(
        data=filtered_aop_dict_from_xml['aops'],
        field_config=AOP_DETAIL_FIELDS,
        output_path=aop_csv_path
    )

    event_csv_file_name = ke_file_name.replace('.json', '.csv')
    event_csv_path = os.path.join(OUTPUT_DIR, event_csv_file_name)
    
    write_csv(
        data=filtered_ke_dict['key_events'],
        field_config=EVENT_DETAIL_FIELDS,
        output_path=event_csv_path,
        sort_key='retention_score',
        reverse_sort=True
    )

# ============================================================================
# END OF SCRIPT EXECUTION
# ============================================================================

if __name__ == "__main__":
    capture_related_entities_for_event_ids(
        logger_name='analyze_depression_aops', 
        event_title_filter=[1346, 1332, 2392], 
        event_ft_filter=[1944, 389, 388, 618, 2078, 875, 2098, 2371, 195, 201, 757], 
        ke_file_name=f'depression_events_{TODAY}.json', 
        aop_file_name=f'depression_aops_{TODAY}.json',
        input_term=None
    )
