"""
Readable outputs for a within-AOP search.

The JSON a within-AOP search writes is the provenance record: complete, and
awkward to read. These two writers are the summary. The markdown report is
organized by term and leads with the terms that matched, each with the records
and quotes that matched it; the CSV holds one row per snippet for filtering.

Both are derived from the search result, so neither re-reads the export.
"""
import csv
from pathlib import Path


ENTITY_LABELS = {"aops": "AOP", "events": "KE", "kers": "KER"}

MATCH_CSV_FIELDS = ["term", "entity", "id", "label", "aop_ids", "field", "snippet"]


def tally(term_counts):
    """"3 AOP fields, 1 KE field" — the entities a term matched, zeros omitted."""
    return ", ".join(
        f"{term_counts[entity]} {ENTITY_LABELS[entity]} "
        f"field{'s' if term_counts[entity] != 1 else ''}"
        for entity in ("aops", "events", "kers") if term_counts[entity]
    )


def count_phrase(result, group):
    """"3 records" / "no records" — how many records a term group matched."""
    count = result["group_counts"][group]
    return f"{count} record{'s' if count != 1 else ''}" if count else "no records"


def match_rows(result):
    """Flatten a search result into one row per (term, record, field, snippet)."""
    rows = []
    for term, hits in result["findings"].items():
        for hit in hits:
            for field, snippets in sorted(hit["snippets_by_field"].items()):
                for snippet in snippets:
                    rows.append({
                        "term": term,
                        "entity": ENTITY_LABELS[hit["entity"]],
                        "id": hit["id"],
                        "label": hit["label"],
                        "aop_ids": ", ".join(hit["aop_ids"]),
                        "field": field,
                        "snippet": snippet,
                    })
    return rows


def write_within_aop_matches_csv(result, output_path):
    """Write one row per matching snippet. Returns the path, or None with no matches."""
    rows = match_rows(result)
    if not rows:
        return None

    output_path = Path(output_path)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATCH_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def render_within_aop_markdown(result, summary, selected_aops):
    """
    Render the search as a markdown report, organized by term.

    Terms that matched come first, each with its records and quotes. Terms that
    matched nothing are listed after, because an absence is only meaningful
    alongside what was searched — which the scope section states exactly.
    """
    scope = result["scope"]
    findings = result["findings"]
    lines = [
        f"# Within-AOP search — AOP-Wiki snapshot {summary['collection_date']}",
        "",
        f"Searched **{len(scope['aops'])} AOPs**, **{len(scope['events'])} key events** and "
        f"**{len(scope['kers'])} KERs** for "
        f"**{len(findings) + len(result['terms_not_found'])} terms**. "
        f"{len(findings)} matched; {len(result['terms_not_found'])} did not.",
        "",
    ]

    if result.get("co_occurrence"):
        lines.append("## Term groups together in one record")
        lines.append("")
        for pair in result["co_occurrence"]:
            first, second = pair["groups"]
            lines.append(f"### {first} + {second} — {len(pair['records'])} records")
            lines.append("")
            if not pair["records"]:
                absence = (
                    f"No AOP, key event or KER in scope matched both *{first}* "
                    f"({count_phrase(result, first)}) and *{second}* "
                    f"({count_phrase(result, second)})."
                )
                if result["group_counts"][first] and result["group_counts"][second]:
                    absence += " Each group is present in scope, but never in the same record."
                lines.append(absence)
                lines.append("")
                continue
            for record in pair["records"]:
                aops = ", ".join(f"AOP {i}" for i in record["aop_ids"])
                lines.append(
                    f"- **{ENTITY_LABELS[record['entity']]} {record['id']}** "
                    f"{record['label']} ({aops})"
                )
                for group in pair["groups"]:
                    terms = ", ".join(repr(term) for term in record["terms_by_group"][group])
                    fields = ", ".join(f"`{field}`" for field in record["fields_by_group"][group])
                    lines.append(f"  - {group}: {terms} in {fields}")
            lines.append("")

    if result.get("groups"):
        lines.append("### Group membership")
        lines.append("")
        for name, terms in result["groups"].items():
            matched = [term for term in terms if term in findings]
            lines.append(
                f"- **{name}** — {count_phrase(result, name)}; "
                f"spellings searched: {', '.join(repr(term) for term in terms)}"
                + (f"; matched: {', '.join(repr(term) for term in matched)}" if matched else "")
            )
        lines.append("")

    if findings:
        lines.append("## Found")
        lines.append("")
        for term, hits in findings.items():
            lines.append(f"### {term!r} — {tally(result['term_counts'][term])}")
            lines.append("")
            for hit in hits:
                aops = ", ".join(f"AOP {i}" for i in hit["aop_ids"])
                lines.append(
                    f"- **{ENTITY_LABELS[hit['entity']]} {hit['id']}** {hit['label']} ({aops})"
                )
                for field, snippets in sorted(hit["snippets_by_field"].items()):
                    lines.append(f"  - `{field}`")
                    for snippet in snippets:
                        lines.append(f"    > {snippet}")
                lines.append("")

    if result["terms_not_found"]:
        lines.append("## Not found")
        lines.append("")
        lines.append("No field of any AOP, key event or KER listed below matched:")
        lines.append("")
        for term in result["terms_not_found"]:
            lines.append(f"- {term!r}")
        lines.append("")
        lines.append(
            "The matcher is word-boundary over HTML-stripped text, so punctuation "
            "differences do not match: a term absent here may be present under "
            "another spelling."
        )
        lines.append("")

    if result.get("case_sensitive_terms"):
        lines.append(
            "Matched case-sensitively: "
            + ", ".join(repr(term) for term in result["case_sensitive_terms"])
            + ". Every other term was matched case-insensitively."
        )
        lines.append("")

    lines.append("## Scope searched")
    lines.append("")
    lines.append("| AOP | Title | Selected by |")
    lines.append("|---|---|---|")
    for aop_id, info in selected_aops.items():
        title = info["title"].replace("|", "\\|")
        lines.append(f"| {aop_id} | {title} | {', '.join(info['selected_by'])} |")
    lines.append("")
    lines.append(f"- Key events searched: {', '.join(scope['events']) or 'none'}")
    lines.append(f"- KERs searched: {', '.join(scope['kers']) or 'none'}")
    for entity, missing in scope["missing"].items():
        if missing:
            lines.append(
                f"- {ENTITY_LABELS[entity]} IDs referenced by these AOPs but absent "
                f"from the export: {', '.join(missing)}"
            )
    lines.append("")
    lines.append("Fields searched per entity:")
    lines.append("")
    for entity, fields in summary["fields_searched"].items():
        lines.append(f"- {ENTITY_LABELS[entity]}: {', '.join(fields)}")
    lines.append("")
    lines.append(
        "KER evidence blocks are searched through their `free_text` only; "
        "the evidence tables are not searched."
    )
    lines.append("")
    return "\n".join(lines)


def write_within_aop_markdown(result, summary, selected_aops, output_path):
    """Write the markdown report. Returns the path."""
    output_path = Path(output_path)
    output_path.write_text(
        render_within_aop_markdown(result, summary, selected_aops), encoding="utf-8"
    )
    return output_path
