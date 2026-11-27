"""
Collect Key Events (KEs) belonging to an AOP from the AOP-Wiki cache,
and maintain the AOP → KE index store.
"""

import json
import os

ANNOTATIONS_DIR = "outputs_for_vc/annotations"
KE_ANNOTATIONS_PATH = os.path.join(ANNOTATIONS_DIR, "ke_annotations.json")
AOP_KE_INDEX_PATH = os.path.join(ANNOTATIONS_DIR, "aop_ke_index.json")


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


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
