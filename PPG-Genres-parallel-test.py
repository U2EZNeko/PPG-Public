#!/usr/bin/env python3
"""
Experimental harness: build genre-mix playlists concurrently (one Plex API client per worker).

Compare end-to-end wall time to the sequential script:

  python PPG-Genres.py
  python PPG-Genres-parallel-test.py --workers 4

Uses the same .env, GENRE_MIXES_FILE, and PPG_ONLY_PLAYLIST_TITLE as PPG-Genres.py.
Run log / Statistics entries use script name "PPG-Genres-parallel-test.py" so you can
tell test runs apart from production.

Env:
  PPG_GENRES_PARALLEL_WORKERS — default worker count if --workers is omitted (default 4).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _load_genres_module():
    path = REPO_ROOT / "PPG-Genres.py"
    spec = importlib.util.spec_from_file_location("ppg_genres_impl", path)
    if spec is None or spec.loader is None:
        print("Cannot load PPG-Genres.py", file=sys.stderr)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ppg_genres_impl"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    os.chdir(REPO_ROOT)
    ap = argparse.ArgumentParser(
        description="Parallel test harness for PPG-Genres (timing vs sequential)."
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("PPG_GENRES_PARALLEL_WORKERS", "4")),
        help="Concurrent playlist workers (default: 4 or PPG_GENRES_PARALLEL_WORKERS).",
    )
    args = ap.parse_args()

    mod = _load_genres_module()
    from module.ppg_run_logger import finish_run, start_run

    start_run("PPG-Genres-parallel-test.py")
    try:
        mod.log_info("🚀 Starting parallel genre playlist generation (test harness)...")
        wall0 = time.perf_counter()
        mod.generate_genre_playlists_parallel(max_workers=args.workers)
        wall1 = time.perf_counter()
        mod.log_info(
            f"⏱️  Parallel harness wall time: {mod.format_duration(wall1 - wall0)}"
        )
        mod.log_info("\n✅ Parallel genre run finished.")
    finally:
        exc = sys.exc_info()
        crashed = exc[0] is not None and not issubclass(exc[0], SystemExit)
        finish_run(had_exception=crashed)


if __name__ == "__main__":
    main()
