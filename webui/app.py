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
import os
import queue
import re
from collections import defaultdict
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

_job_lock = threading.Lock()
# job_id -> job record (active and recently finished; pruned after completion)
_jobs: dict[str, dict] = {}
_MAX_COMPLETED_JOBS_KEPT = 40

# Cap lines kept for “refresh while running” log replay (each line ends with \n).
MAX_JOB_OUTPUT_LINES = 12_000


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

    live_path: Path | None = None
    live_f = None
    if sys.platform == "win32":
        _cleanup_stale_live_logs()
        live_path = _WEB_DIR / ".live" / f"{job_id}.log"
        live_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            live_path.write_text("", encoding="utf-8")
            live_f = open(live_path, "a", encoding="utf-8", newline="")
        except OSError:
            live_f = None
        if live_f is not None:
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
                    "label": SCRIPT_LABELS.get(j["script_id"], j["script_id"]),
                }
            )
    first = active_jobs[0] if len(active_jobs) == 1 else None
    return jsonify(
        {
            "busy": len(active_jobs) > 0,
            "active_jobs": active_jobs,
            "job": first,
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


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    script_id = data.get("script")
    if not script_id or script_id not in SCRIPTS:
        return jsonify({"error": "Invalid or missing script id"}), 400
    if not _script_path(script_id):
        return jsonify({"error": "Script file missing on disk"}), 404

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
        }
        _jobs[job_id] = job_ref

        banner = f"=== Starting: {SCRIPT_LABELS.get(script_id, script_id)} ===\n"
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
            "label": SCRIPT_LABELS.get(script_id, script_id),
        }
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


def main():
    host, port = _load_bind_config()
    print(f"PPG Web UI: http://{host}:{port}/")
    print(f"Config: {_WEB_CONFIG_PATH} (env PPG_WEB_HOST / PPG_WEB_PORT override)")
    print(f"Repo root (script cwd): {REPO_ROOT}")
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
