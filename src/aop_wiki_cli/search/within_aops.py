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


CASE_SENSITIVE_PREFIX = "cs:"


def split_case_flag(term):
    """
    Split a ``cs:``-prefixed term into (term, case_sensitive).

    Acronyms need this. AOP-Wiki writes inhibitory postsynaptic currents as
    "IPSCs", which a case-insensitive search for "iPSCs" matches, turning a
    stem-cell search into a false positive on electrophysiology prose.
    """
    if term.startswith(CASE_SENSITIVE_PREFIX):
        return term[len(CASE_SENSITIVE_PREFIX):].strip(), True
    return term, False


def filter_snippets_by_case(snippets_by_field, term):
    """Keep only the snippets that contain term with its own capitalization."""
    pattern = re.compile(r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b")
    kept = {
        field: [snippet for snippet in snippets if pattern.search(snippet)]
        for field, snippets in snippets_by_field.items()
    }
    return {field: snippets for field, snippets in kept.items() if snippets}


def parse_term_groups(group_specs):
    """
    Parse ``name=term|term`` specifications into {name: [terms]}.

    A group is one concept spelled several ways — AOP-Wiki writes
    microelectrode arrays as "microelectrode array", "micro-electrode array"
    and "MEA" — so that co-occurrence is asked between concepts rather than
    between individual spellings.

    Raises:
        ValueError: on a spec with no '=', an empty name, or no terms.
    """
    groups = {}
    for spec in group_specs:
        name, separator, raw_terms = spec.partition("=")
        name = name.strip()
        terms = [term.strip() for term in raw_terms.split("|") if term.strip()]
        if not separator or not name or not terms:
            raise ValueError(
                f"Term group {spec!r} must be written name=term|term, e.g. "
                "mea='microelectrode array|micro-electrode array|MEA'"
            )
        groups.setdefault(name, []).extend(terms)
    return groups


def co_occurring_records(findings, groups):
    """
    Find the records where two term groups both matched, for each pair of groups.

    Co-occurrence is per record, not per field: a key event naming MEA in its
    measurement_method and iPSCs in its references counts, because both are
    properties of that key event. Every pair is reported, including pairs with
    no record in common, so a zero is a stated result.

    Returns:
        list of {"groups": [name, name], "records": [record, ...]} in group order
    """
    hits_by_group = {}
    for name, terms in groups.items():
        records = {}
        for term in terms:
            for hit in findings.get(term, []):
                key = (hit["entity"], hit["id"])
                record = records.setdefault(key, {
                    "entity": hit["entity"],
                    "id": hit["id"],
                    "label": hit["label"],
                    "aop_ids": hit["aop_ids"],
                    "terms": [],
                    "fields": set(),
                })
                record["terms"].append(term)
                record["fields"].update(hit["snippets_by_field"])
        hits_by_group[name] = records

    names = list(groups)
    pairs = []
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            shared = sorted(
                set(hits_by_group[first]) & set(hits_by_group[second]),
                key=lambda key: (key[0], int(key[1])),
            )
            pairs.append({
                "groups": [first, second],
                "records": [
                    {
                        "entity": entity,
                        "id": entity_id,
                        "label": hits_by_group[first][(entity, entity_id)]["label"],
                        "aop_ids": hits_by_group[first][(entity, entity_id)]["aop_ids"],
                        "terms_by_group": {
                            group: hits_by_group[group][(entity, entity_id)]["terms"]
                            for group in (first, second)
                        },
                        "fields_by_group": {
                            group: sorted(hits_by_group[group][(entity, entity_id)]["fields"])
                            for group in (first, second)
                        },
                    }
                    for entity, entity_id in shared
                ],
            })
    return pairs


def group_match_counts(findings, groups):
    """How many records each term group matched, counted once per record."""
    counts = {}
    for name, terms in groups.items():
        records = {(hit["entity"], hit["id"]) for term in terms for hit in findings.get(term, [])}
        counts[name] = len(records)
    return counts


def search_within_aops(aops_dict, events_dict, kers_dict, selected_aop_ids, terms, groups=None):
    """
    Search the selected AOPs, their key events and their KERs for terms.

    Each term is searched separately so that every snippet is attributable to
    the term that matched it; a summary can then be organized by term.

    Args:
        aops_dict, events_dict, kers_dict: collected entities keyed by string ID
        selected_aop_ids: AOP IDs to search within
        terms: search terms (word-boundary, case-insensitive, HTML stripped)
        groups: optional {name: [terms]}; every pair is tested for records where
                both groups matched. Group terms need not appear in ``terms``;
                they are searched too.

    Returns:
        dict with:
            "scope": the AOP, KE and KER IDs searched, and KE/KER IDs the AOPs
                     reference but the export lacks
            "term_counts": {term: {entity: matching field count}}, zeros included
            "findings": {term: [hit, ...]} for terms that matched, where a hit is
                     {entity, id, label, aop_ids, snippets_by_field}
            "terms_not_found": terms that matched nothing anywhere
            "groups", "group_counts", "co_occurrence": the group view, empty
                     when no groups were given
    """
    groups = groups or {}
    specs = {}
    for spec in list(terms) + [term for terms in groups.values() for term in terms]:
        term, case_sensitive = split_case_flag(spec)
        if specs.setdefault(term, case_sensitive) != case_sensitive:
            raise ValueError(
                f"Term {term!r} was given both case-sensitively and case-insensitively"
            )
    searched = list(specs)
    # Group membership is keyed by the bare term, so a cs: prefix in a group
    # spec does not leak into the findings keys or the report
    bare_groups = {
        name: [split_case_flag(term)[0] for term in group_terms]
        for name, group_terms in groups.items()
    }
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
    for term in searched:
        term_counts[term] = {}
        hits = []
        for entity, records in in_scope.items():
            summary, results = search_entity_data(
                records, {"fields_to_search": TEXT_FIELDS[entity], "terms": [term]}
            )
            serialize_search_results(results)
            matching_fields = summary["terms_searched"][term]
            for entity_id, result in sorted(results.items(), key=lambda item: int(item[0])):
                snippets_by_field = result["snippets_by_field"]
                if specs[term]:
                    kept = filter_snippets_by_case(snippets_by_field, term)
                    matching_fields -= len(snippets_by_field) - len(kept)
                    if not kept:
                        continue
                    snippets_by_field = kept
                hits.append({
                    "entity": entity,
                    "id": entity_id,
                    "label": entity_label(entity, records[entity_id]),
                    "aop_ids": sorted(owners[entity][entity_id], key=int),
                    "snippets_by_field": snippets_by_field,
                })
            term_counts[term][entity] = matching_fields
        if hits:
            findings[term] = hits

    return {
        "scope": scope,
        "term_counts": term_counts,
        "findings": findings,
        "terms_not_found": [term for term in searched if term not in findings],
        "case_sensitive_terms": [term for term, sensitive in specs.items() if sensitive],
        "groups": bare_groups,
        "group_counts": group_match_counts(findings, bare_groups),
        "co_occurrence": co_occurring_records(findings, bare_groups),
    }
