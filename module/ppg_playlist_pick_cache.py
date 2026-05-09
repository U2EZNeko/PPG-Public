"""Optional persistent cache to avoid repeating exact playlist picks across runs."""

from __future__ import annotations

import json
import os
import random
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

DEFAULT_CACHE_PATH = Path("webui") / "data" / "ppg_pick_cache.json"
_CACHE_LOCK = threading.Lock()


def cache_enabled() -> bool:
    raw = (os.getenv("PPG_PICK_CACHE_ENABLED") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def cache_path() -> Path:
    raw = (os.getenv("PPG_PICK_CACHE_FILE") or "").strip()
    if raw:
        return Path(raw)
    return DEFAULT_CACHE_PATH


def _safe_item_id(item) -> str:
    for attr in ("ratingKey", "key"):
        v = getattr(item, attr, None)
        if v is not None and str(v).strip():
            return str(v).strip()
    title = str(getattr(item, "title", "") or "").strip()
    if title:
        return f"title:{title}"
    return f"obj:{id(item)}"


def _load_cache_unlocked(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "scripts": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": 1, "scripts": {}}
    if not isinstance(obj, dict):
        return {"version": 1, "scripts": {}}
    scripts = obj.get("scripts")
    if not isinstance(scripts, dict):
        obj["scripts"] = {}
    obj.setdefault("version", 1)
    return obj


def _save_cache_unlocked(path: Path, cache_obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _attempt_non_repeat_with_candidates(
    *,
    picked_items: list,
    candidates: list,
    previous_ids_sorted: list[str],
    attempts: int = 24,
) -> tuple[list, bool]:
    if not picked_items:
        return picked_items, True
    if not candidates or len(candidates) <= len(picked_items):
        return picked_items, False

    target_n = len(picked_items)
    curr = list(picked_items)
    curr_set = {_safe_item_id(x) for x in curr}
    alternatives = [x for x in candidates if _safe_item_id(x) not in curr_set]
    if not alternatives:
        return curr, False

    for _ in range(max(1, attempts)):
        trial = list(curr)
        replace_n = random.randint(1, min(3, len(trial), len(alternatives)))
        idxs = random.sample(range(len(trial)), replace_n)
        repl = random.sample(alternatives, replace_n)
        for i, v in zip(idxs, repl):
            trial[i] = v
        if sorted(_safe_item_id(x) for x in trial) != previous_ids_sorted:
            return trial, True

    for _ in range(max(1, attempts)):
        trial = random.sample(candidates, target_n)
        if sorted(_safe_item_id(x) for x in trial) != previous_ids_sorted:
            return trial, True

    return curr, False


def choose_and_record(
    *,
    script_name: str,
    playlist_name: str,
    picked_items: list,
    candidates: list,
    logger: Callable[[str], None],
) -> list:
    """Optionally mutate final pick to avoid exact-repeat set from the previous run."""
    if not picked_items or not cache_enabled():
        return picked_items

    path = cache_path()
    with _CACHE_LOCK:
        cache_obj = _load_cache_unlocked(path)
        scripts = cache_obj.setdefault("scripts", {})
        by_script = scripts.setdefault(script_name, {})
        row = by_script.get(playlist_name) if isinstance(by_script.get(playlist_name), dict) else {}
        prev_ids = row.get("picked_ids") if isinstance(row.get("picked_ids"), list) else []
        prev_ids = sorted(str(x) for x in prev_ids if str(x).strip())

        new_items = list(picked_items)
        new_ids = sorted(_safe_item_id(x) for x in new_items)
        changed = True
        if prev_ids and new_ids == prev_ids:
            new_items, changed = _attempt_non_repeat_with_candidates(
                picked_items=new_items,
                candidates=candidates,
                previous_ids_sorted=prev_ids,
            )
            new_ids = sorted(_safe_item_id(x) for x in new_items)
            if changed:
                logger(
                    f"♻️  Pick cache adjusted '{playlist_name}' to avoid exact same set as previous run."
                )
            else:
                logger(
                    f"⚠️  Pick cache could not avoid same exact set for '{playlist_name}' "
                    "(candidate space too small)."
                )

        by_script[playlist_name] = {
            "picked_ids": new_ids,
            "picked_count": len(new_ids),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            _save_cache_unlocked(path, cache_obj)
        except OSError as e:
            logger(f"⚠️  Pick-cache save failed ({path}): {e}")

    return new_items
