#!/usr/bin/env python3
"""
Benchmark: sequential vs threaded Plex work (search + optional tiny playlist write).

This does NOT change PPG-Daily / Weekly / etc. It measures whether overlapping
I/O-bound Plex calls save wall-clock time when you run multiple "playlist-shaped"
units of work at once.

Usage (from repo root, with .env configured):
  python benchmark_parallel_playlists.py
  python benchmark_parallel_playlists.py --tasks 7 --workers 4
  python benchmark_parallel_playlists.py --write   # create/delete a small playlist per task

Env (optional):
  PPG_BENCH_TASKS   default: 5
  PPG_BENCH_WORKERS default: 4
  PLEX_MUSIC_SECTION default: Music
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PLEX_URL = (os.getenv("PLEX_URL") or "").strip()
PLEX_TOKEN = (os.getenv("PLEX_TOKEN") or "").strip()
SECTION = (os.getenv("PLEX_MUSIC_SECTION") or "Music").strip()


def _require_plex_creds() -> None:
    if not PLEX_URL or not PLEX_TOKEN:
        print("Set PLEX_URL and PLEX_TOKEN in .env", file=sys.stderr)
        sys.exit(1)


def _pick_genre_titles(music: Any, max_pool: int) -> list[str]:
    choices = music.listFilterChoices("genre")
    titles: list[str] = []
    for c in choices or []:
        t = getattr(c, "title", None) or getattr(c, "tag", None)
        if t and str(t).strip():
            titles.append(str(t).strip())
    if not titles:
        return []
    random.shuffle(titles)
    return titles[: max(1, min(max_pool, len(titles)))]


def _one_unit_seq(
    plex: Any,
    music: Any,
    genre_titles: list[str],
    slot: int,
    do_write: bool,
    prefix: str,
) -> tuple[float, str]:
    """Single unit using shared plex (sequential path)."""
    t0 = time.perf_counter()
    g = genre_titles[slot % len(genre_titles)]
    tracks = music.search(genre=g, libtype="track", limit=250)
    if not tracks:
        return time.perf_counter() - t0, f"{slot}: no tracks for genre {g!r}"
    sample = tracks[: min(12, len(tracks))]
    if do_write:
        name = f"{prefix}-{slot}-{threading.get_ident()}"
        pl = plex.createPlaylist(name, items=sample)
        try:
            pl.delete()
        except Exception as e:
            return time.perf_counter() - t0, f"{slot}: created {name!r} but delete failed: {e}"
    return time.perf_counter() - t0, f"{slot}: ok ({len(sample)} tracks)"


def _one_unit_par(
    genre_titles: list[str],
    slot: int,
    do_write: bool,
    prefix: str,
) -> tuple[float, str]:
    """Single unit with its own PlexServer (parallel path)."""
    from plexapi.server import PlexServer

    t0 = time.perf_counter()
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    music = plex.library.section(SECTION)
    g = genre_titles[slot % len(genre_titles)]
    tracks = music.search(genre=g, libtype="track", limit=250)
    if not tracks:
        return time.perf_counter() - t0, f"{slot}: no tracks for genre {g!r}"
    sample = tracks[: min(12, len(tracks))]
    if do_write:
        name = f"{prefix}-{slot}-{threading.get_ident()}"
        pl = plex.createPlaylist(name, items=sample)
        try:
            pl.delete()
        except Exception as e:
            return time.perf_counter() - t0, f"{slot}: created {name!r} but delete failed: {e}"
    return time.perf_counter() - t0, f"{slot}: ok ({len(sample)} tracks)"


def run_sequential(
    tasks: int, genre_titles: list[str], do_write: bool, prefix: str
) -> float:
    from plexapi.server import PlexServer

    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    music = plex.library.section(SECTION)
    wall0 = time.perf_counter()
    for slot in range(tasks):
        _one_unit_seq(plex, music, genre_titles, slot, do_write, prefix)
    return time.perf_counter() - wall0


def run_parallel(
    tasks: int,
    workers: int,
    genre_titles: list[str],
    do_write: bool,
    prefix: str,
) -> float:
    wall0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [
            ex.submit(_one_unit_par, genre_titles, slot, do_write, prefix)
            for slot in range(tasks)
        ]
        for f in as_completed(futs):
            f.result()
    return time.perf_counter() - wall0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark sequential vs parallel Plex playlist-shaped work."
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=int(os.getenv("PPG_BENCH_TASKS") or "5"),
        help="Number of independent work units (default 5 or PPG_BENCH_TASKS)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("PPG_BENCH_WORKERS") or "4"),
        help="Thread pool size for parallel mode (default 4 or PPG_BENCH_WORKERS)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Create and delete a small playlist per unit (more realistic, slower)",
    )
    parser.add_argument(
        "--genre-pool",
        type=int,
        default=80,
        help="Max genres to sample from for rotation (default 80)",
    )
    parser.add_argument(
        "--sequential-only",
        action="store_true",
        help="Only run sequential timing",
    )
    parser.add_argument(
        "--parallel-only",
        action="store_true",
        help="Only run parallel timing",
    )
    args = parser.parse_args()
    _require_plex_creds()

    if args.tasks < 1:
        print("--tasks must be >= 1", file=sys.stderr)
        sys.exit(1)

    from plexapi.server import PlexServer

    random.seed()
    plex0 = PlexServer(PLEX_URL, PLEX_TOKEN)
    music0 = plex0.library.section(SECTION)
    genre_titles = _pick_genre_titles(music0, args.genre_pool)
    if len(genre_titles) < 1:
        print("No genres returned from Plex; check PLEX_MUSIC_SECTION.", file=sys.stderr)
        sys.exit(1)

    prefix = f"PPG-Bench-{int(time.time())}"
    print(f"Section: {SECTION!r}  genres in pool: {len(genre_titles)}")
    print(f"Tasks: {args.tasks}  workers (parallel): {args.workers}  write playlists: {args.write}")
    print()

    t_seq = t_par = None
    if not args.parallel_only:
        print("Sequential (one PlexServer, one after another)…")
        t_seq = run_sequential(args.tasks, genre_titles, args.write, prefix)
        print(f"  Wall time: {t_seq:.2f}s")
        print()

    if not args.sequential_only:
        print("Parallel (new PlexServer per unit, ThreadPoolExecutor)…")
        t_par = run_parallel(
            args.tasks, args.workers, genre_titles, args.write, prefix
        )
        print(f"  Wall time: {t_par:.2f}s")
        print()

    if t_seq is not None and t_par is not None and t_par > 0:
        speedup = t_seq / t_par
        print(f"Speedup (sequential / parallel): {speedup:.2f}x")
        if speedup < 1.05:
            print(
                "(Little or no gain is normal if the server is CPU-bound, "
                "rate-limited, or network is the only bottleneck with one link.)"
            )


if __name__ == "__main__":
    main()
