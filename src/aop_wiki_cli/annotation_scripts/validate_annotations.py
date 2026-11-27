"""Validate stored KE annotations against the source ontologies via OAK.

Prototype of the post-selection validation layer (modeled on dismech's
linkml-term-validator workflow): after a term has been assigned by the
annotation pipeline, check that it still holds up against the ontology itself.

Checks per stored term record:
  id       — the stored IRI converts to a CURIE and resolves in the ontology
  label    — the stored label matches the canonical ontology label (drift check)
  scope    — the term's prefix is one the field allows (e.g. no GO as cell_term)
  closure  — the term is a descendant of the field's expected root
             (e.g. cellular_component under GO:0005575, cell_term under
             CL:0000000); requires --scheme sqlite, since OLS adapters do not
             serve ancestor traversal

The default OLS mode needs only core dependencies; --scheme sqlite needs
oaklib, which is intentionally kept in the optional `validation` group.

Usage:
    # Existence + label + scope checks via the OLS4 REST API (network, no downloads)
    uv run python -m aop_wiki_cli.annotation_scripts.validate_annotations

    # Full checks including closure, against local SQLite ontology builds
    # (OAK downloads each ontology build on first use)
    uv run --group validation python -m aop_wiki_cli.annotation_scripts.validate_annotations \\
        --scheme sqlite --closure

    # One KE, one field
    uv run --group validation python -m aop_wiki_cli.annotation_scripts.validate_annotations \\
        --ke 68 --field cellular_component
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

ANNOTATIONS_FILE = "outputs_for_vc/annotations/ke_annotations.json"


# ---------------------------------------------------------------------------
# Field rules: which prefixes a field accepts, and the ancestor-closure root
# each prefix must fall under. A prefix with no root entry gets existence and
# label checks only. These mirror FIELD_ONTOLOGIES in annotate_term_helpers
# and are the prototype for `reachable_from` bindings in the linkml-aop schema.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TermRule:
    prefixes: frozenset
    roots: dict = dataclass_field(default_factory=dict)


FIELD_RULES: dict[str, TermRule] = {
    "cell_term": TermRule(frozenset({"CL"}), {"CL": "CL:0000000"}),
    "organ_term": TermRule(frozenset({"UBERON"}), {"UBERON": "UBERON:0001062"}),
    "cellular_component": TermRule(frozenset({"GO"}), {"GO": "GO:0005575"}),
    "biological_process": TermRule(frozenset({"GO"}), {"GO": "GO:0008150"}),
    "biological_object": TermRule(
        frozenset({"CL", "UBERON", "CHEBI", "PR", "HGNC"}),
        {"CL": "CL:0000000", "UBERON": "UBERON:0001062", "CHEBI": "CHEBI:24431"},
    ),
    "phenotype": TermRule(
        # GO is reachable here because some GO terms are valid via UPHENO;
        # the annotator flags them needs_review, and scope does not fail them.
        frozenset({"UPHENO", "HP", "MP", "GO"}),
        {"HP": "HP:0000118", "MP": "MP:0000001"},
    ),
    "assay_type": TermRule(frozenset({"OBI", "BAO"}), {"OBI": "OBI:0000070"}),
    "taxon_term": TermRule(frozenset({"NCBITAXON"})),
}

# Prefixes OAK cannot resolve reliably (dismech documents the same limitation
# for HGNC); records with these prefixes are reported as skipped, not failed.
UNRESOLVABLE_PREFIXES = {"HGNC"}


# ---------------------------------------------------------------------------
# Pure helpers (no oaklib required; covered by tests)
# ---------------------------------------------------------------------------

def iri_to_curie(iri: str) -> str | None:
    """Convert a stored term IRI to a CURIE, or None when no form is recognized.

    Handles OBO PURLs ('.../obo/GO_0005739' → 'GO:0005739', including
    UniProt-style PR local ids) and CURIE-tailed IRIs ('.../HGNC:7782').
    A string that already looks like a CURIE is returned unchanged.
    """
    if not iri:
        return None
    m = re.search(r"/obo/([A-Za-z]+)_([A-Za-z0-9]+)$", iri)
    if m:
        return f"{m.group(1).upper()}:{m.group(2)}"
    m = re.fullmatch(r"([A-Za-z]+):[A-Za-z0-9._-]+", iri)
    if m:
        return iri
    m = re.search(r"([A-Za-z]+:[A-Za-z0-9._-]+)$", iri)
    if m:
        return m.group(1)
    return None


def iter_term_records(store: dict):
    """Yield (ke_id, location, field, record) for every stored ontology-term
    record in the annotation store: top-level location terms, per-component
    ECS terms, and assay-level terms. Rejections, comments, and unresolved
    label-only entries (no term_id) are not yielded."""
    def _usable(record) -> bool:
        return isinstance(record, dict) and bool(record.get("term_id"))

    for ke_id, ke in store.items():
        for field in ("cell_term", "organ_term", "cellular_component"):
            if _usable(ke.get(field)):
                yield ke_id, field, field, ke[field]
        for ec in ke.get("ec_annotations", []):
            if not isinstance(ec, dict):
                continue
            where = f"ec[{ec.get('subject', '?')!r}]"
            for field in ("biological_object", "biological_process", "phenotype"):
                if _usable(ec.get(field)):
                    yield ke_id, f"{where}.{field}", field, ec[field]
        for assay in ke.get("assays") or []:
            if not isinstance(assay, dict):
                continue
            where = f"assay[{assay.get('id', '?')}]"
            if _usable(assay.get("assay_type")):
                yield ke_id, f"{where}.assay_type", "assay_type", assay["assay_type"]
            for key, field in (("objects", "biological_object"),
                               ("processes", "biological_process"),
                               ("taxon_terms", "taxon_term")):
                for item in assay.get(key) or []:
                    if _usable(item):
                        yield ke_id, f"{where}.{key}", field, item


# ---------------------------------------------------------------------------
# OAK-backed checks
# ---------------------------------------------------------------------------

OLS_TERMS_URL = "https://www.ebi.ac.uk/ols4/api/terms"
OLS_TIMEOUT = 30


class OntologyChecker:
    """Resolves terms via the OLS4 REST API (default) or local OAK SQLite builds.

    The ols scheme uses plain requests with a {OLS_TIMEOUT}s timeout — oaklib's
    OLS adapter delegates to ols_client, whose 5s timeout is not configurable
    and times out routinely. oaklib is only needed for scheme "sqlite".
    """

    def __init__(self, scheme: str):
        self.scheme = scheme
        self._adapters: dict[str, object] = {}
        self._label_cache: dict[str, tuple[str, str | None]] = {}

    def _adapter(self, prefix: str):
        key = prefix.upper()
        if key not in self._adapters:
            from oaklib import get_adapter
            try:
                self._adapters[key] = get_adapter(f"sqlite:obo:{key.lower()}")
            except Exception as e:
                print(f"  ! could not open sqlite adapter for {key}: {e}", file=sys.stderr)
                self._adapters[key] = None
        return self._adapters[key]

    def _label_via_ols(self, curie: str) -> tuple[str, str | None]:
        import requests
        last_error = None
        for attempt in range(3):
            try:
                resp = requests.get(OLS_TERMS_URL, params={"obo_id": curie},
                                    timeout=OLS_TIMEOUT)
                if resp.status_code == 404:
                    return "missing", None
                resp.raise_for_status()
                terms = resp.json().get("_embedded", {}).get("terms", [])
                if not terms:
                    return "missing", None
                defining = next((t for t in terms if t.get("is_defining_ontology")), terms[0])
                label = defining.get("label")
                return ("ok", label) if label else ("missing", None)
            except Exception as e:
                last_error = e
                time.sleep(1 + attempt)
        print(f"  ! OLS lookup failed for {curie}: {last_error}", file=sys.stderr)
        return "error", None

    def _label_via_sqlite(self, curie: str) -> tuple[str, str | None]:
        adapter = self._adapter(curie.split(":", 1)[0])
        if adapter is None:
            return "error", None
        try:
            label = adapter.label(curie)
            return ("ok", label) if label else ("missing", None)
        except Exception as e:
            print(f"  ! lookup failed for {curie}: {e}", file=sys.stderr)
            return "error", None

    def canonical_label(self, curie: str) -> tuple[str, str | None]:
        """Look up the canonical label for curie.

        Returns (status, label): ("ok", label) when resolved, ("missing", None)
        when the ontology answers but has no such term, and ("error", None)
        when the lookup itself failed (network/adapter), after retries —
        an error must never be reported as a missing term.
        """
        if curie not in self._label_cache:
            lookup = self._label_via_ols if self.scheme == "ols" else self._label_via_sqlite
            self._label_cache[curie] = lookup(curie)
        return self._label_cache[curie]

    def in_closure(self, curie: str, root: str) -> bool | None:
        """True/False for subclass-closure membership; None when unavailable."""
        if self.scheme != "sqlite":
            return None
        adapter = self._adapter(curie.split(":", 1)[0])
        if adapter is None:
            return None
        try:
            from oaklib.datamodels.vocabulary import IS_A
            return root in set(adapter.ancestors(curie, predicates=[IS_A], reflexive=True))
        except Exception as e:
            print(f"  ! closure check failed for {curie}: {e}", file=sys.stderr)
            return None


def validate_store(store: dict, checker: OntologyChecker,
                   only_fields: set[str] | None = None,
                   check_closure: bool = False) -> dict:
    """Run all checks over the store. Returns tally dict; prints findings."""
    tally = {"checked": 0, "ok": 0, "skipped": 0,
             "unparseable_id": 0, "not_found": 0, "lookup_error": 0,
             "label_drift": 0, "off_scope": 0,
             "closure_fail": 0, "closure_unchecked": 0}

    for ke_id, location, field, record in iter_term_records(store):
        if only_fields and field not in only_fields:
            continue
        tally["checked"] += 1
        where = f"KE {ke_id} {location}"
        stored_label = record.get("label") or ""

        curie = iri_to_curie(record.get("term_id", ""))
        if curie is None:
            tally["unparseable_id"] += 1
            print(f"UNPARSEABLE  {where}: term_id {record.get('term_id')!r}")
            continue
        prefix = curie.split(":", 1)[0]

        rule = FIELD_RULES.get(field)
        if rule and prefix not in rule.prefixes:
            tally["off_scope"] += 1
            print(f"OFF-SCOPE    {where}: {curie} ({prefix} not allowed for {field})")

        if prefix in UNRESOLVABLE_PREFIXES:
            tally["skipped"] += 1
            print(f"SKIPPED      {where}: {curie} ({prefix} not resolvable via OAK — verify manually)")
            continue

        status, canonical = checker.canonical_label(curie)
        if status == "error":
            tally["lookup_error"] += 1
            print(f"UNCHECKED    {where}: {curie} ({stored_label!r}) — lookup failed, not a verdict")
            continue
        if status == "missing":
            tally["not_found"] += 1
            print(f"NOT FOUND    {where}: {curie} ({stored_label!r})")
            continue
        if canonical.strip().casefold() != stored_label.strip().casefold():
            tally["label_drift"] += 1
            print(f"LABEL DRIFT  {where}: {curie} stored {stored_label!r}, canonical {canonical!r}")

        root = (rule.roots.get(prefix) if rule else None)
        if check_closure and root:
            verdict = checker.in_closure(curie, root)
            if verdict is False:
                tally["closure_fail"] += 1
                print(f"OUT OF SCOPE {where}: {curie} ({stored_label!r}) is not under {root} for {field}")
            elif verdict is None:
                tally["closure_unchecked"] += 1

        tally["ok"] += 1

    return tally


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotations", default=ANNOTATIONS_FILE,
                        help=f"KE annotations JSON (default: {ANNOTATIONS_FILE})")
    parser.add_argument("--ke", action="append", metavar="ID",
                        help="validate only this KE (repeatable)")
    parser.add_argument("--field", action="append", metavar="FIELD",
                        choices=sorted(FIELD_RULES),
                        help="validate only this field (repeatable)")
    parser.add_argument("--scheme", choices=("ols", "sqlite"), default="ols",
                        help="OAK adapter scheme: ols (network, no downloads; default) "
                             "or sqlite (local builds, enables --closure)")
    parser.add_argument("--closure", action="store_true",
                        help="also check ancestor-closure membership (needs --scheme sqlite)")
    args = parser.parse_args()

    if args.closure and args.scheme != "sqlite":
        parser.error("--closure requires --scheme sqlite (OLS adapters do not serve ancestors)")
    if args.scheme == "sqlite":
        try:
            import oaklib  # noqa: F401
        except ImportError:
            sys.exit("--scheme sqlite needs oaklib — run with the validation dependency group:\n"
                     "  uv run --group validation python -m aop_wiki_cli.annotation_scripts.validate_annotations --scheme sqlite")

    store = json.loads(Path(args.annotations).read_text())
    if args.ke:
        missing = [k for k in args.ke if k not in store]
        if missing:
            sys.exit(f"KE(s) not in store: {', '.join(missing)}")
        store = {k: store[k] for k in args.ke}

    checker = OntologyChecker(args.scheme)
    tally = validate_store(store, checker,
                           only_fields=set(args.field) if args.field else None,
                           check_closure=args.closure)

    print("\n" + "=" * 60)
    print(f"Checked {tally['checked']} term record(s): "
          f"{tally['ok']} ok, {tally['skipped']} skipped")
    for key in ("unparseable_id", "not_found", "lookup_error", "label_drift",
                "off_scope", "closure_fail", "closure_unchecked"):
        if tally[key]:
            print(f"  {key}: {tally[key]}")
    failures = tally["unparseable_id"] + tally["not_found"] + tally["closure_fail"]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
