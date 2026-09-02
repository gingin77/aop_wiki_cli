def collect_events_from_matched_aops(matched_aops, events_dict, aops_dict=None):
    """
    Collect enriched event records for all events in matched AOPs, with provenance.

    Returns a dict keyed by event_id (use .keys() for IDs only) with full event metadata
    and a list of which AOPs each event was found in.

    Supports two matched_aops input structures:

    - event_to_aop format (from search_events_to_aops):
        {aop_id: {"aop_info": {"event_ids": [...]}, ...}}
        Pass matched_aops only; event_ids are read from aop_data["aop_info"].

    - search results format (from search_entity_data + serialize_search_results):
        {aop_id: {"entity_id": ..., "title": ..., ...}}
        Also pass aops_dict so event_ids can be looked up from the raw AOP data.

    Args:
        matched_aops: Dict of matched AOPs in one of the two formats above
        events_dict: Canonical events dictionary for event info lookups
                     {event_id: {"title": ..., "completion_score": ..., ...}}
        aops_dict: Optional raw AOPs dictionary. Required when matched_aops is in
                   search results format; event_ids are read from here instead of
                   from matched_aops["aop_info"]

    Returns:
        dict: {event_id: {"event_info": {...}, "title": ..., "found_in_aops": [aop_id, ...]}}
    """
    aop_events = {}

    for aop_id, aop_data in matched_aops.items():
        if aops_dict is not None:
            event_ids = [str(eid) for eid in aops_dict.get(aop_id, {}).get("event_ids", [])]
        else:
            aop_info = aop_data.get("aop_info", {})
            event_ids = aop_info.get("event_ids", [])

        for event_id in event_ids:
            event_id_str = str(event_id)
            if event_id_str in aop_events:
                aop_events[event_id_str]["found_in_aops"].append(aop_id)
            else:
                event_info = events_dict.get(event_id_str, events_dict.get(int(event_id), {}))
                aop_events[event_id_str] = {
                    "event_info": event_info,
                    "title": event_info.get("title", "Unknown"),
                    "found_in_aops": [aop_id],
                }

    return aop_events
