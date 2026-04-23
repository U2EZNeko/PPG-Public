"""
Track consecutive per-playlist failures for review (edit config / delete in Plex).

State file: webui/data/playlist_chronic_failures.json (repo root relative to package).
Threshold: PPG_CHRONIC_FAILURE_THRESHOLD (default 3) consecutive failures without a success
for that playlist title resets the streak.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHRONIC_PATH = _REPO_ROOT / "webui" / "data" / "playlist_chronic_failures.json"
_lock = threading.Lock()


def _threshold() -> int:
    raw = (os.environ.get("PPG_CHRONIC_FAILURE_THRESHOLD") or "").strip()
    if not raw:
        return 3
    try:
        n = int(raw)
    except ValueError:
        return 3
    return max(1, min(n, 999))


def _is_tracked_playlist(name: str) -> bool:
    pl = (name or "").strip()
    if not pl:
        return False
    if pl.startswith("("):
        return False
    return True


def _load_raw() -> dict:
    if not _CHRONIC_PATH.is_file():
        return {"version": 1, "playlists": {}}
    try:
        with open(_CHRONIC_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "playlists": {}}
    if not isinstance(data, dict):
        return {"version": 1, "playlists": {}}
    pls = data.get("playlists")
    if not isinstance(pls, dict):
        pls = {}
    return {"version": 1, "playlists": pls, "meta": data.get("meta") or {}}


def _save_raw(data: dict) -> None:
    try:
        _CHRONIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    tmp = _CHRONIC_PATH.with_suffix(".json.tmp")
    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "threshold": _threshold(),
        "playlists": data.get("playlists") or {},
    }
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CHRONIC_PATH)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def record_playlist_failure(playlist: str, reason: str, script: str) -> None:
    if not _is_tracked_playlist(playlist):
        return
    pl = playlist.strip()
    r = (reason or "").strip()
    if len(r) > 500:
        r = r[:497] + "…"
    sc = (script or "").strip()
    with _lock:
        data = _load_raw()
        playlists: dict = data["playlists"]
        cur = playlists.get(pl)
        if not isinstance(cur, dict):
            cur = {}
        streak = int(cur.get("consecutive_failures") or 0) + 1
        th = _threshold()
        entry = {
            "consecutive_failures": streak,
            "last_failed_at": datetime.now().isoformat(timespec="seconds"),
            "last_reason": r,
            "last_script": sc,
            "needs_review": streak >= th,
            "total_failures_recorded": int(cur.get("total_failures_recorded") or 0) + 1,
        }
        if streak >= th:
            entry["marked_at"] = cur.get("marked_at") or datetime.now().isoformat(
                timespec="seconds"
            )
        else:
            entry["marked_at"] = ""
        playlists[pl] = entry
        _save_raw({"playlists": playlists})


def record_playlist_success(playlist: str) -> None:
    if not _is_tracked_playlist(playlist):
        return
    pl = playlist.strip()
    with _lock:
        data = _load_raw()
        playlists: dict = data["playlists"]
        if pl in playlists:
            del playlists[pl]
            _save_raw({"playlists": playlists})


def read_chronic_failures_for_api() -> dict:
    """Return payload for /api/stats (read-only; no lock held long)."""
    with _lock:
        raw = _load_raw()
    playlists = raw.get("playlists") or {}
    if not isinstance(playlists, dict):
        playlists = {}
    rows = []
    for title, info in playlists.items():
        if not isinstance(info, dict):
            continue
        streak = int(info.get("consecutive_failures") or 0)
        if streak <= 0 and not info.get("needs_review"):
            continue
        rows.append(
            {
                "playlist": title,
                "consecutive_failures": streak,
                "needs_review": bool(info.get("needs_review")),
                "last_failed_at": info.get("last_failed_at") or "",
                "last_reason": info.get("last_reason") or "",
                "last_script": info.get("last_script") or "",
                "marked_at": info.get("marked_at") or "",
                "total_failures_recorded": int(info.get("total_failures_recorded") or 0),
            }
        )
    rows.sort(
        key=lambda x: (
            -int(x.get("needs_review") or 0),
            -int(x.get("consecutive_failures") or 0),
            (x.get("playlist") or "").lower(),
        )
    )
    try:
        rel_file = str(_CHRONIC_PATH.relative_to(_REPO_ROOT))
    except ValueError:
        rel_file = str(_CHRONIC_PATH)
    return {
        "threshold": _threshold(),
        "file": rel_file,
        "playlists": rows,
    }
