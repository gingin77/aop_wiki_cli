"""
Search the text of a chosen set of AOPs, their key events and their KERs.

The other search commands screen every AOP, KE or KER in the export. This one
answers a narrower question: does any record belonging to *these* AOPs mention
a term? It selects AOPs by ID, by title term, or by holding a key event whose
title matches a term, then gathers each AOP's key events and KERs and runs the
same word-boundary matcher (search_entity_data) over their free-text fields.

KER evidence blocks are searched through their free_text only; the evidence
tables are not searched.
"""
import re

from aop_wiki_cli.search.search_text_by_field import (
    build_term_pattern,
    parse_and_clean_text,
    search_entity_data,
)
from aop_wiki_cli.search.event_first_search import (
    find_aops_containing_events,
    find_events_by_title_terms,
)
from aop_wiki_cli.search.result_processors import serialize_search_results


# Every free-text field each entity carries, as collected by the XML parsers.
TEXT_FIELDS = {
    "aops": [
        "title", "short_name", "abstract", "background", "development_strategy",
        "overall_assessment_description", "doa_free_text", "ke_essentiality",
        "woe_evidence", "quantitative_considerations", "known_modulating_factors",
        "potential_applications", "references",
    ],
    "events": [
        "title", "short_name", "description", "measurement_method",
        "doa_free_text", "references",
    ],
    "kers": [
        "description", "biological_plausibility", "empirical_support",
        "weight_of_evidence", "quantitative_understanding", "uncertainties",
        "modulating_factors", "response_relationship", "time_scale",
        "known_loops", "evidence_collection_strategy", "doa_free_text",
        "references",
    ],
}


def select_aops(aops_dict, events_dict, aop_ids=(), aop_title_terms=(), ke_title_terms=()):
    """
    Choose AOPs by ID, by title term, or by containing a key event whose title matches.

    The three selectors are unioned. Each selected AOP records why it was chosen.

    Returns:
        tuple: (selected, missing_ids)
            selected: {aop_id: {"title": str, "selected_by": [str, ...]}}
            missing_ids: requested AOP IDs absent from aops_dict
    """
    selected = {}

    def mark(aop_id, reason):
        entry = selected.setdefault(
            aop_id, {"title": aops_dict[aop_id].get("title", ""), "selected_by": []}
        )
        entry["selected_by"].append(reason)

    missing_ids = []
    for aop_id in (str(i) for i in aop_ids):
        if aop_id in aops_dict:
            mark(aop_id, "aop_id")
        else:
            missing_ids.append(aop_id)

    for aop_id, aop_info in aops_dict.items():
        title = parse_and_clean_text(aop_info.get("title") or "").lower()
        for term in aop_title_terms:
            if re.search(build_term_pattern(term), title):
                mark(aop_id, f"aop_title:{term}")

    if ke_title_terms:
        matched_events = find_events_by_title_terms(events_dict, list(ke_title_terms))
        for aop_id, match in find_aops_containing_events(aops_dict, matched_events).items():
            for event_id in sorted(match["source_events"], key=int):
                mark(aop_id, f"ke_title:KE{event_id}")

    return selected, missing_ids


def entity_label(entity, record):
    """A one-line human label for a matched record: KERs read as a relationship."""
    if entity == "kers":
        upstream = (record.get("upstream_ke") or {}).get("title", "?")
        downstream = (record.get("downstream_ke") or {}).get("title", "?")
        return f"{upstream} -> {downstream}"
    return record.get("title", "")


def search_within_aops(aops_dict, events_dict, kers_dict, selected_aop_ids, terms):
    """
    Search the selected AOPs, their key events and their KERs for terms.

    Each term is searched separately so that every snippet is attributable to
    the term that matched it; a summary can then be organized by term.

    Args:
        aops_dict, events_dict, kers_dict: collected entities keyed by string ID
        selected_aop_ids: AOP IDs to search within
        terms: search terms (word-boundary, case-insensitive, HTML stripped)

    Returns:
        dict with:
            "scope": the AOP, KE and KER IDs searched, and KE/KER IDs the AOPs
                     reference but the export lacks
            "term_counts": {term: {entity: matching field count}}, zeros included
            "findings": {term: [hit, ...]} for terms that matched, where a hit is
                     {entity, id, label, aop_ids, snippets_by_field}
            "terms_not_found": terms that matched nothing anywhere
    """
    selected = [str(i) for i in selected_aop_ids]
    owners = {"aops": {i: [i] for i in selected}, "events": {}, "kers": {}}
    for aop_id in selected:
        aop_info = aops_dict[aop_id]
        for event_id in aop_info.get("event_ids", []):
            owners["events"].setdefault(str(event_id), []).append(aop_id)
        for ker_id in aop_info.get("kers", {}):
            owners["kers"].setdefault(str(ker_id), []).append(aop_id)

    source = {"aops": aops_dict, "events": events_dict, "kers": kers_dict}
    scope = {"missing": {}}
    in_scope = {}
    for entity, id_owners in owners.items():
        in_scope[entity] = {i: source[entity][i] for i in id_owners if i in source[entity]}
        scope[entity] = sorted(in_scope[entity], key=int)
        scope["missing"][entity] = sorted(set(id_owners) - set(in_scope[entity]), key=int)

    term_counts = {}
    findings = {}
    for term in terms:
        term_counts[term] = {}
        hits = []
        for entity, records in in_scope.items():
            summary, results = search_entity_data(
                records, {"fields_to_search": TEXT_FIELDS[entity], "terms": [term]}
            )
            serialize_search_results(results)
            term_counts[term][entity] = summary["terms_searched"][term]
            for entity_id, result in sorted(results.items(), key=lambda item: int(item[0])):
                hits.append({
                    "entity": entity,
                    "id": entity_id,
                    "label": entity_label(entity, records[entity_id]),
                    "aop_ids": sorted(owners[entity][entity_id], key=int),
                    "snippets_by_field": result["snippets_by_field"],
                })
        if hits:
            findings[term] = hits

    return {
        "scope": scope,
        "term_counts": term_counts,
        "findings": findings,
        "terms_not_found": [term for term in terms if term not in findings],
    }
