# KE Grouping — LLM Model Comparison (November 2026)

## Purpose

Evaluate whether the Key Event (KE) grouping pipeline
(`annotation_scripts/collect_similar_events.py`) should switch its LLM from the
original **Opus 4.5** baseline to the cheaper **`claude-sonnet-5-5`**, and
whether running `claude-sonnet-5-5` with extended thinking on or off changes the
result.

**Bottom line:** no formal quality metric exists yet, so the numbers below
describe how the runs **differ**, not which is provably **better**. On that
basis a **pragmatic decision** has been taken: downstream work proceeds with the
tighter **`11-25-2026_sonnet_5-5_thinking_on`** set. The groupings Opus 4.5 made
that `claude-sonnet-5-5` did not can be revisited later if a downstream step
needs them. See [Decision](#decision--open-question).

---

## Setup

- **Input:** identical event cache for all runs
  (`outputs/cache/11-25-2026/all_events_11-25-2026.json`, 1478 eligible events),
  so the **only** variable between the sonnet runs is the model/thinking config.
- **Pipeline:** unchanged three-pass grouping (Pass 1 intra-batch, Pass 2
  cross-batch consolidation, Pass 3 straggler sweep); batch sizes 200 / 50.
- **Comparison tool:** `annotation_scripts/compare_grouping_runs.py`, which
  matches groups across runs by **member-ID overlap (Jaccard)** because group
  keys are not stable between runs. Default match threshold `--min-overlap 0.5`.
- **Provenance:** runs now stamp a `metadata.run_provenance` block (script
  commit, model, thinking config, batch sizes, per-pass token budgets). Runs
  made before that feature show no block.

### Runs (all under `outputs_for_vc/ke_groupings/`)

| Directory | Model | Thinking | Status |
|---|---|---|---|
| `11-25-2026_opus_4-5` | Opus 4.5¹ | — | Baseline |
| `11-25-2026_truncatede_first_sonnet_5-5` | `claude-sonnet-5-5` | adaptive (on) | **Discarded — truncated** |
| `11-25-2026_sonnet_5-5` | `claude-sonnet-5-5` | off (`between_tools`) | Clean |
| `11-25-2026_sonnet_5-5_thinking_on` | `claude-sonnet-5-5` | adaptive (on) | Clean |

¹ The baseline run predates provenance stamping, so its model is not recorded
in-file; "Opus 4.5" is per the directory label.

---

## What we changed along the way

Switching the model was **not** a clean one-line swap; two issues surfaced and
were fixed (see commit history on branch `liver-microphys`):

1. **Response parsing.** Current-generation models run adaptive thinking by
   default, so the response's first content block can be a *thinking* block.
   The code read `message.content[0].text`; it now selects the first **text**
   block via `_response_text()`.
2. **Token-budget truncation (why the first sonnet run was discarded).** With
   thinking on, reasoning shares the per-pass `max_tokens` budget with the JSON
   output. At the original budgets (8192 / 4096 / 8192) this truncated Pass 1
   `batch_000` (parsed as empty) and several Pass 3 batches, deflating the
   counts — that run is kept only as `..._truncatede_first_sonnet_5-5`. Fixes:
   - **Thinking-off run:** `thinking={"type": "between_tools"}` hands the full
     budget back to the JSON (this task issues no tool calls, so thinking is
     effectively disabled).
   - **Thinking-on run:** budgets raised to **16384 / 8192 / 16384** so thinking
     has headroom; no truncation observed.
3. **Parser hardening.** `claude-sonnet-5-5` with thinking off sometimes leaks
   reasoning into the visible text after the JSON (e.g. an array followed by
   `"Correction: … Final answer:"`). `_parse_json_from_response` now decodes the
   first complete JSON value with `json.JSONDecoder.raw_decode` and ignores
   trailing prose. Covered by `tests/test_parse_json_from_response.py`.

---

## Results

### Per-run totals (same 1478-event input)

| Run | Model / config | Groups | Grouped events | Ungrouped |
|---|---|--:|--:|--:|
| `11-25-2026_opus_4-5` | Opus 4.5 | 472 | 1076 | 402 |
| `11-25-2026_sonnet_5-5` | sonnet-5-5, thinking **off** | 249 | 581 | 897 |
| `11-25-2026_sonnet_5-5_thinking_on` | sonnet-5-5, thinking **on** | 155 | 437 | 1042 |

Conservatism is monotonic: **Opus 4.5 (1076) → sonnet-off (581) → sonnet-on
(437)**. Thinking makes `claude-sonnet-5-5` *stricter*, not looser.

### Agreement with the Opus 4.5 baseline (`--min-overlap 0.5`)

| vs baseline | identical groups | changed | dropped (baseline-only) | new (sonnet-only) | events in both | events baseline-only | events sonnet-only |
|---|--:|--:|--:|--:|--:|--:|--:|
| sonnet-5-5 **off** | 114 | 80 | 278 | 62 | 534 | 542 | 47 |
| sonnet-5-5 **on** | 65 | 59 | 348 | 36 | 404 | 672 | 33 |

### sonnet-off vs sonnet-on (direct)

- Groups 249 → 155; grouped events 581 → 437.
- 74 identical groups, 39 changed, 136 dropped (off-only), 45 new (on-only),
  3 merges, 21 splits.
- Of grouped events: 351 in both, 230 off-only, 86 on-only (thinking-on dropped
  230 of thinking-off's grouped events and added 86; net −144).

### Expected-pairing regression tests (`tests/test_expected_ke_groupings.py`)

The fixture holds **5** curated positive pairings (the only ground-truth signal
currently in the repo).

| Run | Result | Missed |
|---|---|---|
| Opus 4.5 | 5 / 5 | — |
| sonnet-5-5 off | 4 / 5 | `NMDAR_directional_opposites` |
| sonnet-5-5 on | 4 / 5 | `Hepatocellular_carcinoma_synonyms` |

The two sonnet runs miss **different** pairings — partly a real config
difference, partly run-to-run LLM nondeterminism. 5 cases cannot rank the runs.

---

## Reading of the numbers (neutral)

1. **Monotonic conservatism** (above).
2. **Thinking-off tracks the Opus baseline more closely** than thinking-on
   (114 vs 65 identical groups; 534 vs 404 events grouped in both).
3. **sonnet-5-5's groupings are largely a *subset* of Opus 4.5's** — only 47
   (off) / 33 (on) events are grouped by sonnet but **not** by the baseline. So
   `claude-sonnet-5-5` is not grouping *differently*; it is doing a stricter
   slice of the same thing.

None of these is a quality claim. Fewer groups could mean **higher precision**
(sonnet correctly declining spurious merges) or **lower recall** (sonnet missing
valid groupings) — the counts cannot tell these apart.

---

## Reproducibility (replicates of the chosen config)

The chosen config (`claude-sonnet-5-5`, thinking on) has now been run three
times, giving two replicate comparisons:

| Pair | What varies | A → B |
|---|---|---|
| `11-25` → `11-27 AM` | model sampling **+ 2 days of wiki content** (different event caches) | committed baseline → `11-27-2026_sonnet_5-5_thinking_on_run_a` |
| `11-27 AM` → `11-27 PM` | model sampling **only** (identical cache, same code, ~3 h apart) | `..._run_a` → `..._run_b` |

Both compared with `compare_grouping_runs.py` at `--min-overlap 0.5`; both B
runs are `run_status.complete: true` from clean commits.

| Metric | 11-25 → 11-27 AM | 11-27 AM → PM |
|---|--:|--:|
| groups (A → B) | 155 → 167 | 167 → 166 |
| identical groups | 72 (46%) | 70 (42%) |
| changed / dropped / new | 38 / 45 / 58 | 41 / 56 / 55 |
| splits | 18 | 20 |
| grouped events (A → B) | 437 → 479 | 479 → 445 |
| events grouped in both | 350 (80% of A) | 358 (75% of A) |

Identical-group rate by type (A's perspective):

| Type | 11-25 → 11-27 AM | 11-27 AM → PM |
|---|--:|--:|
| merge | 24/37 (65%) | 20/31 (65%) |
| soda | 10/15 (67%) | 11/18 (61%) |
| same_object_different_process | 14/36 (39%) | 23/40 (58%) |
| similar_event_different_biological_context | 24/67 (36%) | 16/78 (21%) |

**Reading:**

1. **Same-day replication is no tighter than the cross-day comparison** (42%
   vs 46% identical; 75% vs 80% membership retained). The drift measured
   across two days was therefore essentially all **model sampling variance**;
   wiki-content change contributed ~nothing. This is the replicate evidence
   the caveat below asked for.
2. **Stability is strongly type-dependent.** `merge` is the reproducible core
   (65% identical in both pairs, 1–4 drops); `soda` and
   `same_object_different_process` are moderately stable; `similar_event_
   different_biological_context` is a different, partially overlapping
   **sample of borderline pairs on every run** (21–36% identical, and it
   supplies most drops and most new groups in both pairs). Single-run claims
   about SEDC coverage should say so; if reproducible SEDC ever matters,
   aggregate replicates via the member-overlap matcher (union or intersection).
3. **Aggregate conservatism replicates even though individual groups do not.**
   Thinking-on grouped 437 / 479 / 445 events across its three runs (±5%),
   versus thinking-off's 581 — so the monotonic-conservatism finding above is
   robust to sampling noise. By contrast, the off-vs-on *group-level* overlap
   (74 identical groups) is the same order as the within-config replicate
   overlap (70–72), so group-by-group differences between those configs should
   not be read as config effects.

Data: both same-day replicates are committed under
`outputs_for_vc/ke_groupings/` as `11-27-2026_sonnet_5-5_thinking_on_run_a/`
(AM; the one the 11-25 comparison used) and
`11-27-2026_sonnet_5-5_thinking_on_run_b/` (PM), with the comparisons beside
them: `nov25_vs_nov27.json` + `nov25_to_nov27_crosswalk.csv` (at the
`outputs_for_vc/` root) and `nov27_a_vs_nov27_b.json` +
`nov27_a_to_nov27_b_crosswalk.csv`.

---

## Caveats

- **No correctness metric.** There is no labeled set of "must-group" **and**
  "must-not-group" cases, so precision/recall are unmeasured. "More grouped" is
  **not** known to be "better."
- **Run-to-run nondeterminism — now partially measured.** The thinking-on
  config has replicates (see [Reproducibility](#reproducibility-replicates-of-the-chosen-config)):
  aggregate totals replicate within ~5%, but group-level overlap between
  replicates is only ~42–46%, so group-by-group differences between configs
  are mostly indistinguishable from sampling variance. The thinking-off and
  Opus configs remain single runs.
- **Threshold sensitivity.** `--min-overlap 0.5` inflates "dropped": a group
  whose members mostly scatter counts as fully dropped. Re-run with
  `--min-overlap 0.3` to see how much "dropped" reclassifies as "changed".
- **Cost.** The motivation for `claude-sonnet-5-5` is price (roughly ⅓–½ of the
  Opus tier). That saving only matters if grouping quality is acceptable, which
  is exactly what is unmeasured.

---

## Decision / open question

**Decision (2026-11-25):** downstream work proceeds with
**`11-25-2026_sonnet_5-5_thinking_on`** (155 groups, 437 grouped events). The
tighter set is acceptable for the next steps, and the cost saving over the Opus
tier is banked. This is a pragmatic choice on the current evidence, **not** a
proven-quality verdict.

**Deferred, not closed.** The open question remains:

> The **~670 events that Opus 4.5 grouped but the thinking-on
> `claude-sonnet-5-5` run did not** — are those groupings Opus got **right**
> (sonnet is under-grouping) or ones Opus **over-made** (sonnet correctly
> declined)?

If a downstream step turns out to need some of those "missing" groupings, or if
grouping quality needs to be defended, revisit with a proper evaluation:

1. Sample the baseline-only groupings, the sonnet-only groupings, and the
   splits; print them as titles for a curator to mark keep / reject.
2. Fold those labels into an expanded `tests/expected_ke_groupings.json` with
   **positives and negatives**.
3. Add a scoring harness that reports **precision and recall per run**, turning
   "different" into "better / worse".

The other runs (`11-25-2026_opus_4-5`, `11-25-2026_sonnet_5-5`) are retained in
version control so that revisit is possible without re-running the models.

---

## Reproduce

```bash
# Per-run totals and provenance
uv run python -c "import json,sys; m=json.load(open(sys.argv[1]))['metadata']; \
print(m.get('run_provenance')); print('grouped', m['total_grouped_events'])" \
  outputs_for_vc/ke_groupings/11-25-2026_sonnet_5-5/ke_similar_events_11-25-2026_pass3.json

# Compare any two runs (writes an optional per-group crosswalk CSV)
uv run python -m aop_wiki_cli.annotation_scripts.compare_grouping_runs \
  --file-a outputs_for_vc/ke_groupings/11-25-2026_opus_4-5/ke_similar_events_11-25-2026_pass3.json \
  --file-b outputs_for_vc/ke_groupings/11-25-2026_sonnet_5-5/ke_similar_events_11-25-2026_pass3.json \
  --crosswalk-csv crosswalk.csv

# Regression tests against a specific run
KE_GROUPINGS_FILE=outputs_for_vc/ke_groupings/11-25-2026_sonnet_5-5/ke_similar_events_11-25-2026_pass3.json \
  uv run --with pytest python -m pytest tests/test_expected_ke_groupings.py -q
```
