"""Pair the MIEs and AOs of a collected set of AOPs.

An AOP-Wiki AOP records its molecular initiating events and adverse outcomes as
separate XML elements from its intermediate key events, so the parser stores
them per AOP as ``mie_ids`` and ``ao_ids`` (see
:func:`aop_wiki_cli.parsers.parse_aop_wiki_xml_data.collect_base_aop_info_from_xml`).
The functions here turn that into one row per MIE/AO combination, which is the
shape needed to see which molecular starting points converge on which adverse
outcomes across a collection of AOPs.

AOPs with no MIE, no AO, or neither still get a row, with the missing side left
blank, so that gaps in the collected set stay visible rather than dropping out.
"""

# Placeholder used in a pair row when an AOP declares no MIE or no AO.
UNDECLARED = ""


def _event_title(events_dict, event_id):
    """Look up an event title, tolerating str/int key mismatches."""
    event_id_str = str(event_id)
    event_info = events_dict.get(event_id_str)
    if event_info is None and event_id_str.isdigit():
        event_info = events_dict.get(int(event_id_str))
    if event_info is None:
        return "Unknown"
    # collect_events_from_matched_aops wraps the raw event record
    if "event_info" in event_info and isinstance(event_info["event_info"], dict):
        nested = event_info["event_info"]
        return event_info.get("title") or nested.get("title") or "Unknown"
    return event_info.get("title") or "Unknown"


def build_mie_ao_pairs(aops_dict, events_dict, matched_event_ids=None):
    """Build one row per (AOP, MIE, AO) combination.

    Args:
        aops_dict: {aop_id: aop_record} where each record carries 'mie_ids',
            'ao_ids', 'title' and 'event_ids'
        events_dict: Event records for title lookups, keyed by event ID
        matched_event_ids: Optional collection of the event IDs that caused
            these AOPs to be collected. Used to flag whether the MIE or the AO
            of a pair was itself a search hit.

    Returns:
        list[dict]: pair rows, sorted by AOP ID then MIE ID then AO ID
    """
    matched = {str(eid) for eid in (matched_event_ids or [])}
    rows = []

    for aop_id, aop in aops_dict.items():
        mie_ids = [str(eid) for eid in aop.get("mie_ids", [])] or [UNDECLARED]
        ao_ids = [str(eid) for eid in aop.get("ao_ids", [])] or [UNDECLARED]

        for mie_id in mie_ids:
            for ao_id in ao_ids:
                rows.append({
                    "aop_id": str(aop_id),
                    "aop_title": aop.get("title", ""),
                    "oecd_status": aop.get("oecd_status", ""),
                    "mie_id": mie_id,
                    "mie_title": _event_title(events_dict, mie_id) if mie_id else UNDECLARED,
                    "mie_matched_search_term": mie_id in matched if mie_id else False,
                    "ao_id": ao_id,
                    "ao_title": _event_title(events_dict, ao_id) if ao_id else UNDECLARED,
                    "ao_matched_search_term": ao_id in matched if ao_id else False,
                    "num_events_in_aop": len(aop.get("event_ids", [])),
                    "num_kers_in_aop": len(aop.get("kers", {}) or {}),
                })

    return sorted(rows, key=lambda r: (_sort_key(r["aop_id"]), _sort_key(r["mie_id"]), _sort_key(r["ao_id"])))


def _sort_key(value):
    """Sort numeric IDs numerically, keeping blanks last."""
    return (0, int(value)) if str(value).isdigit() else (1, 0)


def summarize_mie_ao_pairs(rows):
    """Summary counts over a list of pair rows."""
    aop_ids = {row["aop_id"] for row in rows}
    mie_ids = {row["mie_id"] for row in rows if row["mie_id"]}
    ao_ids = {row["ao_id"] for row in rows if row["ao_id"]}
    return {
        "total_pairs": len(rows),
        "total_aops": len(aop_ids),
        "unique_mies": len(mie_ids),
        "unique_aos": len(ao_ids),
        "aops_without_mie": len({row["aop_id"] for row in rows if not row["mie_id"]}),
        "aops_without_ao": len({row["aop_id"] for row in rows if not row["ao_id"]}),
    }


def filter_kers_by_aop_ids(kers_dict, aop_ids):
    """Select the KERs that belong to any of the given AOPs.

    KER records carry the AOPs they appear in as 'aop_ids', so membership is
    read straight off the KER rather than inferred from its endpoints.
    """
    wanted = {str(aop_id) for aop_id in aop_ids}
    return {
        ker_id: ker
        for ker_id, ker in kers_dict.items()
        if wanted & {str(aop_id) for aop_id in ker.get("aop_ids", [])}
    }


MIE_AO_PAIR_COLUMNS = [
    ("aop_id", "AOP"),
    ("aop_title", "AOP title"),
    ("oecd_status", "OECD status"),
    ("mie_id", "MIE (KE ID)"),
    ("mie_title", "MIE title"),
    ("ao_id", "AO (KE ID)"),
    ("ao_title", "AO title"),
    ("num_events_in_aop", "KEs"),
    ("num_kers_in_aop", "KERs"),
]


def render_mie_ao_markdown_table(rows, columns=MIE_AO_PAIR_COLUMNS):
    """Render pair rows as a GitHub-flavored markdown table."""
    header = "| " + " | ".join(label for _, label in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, divider]
    for row in rows:
        cells = [_md_cell(row.get(key, "")) for key, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _md_cell(value):
    """Flatten a value into a single markdown table cell."""
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ").strip()
