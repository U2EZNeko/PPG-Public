"""
Optional regex filters: drop tracks whose title and/or album title matches.

Env (after load_dotenv):
  SKIP_SONG_TITLE_REGEX — if set, tracks whose title matches are excluded (case-insensitive).
  SKIP_ALBUM_TITLE_REGEX — if set, tracks whose album title matches are excluded.

Leave empty to disable. Invalid regex causes process exit with stderr message.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from re import Pattern
from typing import TypeVar

T = TypeVar("T")


def load_skip_title_album_regexes() -> tuple[Pattern | None, Pattern | None]:
    def _compile(label: str, raw: str | None) -> Pattern | None:
        s = (raw or "").strip()
        if not s:
            return None
        try:
            return re.compile(s, re.IGNORECASE | re.UNICODE)
        except re.error as e:
            print(f"ERROR: {label} is not a valid regex: {e}", file=sys.stderr)
            raise SystemExit(1) from e

    return (
        _compile("SKIP_SONG_TITLE_REGEX", os.getenv("SKIP_SONG_TITLE_REGEX")),
        _compile("SKIP_ALBUM_TITLE_REGEX", os.getenv("SKIP_ALBUM_TITLE_REGEX")),
    )


def get_track_title_for_filter(track: object) -> str:
    return str(getattr(track, "title", "") or "")


def get_track_album_for_filter(track: object) -> str:
    try:
        if hasattr(track, "parentTitle") and track.parentTitle:
            return str(track.parentTitle)
        if hasattr(track, "album") and track.album:
            album = track.album() if callable(track.album) else track.album
            if album and hasattr(album, "title") and album.title:
                return str(album.title)
    except Exception:
        pass
    return ""


def track_matches_skip_regex(
    track: object,
    song_re: Pattern | None,
    album_re: Pattern | None,
) -> bool:
    if song_re and song_re.search(get_track_title_for_filter(track)):
        return True
    if album_re and album_re.search(get_track_album_for_filter(track)):
        return True
    return False


def filter_tracks_by_title_album_regex(
    tracks: list[T],
    song_re: Pattern | None,
    album_re: Pattern | None,
    log_info: Callable[[str], None] | None = None,
) -> list[T]:
    if not tracks or (not song_re and not album_re):
        return tracks
    n = len(tracks)
    out = [t for t in tracks if not track_matches_skip_regex(t, song_re, album_re)]
    removed = n - len(out)
    if removed and log_info:
        log_info(
            f"🚫 Title/album regex removed {removed} track(s) ({len(out)} remain)"
        )
    return out


def filter_playlist_and_pool_for_quality(
    playlist_songs: list,
    pool: list,
    song_re: Pattern | None,
    album_re: Pattern | None,
    log_info: Callable[[str], None],
) -> tuple[list, list]:
    if not song_re and not album_re:
        return playlist_songs, pool
    n0, n1 = len(playlist_songs), len(pool)
    ps = filter_tracks_by_title_album_regex(playlist_songs, song_re, album_re)
    pl = filter_tracks_by_title_album_regex(pool, song_re, album_re)
    r0, r1 = n0 - len(ps), n1 - len(pl)
    if r0 or r1:
        log_info(
            f"🚫 Title/album regex: removed {r0} from playlist candidate, {r1} from pool"
        )
    return ps, pl
