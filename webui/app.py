"""
PPG Web UI — run playlist generator scripts from the browser.

Bind address: defaults from webui/config.json, then overridden by .env
(PPG_WEB_HOST, PPG_WEB_PORT) — see example.env.

Scripts execute with the repo root as cwd so python-dotenv in each script
loads .env from the project root.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import logging
import os
import queue
import re
from collections import defaultdict, deque
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def _dotenv_path() -> Path | None:
    p = (REPO_ROOT / ".env").resolve()
    try:
        p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    return p


# PPG scripts store a line like "Updated on: 2026-04-22 14:30:00" in playlist summaries.
_UPDATED_ON_IN_SUMMARY = re.compile(r"^Updated on:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _updated_on_from_playlist_summary(summary: str | None) -> str | None:
    if not summary or not summary.strip():
        return None
    m = _UPDATED_ON_IN_SUMMARY.search(summary)
    if not m:
        return None
    text = (m.group(1) or "").strip()
    return text or None


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_output_noise(line: str) -> str:
    s = _ANSI_ESCAPE.sub("", line)
    return s.strip()


def _numbered_playlist_label(script_id: str, n: int) -> str:
    if script_id == "daily":
        return f"Daily Playlist {n}"
    if script_id == "weekly":
        return f"Weekly Playlist {n}"
    if script_id == "liked_artists":
        return f"Artist Mix ({n})"
    return f"Playlist {n}"


def _failed_playlists_from_log(log_text: str, script_id: str) -> list[dict]:
    """Infer playlist-level failures from script stdout (PPG log patterns)."""
    by_pl: dict[str, list[str]] = defaultdict(list)

    def note(playlist: str, line: str) -> None:
        pl = (playlist or "").strip()
        if not pl:
            return
        if line not in by_pl[pl]:
            by_pl[pl].append(line)

    for raw in log_text.splitlines():
        line = _strip_output_noise(raw)
        if not line:
            continue

        m = re.search(r"Time taken for '([^']+)'\s*\(failed\):", line)
        if m:
            note(m.group(1), line)
            continue
        m = re.search(r"Time taken for Playlist (\d+) \(failed\):", line)
        if m:
            note(_numbered_playlist_label(script_id, int(m.group(1))), line)
            continue
        m = re.search(r"Not enough songs for Playlist '([^']+)', skipping\.?", line, re.I)
        if m:
            note(m.group(1), line)
            continue
        m = re.search(r"Error during playlist generation for Playlist '([^']+)':", line)
        if m:
            note(m.group(1), line)
            continue
        m = re.search(r"Error during playlist generation for Playlist (\d+):", line)
        if m:
            note(_numbered_playlist_label(script_id, int(m.group(1))), line)
            continue
        m = re.search(r"Skipping playlist (\d+)\.", line)
        if m:
            note(_numbered_playlist_label(script_id, int(m.group(1))), line)
            continue
        m = re.search(r"No genres found for '([^']+)', skipping", line)
        if m:
            note(f"{m.group(1)} Mix", line)
            continue

    out: list[dict] = []
    for pl in sorted(by_pl.keys(), key=str.lower):
        details = " · ".join(by_pl[pl])
        if len(details) > 500:
            details = details[:497] + "…"
        out.append({"playlist": pl, "details": details})
    return out


LOG_TXT_PATH = REPO_ROOT / "log.txt"
RUN_STATE_PATH = REPO_ROOT / ".ppg_run_state.json"
EVENTS_JSONL_PATH = REPO_ROOT / "webui" / "data" / "ppg_events.jsonl"
# Survives web UI restarts: repo-root paths so the script subprocess cwd stays valid.
WEB_ACTIVE_JOBS_PATH = REPO_ROOT / "webui" / "data" / "active_web_jobs.json"

# Per-playlist timing lines use an em dash (—) before optional failure notes.
_TIMING_LINE = re.compile(
    r"^\s*-\s*(.+):\s*(.+?)\s+\((ok|failed)\)(?:\s+[—–-]\s*(.*))?$"
)


def _parse_log_duration_to_seconds(label: str) -> float | None:
    """Parse durations as written by ppg_run_logger (e.g. 36.9s, 5m 37s, 1h 2m 3s)."""
    s = (label or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+)h (\d+)m (\d+)s", s)
    if m:
        return float(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
    m = re.fullmatch(r"(\d+)m (\d+)s", s)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2)))
    m = re.fullmatch(r"(\d+\.?\d*)s", s)
    if m:
        return float(m.group(1))
    return None


def _split_log_into_run_blocks(text: str) -> list[str]:
    parts = re.split(r"(?m)^=+\s*$", text)
    blocks: list[str] = []
    for chunk in parts:
        c = chunk.strip()
        if "Run:" in c:
            blocks.append(c)
    return blocks


def _parse_single_run_block(chunk: str) -> dict | None:
    """Parse one run section from log.txt (between separator lines)."""
    meta: dict = {
        "script": "",
        "started": "",
        "finished": "",
        "duration_label": "",
        "duration_seconds": None,
        "result": "",
        "playlists_ok": 0,
        "timing": [],
        "failures": [],
    }
    section: str | None = None
    for raw in chunk.splitlines():
        line = raw.rstrip("\n")
        st = line.strip()
        if st.startswith("Run:"):
            meta["script"] = line.split("Run:", 1)[1].strip()
            section = None
            continue
        if st.startswith("Started:"):
            meta["started"] = line.split("Started:", 1)[1].strip()
            continue
        if st.startswith("Finished:"):
            meta["finished"] = line.split("Finished:", 1)[1].strip()
            continue
        if st.startswith("Duration:"):
            dl = line.split("Duration:", 1)[1].strip()
            meta["duration_label"] = dl
            meta["duration_seconds"] = _parse_log_duration_to_seconds(dl)
            continue
        if st.startswith("Result:"):
            meta["result"] = line.split("Result:", 1)[1].strip()
            continue
        if st.startswith("Playlists updated successfully:"):
            tail = line.split("Playlists updated successfully:", 1)[1].strip()
            try:
                meta["playlists_ok"] = int(tail.split()[0])
            except (ValueError, IndexError):
                meta["playlists_ok"] = 0
            continue
        if st == "Per-playlist timing:":
            section = "timing"
            continue
        if st.startswith("Failures:"):
            section = "failures"
            tail = line.split("Failures:", 1)[1].strip()
            if tail and tail != "none":
                pl, _, reason = tail.partition(": ")
                if pl.strip():
                    meta["failures"].append(
                        {"playlist": pl.strip(), "reason": (reason or "").strip()}
                    )
            continue
        if section == "timing":
            m = _TIMING_LINE.match(line)
            if m:
                pl, dlab, status, note = (
                    m.group(1).strip(),
                    m.group(2).strip(),
                    m.group(3),
                    (m.group(4) or "").strip(),
                )
                sec = _parse_log_duration_to_seconds(dlab)
                meta["timing"].append(
                    {
                        "playlist": pl,
                        "duration_label": dlab,
                        "seconds": sec,
                        "ok": status == "ok",
                        "note": note,
                    }
                )
            continue
        if section == "failures" and st.startswith("- "):
            rest = line.strip()[2:].strip()
            if ": " in rest:
                pl, _, reason = rest.partition(": ")
                meta["failures"].append(
                    {"playlist": pl.strip(), "reason": reason.strip()}
                )
            else:
                meta["failures"].append({"playlist": rest, "reason": ""})
            continue

    if not meta["script"]:
        return None
    return meta


def _load_active_run_state() -> dict | None:
    """Snapshot written by ppg_run_logger after each playlist completes."""
    if not RUN_STATE_PATH.is_file():
        return None
    try:
        data = json.loads(RUN_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("active"):
        return None
    return data


def _web_script_id_for_runner_filename(filename: str | None) -> str | None:
    """Map ppg_run_logger script_name (e.g. PPG-Moods.py) to web UI script id."""
    if not filename:
        return None
    fn = str(filename).strip()
    if not fn:
        return None
    for sid, script_fn in SCRIPTS.items():
        if fn == script_fn:
            return sid
    return None


def _event_ts_display(iso_val: str | None) -> str:
    if not iso_val:
        return ""
    s = str(iso_val).replace("T", " ")
    return s[:19] if len(s) >= 19 else s


def _runs_from_events_jsonl(path: Path, max_runs: int) -> list[dict]:
    """Rebuild run summaries from ppg_events.jsonl (CLI / cron friendly)."""
    if not path.is_file():
        return []
    open_by_id: dict[str, dict] = {}
    completed: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict) or ev.get("v") != 1:
                    continue
                typ = ev.get("type")
                rid = ev.get("run_id")
                if not rid:
                    continue
                rid_s = str(rid)
                if typ == "run_start":
                    open_by_id[rid_s] = {
                        "script": ev.get("script") or "",
                        "started": _event_ts_display(ev.get("t")),
                        "finished": "",
                        "duration_label": "",
                        "duration_seconds": None,
                        "result": "incomplete",
                        "playlists_ok": 0,
                        "timing": [],
                        "failures": [],
                    }
                elif typ == "playlist" and rid_s in open_by_id:
                    run = open_by_id[rid_s]
                    sec_raw = ev.get("seconds")
                    try:
                        sec_f = float(sec_raw) if sec_raw is not None else None
                    except (TypeError, ValueError):
                        sec_f = None
                    run["timing"].append(
                        {
                            "playlist": ev.get("playlist") or "",
                            "duration_label": ev.get("duration_label") or "",
                            "seconds": sec_f,
                            "ok": bool(ev.get("ok")),
                            "note": (ev.get("note") or "").strip(),
                        }
                    )
                elif typ == "failure" and rid_s in open_by_id:
                    pl = (ev.get("playlist") or "").strip()
                    if pl:
                        open_by_id[rid_s]["failures"].append(
                            {
                                "playlist": pl,
                                "reason": (ev.get("reason") or "").strip(),
                            }
                        )
                elif typ == "run_end":
                    run = open_by_id.pop(rid_s, None)
                    if run is None:
                        continue
                    run["finished"] = _event_ts_display(ev.get("t"))
                    ds = ev.get("duration_sec")
                    try:
                        run["duration_seconds"] = float(ds) if ds is not None else None
                    except (TypeError, ValueError):
                        run["duration_seconds"] = None
                    run["duration_label"] = (ev.get("duration_label") or "").strip()
                    run["result"] = (
                        "crashed (uncaught exception)"
                        if ev.get("had_exception")
                        else "completed"
                    )
                    try:
                        run["playlists_ok"] = int(ev.get("playlists_ok") or 0)
                    except (TypeError, ValueError):
                        run["playlists_ok"] = 0
                    completed.append(run)
    except OSError:
        return []

    for run in open_by_id.values():
        run["result"] = "incomplete (interrupted or still running)"
        completed.append(run)

    completed.sort(
        key=lambda x: (
            x.get("finished") or x.get("started") or "",
            x.get("started") or "",
        )
    )
    if max_runs > 0 and len(completed) > max_runs:
        completed = completed[-max_runs:]
    return completed


def _run_merge_key(r: dict) -> tuple[str, str, str]:
    return (
        r.get("script") or "",
        r.get("started") or "",
        r.get("finished") or "",
    )


def _build_stats_payload(*, max_runs: int, max_slowest: int, max_recent: int) -> dict:
    log_exists = LOG_TXT_PATH.is_file()
    log_bytes = 0
    text = ""
    if log_exists:
        try:
            log_bytes = LOG_TXT_PATH.stat().st_size
            text = LOG_TXT_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {
                "ok": False,
                "error": str(e),
                "log_path": str(LOG_TXT_PATH),
                "log_exists": True,
            }

    blocks = _split_log_into_run_blocks(text) if text.strip() else []
    if max_runs > 0 and len(blocks) > max_runs:
        blocks = blocks[-max_runs:]

    runs_log: list[dict] = []
    for b in blocks:
        p = _parse_single_run_block(b)
        if p:
            runs_log.append(p)

    runs_evt = _runs_from_events_jsonl(EVENTS_JSONL_PATH, 0)
    evt_keys = {_run_merge_key(r) for r in runs_evt}
    runs: list[dict] = list(runs_evt)
    for r in runs_log:
        if _run_merge_key(r) not in evt_keys:
            runs.append(r)
    runs.sort(
        key=lambda x: (
            x.get("finished") or x.get("started") or "",
            x.get("started") or "",
        )
    )
    if max_runs > 0 and len(runs) > max_runs:
        runs = runs[-max_runs:]

    slowest_pool: list[dict] = []
    fail_events: list[dict] = []

    for r in runs:
        script = r["script"]
        finished = r["finished"]
        started = r["started"]
        for t in r["timing"]:
            if t.get("ok") and t.get("seconds") is not None:
                slowest_pool.append(
                    {
                        "playlist": t["playlist"],
                        "seconds": t["seconds"],
                        "duration_label": t["duration_label"],
                        "script": script,
                        "finished": finished,
                        "started": started,
                    }
                )

        # One row per playlist per run (avoid double-counting timing + Failures: block).
        seen_fail_pl: set[str] = set()
        for f in r["failures"]:
            pl = f["playlist"]
            if pl in seen_fail_pl:
                continue
            seen_fail_pl.add(pl)
            fail_events.append(
                {
                    "playlist": pl,
                    "reason": (f.get("reason") or "").strip() or "(no reason in log)",
                    "script": script,
                    "finished": finished,
                    "source": "failures_block",
                }
            )
        for t in r["timing"]:
            if t.get("ok"):
                continue
            pl = t["playlist"]
            if pl in seen_fail_pl:
                continue
            seen_fail_pl.add(pl)
            reason = (t.get("note") or "").strip()
            fail_events.append(
                {
                    "playlist": pl,
                    "reason": reason or "failed",
                    "script": script,
                    "finished": finished,
                    "source": "timing",
                }
            )

    current_run = _load_active_run_state()
    finished_live = "(in progress)"
    if current_run:
        script_ar = current_run.get("script_name") or ""
        started_raw = current_run.get("started_at") or ""
        started_ar = started_raw.replace("T", " ") if started_raw else ""
        for row in current_run.get("playlist_timing") or []:
            if not isinstance(row, dict):
                continue
            if row.get("ok") and row.get("seconds") is not None:
                slowest_pool.append(
                    {
                        "playlist": row.get("playlist") or "",
                        "seconds": float(row["seconds"]),
                        "duration_label": row.get("duration_label") or "",
                        "script": script_ar,
                        "finished": finished_live,
                        "started": started_ar,
                    }
                )
        seen_live: set[str] = set()
        for f in current_run.get("failures") or []:
            if not isinstance(f, dict):
                continue
            pl = (f.get("playlist") or "").strip()
            if not pl or pl in seen_live:
                continue
            seen_live.add(pl)
            fail_events.append(
                {
                    "playlist": pl,
                    "reason": (f.get("reason") or "").strip()
                    or "(no reason in log)",
                    "script": script_ar,
                    "finished": finished_live,
                    "source": "failures_block",
                }
            )
        for row in current_run.get("playlist_timing") or []:
            if not isinstance(row, dict) or row.get("ok"):
                continue
            pl = (row.get("playlist") or "").strip()
            if not pl or pl in seen_live:
                continue
            seen_live.add(pl)
            reason = (row.get("note") or "").strip()
            fail_events.append(
                {
                    "playlist": pl,
                    "reason": reason or "failed",
                    "script": script_ar,
                    "finished": finished_live,
                    "source": "timing",
                }
            )

    slowest_pool.sort(key=lambda x: -x["seconds"])
    slowest_ok = slowest_pool[:max_slowest]

    by_pl: dict[str, dict] = {}
    for ev in fail_events:
        pl = ev["playlist"]
        if pl not in by_pl:
            by_pl[pl] = {
                "playlist": pl,
                "count": 0,
                "examples": [],
            }
        by_pl[pl]["count"] += 1
        ex = by_pl[pl]["examples"]
        if len(ex) < 5:
            ex.append(
                {
                    "reason": ev["reason"],
                    "script": ev["script"],
                    "finished": ev["finished"],
                    "source": ev["source"],
                }
            )

    failed_playlists = sorted(
        by_pl.values(), key=lambda x: (-x["count"], x["playlist"].lower())
    )

    script_stats: dict[str, dict] = defaultdict(
        lambda: {
            "script": "",
            "runs": 0,
            "last_finished": "",
            "last_result": "",
            "total_timing_rows": 0,
            "failed_timing_rows": 0,
        }
    )
    for r in runs:
        s = r["script"]
        st = script_stats[s]
        st["script"] = s
        st["runs"] += 1
        if r["finished"] >= st["last_finished"]:
            st["last_finished"] = r["finished"]
            st["last_result"] = r["result"]
        st["total_timing_rows"] += len(r["timing"])
        st["failed_timing_rows"] += sum(1 for t in r["timing"] if not t.get("ok"))

    by_script = sorted(
        script_stats.values(), key=lambda x: (-x["runs"], x["script"].lower())
    )

    recent: list[dict] = []
    for r in reversed(runs[-max_recent:]):
        timing = r["timing"]
        seen_pl: set[str] = set()
        n_distinct_fail = 0
        for f in r["failures"]:
            pl = f["playlist"]
            if pl not in seen_pl:
                seen_pl.add(pl)
                n_distinct_fail += 1
        for t in timing:
            if t.get("ok"):
                continue
            pl = t["playlist"]
            if pl not in seen_pl:
                seen_pl.add(pl)
                n_distinct_fail += 1
        recent.append(
            {
                "script": r["script"],
                "started": r["started"],
                "finished": r["finished"],
                "duration_label": r["duration_label"],
                "duration_seconds": r["duration_seconds"],
                "result": r["result"],
                "playlists_ok": r["playlists_ok"],
                "timing_rows": len(timing),
                "failures_distinct": n_distinct_fail,
            }
        )

    if current_run:
        timing_live = current_run.get("playlist_timing") or []
        seen_lr: set[str] = set()
        n_distinct_fail_lr = 0
        for f in current_run.get("failures") or []:
            if not isinstance(f, dict):
                continue
            pl = (f.get("playlist") or "").strip()
            if pl and pl not in seen_lr:
                seen_lr.add(pl)
                n_distinct_fail_lr += 1
        for t in timing_live:
            if not isinstance(t, dict) or t.get("ok"):
                continue
            pl = (t.get("playlist") or "").strip()
            if pl and pl not in seen_lr:
                seen_lr.add(pl)
                n_distinct_fail_lr += 1
        started_disp = (current_run.get("started_at") or "").replace("T", " ")
        if len(started_disp) >= 19:
            started_disp = started_disp[:19]
        recent.insert(
            0,
            {
                "script": current_run.get("script_name") or "",
                "started": started_disp,
                "finished": "",
                "duration_label": "—",
                "duration_seconds": None,
                "result": "in progress",
                "playlists_ok": current_run.get("playlists_ok"),
                "timing_rows": len(timing_live),
                "failures_distinct": n_distinct_fail_lr,
            },
        )

    events_exists = EVENTS_JSONL_PATH.is_file()
    events_bytes = 0
    if events_exists:
        try:
            events_bytes = EVENTS_JSONL_PATH.stat().st_size
        except OSError:
            events_exists = False

    chronic_payload: dict = {
        "threshold": 3,
        "file": "webui/data/playlist_chronic_failures.json",
        "playlists": [],
    }
    try:
        from module.ppg_chronic_failures import read_chronic_failures_for_api

        chronic_payload = read_chronic_failures_for_api()
    except Exception:
        pass

    return {
        "ok": True,
        "log_path": str(LOG_TXT_PATH),
        "log_exists": log_exists,
        "log_bytes": log_bytes,
        "runs_in_log": len(blocks),
        "events_path": str(EVENTS_JSONL_PATH),
        "events_exists": events_exists,
        "events_bytes": events_bytes,
        "runs_from_events": len(runs_evt),
        "runs_parsed": len(runs),
        "slowest_ok": slowest_ok,
        "failed_playlists": failed_playlists,
        "recent_runs": recent,
        "by_script": by_script,
        "current_run": current_run,
        "chronic_failures": chronic_payload.get("playlists") or [],
        "chronic_threshold": chronic_payload.get("threshold"),
        "chronic_file": chronic_payload.get("file"),
    }


_WEB_DIR = Path(__file__).resolve().parent
_WEB_CONFIG_PATH = _WEB_DIR / "config.json"

# Whitelist: id -> filename (must live in REPO_ROOT)
SCRIPTS = {
    "daily": "PPG-Daily.py",
    "weekly": "PPG-Weekly.py",
    "moods": "PPG-Moods.py",
    "genres": "PPG-Genres.py",
    "liked_artists": "PPG-LikedArtists.py",
    "liked_artists_collection": "PPG-LikedArtistsCollection.py",
    "fetch_liked": "fetch-liked-artists.py",
}

SCRIPT_LABELS = {
    "daily": "PPG Daily",
    "weekly": "PPG Weekly",
    "moods": "PPG Moods",
    "genres": "PPG Genres",
    "liked_artists": "PPG Liked Artists",
    "liked_artists_collection": "Liked artists → Plex collection",
    "fetch_liked": "Fetch liked artists (cache)",
}

SCRIPT_NOTES: dict[str, str] = {}

# Editable group JSON files (repo root); ids are stable API keys
JSON_GROUP_FILES: dict[str, str] = {
    "daily_weekly_genre_pools": "daily_weekly_genre_pools.json",
    "mood_groups": "mood_groups.json",
    "named_genre_mix_playlists": "named_genre_mix_playlists.json",
}
JSON_GROUP_LABELS: dict[str, str] = {
    "daily_weekly_genre_pools": "Daily & Weekly — genre pools (random recipe per playlist)",
    "mood_groups": 'Moods — one "Name Mix" playlist per entry (PPG-Moods)',
    "named_genre_mix_playlists": 'PPG-Genres — one "Name Mix" playlist per entry',
}

_PPG_TITLE_DAILY = re.compile(r"^Daily Playlist \d+$")
_PPG_TITLE_WEEKLY = re.compile(r"^Weekly Playlist \d+$")
_PPG_TITLE_ARTIST_MIX = re.compile(r"^Artist Mix \(\d+\)$")


def _json_top_level_string_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(data, dict):
        return set()
    out: set[str] = set()
    for k in data.keys():
        if isinstance(k, str):
            out.add(k)
        elif isinstance(k, int):
            out.add(str(k))
    return out


def _ppg_mix_playlist_titles_from_config() -> set[str]:
    """Titles PPG-Moods / PPG-Genres use: '{group} Mix' for each JSON object key."""
    mood = _json_top_level_string_keys(REPO_ROOT / JSON_GROUP_FILES["mood_groups"])
    mixes = _json_top_level_string_keys(
        REPO_ROOT / JSON_GROUP_FILES["named_genre_mix_playlists"]
    )
    return {f"{k} Mix" for k in mood | mixes}


def _playlist_is_ppg_managed(title: str | None, mix_titles: set[str]) -> bool:
    """True if the Plex playlist title matches what PPG generator scripts create."""
    t = (title or "").strip()
    if not t:
        return False
    if t == "Liked Artists Collection":
        return True
    if (
        _PPG_TITLE_DAILY.match(t)
        or _PPG_TITLE_WEEKLY.match(t)
        or _PPG_TITLE_ARTIST_MIX.match(t)
    ):
        return True
    return t in mix_titles


def _mix_title_base_key(title: str) -> str | None:
    t = (title or "").strip()
    if len(t) < 5 or not t.endswith(" Mix"):
        return None
    return t[:-4].strip()


def classify_regenerate_playlist(title: str) -> tuple[str | None, str | None]:
    """Map a Plex playlist title to SCRIPTS id for single-playlist regeneration."""
    t = (title or "").strip()
    if not t:
        return None, "Missing playlist title"
    if t == "Liked Artists Collection":
        return "liked_artists_collection", None
    if _PPG_TITLE_DAILY.match(t):
        return "daily", None
    if _PPG_TITLE_WEEKLY.match(t):
        return "weekly", None
    if _PPG_TITLE_ARTIST_MIX.match(t):
        return "liked_artists", None
    mix_titles = _ppg_mix_playlist_titles_from_config()
    if t not in mix_titles:
        return (
            None,
            "Not a recognized PPG playlist title (daily, weekly, genre/mood mix, artist mix, or collection).",
        )
    key = _mix_title_base_key(t)
    if not key:
        return None, "Invalid mix title"
    genre_keys = _json_top_level_string_keys(
        REPO_ROOT / JSON_GROUP_FILES["named_genre_mix_playlists"]
    )
    mood_keys = _json_top_level_string_keys(REPO_ROOT / JSON_GROUP_FILES["mood_groups"])
    if key in genre_keys:
        return "genres", None
    if key in mood_keys:
        return "moods", None
    return (
        None,
        "Mix name is not a key in named_genre_mix_playlists.json or mood_groups.json.",
    )


def _env_int(name: str) -> int | None:
    v = (os.getenv(name) or "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _count_top_level_keys(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return 0
    if isinstance(data, dict):
        return len(data)
    return 0


def _resolve_repo_path(raw: str | None) -> Path | None:
    if not raw or not str(raw).strip():
        return None
    p = Path(raw.strip())
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    return p


def _count_liked_artists_in_cache(path: Path | None) -> int | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    detailed = data.get("liked_artists_detailed", [])
    legacy = data.get("liked_artists", [])
    if detailed and isinstance(detailed, list) and detailed and isinstance(detailed[0], dict):
        return sum(1 for a in detailed if isinstance(a, dict) and (a.get("name") or "").strip())
    if legacy and isinstance(legacy, list):
        return sum(1 for x in legacy if isinstance(x, str) and x.strip())
    return 0


# Title must match PPG-LikedArtistsCollection.playlist_title
_LIKED_ARTISTS_COLLECTION_TITLE = "Liked Artists Collection"
_LAC_LEAF_CACHE: dict[str, float | int | None] = {"ts": 0.0, "n": None}
_LAC_LEAF_TTL_SEC = 35.0


def _plex_liked_artists_collection_leaf_count() -> int | None:
    """Current track count for the Plex audio playlist managed by PPG-LikedArtistsCollection."""
    now = time.monotonic()
    if (
        now - float(_LAC_LEAF_CACHE["ts"]) < _LAC_LEAF_TTL_SEC
        and float(_LAC_LEAF_CACHE["ts"]) > 0
    ):
        return None if _LAC_LEAF_CACHE["n"] is None else int(_LAC_LEAF_CACHE["n"])

    n: int | None = None
    url = (os.getenv("PLEX_URL") or "").strip()
    token = (os.getenv("PLEX_TOKEN") or "").strip()
    if url and token:
        try:
            from plexapi.server import PlexServer

            plex = PlexServer(url, token)
            target = _LIKED_ARTISTS_COLLECTION_TITLE
            for pl in plex.playlists(playlistType="audio"):
                try:
                    if (pl.title or "").strip() != target:
                        continue
                    lc = getattr(pl, "leafCount", None)
                    if lc is not None:
                        n = int(lc)
                    break
                except Exception:
                    continue
        except Exception:
            n = None

    _LAC_LEAF_CACHE["ts"] = now
    _LAC_LEAF_CACHE["n"] = n
    return n


def _tracks_label(n: int) -> str:
    return f"{n:,} track" + ("" if n == 1 else "s")


def _invalidate_lac_leaf_cache_after_run(script_id: str, exit_code: int) -> None:
    if script_id == "liked_artists_collection" and exit_code == 0:
        _LAC_LEAF_CACHE["ts"] = 0.0
        _LAC_LEAF_CACHE["n"] = None


def _playlist_total_for_script(script_id: str) -> int | None:
    """Expected Plex playlist builds per run (for web UI progress). None if not applicable."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    if script_id == "daily":
        return _env_int("DAILY_PLAYLIST_COUNT")
    if script_id == "weekly":
        return _env_int("WEEKLY_PLAYLIST_COUNT")
    if script_id == "liked_artists":
        return _env_int("LIKED_ARTISTS_PLAYLIST_COUNT")
    if script_id == "moods":
        n = _count_top_level_keys(REPO_ROOT / JSON_GROUP_FILES["mood_groups"])
        return n if n > 0 else None
    if script_id == "genres":
        n = _count_top_level_keys(
            REPO_ROOT / JSON_GROUP_FILES["named_genre_mix_playlists"]
        )
        return n if n > 0 else None
    return None


