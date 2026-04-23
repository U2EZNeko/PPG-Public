"""
Append a short run summary to log.txt in the repo root after each generator script.

Also appends structured lines to webui/data/ppg_events.jsonl on every run_start,
playlist timing, failure, and run_end so the web Statistics tab and /api/stats
stay accurate for cron/CLI runs (paths are repo-root, not cwd-relative).

Used by PPG-*.py entry points: start_run() at startup, finish_run() in finally,
fail_playlist() / playlist_succeeded() during the run.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path


def _ensure_utf8_stdio() -> None:
    """Avoid UnicodeEncodeError on Windows (cp1252) when printing emoji in logs."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconf = getattr(stream, "reconfigure", None)
        if not reconf:
            continue
        try:
            reconf(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


_ensure_utf8_stdio()

_REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = _REPO_ROOT / "log.txt"
RUN_STATE_PATH = _REPO_ROOT / ".ppg_run_state.json"
# Append-only machine log for the web UI / Statistics (cron-safe: paths not cwd-relative).
EVENTS_PATH = _REPO_ROOT / "webui" / "data" / "ppg_events.jsonl"
MAX_EVENTS_FILE_BYTES = 25_000_000
_lock = threading.Lock()

_current: "RunRecorder | None" = None


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = int(seconds // 60), int(seconds % 60)
        return f"{m}m {s}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m}m {s}s"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _rotate_events_file() -> None:
    bak = EVENTS_PATH.with_suffix(".jsonl.bak")
    try:
        if bak.is_file():
            bak.unlink()
    except OSError:
        pass
    try:
        if EVENTS_PATH.is_file():
            EVENTS_PATH.rename(bak)
    except OSError:
        pass


def _append_jsonl_event(payload: dict) -> None:
    """Append one JSON object per line for the web UI (works for cron / CLI runs)."""
    try:
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _lock:
        try:
            if (
                EVENTS_PATH.is_file()
                and EVENTS_PATH.stat().st_size >= MAX_EVENTS_FILE_BYTES
            ):
                _rotate_events_file()
        except OSError:
            pass
        try:
            with open(EVENTS_PATH, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass


class RunRecorder:
    __slots__ = ("script_name", "run_id", "_t0", "failures", "ok_count", "playlist_timing")

    def __init__(self, script_name: str) -> None:
        self.script_name = script_name
        self.run_id = uuid.uuid4().hex[:16]
        self._t0 = time.time()
        self.failures: list[tuple[str, str]] = []
        self.ok_count = 0
        self.playlist_timing: list[tuple[str, float, bool, str]] = []

    def record_playlist_result(
        self, playlist: str, seconds: float, ok: bool, note: str = ""
    ) -> None:
        pl = (playlist or "").strip()
        if not pl:
            return
        n = (note or "").strip()
        if len(n) > 400:
            n = n[:397] + "…"
        self.playlist_timing.append((pl, float(seconds), bool(ok), n))

    def fail_playlist(self, playlist: str, reason: str = "") -> None:
        pl = (playlist or "").strip()
        if not pl:
            return
        r = (reason or "").strip()
        if len(r) > 600:
            r = r[:597] + "…"
        self.failures.append((pl, r))

    def playlist_succeeded(self) -> None:
        self.ok_count += 1

    def sync_state_file(self, *, active: bool) -> None:
        """Write live run snapshot for the web UI Statistics tab (atomic replace)."""
        payload = {
            "version": 1,
            "active": active,
            "run_id": self.run_id,
            "script_name": self.script_name,
            "started_at": datetime.fromtimestamp(self._t0).isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "playlists_ok": self.ok_count,
            "playlist_timing": [
                {
                    "playlist": pl,
                    "seconds": sec,
                    "ok": ok,
                    "note": note,
                    "duration_label": _format_duration(sec),
                }
                for pl, sec, ok, note in self.playlist_timing
            ],
            "failures": [
                {"playlist": pl, "reason": r} for pl, r in self.failures
            ],
        }
        tmp = RUN_STATE_PATH.with_suffix(".json.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with _lock:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(RUN_STATE_PATH)

    def append_to_file(self, *, had_exception: bool) -> None:
        duration = time.time() - self._t0
        started = datetime.fromtimestamp(self._t0).strftime("%Y-%m-%d %H:%M:%S")
        finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "=" * 60,
            f"Run: {self.script_name}",
            f"Started: {started}",
            f"Finished: {finished}",
            f"Duration: {_format_duration(duration)}",
            f"Result: {'crashed (uncaught exception)' if had_exception else 'completed'}",
            f"Playlists updated successfully: {self.ok_count}",
        ]
        if self.playlist_timing:
            lines.append("Per-playlist timing:")
            for pl, sec, ok, note in self.playlist_timing:
                status = "ok" if ok else "failed"
                dur = _format_duration(sec)
                if ok:
                    lines.append(f"  - {pl}: {dur} ({status})")
                else:
                    tail = f" — {note}" if note else ""
                    lines.append(f"  - {pl}: {dur} ({status}){tail}")
        if self.failures:
            lines.append("Failures:")
            for pl, reason in self.failures:
                lines.append(f"  - {pl}: {reason}" if reason else f"  - {pl}")
        else:
            lines.append("Failures: none")
        lines.append("")
        text = "\n".join(lines)
        self._print_timing_report()
        with _lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(text)

    def _print_timing_report(self) -> None:
        if not self.playlist_timing:
            return
        print("\n📋 Playlist timing summary")
        for pl, sec, ok, note in self.playlist_timing:
            status = "ok" if ok else "failed"
            dur = _format_duration(sec)
            if ok:
                print(f"   • {pl}: {dur} ({status})")
            else:
                tail = f" — {note}" if note else ""
                print(f"   • {pl}: {dur} ({status}){tail}")
        n_fail = sum(1 for x in self.playlist_timing if not x[2])
        n_tot = len(self.playlist_timing)
        if n_fail:
            print(f"   ({n_fail} of {n_tot} playlist(s) did not complete successfully)")
        print("")


def _sync_live_state() -> None:
    if _current is None:
        return
    try:
        _current.sync_state_file(active=True)
    except OSError:
        pass


def start_run(script_name: str) -> None:
    global _current
    _current = RunRecorder(script_name)
    _append_jsonl_event(
        {
            "v": 1,
            "type": "run_start",
            "run_id": _current.run_id,
            "script": script_name,
            "t": _now_iso(),
        }
    )
    _sync_live_state()


def fail_playlist(playlist: str, reason: str = "") -> None:
    if _current is not None:
        _current.fail_playlist(playlist, reason)
        pl = (playlist or "").strip()
        if pl:
            r = (reason or "").strip()
            if len(r) > 600:
                r = r[:597] + "…"
            _append_jsonl_event(
                {
                    "v": 1,
                    "type": "failure",
                    "run_id": _current.run_id,
                    "script": _current.script_name,
                    "playlist": pl,
                    "reason": r,
                    "t": _now_iso(),
                }
            )
            try:
                from .ppg_chronic_failures import record_playlist_failure

                record_playlist_failure(pl, r, _current.script_name)
            except Exception:
                pass
        _sync_live_state()


def playlist_succeeded() -> None:
    if _current is not None:
        _current.playlist_succeeded()
        _sync_live_state()


def record_playlist_result(
    playlist: str, seconds: float, ok: bool, note: str = ""
) -> None:
    if _current is not None:
        _current.record_playlist_result(playlist, seconds, ok, note)
        pl = (playlist or "").strip()
        if pl:
            n = (note or "").strip()
            if len(n) > 400:
                n = n[:397] + "…"
            _append_jsonl_event(
                {
                    "v": 1,
                    "type": "playlist",
                    "run_id": _current.run_id,
                    "script": _current.script_name,
                    "playlist": pl,
                    "seconds": float(seconds),
                    "ok": bool(ok),
                    "note": n,
                    "duration_label": _format_duration(float(seconds)),
                    "t": _now_iso(),
                }
            )
            if ok:
                try:
                    from .ppg_chronic_failures import record_playlist_success

                    record_playlist_success(pl)
                except Exception:
                    pass
        _sync_live_state()


def finish_run(had_exception: bool = False) -> None:
    global _current
    if _current is None:
        return
    rec = _current
    _current = None
    duration = time.time() - rec._t0
    _append_jsonl_event(
        {
            "v": 1,
            "type": "run_end",
            "run_id": rec.run_id,
            "script": rec.script_name,
            "t": _now_iso(),
            "had_exception": bool(had_exception),
            "duration_sec": duration,
            "duration_label": _format_duration(duration),
            "playlists_ok": rec.ok_count,
            "timing_count": len(rec.playlist_timing),
            "failures_count": len(rec.failures),
        }
    )
    rec.append_to_file(had_exception=had_exception)
    try:
        from .ppg_telegram import maybe_notify_run_finished

        maybe_notify_run_finished(rec, had_exception)
    except ImportError:
        pass
    except Exception as e:
        print(f"ppg_telegram: {e}", file=sys.stderr)
    try:
        RUN_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        RUN_STATE_PATH.with_suffix(".json.tmp").unlink(missing_ok=True)
    except OSError:
        pass
