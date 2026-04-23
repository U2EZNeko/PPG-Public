"""Helpers for web UI / CLI single-playlist regeneration (PPG_ONLY_PLAYLIST_TITLE)."""

from __future__ import annotations

import os


def skip_unless_target_playlist(playlist_name: str) -> bool:
    """
    When PPG_ONLY_PLAYLIST_TITLE is set, return True if this iteration should be skipped.
    Compares exact title strings (same as Plex playlist titles).
    """
    only = (os.environ.get("PPG_ONLY_PLAYLIST_TITLE") or "").strip()
    if not only:
        return False
    return only != (playlist_name or "").strip()