def script_card_meta() -> dict[str, str | None]:
    """One-line hints for script cards: playlist counts from .env/JSON, artists for cache script."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    meta: dict[str, str | None] = {}

    n = _env_int("DAILY_PLAYLIST_COUNT")
    meta["daily"] = f"{n} playlists" if n is not None and n >= 0 else None

    n = _env_int("WEEKLY_PLAYLIST_COUNT")
    meta["weekly"] = f"{n} playlists" if n is not None and n >= 0 else None

    n = _env_int("LIKED_ARTISTS_PLAYLIST_COUNT")
    meta["liked_artists"] = f"{n} playlists" if n is not None and n >= 0 else None

    nm = _count_top_level_keys(REPO_ROOT / JSON_GROUP_FILES["mood_groups"])
    meta["moods"] = f"{nm} playlists" if nm > 0 else None

    ng = _count_top_level_keys(
        REPO_ROOT / JSON_GROUP_FILES["named_genre_mix_playlists"]
    )
    meta["genres"] = f"{ng} playlists" if ng > 0 else None

    lac_n = _plex_liked_artists_collection_leaf_count()
    meta["liked_artists_collection"] = (
        _tracks_label(lac_n) if lac_n is not None else None
    )

    cache_path = _resolve_repo_path(os.getenv("LIKED_ARTISTS_CACHE_FILE"))
    na = _count_liked_artists_in_cache(cache_path)
    meta["fetch_liked"] = f"{na:,} artists" if na is not None else None

    return meta


app = Flask(
    __name__,
    template_folder=str(_WEB_DIR / "templates"),
    static_folder=str(_WEB_DIR / "static"),
    static_url_path="/static",
)

_CONSOLE_DASHBOARD_LOCK = threading.Lock()
_CONSOLE_DASHBOARD_LINES: deque[str] = deque(maxlen=10)
_CONSOLE_DASHBOARD_HEADER: list[str] = []


def _console_dashboard_enabled() -> bool:
    return bool(sys.stdout and sys.stdout.isatty())


def _render_console_dashboard() -> None:
    if not _console_dashboard_enabled():
        return
    header = _CONSOLE_DASHBOARD_HEADER or ["PPG Web UI"]
    body = list(_CONSOLE_DASHBOARD_LINES)
    while len(body) < 10:
        body.append("")
    sep = "-" * 72
    frame: list[str] = []
    frame.extend(header)
    frame.append(sep)
    frame.append("Last 10 messages (live)")
    frame.append(sep)
    frame.extend(body)
    out = "\x1b[2J\x1b[H" + "\n".join(frame) + "\n"
    try:
        sys.stdout.write(out)
        sys.stdout.flush()
    except OSError:
        pass


def _console_dashboard_push(msg: str) -> None:
    text = (msg or "").strip()
    if not text:
        return
    with _CONSOLE_DASHBOARD_LOCK:
        _CONSOLE_DASHBOARD_LINES.append(text)
        _render_console_dashboard()

_job_lock = threading.Lock()
# job_id -> job record (active and recently finished; pruned after completion)
_jobs: dict[str, dict] = {}
_MAX_COMPLETED_JOBS_KEPT = 40
WEB_JOBS_REHYDRATE_DONE = False

# Cap lines kept for “refresh while running” log replay (each line ends with \n).
MAX_JOB_OUTPUT_LINES = 12_000


def _live_log_path_for_job(job_id: str) -> Path:
    return _WEB_DIR / ".live" / f"{job_id}.log"


def _pid_still_running(pid: int) -> bool:
    """True if a process with this pid exists (best-effort, cross-platform)."""
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        k = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        k.CloseHandle(int(h))
        return True
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    else:
        return True


def _read_active_web_jobs() -> list[dict]:
    if not WEB_ACTIVE_JOBS_PATH.is_file():
        return []
    try:
        raw = json.loads(WEB_ACTIVE_JOBS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, dict):
        return []
    jobs = raw.get("jobs")
    if not isinstance(jobs, list):
        return []
    out: list[dict] = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        jid = j.get("id")
        sid = j.get("script_id")
        pid = j.get("pid")
        if (
            not isinstance(jid, str)
            or not isinstance(sid, str)
            or not isinstance(pid, (int, float))
        ):
            continue
        out.append(
            {
                "id": str(jid),
                "script_id": str(sid),
                "pid": int(pid),
                "recovered": bool(j.get("recovered")),
            }
        )
    return out


def _write_active_web_jobs(jobs: list[dict]) -> None:
    try:
        WEB_ACTIVE_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        WEB_ACTIVE_JOBS_PATH.write_text(
            json.dumps({"jobs": jobs}, indent=0, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _register_active_web_job(
    job_id: str, script_id: str, pid: int, *, recovered: bool
) -> None:
    with _job_lock:
        current = [j for j in _read_active_web_jobs() if j.get("id") != job_id]
        current.append(
            {
                "id": job_id,
                "script_id": script_id,
                "pid": int(pid),
                "recovered": recovered,
            }
        )
        _write_active_web_jobs(current)


def _unregister_active_web_job(job_id: str) -> None:
    with _job_lock:
        current = [j for j in _read_active_web_jobs() if j.get("id") != job_id]
        _write_active_web_jobs(current)


def _read_live_log_to_buffer_list(job_id: str) -> list[str]:
    p = _live_log_path_for_job(job_id)
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    return text.splitlines(keepends=True)


def _watch_recovered_subprocess(
    job_id: str, pid: int, out_q: queue.Queue, job_ref: dict
) -> None:
    """After UI restart, wait until pid exits; then emit result and mark job done."""
    while _pid_still_running(pid):
        time.sleep(0.45)
    note = "\n[Web UI reconnected: subprocess has exited. Exit code is unknown.]\n"
    lock = job_ref.get("output_lock")
    if lock is not None:
        with lock:
            buf: list = job_ref["output_buffer"]
            buf.append(note)
            _trim_job_output_buffer(buf)
    out_q.put({"type": "line", "text": note})
    out_q.put({"type": "result", "exit_code": -1})
    _mark_job_completed(job_ref)
    job_ref["done"].set()
    _unregister_active_web_job(job_id)


def _rehydrate_web_jobs() -> None:
    """Re-register jobs that were still running when the last web UI process died."""
    global WEB_JOBS_REHYDRATE_DONE
    if WEB_JOBS_REHYDRATE_DONE:
        return
    WEB_JOBS_REHYDRATE_DONE = True

    saved = _read_active_web_jobs()
    if not saved:
        return
    pruned: list[dict] = []
    for ent in saved:
        jid = ent["id"]
        sid = ent["script_id"]
        pid = int(ent["pid"])
        if not _pid_still_running(pid) or sid not in SCRIPTS:
            continue
        pruned.append(
            {
                "id": jid,
                "script_id": sid,
                "pid": pid,
                "recovered": True,
            }
        )
    if len(pruned) != len(saved):
        _write_active_web_jobs(pruned)
    for ent in pruned:
        jid = ent["id"]
        sid = ent["script_id"]
        pid = int(ent["pid"])
        out_q: queue.Queue = queue.Queue()
        done = threading.Event()
        log_lines = _read_live_log_to_buffer_list(jid)
        if log_lines:
            head = f"… Log restored from {_live_log_path_for_job(jid).name} …\n\n"
            output_buf: list[str] = [head] + log_lines
        else:
            output_buf = [
                f"… Recovered {SCRIPT_LABELS.get(sid, sid)} (pid {pid}) after web UI "
                f"restart. The on-disk log is empty; stream updates when the process exits.\n"
            ]
        output_lock = threading.Lock()
        job_ref = {
            "id": jid,
            "script_id": sid,
            "queue": out_q,
            "done": done,
            "output_buffer": output_buf,
            "output_lock": output_lock,
            "completed_ts": 0.0,
            "recovered": True,
            "pid": pid,
            "proc": None,
            "playlist_total": None,
            "env_overrides": {},
            "label_override": None,
        }
        t = threading.Thread(
            target=_watch_recovered_subprocess,
            args=(jid, pid, out_q, job_ref),
            name=f"ppg-recover-{jid[:8]}",
            daemon=True,
        )
        with _job_lock:
            if jid in _jobs:
                continue
            _jobs[jid] = job_ref
        t.start()


def _trim_job_output_buffer(buf: list[str]) -> None:
    excess = len(buf) - MAX_JOB_OUTPUT_LINES
    if excess > 0:
        del buf[0:excess]


def _cleanup_stale_live_logs(max_age_sec: float = 86400 * 7) -> None:
    """Drop old webui/.live/*.log files so the directory does not grow forever.

    Logs are not removed as soon as a job ends: a separate PowerShell window
    tails the same path with Get-Content -Wait, and deleting the file mid-run
    causes FileNotFound errors in that window.
    """
    d = _WEB_DIR / ".live"
    if not d.is_dir():
        return
    cutoff = time.time() - max_age_sec
    for p in d.glob("*.log"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
        except OSError:
            pass


_cleanup_stale_live_logs()


def _script_path(script_id: str) -> Path | None:
    if script_id not in SCRIPTS:
        return None
    path = REPO_ROOT / SCRIPTS[script_id]
    return path if path.is_file() else None


def _json_group_path(file_id: str) -> Path | None:
    if file_id not in JSON_GROUP_FILES:
        return None
    path = (REPO_ROOT / JSON_GROUP_FILES[file_id]).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    return path


def _win_launch_live_log_tailer(log_file: Path) -> None:
    """Open a new console running PowerShell Get-Content -Wait on log_file (Windows)."""
    path_lit = str(log_file.resolve())
    # Single-quoted path in PowerShell: escape embedded ' as ''
    path_ps = path_lit.replace("'", "''")
    ps_cmd = (
        f"$p = '{path_ps}'; "
        "$deadline = (Get-Date).AddSeconds(30); "
        "while (-not (Test-Path -LiteralPath $p)) { "
        "if ((Get-Date) -gt $deadline) "
        "{ Write-Host 'Timed out waiting for log file:' $p; exit 1 }; "
        "Start-Sleep -Milliseconds 150 }; "
        "Get-Content -LiteralPath $p -Encoding utf8 -Wait -Tail 0"
    )
    try:
        subprocess.Popen(
            [
                "cmd.exe",
                "/c",
                "start",
                "PPG live output",
                "powershell.exe",
                "-NoLogo",
                "-NoExit",
                "-Command",
                ps_cmd,
            ],
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _pump_merged_output(
    proc: subprocess.Popen,
    out_q: queue.Queue,
    live_f,
    buf: list[str],
    buf_lock: threading.Lock | None = None,
) -> None:
    """Read merged stdout+stderr as bytes so tqdm \\r updates do not block on readline()."""
    out = proc.stdout
    assert out is not None
    lock_cm = contextlib.nullcontext()
    if buf_lock is not None:
        lock_cm = buf_lock
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    tail = ""
    while True:
        block = out.read(8192)
        if not block:
            tail += dec.decode(b"", final=True)
            break
        tail += dec.decode(block)
        tail = tail.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in tail:
            line, tail = tail.split("\n", 1)
            line = line + "\n"
            with lock_cm:
                buf.append(line)
                _trim_job_output_buffer(buf)
            out_q.put({"type": "line", "text": line})
            if live_f:
                try:
                    live_f.write(line)
                    live_f.flush()
                except OSError:
                    pass
    if tail:
        line = tail if tail.endswith("\n") else tail + "\n"
        with lock_cm:
            buf.append(line)
            _trim_job_output_buffer(buf)
        out_q.put({"type": "line", "text": line})
        if live_f:
            try:
                live_f.write(line)
                live_f.flush()
            except OSError:
                pass


def _mark_job_completed(job_ref: dict) -> None:
    job_ref["completed_ts"] = time.time()


def _active_job_for_script_unlocked(script_id: str) -> dict | None:
    for j in _jobs.values():
        if j["script_id"] == script_id and not j["done"].is_set():
            return j
    return None


def _prune_completed_jobs_unlocked() -> None:
    """Remove oldest finished jobs so memory stays bounded."""
    done_jobs = [
        (jid, j)
        for jid, j in _jobs.items()
        if j["done"].is_set()
    ]
    if len(done_jobs) <= _MAX_COMPLETED_JOBS_KEPT:
        return
    done_jobs.sort(key=lambda x: float(x[1].get("completed_ts") or 0.0))
    for jid, _ in done_jobs[: len(done_jobs) - _MAX_COMPLETED_JOBS_KEPT]:
        _jobs.pop(jid, None)


def _run_script_worker(
    job_id: str,
    script_id: str,
    out_q: queue.Queue,
    done: threading.Event,
    output_buf: list[str],
    output_lock: threading.Lock,
    job_ref: dict,
) -> None:
    def finish() -> None:
        _unregister_active_web_job(job_id)
        _mark_job_completed(job_ref)
        done.set()

    path = _script_path(script_id)
    if not path:
        msg = "Script not found\n"
        with output_lock:
            output_buf.append(msg)
            _trim_job_output_buffer(output_buf)
        out_q.put({"type": "error", "message": "Script not found"})
        out_q.put({"type": "result", "exit_code": 127})
        finish()
        return

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for _ek, _ev in (job_ref.get("env_overrides") or {}).items():
        env[str(_ek)] = str(_ev)

    live_f = None
    _cleanup_stale_live_logs()
    live_path = _live_log_path_for_job(job_id)
    live_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        live_path.write_text("", encoding="utf-8")
        live_f = open(live_path, "a", encoding="utf-8", newline="")
    except OSError:
        live_f = None
    if live_f is not None and sys.platform == "win32":
        _win_launch_live_log_tailer(live_path)
        time.sleep(0.25)
        live_msg = (
            "Opened a separate console window with the same live output "
            f"(mirrors below; temp file {live_path.name}).\n\n"
        )
        with output_lock:
            output_buf.append(live_msg)
            _trim_job_output_buffer(output_buf)
        out_q.put({"type": "line", "text": live_msg})
    elif live_f is not None:
        rec_msg = f"On-disk log for recovery: {live_path.name}\n\n"
        with output_lock:
            output_buf.append(rec_msg)
            _trim_job_output_buffer(output_buf)
        out_q.put({"type": "line", "text": rec_msg})

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(path)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=env,
        )
    except OSError as e:
        err_line = str(e) + "\n"
        with output_lock:
            output_buf.append(err_line)
            _trim_job_output_buffer(output_buf)
        out_q.put({"type": "error", "message": str(e)})
        out_q.put({"type": "result", "exit_code": 126})
        finish()
        if live_f is not None:
            try:
                live_f.close()
            except OSError:
                pass
        return

    job_ref["pid"] = proc.pid
    job_ref["proc"] = proc
    _register_active_web_job(job_id, script_id, proc.pid, recovered=False)

    exit_code = -1
    buf = output_buf
    try:
        _pump_merged_output(proc, out_q, live_f, buf, output_lock)
    except Exception as e:
        err_line = f"Read error: {e}\n"
        with output_lock:
            output_buf.append(err_line)
            _trim_job_output_buffer(output_buf)
        out_q.put({"type": "error", "message": f"Read error: {e}"})
    finally:
        exit_code = proc.wait()
        if live_f:
            try:
                live_f.close()
            except OSError:
                pass
        try:
            with output_lock:
                buf_snapshot = list(output_buf)
            failed = _failed_playlists_from_log("".join(buf_snapshot), script_id)
            if failed:
                out_q.put({"type": "run_summary", "failed_playlists": failed})
        except Exception:
            pass
        _invalidate_lac_leaf_cache_after_run(script_id, exit_code)
        out_q.put({"type": "result", "exit_code": exit_code})
        finish()


@app.route("/")
def index():
    scripts_meta = [
        {
            "id": sid,
            "file": SCRIPTS[sid],
            "label": SCRIPT_LABELS.get(sid, sid),
            "note": SCRIPT_NOTES.get(sid),
        }
        for sid in SCRIPTS
    ]
    json_groups_meta = [
        {
            "id": fid,
            "file": JSON_GROUP_FILES[fid],
            "label": JSON_GROUP_LABELS.get(fid, fid),
            "group_count": _count_top_level_keys(REPO_ROOT / JSON_GROUP_FILES[fid]),
        }
        for fid in JSON_GROUP_FILES
    ]
    return render_template(
        "index.html",
        scripts=scripts_meta,
        json_groups=json_groups_meta,
        repo_root=str(REPO_ROOT),
        script_meta=script_card_meta(),
    )


@app.route("/api/script-meta")
def api_script_meta():
    """Playlist / artist counts for script grid cards (reflects current .env + JSON on disk)."""
    return jsonify(script_card_meta())


@app.route("/api/scripts")
def api_scripts():
    m = script_card_meta()
    return jsonify(
        [
            {
                "id": sid,
                "file": SCRIPTS[sid],
                "label": SCRIPT_LABELS.get(sid, sid),
                "note": SCRIPT_NOTES.get(sid),
                "meta": m.get(sid),
            }
            for sid in SCRIPTS
        ]
    )


@app.route("/api/status")
def api_status():
    with _job_lock:
        active_jobs: list[dict] = []
        for j in _jobs.values():
            if j["done"].is_set():
                continue
            active_jobs.append(
                {
                    "id": j["id"],
                    "script_id": j["script_id"],
                    "label": j.get("label_override")
                    or SCRIPT_LABELS.get(j["script_id"], j["script_id"]),
                    "playlist_total": j.get("playlist_total"),
                    "recovered": bool(j.get("recovered")),
                }
            )
    first = active_jobs[0] if len(active_jobs) == 1 else None
    ext_raw = _load_active_run_state()
    ext_out: dict | None = None
    if ext_raw:
        sid = _web_script_id_for_runner_filename(ext_raw.get("script_name"))
        ext_out = {**ext_raw, "web_script_id": sid}
    return jsonify(
        {
            "busy": len(active_jobs) > 0,
            "active_jobs": active_jobs,
            "job": first,
            "external_run": ext_out,
        }
    )


@app.route("/api/job/<job_id>/output", methods=["GET"])
def api_job_output(job_id: str):
    """Buffered stdout for a job (used to refill the log after a page refresh)."""
    with _job_lock:
        j = _jobs.get(job_id)
        if not j:
            return jsonify({"error": "Unknown job", "text": "", "line_count": 0}), 404
        buf = j["output_buffer"]
        lock = j["output_lock"]
        with lock:
            text = "".join(buf)
            n = len(buf)
    return jsonify({"text": text, "line_count": n})


@app.route("/api/stats")
def api_stats():
    """Aggregate playlist timing and failures from repo log.txt."""
    try:
        max_runs = int(request.args.get("max_runs", "500"))
    except (TypeError, ValueError):
        max_runs = 500
    try:
        max_slowest = int(request.args.get("max_slowest", "40"))
    except (TypeError, ValueError):
        max_slowest = 40
    try:
        max_recent = int(request.args.get("max_recent", "30"))
    except (TypeError, ValueError):
        max_recent = 30
    max_runs = max(0, min(max_runs, 5000))
    max_slowest = max(1, min(max_slowest, 200))
    max_recent = max(1, min(max_recent, 200))
    payload = _build_stats_payload(
        max_runs=max_runs, max_slowest=max_slowest, max_recent=max_recent
    )
    if not payload.get("ok"):
        return jsonify(payload), 500
    return jsonify(payload)


def _launch_script_job(
    script_id: str,
    *,
    env_overrides: dict[str, str] | None = None,
    label_override: str | None = None,
):
    """Start a generator subprocess job (full run or single-playlist via env)."""
    if not _script_path(script_id):
        return jsonify({"error": "Script file missing on disk"}), 404

    overrides = dict(env_overrides or {})
    is_single = bool(overrides.get("PPG_ONLY_PLAYLIST_TITLE"))
    display_label = label_override or SCRIPT_LABELS.get(script_id, script_id)
    playlist_total = (
        1 if is_single else _playlist_total_for_script(script_id)
    )

    with _job_lock:
        existing = _active_job_for_script_unlocked(script_id)
        if existing is not None:
            return (
                jsonify(
                    {
                        "error": "This script is already running",
                        "job_id": existing["id"],
                        "script_id": script_id,
                    }
                ),
                409,
            )

        _prune_completed_jobs_unlocked()

        job_id = str(uuid.uuid4())
        out_q: queue.Queue = queue.Queue()
        done = threading.Event()
        output_buf: list[str] = []
        output_lock = threading.Lock()
        job_ref = {
            "id": job_id,
            "script_id": script_id,
            "queue": out_q,
            "done": done,
            "output_buffer": output_buf,
            "output_lock": output_lock,
            "completed_ts": 0.0,
            "proc": None,
            "pid": None,
            "recovered": False,
            "playlist_total": playlist_total,
            "env_overrides": overrides,
            "label_override": label_override,
        }
        _jobs[job_id] = job_ref

        banner = f"=== Starting: {display_label} ===\n"
        with output_lock:
            output_buf.append(banner)
            _trim_job_output_buffer(output_buf)
        out_q.put({"type": "line", "text": banner})

        t = threading.Thread(
            target=_run_script_worker,
            args=(job_id, script_id, out_q, done, output_buf, output_lock, job_ref),
            daemon=True,
        )
        t.start()

    return jsonify(
        {
            "job_id": job_id,
            "script_id": script_id,
            "label": display_label,
            "playlist_total": playlist_total,
        }
    )


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    script_id = data.get("script")
    if not script_id or script_id not in SCRIPTS:
        return jsonify({"error": "Invalid or missing script id"}), 400
    return _launch_script_job(script_id)


@app.route("/api/regenerate-playlist", methods=["POST"])
def api_regenerate_playlist():
    """Regenerate one PPG-managed playlist (sets PPG_ONLY_PLAYLIST_TITLE for the child)."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Missing title"}), 400
    if data.get("smart"):
        return jsonify(
            {"error": "Smart playlists cannot be rebuilt with this action."}
        ), 400

    script_id, err = classify_regenerate_playlist(title)
    if err or not script_id:
        return jsonify({"error": err or "Unknown playlist"}), 400

    label = f"{SCRIPT_LABELS.get(script_id, script_id)} — {title}"
    return _launch_script_job(
        script_id,
        env_overrides={"PPG_ONLY_PLAYLIST_TITLE": title},
        label_override=label,
    )


@app.route("/api/json-groups")
def api_json_groups_list():
    items = []
    for fid in JSON_GROUP_FILES:
        p = _json_group_path(fid)
        items.append(
            {
                "id": fid,
                "file": JSON_GROUP_FILES[fid],
                "label": JSON_GROUP_LABELS.get(fid, fid),
                "exists": p.is_file() if p else False,
                "group_count": _count_top_level_keys(REPO_ROOT / JSON_GROUP_FILES[fid]),
            }
        )
    return jsonify(items)


@app.route("/api/json-groups/<file_id>", methods=["GET"])
def api_json_group_get(file_id: str):
    path = _json_group_path(file_id)
    if not path:
        return jsonify({"error": "Unknown file"}), 404
    if not path.is_file():
        return jsonify(
            {
                "id": file_id,
                "exists": False,
                "content": "{\n}\n",
            }
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"id": file_id, "exists": True, "content": text})


@app.route("/api/json-groups/<file_id>", methods=["PUT"])
def api_json_group_put(file_id: str):
    path = _json_group_path(file_id)
    if not path:
        return jsonify({"error": "Unknown file"}), 404
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if not isinstance(content, str):
        return jsonify({"error": "Missing string field 'content'"}), 400
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON: {e}"}), 400
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/dotenv", methods=["GET"])
def api_dotenv_get():
    path = _dotenv_path()
    if not path:
        return jsonify({"error": "Invalid .env path"}), 400
    if not path.is_file():
        return jsonify({"exists": False, "content": ""})
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"exists": True, "content": text})


@app.route("/api/dotenv", methods=["PUT"])
def api_dotenv_put():
    path = _dotenv_path()
    if not path:
        return jsonify({"error": "Invalid .env path"}), 400
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if not isinstance(content, str):
        return jsonify({"error": "Missing string field 'content'"}), 400
    tmp = path.parent / f"{path.name}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/plex/genres", methods=["GET", "POST"])
def api_plex_genres():
    """Return sorted unique genre titles from the Plex Music library (for the group editor)."""
    try:
        from dotenv import load_dotenv
        from plexapi.server import PlexServer

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    url = (os.getenv("PLEX_URL") or "").strip()
    token = (os.getenv("PLEX_TOKEN") or "").strip()
    section_name = (os.getenv("PLEX_MUSIC_SECTION") or "Music").strip()
    if not url or not token:
        return jsonify(
            {"error": "Set PLEX_URL and PLEX_TOKEN in .env to fetch genres."}
        ), 400

    try:
        plex = PlexServer(url, token)
        music = plex.library.section(section_name)
        choices = music.listFilterChoices("genre")
        genres = sorted(
            {
                str(c.title).strip()
                for c in choices
                if c is not None and getattr(c, "title", None)
            }
        )
        return jsonify(
            {
                "genres": genres,
                "count": len(genres),
                "library_section": section_name,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/plex/moods", methods=["GET", "POST"])
def api_plex_moods():
    """Return sorted unique mood titles from the Plex Music library (for the group editor)."""
    try:
        from dotenv import load_dotenv
        from plexapi.server import PlexServer

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    url = (os.getenv("PLEX_URL") or "").strip()
    token = (os.getenv("PLEX_TOKEN") or "").strip()
    section_name = (os.getenv("PLEX_MUSIC_SECTION") or "Music").strip()
    if not url or not token:
        return jsonify(
            {"error": "Set PLEX_URL and PLEX_TOKEN in .env to fetch moods."}
        ), 400

    try:
        plex = PlexServer(url, token)
        music = plex.library.section(section_name)
        choices = music.listFilterChoices("mood")
        moods = sorted(
            {
                str(c.title).strip()
                for c in choices
                if c is not None and getattr(c, "title", None)
            }
        )
        return jsonify(
            {
                "moods": moods,
                "count": len(moods),
                "library_section": section_name,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/plex/playlists", methods=["GET"])
def api_plex_playlists():
    """List audio playlists on the Plex server with summaries and parsed Updated-on times."""
    try:
        from dotenv import load_dotenv
        from plexapi.server import PlexServer

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    url = (os.getenv("PLEX_URL") or "").strip()
    token = (os.getenv("PLEX_TOKEN") or "").strip()
    if not url or not token:
        return jsonify(
            {"error": "Set PLEX_URL and PLEX_TOKEN in .env to list playlists."}
        ), 400

    try:
        plex = PlexServer(url, token)
        mix_titles = _ppg_mix_playlist_titles_from_config()
        items = []
        for pl in plex.playlists(playlistType="audio"):
            try:
                summary = getattr(pl, "summary", None) or ""
                title = pl.title or ""
                items.append(
                    {
                        "title": title,
                        "playlistType": pl.playlistType or "audio",
                        "smart": bool(getattr(pl, "smart", False)),
                        "ppg": _playlist_is_ppg_managed(title, mix_titles),
                        "leafCount": getattr(pl, "leafCount", None),
                        "ratingKey": getattr(pl, "ratingKey", None),
                        "summary": summary,
                        "updatedOn": _updated_on_from_playlist_summary(summary),
                    }
                )
            except Exception:
                continue
        items.sort(key=lambda x: (x["title"] or "").lower())
        return jsonify({"playlists": items, "count": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


_MAX_PLAYLIST_DELETE_BATCH = 500


@app.route("/api/plex/playlists/delete", methods=["POST"])
def api_plex_playlists_delete():
    """Delete audio playlists on the Plex server by ratingKey (from /api/plex/playlists)."""
    try:
        from dotenv import load_dotenv
        from plexapi.server import PlexServer

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    url = (os.getenv("PLEX_URL") or "").strip()
    token = (os.getenv("PLEX_TOKEN") or "").strip()
    if not url or not token:
        return jsonify(
            {"error": "Set PLEX_URL and PLEX_TOKEN in .env to delete playlists."}
        ), 400

    body = request.get_json(force=True, silent=True) or {}
    raw_keys = body.get("rating_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        return jsonify({"error": "Provide a non-empty rating_keys array."}), 400

    try:
        int_keys = [int(k) for k in raw_keys]
    except (TypeError, ValueError):
        return jsonify({"error": "rating_keys must be integers."}), 400

    if len(int_keys) > _MAX_PLAYLIST_DELETE_BATCH:
        return jsonify(
            {
                "error": f"Too many playlists in one request (max {_MAX_PLAYLIST_DELETE_BATCH})."
            }
        ), 400

    seen: set[int] = set()
    deduped: list[int] = []
    for k in int_keys:
        if k not in seen:
            seen.add(k)
            deduped.append(k)

    deleted: list[int] = []
    errors: list[dict] = []
    try:
        plex = PlexServer(url, token)
        for rk in deduped:
            try:
                item = plex.fetchItem(rk)
            except Exception as e:
                errors.append({"rating_key": rk, "error": str(e)})
                continue
            if item is None:
                errors.append({"rating_key": rk, "error": "Not found"})
                continue
            item_type = (getattr(item, "type", None) or getattr(item, "TYPE", None) or "")
            if str(item_type).lower() != "playlist":
                errors.append(
                    {
                        "rating_key": rk,
                        "error": f"Not a playlist (type={item_type!r})",
                    }
                )
                continue
            try:
                item.delete()
                deleted.append(rk)
            except Exception as e:
                errors.append({"rating_key": rk, "error": str(e)})
        return jsonify({"deleted": deleted, "errors": errors})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


def _sse_format(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.route("/api/stream/<job_id>")
def api_stream(job_id: str):
    with _job_lock:
        j = _jobs.get(job_id)
        if not j:
            return jsonify({"error": "Unknown or expired job"}), 404
        out_q = j["queue"]
        done = j["done"]

    def generate():
        while True:
            try:
                item = out_q.get(timeout=15)
            except queue.Empty:
                yield _sse_format({"type": "heartbeat"})
                if done.is_set() and out_q.empty():
                    break
                continue

            yield _sse_format(item)
            if item.get("type") == "result":
                break
            if item.get("type") == "error" and done.is_set():
                break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.after_request
def _console_log_recent_requests(response):
    # Polling endpoint hits every second; keep dashboard focused on useful events.
    path = request.path or ""
    method = request.method or ""
    status = int(getattr(response, "status_code", 0) or 0)
    skip = path == "/api/status" and method == "GET" and 200 <= status < 400
    if not skip:
        remote = request.remote_addr or "-"
        _console_dashboard_push(f"{method} {path} -> {status} ({remote})")
    return response


def _load_bind_config() -> tuple[str, int]:
    """host, port — webui/config.json first, then .env (PPG_WEB_HOST / PPG_WEB_PORT)."""
    host = "127.0.0.1"
    port = 5959

    if _WEB_CONFIG_PATH.is_file():
        try:
            with open(_WEB_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("host"), str) and data["host"].strip():
                host = data["host"].strip()
            if data.get("port") is not None:
                port = int(data["port"])
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
            print(f"⚠️  Could not read {_WEB_CONFIG_PATH}: {e} — using defaults.")

    env_host = os.environ.get("PPG_WEB_HOST")
    if env_host is not None and env_host.strip():
        host = env_host.strip()
    env_port = os.environ.get("PPG_WEB_PORT")
    if env_port is not None and str(env_port).strip():
        port = int(env_port.strip())

    return host, port


# Restore in-memory job tracking (and stream queue) if web UI exited while a
# subprocess from /api/run was still alive (e.g. service restart, crash).
_rehydrate_web_jobs()


def main():
    host, port = _load_bind_config()
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    with _CONSOLE_DASHBOARD_LOCK:
        _CONSOLE_DASHBOARD_HEADER.clear()
        _CONSOLE_DASHBOARD_HEADER.extend(
            [
                f"PPG Web UI: http://{host}:{port}/",
                f"Config: {_WEB_CONFIG_PATH} (env PPG_WEB_HOST / PPG_WEB_PORT override)",
                f"Repo root (script cwd): {REPO_ROOT}",
                "HTTP request line logging is compact mode (polling suppressed).",
            ]
        )
        _CONSOLE_DASHBOARD_LINES.clear()
        _CONSOLE_DASHBOARD_LINES.append("Server starting...")
        _render_console_dashboard()
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
