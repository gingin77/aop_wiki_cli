"""
Group AOP-Wiki Key Events by title similarity using an LLM.

Reads all Event IDs and titles from outputs/cache/<date>/all_events_<date>.json,
sends them to Claude in batches to identify groups of events describing the same
underlying biology, then consolidates cross-batch groups in a second pass.

Three-pass approach
-------------------
Pass 1 — Intra-batch grouping (~150 events per batch):
    Each batch returns a list of groups (group_key, type, member IDs, rationale).
    Results are cached per-batch under outputs/ke_groupings/<date>/batches/
    so interrupted runs resume without re-calling the LLM.

Pass 2 — Cross-batch consolidation:
    All Pass 1 groups are sent to the LLM in a single call. The LLM returns
    only merge instructions (keep/absorb pairs) — not a full re-output of all
    groups — so output tokens are proportional to the number of merges found.
    Merges are applied in Python by `_apply_consolidation_merges`. Result
    snapshot written to ke_similar_events_<date>_pass2.json.

Pass 3 — Straggler sweep (optional; skip with --skip-pass3):
    Processed-but-ungrouped events are swept in batches (PASS_3_BATCH_SIZE events
    each) against all existing groups. The LLM assigns stragglers to existing
    groups or forms new groups among them — catching cross-batch matches missed by
    Pass 1. Result snapshot written to ke_similar_events_<date>_pass3.json.

Output
------
outputs/ke_groupings/<date>/ke_similar_events_<date>_pass2.json  (always written)
outputs/ke_groupings/<date>/ke_similar_events_<date>_pass3.json  (when Pass 3 runs)

Top-level JSON keys:
  metadata          — run statistics, per-type group/event counts, and a
                       run_provenance block (script commit, LLM model, batch
                       sizes and per-pass token budgets that produced the run)
  events_to_merge   — "merge" groups: {group_key: {merged_event_titles, rationale,
                       shared_aop_check}}
  soda_events       — "soda" groups (Same Object, Directionally Opposite):
                       same endpoint measured in strictly opposite directions
  same_object_different_process_events
                    — same biological target, distinct process (e.g. binding vs
                       inhibition of the same molecule)
  similar_event_different_biological_context_events
                    — same process but one specifies a cell type, tissue, organ,
                       or compartment that the other lacks or differs in
  ungrouped_processed_events
                    — {id: title} events that were processed but not placed in
                       any group

Each group includes a shared_aop_check field reporting whether all member events
co-occur in the same AOP, distinguishing non-OFA from open-for-adoption AOPs.

Usage
-----
    uv run python annotation_scripts/collect_similar_events.py
    uv run python annotation_scripts/collect_similar_events.py --date 05-06-2026
    uv run python annotation_scripts/collect_similar_events.py --batch-size 100
    uv run python annotation_scripts/collect_similar_events.py --max-batches 2
    uv run python annotation_scripts/collect_similar_events.py --skip-pass3
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone

import anthropic
from dotenv import load_dotenv

# Add project root so src.* imports work when run from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.utilities import set_up_logger, get_dated_cache_dir
from src.parsers import collect_entity_with_cache, collect_aops_from_xml, collect_events_from_xml

load_dotenv(override=True)

logger = set_up_logger("collect-similar-events", level=logging.INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR_ROOT = "outputs/cache"
OUTPUT_DIR_ROOT = "outputs/ke_groupings"

LLM_MODEL = "claude-sonnet-4-6"
DEFAULT_BATCH_SIZE = 200
PASS_3_BATCH_SIZE = 50  # ungrouped events per Pass 3 LLM call (keep low to avoid output token truncation)

# Output token budgets per pass, referenced both at the LLM call sites and in the
# run-provenance stamp so the recorded value can never drift from what actually ran.
PASS_1_MAX_TOKENS = 8192
PASS_2_MAX_TOKENS = 4096
PASS_3_MAX_TOKENS = 8192

_SCRIPT_PATH = os.path.abspath(__file__)


def _git_commit() -> tuple[str | None, bool | None]:
    """Return (short_commit_sha, dirty) for this checkout, or (None, None).

    `dirty` is True when the working tree has uncommitted changes (so the running
    code may differ from the recorded commit). Both are None when git is
    unavailable or this is not a repository — provenance degrades gracefully
    rather than failing a run.
    """
    repo_dir = os.path.dirname(_SCRIPT_PATH)
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True, check=True,
        ).stdout
        return sha or None, bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _run_provenance(batch_size: int) -> dict:
    """Record the code and parameters that produced a grouping run.

    Stamped into the output metadata so a snapshot is self-documenting: which
    script commit, LLM model, batch sizes and per-pass token budgets ran. The
    model and token budgets were previously only hardcoded constants, invisible
    in the output.
    """
    sha, dirty = _git_commit()
    return {
        "script": os.path.relpath(_SCRIPT_PATH, os.path.dirname(os.path.dirname(_SCRIPT_PATH))),
        "git_commit": sha,
        "git_dirty": dirty,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "llm_model": LLM_MODEL,
        "pass_1_batch_size": batch_size,
        "pass_3_batch_size": PASS_3_BATCH_SIZE,
        "pass_1_max_tokens": PASS_1_MAX_TOKENS,
        "pass_2_max_tokens": PASS_2_MAX_TOKENS,
        "pass_3_max_tokens": PASS_3_MAX_TOKENS,
    }

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _ensure_caches(date_str: str) -> tuple[str, str]:
    """Ensure event and AOP cache files exist for date_str, generating them if needed.

    Returns (event_cache_path, aop_cache_path).
    """
    work_date = date.today()
    cache_dir = get_dated_cache_dir(CACHE_DIR_ROOT, work_date)
    os.makedirs(cache_dir, exist_ok=True)

    event_cache_path = os.path.join(cache_dir, f"all_events_{date_str}.json")
    aop_cache_path = os.path.join(cache_dir, f"all_aops_{date_str}.json")

    if not os.path.exists(event_cache_path):
        logger.info("Generating event cache for %s...", date_str)
        collect_entity_with_cache("events", collect_events_from_xml, work_date, cache_dir, True, logger)

    if not os.path.exists(aop_cache_path):
        logger.info("Generating AOP cache for %s...", date_str)
        collect_entity_with_cache("aops", collect_aops_from_xml, work_date, cache_dir, True, logger)

    return event_cache_path, aop_cache_path


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _make_client() -> anthropic.Anthropic | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — LLM calls will be skipped.")
        return None
    return anthropic.Anthropic(api_key=api_key)


def _call_with_retry(
    client: anthropic.Anthropic,
    *,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    max_retries: int = 3,
    base_delay: float = 5.0,
) -> anthropic.types.Message:
    """Call client.messages.create with exponential-backoff retry on 5xx errors."""
    import time
    for attempt in range(max_retries):
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
        except anthropic.InternalServerError as exc:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Anthropic 500 error (attempt %d/%d): %s — retrying in %.0fs.",
                attempt + 1, max_retries, exc, delay,
            )
            time.sleep(delay)


def _parse_json_from_response(raw: str) -> dict | list | None:
    """Extract and parse the first JSON object or array from an LLM response.

    Handles responses wrapped in markdown code fences (```json ... ```) as well
    as bare JSON embedded in prose.
    """
    # Prefer content inside a markdown code fence
    fence_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*```', raw)
    if fence_match:
        candidate = fence_match.group(1)
    else:
        # Fall back: find the first [ or { and take everything from there
        first = re.search(r'[\[\{]', raw)
        if not first:
            logger.error("Could not find JSON in LLM response: %r", raw[:200])
            return None
        candidate = raw[first.start():]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error: %s — raw: %r", exc, raw[:200])
        return None


# ---------------------------------------------------------------------------
# Group-key uniqueness helpers
# ---------------------------------------------------------------------------

def _unique_key(base: str, used) -> str:
    """Return `base` if unused, else `base_2`, `base_3`, ... not already in `used`.

    `used` may be any container supporting `in` membership (a set, or a dict
    keyed by group_key).
    """
    if base not in used:
        return base
    n = 2
    while f"{base}_{n}" in used:
        n += 1
    return f"{base}_{n}"


def _dedupe_group_keys(groups: list[dict]) -> list[dict]:
    """Make every group's `group_key` distinct (mutates the dicts in place).

    The LLM assigns group_keys independently per batch, so the same key can
    recur across batches for unrelated groups. Downstream code — Pass 2
    consolidation (`_apply_consolidation_merges`), output assembly, and the
    compare script — treats group_key as a unique identifier, and a collision
    there silently drops a group's members. Renaming collisions to `<key>_2`,
    `<key>_3`, ... before any of that runs keeps each group addressable.
    """
    seen: set[str] = set()
    for group in groups:
        base = group.get("group_key") or "group"
        key = _unique_key(base, seen)
        seen.add(key)
        group["group_key"] = key
    return groups


# ---------------------------------------------------------------------------
# Shared prompt guardrails (appended to all three pass prompts)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shared group type definitions (used by Pass 1 and Pass 3 prompts)
# ---------------------------------------------------------------------------

_GROUP_TYPE_DEFINITIONS = """
  "merge"  — events that should be merged because they describe the same biological
             event in the same direction, using different wording, abbreviations, or
             specificity (e.g. "collagen accumulation" and "collagen deposition", or
             "TGF-beta activation" and "TGF-β, Activation").

  "same_object_different_action (soda)" — Same Object, Directionally Opposite: events
             that measure the same biological endpoint but in STRICTLY OPPOSITE
             directions — one increases and the other decreases, or one activates and
             the other inhibits the SAME receptor/protein (e.g. "Increase, Plasma
             vitellogenin" paired with "Reduction, Plasma vitellogenin"; or "Agonism,
             Estrogen receptor" paired with "Antagonism, Estrogen receptor").
             IMPORTANT: "soda" is ONLY for directional opposites of the identical
             endpoint. Do NOT use "soda" for a "binding" event paired with an
             "inhibition" or "activation" event — those belong in
             "same_object_different_process".

  "same_object_different_process" — events that share the same biological target
             or object but involve clearly distinct processes that cannot be assumed
             equivalent without additional context. The most common case is a
             "binding" event paired with an "inhibition", "activation", or
             "degradation" event for the same molecule: binding does not imply a
             functional outcome, so these must NOT be classified as "soda" or "merge".
             Group them here so curators can review whether the functional relationship
             is documented. Example: "Binding of inhibitor, Complex I" and
             "Inhibition, Complex I" share the same object but binding alone does not
             confirm inhibition — use "same_object_different_process", not "soda".
             IMPORTANT: "same object" means the IDENTICAL molecule, receptor, or
             entity — not merely related molecules. An enzyme and its substrate or
             product are DIFFERENT objects (e.g. aromatase ≠ estradiol; AChE ≠
             acetylcholine). Do NOT group events across different biological objects
             even if they are part of the same pathway.

  "similar_event_different_biological_context" — events that describe the same
             process in the same direction, but one specifies a biological context
             (cell type, tissue, organ, compartment) while the other either does not list
             a biological context or the biological context is different. These
             should NOT be merged because the specificity difference is biologically
             meaningful for AOP placement. Group them here for curator review.
             Example: "Inhibition, Aromatase" (general) paired with "reduction in
             ovarian granulosa cells, Aromatase (Cyp19a1)" (cell-specific); or "liver
             fibrosis" paired with "pulmonary fibrosis".
"""

_GROUPING_MISTAKES = """
CRITICAL MISTAKES TO AVOID:

1. Do NOT put events with conflicting directions into the same "merge" group.
   Check whether the group members are increases or decreases and only include
   events going the SAME direction. If two events describe the same endpoint in
   opposite directions, they belong in a "soda" group together — not a merge group.
   Two small precise merge groups (one for each direction) is better than one large
   SODA group. Only fall back to a SODA group when no same-direction merge partner
   exists. Do NOT create a SODA group with 4+ members when the existing merge group
   already has 3+ — leave the opposing event ungrouped instead.
   BAD EXAMPLE: Putting "Increase, Fatty acid beta-oxidation" or "Increase, Lipid
   degradation" into a merge group whose other members all describe DECREASED
   fatty acid beta-oxidation.
   BAD EXAMPLE: Putting "Decrease, Triglyceride" into a merge group whose other
   members all describe INCREASED triglyceride formation/accumulation.

2. Do NOT put pathway-adjacent or downstream events into the same "merge" group.
   Merge means synonym-level equivalence only. Events that are upstream causes,
   downstream effects, or co-regulated pathway members of a group's topic are NOT
   synonyms for each other.
   BAD EXAMPLE: Grouping "Activation, SREBF1", "Up Regulation, SCD-1", or
   "Increase, De novo lipogenesis" with "Up Regulation, FAS" (fatty acid synthase)
   — these are different molecules and processes in the same pathway.
   BAD EXAMPLE: Grouping "Activation, TGF-beta pathway" with "Increase, Collagen
   accumulation" — TGF-beta activation is an upstream cause, not a synonym for
   collagen accumulation.

3. If you determine a group or assignment is not biologically justified, OMIT IT
   ENTIRELY. Do not output it with a rationale saying "withdrawing this grouping"
   or "these are different biological events". Simply do not include it.

4. Do NOT combine events that operate at different levels of biological scale or
   specificity using "merge", "soda", or "same_object_different_process".
   A generalized process that can occur across many tissue types is NOT equivalent
   to an organ-specific or tissue-specific form of that process, even if they share
   the same general mechanism.
   In particular, organ-level fibrosis events (liver fibrosis, pulmonary fibrosis,
   cardiac fibrosis, renal fibrosis) must NOT be placed in a "merge" group with each
   other or with cellular/tissue-level events like "Increase, Collagen accumulation"
   — fibrosis at a specific organ is a pathological outcome, while collagen
   accumulation is a cellular/ECM process that may contribute to fibrosis in any
   tissue.
   HOWEVER, multiple organ-specific fibrosis events (e.g. "Increase, Liver fibrosis"
   + "Increase, Pulmonary fibrosis" + "Increase, Cardiac fibrosis") ARE appropriate
   candidates for a "similar_event_different_biological_context" group — they describe
   the same process (fibrosis) in different organ contexts.
   Similarly, "Increase, Liver fibrosis" paired with "Increase, Collagen accumulation"
   may belong in "similar_event_different_biological_context" (organ-level outcome vs.
   cellular process contributing to it), not "merge".
   BAD EXAMPLE: Merging "Increase, Liver fibrosis" with "Increase, Collagen
   accumulation" — liver fibrosis is organ-level pathology; collagen accumulation
   is a cellular process. Use "similar_event_different_biological_context" instead.
   BAD EXAMPLE: Merging "Increase, Liver fibrosis" with "Increase, Pulmonary
   fibrosis" — these are the same process in different organs. Use
   "similar_event_different_biological_context" instead.
"""

# ---------------------------------------------------------------------------
# Shared grouping rules (used by Pass 1 and Pass 3 prompts)
# ---------------------------------------------------------------------------

_GROUPING_RULES = """
Grouping rules:
- Do NOT group events that are merely related (e.g. "inflammation" and
  "macrophage infiltration" should NOT be grouped).
- Each event ID may appear in at most one group.
- Only group or assign an event when the match is clear and biologically
  justified — do not force groupings.
- When in doubt between "merge" and "same_object_different_process", choose
  "same_object_different_process" to flag curator review.
- When one event adds a cell type, tissue, organ, or compartment qualifier that
  the paired event lacks, use "similar_event_different_biological_context" rather
  than "merge".
"""

# ---------------------------------------------------------------------------
# Pass 1 — Intra-batch grouping
# ---------------------------------------------------------------------------

BATCH_SYSTEM_PROMPT = (
    """You are a biologist reviewing AOP-Wiki Key Event (KE) titles.
Your task: identify groups of events that describe the same underlying biological
object, process, or phenotype and classify each group as one of four types:
"""
    + _GROUP_TYPE_DEFINITIONS
    + _GROUPING_RULES
    + """
Reply with ONLY a JSON array of group objects. Each object must have:
  "group_key":   a short snake_case identifier for the group
  "type":        "merge", "soda", "same_object_different_process", or "similar_event_different_biological_context"
  "member_ids":  array of string event IDs in this group (minimum 2)
  "rationale":   one sentence explaining why these are grouped

Example:
[
  {
    "group_key": "collagen_accumulation",
    "type": "merge",
    "member_ids": ["ID_A", "ID_B"],
    "rationale": "Both describe increased collagen deposition in tissue."
  },
  {
    "group_key": "vitellogenin_plasma_levels",
    "type": "soda",
    "member_ids": ["ID_C", "ID_D"],
    "rationale": "Both measure plasma vitellogenin but in opposite directions."
  },
  {
    "group_key": "complex_i_binding_vs_inhibition",
    "type": "same_object_different_process",
    "member_ids": ["ID_X", "ID_Y"],
    "rationale": "Both target Complex I but binding does not confirm inhibition without additional context."
  },
  {
    "group_key": "aromatase_inhibition_general_vs_granulosa",
    "type": "similar_event_different_biological_context",
    "member_ids": ["ID_E", "ID_F"],
    "rationale": "Both describe aromatase inhibition but one specifies ovarian granulosa cells while the other is general."
  }
]

If there are no similar pairs in this batch, reply with: []
"""
    + _GROUPING_MISTAKES
)


def _build_batch_prompt(batch: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"  ID {ke_id}: {title}" for ke_id, title in batch)
    return f"Review these {len(batch)} AOP-Wiki Key Events and group similar ones:\n\n{lines}"


def _run_batch(
    client: anthropic.Anthropic,
    batch: list[tuple[str, str]],
    batch_idx: int,
) -> list[dict]:
    """Call the LLM for one batch. Returns a list of group dicts."""
    logger.info("  Batch %d: %d events", batch_idx, len(batch))
    prompt = _build_batch_prompt(batch)
    message = _call_with_retry(
        client,
        model=LLM_MODEL,
        max_tokens=PASS_1_MAX_TOKENS,
        system=BATCH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if message.stop_reason == "max_tokens":
        logger.warning("  Batch %d: response truncated (max_tokens reached) — output may be incomplete.", batch_idx)
    raw = message.content[0].text.strip()
    parsed = _parse_json_from_response(raw)
    if not isinstance(parsed, list):
        logger.warning("  Batch %d: unexpected response shape, skipping.", batch_idx)
        return []
    # Filter out malformed entries
    valid = []
    for item in parsed:
        if (
            isinstance(item, dict)
            and isinstance(item.get("member_ids"), list)
            and len(item["member_ids"]) >= 2
        ):
            valid.append(item)
    logger.info("  Batch %d: %d group(s) found.", batch_idx, len(valid))
    return valid


def _iter_batches(
    events: dict[str, str],
    batch_size: int,
    max_batches: int | None = None,
) -> list[tuple[int, list[tuple[str, str]]]]:
    """
    Slice events into numbered batches of batch_size.
    Returns a list of (batch_idx, batch) tuples where batch is [(id, title), ...].
    Stops after max_batches batches when set.
    """
    items = list(events.items())  # [(id, title), ...]
    result = []
    for batch_idx, start in enumerate(range(0, len(items), batch_size)):
        if max_batches is not None and batch_idx >= max_batches:
            logger.info("_iter_batches: reached --max-batches limit (%d). Stopping early.", max_batches)
            break
        result.append((batch_idx, items[start : start + batch_size]))
    return result


def run_pass1(
    client: anthropic.Anthropic,
    events: dict[str, str],
    batch_size: int,
    batches_dir: str,
    max_batches: int | None = None,
) -> tuple[list[dict], set[str]]:
    """
    Split events into batches, run intra-batch grouping, cache each result.
    Returns (all_groups, processed_ids) where processed_ids is the set of
    event IDs that were actually included in a batch (may be a subset when
    --max-batches is set).

    max_batches: if set, stop after this many batches (useful for testing).
    """
    os.makedirs(batches_dir, exist_ok=True)
    all_groups: list[dict] = []
    processed_ids: set[str] = set()

    for batch_idx, batch in _iter_batches(events, batch_size, max_batches):
        processed_ids.update(ke_id for ke_id, _ in batch)
        cache_path = os.path.join(batches_dir, f"batch_{batch_idx:03d}.json")

        if os.path.exists(cache_path):
            logger.info("Pass 1 batch %d: loading from cache (%s)", batch_idx, cache_path)
            with open(cache_path) as f:
                groups = json.load(f)
        else:
            groups = _run_batch(client, batch, batch_idx)
            with open(cache_path, "w") as f:
                json.dump(groups, f, indent=2)

        all_groups.extend(groups)

    _dedupe_group_keys(all_groups)
    return all_groups, processed_ids


# ---------------------------------------------------------------------------
# Pass 2 — Cross-batch consolidation
# ---------------------------------------------------------------------------

CONSOLIDATION_SYSTEM_PROMPT = """You are a biologist reviewing groups of AOP-Wiki Key Events
that were identified as similar within separate batches.

Each group has a "type" of "merge", "soda", "same_object_different_process",
or "similar_event_different_biological_context".

Your task: identify groups from different batches that describe the same underlying
biological event and should be merged into one. Only merge groups that share the
same type. For example, a batch-1 group "collagen_accumulation" and a batch-2
group "collagen_deposition" should be merged because they describe the same process.

Rules:
- Only merge groups that clearly refer to the same biological event.
- Do not merge groups that are merely related.
- Do not change the type of any group.
- A group may only appear in one merge instruction.

Reply with ONLY a JSON array of merge instructions. Each instruction identifies
one group to keep and one or more groups to absorb into it:
  {
    "keep":   "<group_key to keep>",
    "absorb": ["<group_key>", ...],
    "rationale": "<one sentence>"
  }

If no cross-batch duplicates exist, reply with: []
Do NOT re-output groups that have no match — only list merges.
""" + _GROUPING_MISTAKES


def _build_consolidation_prompt(groups: list[dict]) -> str:
    lines = [f"Review these {len(groups)} groups for cross-batch duplicates to merge:\n"]
    for g in groups:
        lines.append(
            f'  group_key: {g["group_key"]!r}  type: {g.get("type", "merge")!r}\n'
            f'  rationale: {g.get("rationale", "")!r}\n'
        )
    return "\n".join(lines)


def _apply_consolidation_merges(
    all_groups: list[dict],
    merges: list[dict],
) -> list[dict]:
    """Apply merge instructions returned by the LLM to all_groups.

    Each instruction has {"keep": key, "absorb": [key, ...]}. The absorb groups'
    member_ids are folded into the keep group; absorb groups are removed.
    Returns a new list with duplicates removed and member_ids unified.
    """
    groups_by_key: dict[str, dict] = {g["group_key"]: g for g in all_groups}
    absorbed_keys: set[str] = set()

    for instruction in merges:
        keep_key = instruction.get("keep", "")
        absorb_keys = instruction.get("absorb", [])
        if keep_key not in groups_by_key:
            logger.warning("Pass 2: merge instruction references unknown keep key %r — skipping.", keep_key)
            continue
        keep_group = groups_by_key[keep_key]
        keep_ids: list = keep_group.setdefault("member_ids", [])
        keep_id_set = set(str(i) for i in keep_ids)
        for absorb_key in absorb_keys:
            if absorb_key not in groups_by_key:
                logger.warning("Pass 2: merge instruction references unknown absorb key %r — skipping.", absorb_key)
                continue
            for mid in groups_by_key[absorb_key].get("member_ids", []):
                mid_str = str(mid)
                if mid_str not in keep_id_set:
                    keep_ids.append(mid_str)
                    keep_id_set.add(mid_str)
            absorbed_keys.add(absorb_key)
            logger.debug("Pass 2: absorbed %r into %r", absorb_key, keep_key)

    result = [g for g in all_groups if g["group_key"] not in absorbed_keys]
    logger.info(
        "Pass 2: %d merge instructions applied; %d groups absorbed; %d groups remaining.",
        len(merges), len(absorbed_keys), len(result),
    )
    return result


def run_pass2(
    client: anthropic.Anthropic,
    all_groups: list[dict],
    consolidation_cache_path: str,
) -> list[dict]:
    """
    Merge cross-batch duplicate groups. Returns the final consolidated list.

    The LLM returns only merge instructions (keep/absorb pairs), not a full
    re-output of all groups — so output tokens are proportional to the number
    of merges found, not the number of groups. This allows all groups to be
    sent in a single call regardless of how many batches Pass 1 produced.

    Uses a cache file so re-runs skip the LLM call.
    """
    if not all_groups:
        logger.info("Pass 2: no groups to consolidate.")
        return []

    if os.path.exists(consolidation_cache_path):
        logger.info("Pass 2: loading consolidation from cache (%s)", consolidation_cache_path)
        with open(consolidation_cache_path) as f:
            return json.load(f)

    logger.info("Pass 2: sending %d groups for consolidation.", len(all_groups))
    prompt = _build_consolidation_prompt(all_groups)
    message = _call_with_retry(
        client,
        model=LLM_MODEL,
        max_tokens=PASS_2_MAX_TOKENS,
        system=CONSOLIDATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if message.stop_reason == "max_tokens":
        logger.warning("Pass 2: response truncated (max_tokens reached) — consolidation may be incomplete.")
    raw = message.content[0].text.strip()
    parsed = _parse_json_from_response(raw)
    if isinstance(parsed, list):
        consolidated = _apply_consolidation_merges(all_groups, parsed)
    else:
        logger.warning("Pass 2: unexpected response shape, returning groups unmerged.")
        consolidated = all_groups

    with open(consolidation_cache_path, "w") as f:
        json.dump(consolidated, f, indent=2)

    logger.info("Pass 2: %d final groups after consolidation.", len(consolidated))
    return consolidated


# ---------------------------------------------------------------------------
# Pass 3 — Straggler sweep (ungrouped events vs. existing groups)
# ---------------------------------------------------------------------------

PASS3_SYSTEM_PROMPT = (
    """You are a biologist reviewing AOP-Wiki Key Event titles.

You are given:
1. EXISTING GROUPS — groups already identified in earlier processing, each with a
   group_key, type, and the titles of their current members.
2. UNGROUPED EVENTS — events that were not placed in any group during earlier
   processing, each with an ID and title.

Your two tasks:
A. For each ungrouped event, decide if it clearly belongs in one of the existing
   groups. Apply the same type rules:
"""
    + _GROUP_TYPE_DEFINITIONS
    + _GROUPING_RULES
    + """
B. Among the ungrouped events themselves, identify any NEW groups (pairs or larger
   sets) not captured above. Use the same four types.

Reply with ONLY a JSON object with exactly two keys:

"existing_group_assignments": array of assignment objects:
  {
    "event_id": "<string ID of the ungrouped event>",
    "group_key": "<key of the existing group it belongs in>",
    "rationale": "<one sentence>"
  }

"new_groups": array of new group objects:
  {
    "group_key": "<snake_case identifier>",
    "type": "<merge|soda|same_object_different_process|similar_event_different_biological_context>",
    "member_ids": ["<id>", "<id>", ...],
    "rationale": "<one sentence>"
  }

If there are no assignments or new groups, use empty arrays.
"""
    + _GROUPING_MISTAKES
)


def _build_pass3_prompt(
    ungrouped_batch: list[tuple[str, str]],
    existing_groups: list[dict],
    events: dict[str, str],
) -> str:
    lines = ["EXISTING GROUPS:"]
    for g in existing_groups:
        titles = ", ".join(
            f'"{events.get(str(mid), str(mid))}"'
            for mid in g.get("member_ids", [])[:6]  # cap at 6 titles to save tokens
        )
        rationale = g.get("rationale", "")
        lines.append(
            f'  {g["group_key"]} (type={g.get("type","merge")}): {titles}'
        )
        if rationale:
            lines.append(f'    rationale: {rationale}')
    lines.append("")
    lines.append(f"UNGROUPED EVENTS ({len(ungrouped_batch)} total):")
    for ke_id, title in ungrouped_batch:
        lines.append(f"  ID {ke_id}: {title}")
    return "\n".join(lines)


def run_pass3(
    client: anthropic.Anthropic,
    ungrouped_events: dict[str, str],
    final_groups: list[dict],
    pass3_dir: str,
    pass3_cache_path: str,
    all_events: dict[str, str] | None = None,
) -> dict:
    """
    Sweep ungrouped events against existing groups (and each other).
    Returns a merged dict:
      {
        "existing_group_assignments": [...],
        "new_groups": [...]
      }
    Uses per-batch caches under pass3_dir; final merged result cached at
    pass3_cache_path.

    ``all_events`` should map every known event ID to its title so that
    existing-group members are rendered by title (not bare ID) in the
    prompt. Ungrouped events are always included in the lookup.
    """
    if not ungrouped_events:
        logger.info("Pass 3: no ungrouped events to sweep.")
        return {"existing_group_assignments": [], "new_groups": []}

    if os.path.exists(pass3_cache_path):
        logger.info("Pass 3: loading from cache (%s)", pass3_cache_path)
        with open(pass3_cache_path) as f:
            return json.load(f)

    os.makedirs(pass3_dir, exist_ok=True)
    items = list(ungrouped_events.items())
    # Title lookup for the prompt builder: must cover existing-group members
    # (from all_events) as well as the ungrouped events being swept.
    events_lookup = {**(all_events or {}), **ungrouped_events}

    all_assignments: list[dict] = []
    all_new_groups: list[dict] = []
    # Track which IDs have already been assigned so we don't duplicate
    assigned_ids: set[str] = set()

    for batch_idx, start in enumerate(range(0, len(items), PASS_3_BATCH_SIZE)):
        batch = items[start : start + PASS_3_BATCH_SIZE]
        cache_path = os.path.join(pass3_dir, f"batch_{batch_idx:03d}.json")

        if os.path.exists(cache_path):
            logger.info("Pass 3 batch %d: loading from cache.", batch_idx)
            with open(cache_path) as f:
                result = json.load(f)
        else:
            logger.info("Pass 3 batch %d: %d ungrouped events.", batch_idx, len(batch))
            prompt = _build_pass3_prompt(batch, final_groups, events_lookup)
            message = _call_with_retry(
                client,
                model=LLM_MODEL,
                max_tokens=PASS_3_MAX_TOKENS,
                system=PASS3_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if message.stop_reason == "max_tokens":
                # Genuinely skip a truncated batch: its JSON is incomplete, so
                # parsing it would yield partial/invalid assignments. Leave it
                # uncached so a later run (e.g. with a higher max_tokens) retries.
                logger.warning(
                    "Pass 3 batch %d: response truncated (max_tokens reached) — "
                    "batch skipped and not cached (will be retried on re-run).",
                    batch_idx,
                )
                result = {"existing_group_assignments": [], "new_groups": []}
            else:
                raw = message.content[0].text.strip()
                parsed = _parse_json_from_response(raw)
                if not isinstance(parsed, dict):
                    logger.warning("Pass 3 batch %d: unexpected response shape, skipping.", batch_idx)
                    result = {"existing_group_assignments": [], "new_groups": []}
                else:
                    result = {
                        "existing_group_assignments": parsed.get("existing_group_assignments", []),
                        "new_groups": parsed.get("new_groups", []),
                    }
                with open(cache_path, "w") as f:
                    json.dump(result, f, indent=2)

        # Filter assignments: only keep valid IDs not already assigned
        valid_ids_in_batch = {ke_id for ke_id, _ in batch}
        for assignment in result.get("existing_group_assignments", []):
            eid = str(assignment.get("event_id", ""))
            if eid in valid_ids_in_batch and eid not in assigned_ids:
                all_assignments.append(assignment)
                assigned_ids.add(eid)
        # Filter new groups: only keep those with >= 2 valid member IDs
        for ng in result.get("new_groups", []):
            member_ids = [str(m) for m in ng.get("member_ids", [])]
            valid_members = [m for m in member_ids if m in valid_ids_in_batch and m not in assigned_ids]
            if len(valid_members) >= 2:
                ng["member_ids"] = valid_members
                all_new_groups.append(ng)
                assigned_ids.update(valid_members)

    merged = {
        "existing_group_assignments": all_assignments,
        "new_groups": all_new_groups,
    }
    with open(pass3_cache_path, "w") as f:
        json.dump(merged, f, indent=2)

    logger.info(
        "Pass 3: %d assignments to existing groups, %d new groups.",
        len(all_assignments),
        len(all_new_groups),
    )
    return merged


def apply_pass3_results(
    final_groups: list[dict],
    pass3_result: dict,
) -> list[dict]:
    """
    Merge Pass 3 results into final_groups (mutates in place):
    - Add member_ids from existing_group_assignments to matching groups.
    - Append new_groups to final_groups.
    Returns final_groups.
    """
    # Build a fast lookup by group_key
    groups_by_key: dict[str, dict] = {g["group_key"]: g for g in final_groups}

    for assignment in pass3_result.get("existing_group_assignments", []):
        group_key = assignment.get("group_key", "")
        event_id = str(assignment.get("event_id", ""))
        if not group_key or not event_id:
            continue
        if group_key in groups_by_key:
            existing_ids = groups_by_key[group_key].setdefault("member_ids", [])
            if event_id not in existing_ids:
                existing_ids.append(event_id)
                logger.debug("Pass 3: added %s to group %s", event_id, group_key)
        else:
            logger.warning("Pass 3: assignment references unknown group_key %r — skipping.", group_key)

    for new_group in pass3_result.get("new_groups", []):
        if isinstance(new_group.get("member_ids"), list) and len(new_group["member_ids"]) >= 2:
            final_groups.append(new_group)

    return final_groups


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a group_key to a clean snake_case string."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")

def _statement_for_shared_aop_check(non_ofa, ofa):
    if len(non_ofa) > 0:
        # Count only non-OFA AOPs here (OFA ones are surfaced separately) — the
        # label is explicit so it is not read as the full shared-AOP total.
        statement = f"Co-occur in one or more AOPs, non-OFA AOPs with co-occurrence: {len(non_ofa)}"
        if ofa:
            statement += f" (plus {len(ofa)} OFA AOP(s))"
        return statement
    elif len(ofa) != 0 and len(non_ofa) == 0:
        return "Co-occur in an AOP that is OFA but no other AOPs"
    else:
        return None

def _compute_shared_aop_check(
    member_ids: list[str],
    event_aop_ids: dict[str, list[str]],
    open_for_adoption_aop_ids: set[str],
) -> dict:
    """Return AOPs that contain ALL grouped events, split by OFA license.

    Returns {} when no shared AOPs exist.
    """
    if not member_ids:
        return {}
    sets = [set(event_aop_ids.get(ke_id, [])) for ke_id in member_ids]
    shared = sorted(sets[0].intersection(*sets[1:]), key=lambda x: int(x) if x.isdigit() else 0)
    non_ofa = [aop_id for aop_id in shared if aop_id not in open_for_adoption_aop_ids]
    ofa = [aop_id for aop_id in shared if aop_id in open_for_adoption_aop_ids]
    statement = _statement_for_shared_aop_check(non_ofa, ofa)
    if statement is None:
        return {}
    return {
        "statement": statement,
        "total_non_ofa_aops_with_co-occurrence": len(non_ofa),
        "non_open_for_adoption_aops_holding_grouped_events": non_ofa,
        "open_for_adoption_aops_holding_grouped_events": ofa,
    }

def assemble_output(
    final_groups: list[dict],
    events: dict[str, str],
    processed_ids: set[str],
    date_str: str,
    cache_path: str,
    batch_size: int,
    skipped_orphan: int = 0,
    skipped_license: int = 0,
    event_aop_ids: dict[str, list[str]] | None = None,
    open_for_adoption_aop_ids: set[str] | None = None,
) -> dict:
    """Build the final output JSON from consolidated groups."""
    _event_aop_ids: dict[str, list[str]] = event_aop_ids or {}
    _ofa_ids: set[str] = open_for_adoption_aop_ids or set()

    grouped_ids: set[str] = set()
    events_to_merge: dict[str, dict] = {}
    soda_events: dict[str, dict] = {}
    sodp_events: dict[str, dict] = {}  # same_object_different_process
    sedc_events: dict[str, dict] = {}  # similar_event_different_biological_context
    used_keys: set[str] = set()  # keep slugified keys unique across ALL buckets

    for group in final_groups:
        raw_key = group.get("group_key", "unknown")
        key = _unique_key(_slugify(raw_key), used_keys)
        used_keys.add(key)
        group_type = group.get("type", "merge")  # default to merge for old cache files
        member_ids = [str(i) for i in group.get("member_ids", [])]
        grouped_ids.update(member_ids)
        shared_aop_check = _compute_shared_aop_check(member_ids, _event_aop_ids, _ofa_ids)

        if group_type == "soda":
            soda_events[key] = {
                "event_ids": member_ids,
                "event_titles": {ke_id: events.get(ke_id, "") for ke_id in member_ids},
                "rationale": group.get("rationale", ""),
                "shared_aop_check": shared_aop_check,
            }
        elif group_type == "same_object_different_process":
            sodp_events[key] = {
                "event_ids": member_ids,
                "event_titles": {ke_id: events.get(ke_id, "") for ke_id in member_ids},
                "rationale": group.get("rationale", ""),
                "shared_aop_check": shared_aop_check,
            }
        elif group_type == "similar_event_different_biological_context":
            sedc_events[key] = {
                "event_ids": member_ids,
                "event_titles": {ke_id: events.get(ke_id, "") for ke_id in member_ids},
                "rationale": group.get("rationale", ""),
                "shared_aop_check": shared_aop_check,
            }
        else:
            events_to_merge[key] = {
                "merged_event_titles": {ke_id: events.get(ke_id, "") for ke_id in member_ids},
                "rationale": group.get("rationale", ""),
                "shared_aop_check": shared_aop_check,
            }

    # Processed-but-ungrouped: {id: title} dict for easy review
    ungrouped_processed = {
        ke_id: events[ke_id]
        for ke_id in sorted(processed_ids - grouped_ids, key=lambda x: int(x))
    }
    unprocessed_count = len([ke_id for ke_id in events if ke_id not in processed_ids])

    all_groups_combined = (
        list(events_to_merge.values())
        + list(soda_events.values())
        + list(sodp_events.values())
        + list(sedc_events.values())
    )
    total_co_occurring = sum(
        1 for g in all_groups_combined
        if (g.get("shared_aop_check", {}).get("statement") or "").startswith("Co-occur in one or more AOPs")
    )
    total_ofa_only = sum(
        1 for g in all_groups_combined
        if g.get("shared_aop_check", {}).get("statement") == "Co-occur in an AOP that is OFA but no other AOPs"
    )

    return {
        "metadata": {
            "date": date_str,
            "source_cache": cache_path,
            "run_provenance": _run_provenance(batch_size),
            "total_events": len(events),
            "events_processed": len(processed_ids),
            "events_unprocessed": unprocessed_count,
            "total_grouped_events": len(grouped_ids),
            "total_ungrouped_processed_events": len(ungrouped_processed),
            "total_skipped_orphan_events": skipped_orphan,
            "total_skipped_only_open_for_adoption_events": skipped_license,
            "merge_groups": {
                "total_groups": len(events_to_merge),
                "total_events_in_groups": sum(len(v["merged_event_titles"]) for v in events_to_merge.values()),
                "groups_with_events_co_occurring_in_aops": sum(1 for v in events_to_merge.values() if (v.get("shared_aop_check", {}).get("statement") or "").startswith("Co-occur in one or more AOPs")),
                "groups_with_events_co_occurring_only_in_ofa_aops": sum(1 for v in events_to_merge.values() if v.get("shared_aop_check", {}).get("statement") == "Co-occur in an AOP that is OFA but no other AOPs"),
            },
            "soda_groups": {
                "total_groups": len(soda_events),
                "total_events_in_groups": sum(len(v["event_ids"]) for v in soda_events.values()),
                "groups_with_events_co_occurring_in_aops": sum(1 for v in soda_events.values() if (v.get("shared_aop_check", {}).get("statement") or "").startswith("Co-occur in one or more AOPs")),
                "groups_with_events_co_occurring_only_in_ofa_aops": sum(1 for v in soda_events.values() if v.get("shared_aop_check", {}).get("statement") == "Co-occur in an AOP that is OFA but no other AOPs"),
            },
            "same_object_different_process_groups": {
                "total_groups": len(sodp_events),
                "total_events_in_groups": sum(len(v["event_ids"]) for v in sodp_events.values()),
                "groups_with_events_co_occurring_in_aops": sum(1 for v in sodp_events.values() if (v.get("shared_aop_check", {}).get("statement") or "").startswith("Co-occur in one or more AOPs")),
                "groups_with_events_co_occurring_only_in_ofa_aops": sum(1 for v in sodp_events.values() if v.get("shared_aop_check", {}).get("statement") == "Co-occur in an AOP that is OFA but no other AOPs"),
            },
            "similar_event_different_context_groups": {
                "total_groups": len(sedc_events),
                "total_events_in_groups": sum(len(v["event_ids"]) for v in sedc_events.values()),
                "groups_with_events_co_occurring_in_aops": sum(1 for v in sedc_events.values() if (v.get("shared_aop_check", {}).get("statement") or "").startswith("Co-occur in one or more AOPs")),
                "groups_with_events_co_occurring_only_in_ofa_aops": sum(1 for v in sedc_events.values() if v.get("shared_aop_check", {}).get("statement") == "Co-occur in an AOP that is OFA but no other AOPs"),
            },
            "total_groups_with_events_co_occurring_in_aops": total_co_occurring,
            "total_groups_with_events_co_occurring_only_in_ofa_aops": total_ofa_only,
            "batch_size": batch_size,
        },
        "events_to_merge": events_to_merge,
        "soda_events": soda_events,
        "same_object_different_process_events": sodp_events,
        "similar_event_different_biological_context_events": sedc_events,
        "ungrouped_processed_events": ungrouped_processed,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Group AOP-Wiki Key Events by title similarity using an LLM."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Cache date MM-DD-YYYY (default: today; generates fresh caches if absent)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Events per intra-batch LLM call (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Stop Pass 1 after this many batches (useful for testing)",
    )
    parser.add_argument(
        "--skip-pass3",
        action="store_true",
        help="Skip the Pass 3 straggler sweep (useful for testing or re-runs where pass3 cache exists)",
    )
    args = parser.parse_args()

    if args.date is None:
        # No date given: use today and ensure fresh caches are generated
        date_str = date.today().strftime("%m-%d-%Y")
        cache_path, aop_cache_path = _ensure_caches(date_str)
    else:
        date_str = args.date
        cache_path = os.path.join(CACHE_DIR_ROOT, date_str, f"all_events_{date_str}.json")
        aop_cache_path = os.path.join(CACHE_DIR_ROOT, date_str, f"all_aops_{date_str}.json")
        if not os.path.exists(cache_path):
            logger.error("Event cache not found for --date %s: %s", date_str, cache_path)
            sys.exit(1)
        if not os.path.exists(aop_cache_path):
            logger.error("AOP cache not found for --date %s: %s", date_str, aop_cache_path)
            sys.exit(1)

    logger.info("Loading events from %s", cache_path)
    with open(cache_path) as f:
        raw_cache = json.load(f)

    # Extract {id: title} — skip orphans, open-for-adoption-only, and blank/placeholder titles
    events: dict[str, str] = {}
    skipped_orphan = 0
    skipped_license = 0
    skipped_title = 0
    for ke_id, record in raw_cache.items():
        # Skip orphan events (no associated AOPs)
        if not record.get("aop_ids"):
            skipped_orphan += 1
            continue
        # Skip events whose only license is "open for adoption" (not yet curated)
        if record.get("summary_licenses", {}).get("only_open_for_adoption", False):
            skipped_license += 1
            continue
        title = (record.get("title") or "").strip()
        if not title or title.lower() in {"n/a, unknown", "unknown", "testjf"}:
            skipped_title += 1
            continue
        events[ke_id] = title
    logger.info(
        "%d events loaded; skipped %d orphans, %d open-for-adoption-only, %d blank/placeholder titles.",
        len(events), skipped_orphan, skipped_license, skipped_title,
    )

    # Set up output directories
    output_dir = os.path.join(OUTPUT_DIR_ROOT, date_str)
    batches_dir = os.path.join(output_dir, "batches")
    os.makedirs(output_dir, exist_ok=True)

    consolidation_cache = os.path.join(output_dir, "consolidation_pass2.json")

    client = _make_client()
    if client is None:
        logger.error("Cannot run without ANTHROPIC_API_KEY.")
        sys.exit(1)

    # Pass 1 — intra-batch grouping
    logger.info("=== Pass 1: intra-batch grouping (batch_size=%d) ===", args.batch_size)
    all_groups, processed_ids = run_pass1(client, events, args.batch_size, batches_dir, args.max_batches)
    logger.info("Pass 1 complete: %d raw groups across %d processed events.", len(all_groups), len(processed_ids))

    # Pass 2 — cross-batch consolidation
    logger.info("=== Pass 2: cross-batch consolidation ===")
    final_groups = run_pass2(client, all_groups, consolidation_cache)

    # Load AOP cache for shared_aop_check enrichment (needed for both pass2 and pass3 outputs)
    logger.info("Loading AOP cache from %s", aop_cache_path)
    with open(aop_cache_path) as f:
        raw_aop_cache = json.load(f)
    event_aop_ids = {ke_id: record.get("aop_ids", []) for ke_id, record in raw_cache.items()}
    open_for_adoption_aop_ids = {
        aop_id
        for aop_id, aop in raw_aop_cache.items()
        if aop.get("wiki_license") == "Open for adoption"
    }
    logger.info(
        "AOP cache: %d AOPs, %d open-for-adoption.",
        len(raw_aop_cache), len(open_for_adoption_aop_ids),
    )

    # Assemble and write Pass 2 output snapshot
    output_path_pass2 = os.path.join(output_dir, f"ke_similar_events_{date_str}_pass2.json")
    output = assemble_output(
        final_groups, events, processed_ids, date_str, cache_path, args.batch_size,
        skipped_orphan, skipped_license, event_aop_ids, open_for_adoption_aop_ids,
    )
    with open(output_path_pass2, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Pass 2 output: %s", output_path_pass2)

    # Pass 3 — straggler sweep: ungrouped events vs. existing groups
    if not args.skip_pass3:
        grouped_after_p2 = {str(mid) for g in final_groups for mid in g.get("member_ids", [])}
        ungrouped_after_p2 = {
            ke_id: title
            for ke_id, title in events.items()
            if ke_id in processed_ids and ke_id not in grouped_after_p2
        }
        logger.info(
            "=== Pass 3: straggler sweep (%d ungrouped processed events) ===",
            len(ungrouped_after_p2),
        )
        pass3_dir = os.path.join(output_dir, "pass3")
        pass3_cache = os.path.join(output_dir, "pass3_straggler_sweep.json")
        pass3_result = run_pass3(
            client, ungrouped_after_p2, final_groups, pass3_dir, pass3_cache, all_events=events
        )
        final_groups = apply_pass3_results(final_groups, pass3_result)
        _dedupe_group_keys(final_groups)

        output_path_pass3 = os.path.join(output_dir, f"ke_similar_events_{date_str}_pass3.json")
        output = assemble_output(
            final_groups, events, processed_ids, date_str, cache_path, args.batch_size,
            skipped_orphan, skipped_license, event_aop_ids, open_for_adoption_aop_ids,
        )
        with open(output_path_pass3, "w") as f:
            json.dump(output, f, indent=2)
        logger.info("Pass 3 output: %s", output_path_pass3)
        output_path = output_path_pass3
    else:
        logger.info("Pass 3: skipped (--skip-pass3).")
        output_path = output_path_pass2

    logger.info(
        "Done. \n"
        "%d merge groups (%d events), \n"
        "%d SODA groups (%d events), \n"
        "%d similar-object groups (%d events), \n"
        "%d different-context groups (%d events). \n"
        "%d processed events (%d ungrouped, %d not yet processed).\n"
        "Final output: %s",
        output["metadata"]["merge_groups"]["total_groups"],
        output["metadata"]["merge_groups"]["total_events_in_groups"],
        output["metadata"]["soda_groups"]["total_groups"],
        output["metadata"]["soda_groups"]["total_events_in_groups"],
        output["metadata"]["same_object_different_process_groups"]["total_groups"],
        output["metadata"]["same_object_different_process_groups"]["total_events_in_groups"],
        output["metadata"]["similar_event_different_context_groups"]["total_groups"],
        output["metadata"]["similar_event_different_context_groups"]["total_events_in_groups"],
        output["metadata"]["events_processed"],
        len(output["ungrouped_processed_events"]),
        output["metadata"]["events_unprocessed"],
        output_path,
    )


if __name__ == "__main__":
    main()
