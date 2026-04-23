"""Minimum pool size as a fraction of SONGS_PER_PLAYLIST (shared across generator scripts)."""

from __future__ import annotations

import os
import sys


def validate_min_songs_env(per_script_key: str, script_label: str) -> None:
    """
    Ensure either PPG_MIN_SONGS_REQUIRED_PERCENT (one value for all scripts) or the
    per-script fallback variable is set and numeric.
    """
    g_raw = (os.environ.get("PPG_MIN_SONGS_REQUIRED_PERCENT") or "").strip()
    if g_raw:
        try:
            float(g_raw)
        except ValueError:
            print(
                f"❌ ERROR: PPG_MIN_SONGS_REQUIRED_PERCENT must be a number (e.g. 0.75), got {g_raw!r}. ({script_label})",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        return

    v = os.getenv(per_script_key)
    if v is None or str(v).strip() == "":
        print(
            f"❌ ERROR: Set PPG_MIN_SONGS_REQUIRED_PERCENT (all scripts) or {per_script_key} for {script_label}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        float(v)
    except ValueError:
        print(
            f"❌ ERROR: {per_script_key} must be a number, got {v!r}. ({script_label})",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def resolve_min_songs_fraction(per_script_key: str) -> float:
    """Fraction of SONGS_PER_PLAYLIST required in the track pool before building a playlist."""
    g = (os.environ.get("PPG_MIN_SONGS_REQUIRED_PERCENT") or "").strip()
    if g:
        return float(g)
    v = os.getenv(per_script_key)
    return float(v)
