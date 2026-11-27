"""
Shared storage for KE annotations: the annotation store, the AOP → KE index,
and resolution of the dated AOP-Wiki event cache files.
"""

import json
import os
from datetime import datetime
from pathlib import Path

ANNOTATIONS_DIR = "outputs_for_vc/annotations"
KE_ANNOTATIONS_PATH = os.path.join(ANNOTATIONS_DIR, "ke_annotations.json")
AOP_KE_INDEX_PATH = os.path.join(ANNOTATIONS_DIR, "aop_ke_index.json")
WORKFLOW_METADATA_PATH = os.path.join(ANNOTATIONS_DIR, "workflow_metadata.json")

CACHE_DIR_ROOT = "outputs/cache"


def events_cache_file(date_str: str) -> str:
    """Path of the all-events cache for a MM-DD-YYYY date (may not exist)."""
    return os.path.join(CACHE_DIR_ROOT, date_str, f"all_events_{date_str}.json")


def aops_cache_file(date_str: str) -> str:
    """Path of the all-AOPs cache for a MM-DD-YYYY date (may not exist)."""
    return os.path.join(CACHE_DIR_ROOT, date_str, f"all_aops_{date_str}.json")


def latest_cache_file() -> str | None:
    """Path of the most recent dated all-events cache, or None if none exists."""
    cache_root = Path(CACHE_DIR_ROOT)
    if not cache_root.exists():
        return None
    dated = []
    for d in cache_root.iterdir():
        if d.is_dir():
            try:
                dated.append((datetime.strptime(d.name, "%m-%d-%Y"), d))
            except ValueError:
                pass
    if not dated:
        return None
    latest = max(dated, key=lambda x: x[0])[1]
    path = latest / f"all_events_{latest.name}.json"
    return str(path) if path.exists() else None


def find_cache_file(date_str: str | None = None) -> str | None:
    """Cache for the given date if present, else the most recent one."""
    if date_str:
        path = events_cache_file(date_str)
        return path if os.path.exists(path) else None
    return latest_cache_file()


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def append_run_metadata(record: dict) -> None:
    """Append one run-provenance record to the workflow metadata store."""
    data = _load_json(WORKFLOW_METADATA_PATH)
    data.setdefault("runs", []).append(record)
    _save_json(WORKFLOW_METADATA_PATH, data)


def load_ke_annotations() -> dict:
    return _load_json(KE_ANNOTATIONS_PATH)


def save_ke_annotations(store: dict) -> None:
    _save_json(KE_ANNOTATIONS_PATH, store)


def list_aop_kes(aop_id: str, cache_file: str) -> list[tuple[str, str]]:
    """Return [(ke_id, title), ...] for all KEs in the AOP, sorted by KE ID."""
    with open(cache_file) as f:
        events = json.load(f)
    kes = [
        (k, v.get("title", ""))
        for k, v in events.items()
        if aop_id in [str(x) for x in v.get("aop_ids", [])]
    ]
    return sorted(kes, key=lambda x: int(x[0]))


def register_ke_in_aop(aop_id: str, ke_id: str) -> None:
    """Add ke_id to the AOP index under aop_id if not already present."""
    aop_store = _load_json(AOP_KE_INDEX_PATH)
    ke_ids = aop_store.setdefault(aop_id, [])
    if ke_id not in ke_ids:
        ke_ids.append(ke_id)
        _save_json(AOP_KE_INDEX_PATH, aop_store)
