# DILI AOP Collection

How to collect every AOP-Wiki AOP that covers drug-induced liver injury (DILI), together with its key
events (KEs) and key event relationships (KERs), and how the MIE/AO pairing table is produced from it.

## Approach

The collection is **event-first**, not title-first. Searching AOP titles for "liver" misses AOPs whose
title names a stressor or a mechanism but whose pathway runs through the liver. So the search matches
**key event titles** against a list of hepatic terms, then collects every AOP that contains one of those
key events, then collects everything else in those AOPs.

```text
hepatic terms
     ↓  match against KE titles
matched key events
     ↓  find the AOPs containing them
matched AOPs  ────────────────┐
     ↓  collect all their KEs │  select the KERs naming these AOPs
all KEs in those AOPs         └→ KERs in those AOPs
     ↓  read each AOP's MIEs and AOs
MIE × AO pair table
```

## Steps and the scripts used

| # | Step | Script / CLI command | Source |
| - | ---- | -------------------- | ------ |
| 1 | Define the hepatic search terms | `DILI` config | `src/aop_wiki_cli/configs/dili_aops.py` |
| 2 | Download and parse the AOP-Wiki XML export | `collect_xml_data` | `src/aop_wiki_cli/collection/get_aop_wiki_xml_data.py` |
| 3 | Match KE titles, find the AOPs holding them | `search_events_to_aops` | `src/aop_wiki_cli/search/event_first_search.py` |
| 4 | Collect every KE in the matched AOPs | `collect_events_from_matched_aops` | `src/aop_wiki_cli/collection/collect_associated_aop_wiki_entities.py` |
| 5 | Select the KERs belonging to the matched AOPs | `filter_kers_by_aop_ids` | `src/aop_wiki_cli/analysis/pair_mies_and_aos.py` |
| 6 | Pair each AOP's MIEs with its AOs | `build_mie_ao_pairs` | `src/aop_wiki_cli/analysis/pair_mies_and_aos.py` |
| 7 | Render the CSV and markdown tables | `pair-mies-and-aos` | `src/aop_wiki_cli/cli.py` |

Steps 2-7 all run from one command:

```bash
uv run aop-wiki-cli pair-mies-and-aos dili_aops
```

Useful variations:

```bash
# Write everything under a working directory of your choosing
uv run aop-wiki-cli --data-dir ~/dili-work pair-mies-and-aos dili_aops

# Re-run against a previously cached XML export instead of today's
uv run aop-wiki-cli pair-mies-and-aos dili_aops --date 09-18-2026

# Ignore the cache and re-download the XML export
uv run aop-wiki-cli pair-mies-and-aos dili_aops --force-refresh

# Print more than the default 25 pair rows to the console
uv run aop-wiki-cli pair-mies-and-aos dili_aops --limit 200
```

The first run for a given date parses the full XML export, which is slow; later runs for that date read
`<data-dir>/outputs/cache/<date>/`.

### The AOP and KE search on its own

If only the AOPs and KEs are wanted, without the KERs or the pairing table, the shipped search command
uses the same config and the same steps 2-4:

```bash
uv run aop-wiki-cli search-with-config dili_aops
```

### The KERs of a specific key event

To go the other way and list the KERs a particular KE takes part in, split by whether it sits upstream or
downstream:

```bash
uv run aop-wiki-cli find-kers-for-events --ke-ids 1616
uv run aop-wiki-cli find-kers-for-events --ke-terms "cholestasis,hepatic steatosis"
```

## Search terms

`SEARCH_PARAMS["ke_title_terms"]` in `src/aop_wiki_cli/configs/dili_aops.py` holds the term list, grouped as:

- **Organ and cell types** — liver, hepatic, hepatocyte(s), hepatocellular, hepatotoxicity, hepatitis,
  hepatobiliary, hepatotoxicant, Kupffer, stellate cell, cholangiocyte(s), sinusoidal
