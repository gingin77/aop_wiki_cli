"""
Collect Key Events (KEs) belonging to an AOP from the AOP-Wiki cache,
and maintain the AOP → KE index store.
"""

import json
import os

AOP_ANNOTATIONS_DIR = "outputs_for_vc/annotations"
AOP_STORE_PATH = os.path.join(AOP_ANNOTATIONS_DIR, "aop_based_ke_store.json")
SHARED_STORE_PATH = os.path.join(AOP_ANNOTATIONS_DIR, "ke_annotations.json")


def _load_shared_store() -> dict:
    if os.path.exists(SHARED_STORE_PATH):
        with open(SHARED_STORE_PATH) as f:
            return json.load(f)
    return {}


def _save_shared_store(store: dict) -> None:
    os.makedirs(AOP_ANNOTATIONS_DIR, exist_ok=True)
    with open(SHARED_STORE_PATH, "w") as f:
        json.dump(store, f, indent=2)


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


def _load_aop_store() -> dict:
    if os.path.exists(AOP_STORE_PATH):
        with open(AOP_STORE_PATH) as f:
            return json.load(f)
    return {}


def _save_aop_store(aop_store: dict) -> None:
    os.makedirs(AOP_ANNOTATIONS_DIR, exist_ok=True)
    with open(AOP_STORE_PATH, "w") as f:
        json.dump(aop_store, f, indent=2)


def register_ke_in_aop(aop_id: str, ke_id: str) -> None:
    """Add ke_id to the AOP index under aop_id if not already present."""
    aop_store = _load_aop_store()
    ke_ids = aop_store.setdefault(aop_id, [])
    if ke_id not in ke_ids:
        ke_ids.append(ke_id)
        _save_aop_store(aop_store)