- **Hepatic adverse outcomes** — steatosis, steatohepatitis, cholestasis, cholestatic, cirrhosis, NAFLD,
  NASH, MASLD, MASH, fatty liver, DILI
- **Hepatic processes and receptors** — bile, bile acid, bile salt, biliary, BSEP, bile salt export pump,
  bile duct, LXR, liver X receptor, FXR, farnesoid X receptor, PXR, pregnane X receptor, constitutive
  androstane receptor

Terms are matched case-insensitively with word boundaries, so `hepatic` does not match `hepatocyte` —
both spellings and both plurals have to be listed.

Generic injury words (necrosis, fibrosis, apoptosis, inflammation) are deliberately **left out**. They
match key events in every organ, and a hepatic instance of them is collected anyway once the AOP it
belongs to is reached through one of the terms above.

The terms describe hepatic **biology**, not the drug stressor, which is broader than DILI on purpose:
AOP-Wiki key event titles describe mechanism ("Increase, Hepatic steatosis"), and rarely name the agent
class, so requiring a drug qualifier would drop liver AOPs that are squarely DILI-relevant. For the same
reason `drug-induced` is not a term -- it would match every organ ("Drug-induced QT prolongation"). The
acronym `DILI` is listed because it matches nothing else; the spelled-out "drug-induced liver injury" is
already caught by `liver`.

`aop_title_exclusion_terms` is empty by default, so the collection stays inclusive. To drop
ecotoxicology AOPs that reach the liver in fish or invertebrates, add terms to that list in the config —
for example `fish`, `zebrafish`, `Danio rerio`, `Daphnia`, `mollusk`, `amphibian`, `vitellogenin`.

## Outputs

Written to `<data-dir>/outputs/dili_aops/`, where `<data-dir>` is `--data-dir`, `$AOP_WIKI_CLI_DATA_DIR`,
or the current directory:

| File | Contents |
| ---- | -------- |
| `dili_aops_entities_<date>.json` | `matched_events` (the KE title hits), `matched_aops` (AOPs containing them), `aop_events` (every KE in those AOPs), `aop_kers` (every KER in those AOPs), `mie_ao_pairs`, and a `summary` with the counts |
| `dili_aops_mie_ao_pairs_<date>.csv` | One row per AOP/MIE/AO combination |
| `dili_aops_mie_ao_pairs_<date>.md` | The same table as markdown |

### The MIE/AO pair table

One row per combination, so an AOP with two AOs contributes two rows:

| Column | Meaning |
| ------ | ------- |
| `aop_id`, `aop_title`, `oecd_status` | The AOP the pair comes from |
| `mie_id`, `mie_title` | A molecular initiating event of that AOP |
| `ao_id`, `ao_title` | An adverse outcome of that AOP |
| `mie_matched_search_term`, `ao_matched_search_term` | Whether that endpoint was itself one of the hepatic KE title hits, as opposed to being collected because its AOP was |
| `num_events_in_aop`, `num_kers_in_aop` | Size of the AOP the pair comes from |

MIE and AO are **roles within one AOP**, not properties of a key event: the same KE can be an MIE in one
AOP and an intermediate KE in another. The roles are read from the AOP's own
`<molecular-initiating-event>` and `<adverse-outcome>` XML elements and stored per AOP as `mie_ids` and
`ao_ids` by `collect_base_aop_info_from_xml`
(`src/aop_wiki_cli/parsers/parse_aop_wiki_xml_data.py`).

An AOP that declares no MIE, no AO, or neither still gets a row with the missing side blank, so gaps in
the collected set stay visible. `summary.mie_ao_pairs` counts them as `aops_without_mie` and
`aops_without_ao`.

## Tests

`tests/test_pair_mies_and_aos.py` covers the role parsing and the pairing, offline, against a small XML
fixture and mock entity dictionaries:

```bash
uv run python -m pytest tests/test_pair_mies_and_aos.py
```
