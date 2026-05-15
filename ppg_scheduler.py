#!/usr/bin/env python3
"""
PPG scheduler — run generator scripts on intervals or at fixed times.

Reads ppg_schedule.json (override with PPG_SCHEDULE_FILE). Intended to run as a
long-lived service alongside the web UI (systemd user unit ppg-scheduler.service).

  python ppg_scheduler.py              # daemon loop
  python ppg_scheduler.py --once ID    # run one job now (for testing)
  python ppg_scheduler.py --list       # show jobs and next run times
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent

# Repo on path for module.*
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

from module.ppg_schedule import (  # noqa: E402
    REPO_ROOT as SCHEDULE_REPO_ROOT,
    ScheduledJob,
    default_schedule_path,
    job_is_due,
    job_next_run,
    load_schedule_file,
    next_run_after,
)

LOG_PATH = REPO_ROOT / "ppg_scheduler.log"
STATE_PATH = REPO_ROOT / "webui" / "data" / "ppg_scheduler_state.json"
JOB_LOG_DIR = STATE_PATH.parent / "scheduler_runs"
POLL_SECONDS = max(5, int(os.getenv("PPG_SCHEDULER_POLL_SECONDS", "30") or "30"))
HEARTBEAT_SECONDS = max(
    60, int(os.getenv("PPG_SCHEDULER_HEARTBEAT_SECONDS", "300") or "300")
)
# When enabled, append each job's stdout/stderr to webui/data/scheduler_runs/<job_id>.log
# (Scheduler tab tails this file). Set PPG_SCHEDULER_JOB_LOG=0 to disable.
JOB_LOG_MIRROR = os.getenv("PPG_SCHEDULER_JOB_LOG", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"ppg_scheduler: could not write {LOG_PATH}: {e}", file=sys.stderr, flush=True)


def _load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        obj = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def _lock_path(job_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
    return STATE_PATH.parent / f"ppg_schedule_lock_{safe}.lock"


def _try_acquire_lock(job_id: str) -> bool:
    path = _lock_path(job_id)
    try:
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < 6 * 3600:
                return False
        path.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def _release_lock(job_id: str) -> None:
    try:
        _lock_path(job_id).unlink(missing_ok=True)
    except OSError:
        pass


def _run_subprocess_foreground(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    mirror_log: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a script in the foreground (blocking, inherited stdio for journalctl)."""
    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["stdout"] = None
        kwargs["stderr"] = None
        return subprocess.run(cmd, **kwargs)

    kwargs["start_new_session"] = False
    if mirror_log is None:
        kwargs["stdout"] = None
        kwargs["stderr"] = None
        return subprocess.run(cmd, **kwargs)

    mirror_log.parent.mkdir(parents=True, exist_ok=True)
    jf = open(mirror_log, "a", encoding="utf-8", newline="\n", buffering=1)
    jf.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} =====\n")
    jf.flush()
    kwargs["stdout"] = jf
    kwargs["stderr"] = subprocess.STDOUT
    try:
        return subprocess.run(cmd, **kwargs)
    finally:
        jf.close()


def run_job(job: ScheduledJob, *, python_exe: str | None = None) -> int:
    py = python_exe or sys.executable
    cmd = job.build_command(py, SCHEDULE_REPO_ROOT)
    env = os.environ.copy()
    if job.env:
        env.update(job.env)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONPATH"] = str(SCHEDULE_REPO_ROOT)
    mirror = JOB_LOG_DIR / f"{job.id}.log" if JOB_LOG_MIRROR else None
    _log(f"[{job.id}] START {' '.join(cmd)}")
    if mirror is not None:
        _log(f"[{job.id}] mirroring output to {mirror}")
    try:
        proc = _run_subprocess_foreground(
            cmd,
            cwd=str(SCHEDULE_REPO_ROOT),
            env=env,
            mirror_log=mirror,
        )
        code = int(proc.returncode)
    except OSError as e:
        _log(f"[{job.id}] FAILED to start: {e}")
        return 127
    if code == 0:
        _log(f"[{job.id}] OK exit={code}")
    else:
        _log(
            f"[{job.id}] ERROR exit={code} "
            "(check script output above, log.txt, and ppg_events.jsonl in the repo)"
        )
    return code


def cmd_list(jobs: list[ScheduledJob]) -> int:
    state = _load_state()
    now = datetime.now()
    _log(f"Schedule file: {default_schedule_path()}")
    _log(f"State file: {STATE_PATH}")
    _log(f"Log file: {LOG_PATH}")
    for job in jobs:
        row = state.get(job.id) if isinstance(state.get(job.id), dict) else {}
        if not job.enabled:
            _log(f"  {job.id}: disabled ({job.script})")
            continue
        try:
            nxt = job_next_run(job, row)
            due = job_is_due(job, row, now=now)
        except ValueError as e:
            _log(f"  {job.id}: INVALID schedule — {e}")
            continue
        last = row.get("last_finished") or "never"
        exit_c = row.get("last_exit_code")
        exit_s = f" exit={exit_c}" if exit_c is not None else ""
        lock = _lock_path(job.id)
        lock_s = " [LOCKED]" if lock.is_file() else ""
        _log(
            f"  {job.id}: {job.script} — next {nxt.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({job.schedule.get('type')})"
            f"{' DUE NOW' if due else ''}{lock_s}"
        )
        _log(f"      last finished: {last}{exit_s}")
    return 0


class _ScheduleCache:
    """Reload ppg_schedule.json when the file changes (web UI save needs no daemon restart)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.mtime: float | None = None
        self.all_jobs: list[ScheduledJob] = []
        self.enabled: list[ScheduledJob] = []

    def reload_if_changed(self, *, force: bool = False) -> bool:
        try:
            mtime = self.path.stat().st_mtime
        except OSError as e:
            if not self.all_jobs:
                _log(f"Schedule file not readable: {self.path} ({e})")
            return False
        if not force and self.mtime is not None and mtime == self.mtime and self.all_jobs:
            return False
        try:
            jobs, _meta = load_schedule_file(self.path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
            _log(f"Schedule reload failed (keeping previous jobs): {e}")
            return False
        prev_ids = {j.id for j in self.all_jobs}
        new_ids = {j.id for j in jobs}
        self.mtime = mtime
        self.all_jobs = jobs
        self.enabled = [j for j in jobs if j.enabled]
        if not prev_ids:
            _log(
                f"Schedule loaded ({self.path.name}) — "
                f"{len(jobs)} job(s), {len(self.enabled)} enabled"
            )
        else:
            added = new_ids - prev_ids
            removed = prev_ids - new_ids
            parts = [f"{len(jobs)} job(s), {len(self.enabled)} enabled"]
            if added:
                parts.append("added " + ", ".join(sorted(added)))
            if removed:
                parts.append("removed " + ", ".join(sorted(removed)))
            if not added and not removed:
                parts.append("updated")
            _log(f"Schedule reloaded ({self.path.name}) — " + "; ".join(parts))
        return True


def _interruptible_sleep(until: datetime, cache: _ScheduleCache) -> None:
    """Sleep until ``until``, checking for schedule file changes about once per second."""
    while True:
        cache.reload_if_changed()
        remaining = (until - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))


def cmd_once(jobs: list[ScheduledJob], job_id: str) -> int:
    match = [j for j in jobs if j.id == job_id]
    if not match:
        _log(f"Unknown job id {job_id!r}")
        return 1
    job = match[0]
    if not _try_acquire_lock(job.id):
        _log(f"[{job.id}] already running (lock present)")
        return 1
    try:
        code = run_job(job)
    finally:
        _release_lock(job.id)
    state = _load_state()
    state[job.id] = {
        "last_started": datetime.now().isoformat(timespec="seconds"),
        "last_finished": datetime.now().isoformat(timespec="seconds"),
        "last_exit_code": code,
    }
    _save_state(state)
    return code


def daemon_loop(schedule_path: Path) -> None:
    cache = _ScheduleCache(schedule_path)
    cache.reload_if_changed(force=True)
    if not cache.all_jobs:
        _log("No valid schedule yet; watching for ppg_schedule.json …")
    elif not cache.enabled:
        _log("No enabled jobs; watching for schedule changes …")
    _log(f"Repo root: {REPO_ROOT.resolve()}")
    _log(f"Schedule file: {schedule_path.resolve()}")
    _log(
        f"PPG scheduler started — poll every {POLL_SECONDS}s, "
        f"heartbeat every {HEARTBEAT_SECONDS}s, log {LOG_PATH.resolve()}"
    )
    last_heartbeat: datetime | None = None
    while True:
        cache.reload_if_changed()
        enabled = cache.enabled
        now = datetime.now()
        state = _load_state()
        next_wake = now + timedelta(seconds=POLL_SECONDS)
        if last_heartbeat is None or (now - last_heartbeat).total_seconds() >= HEARTBEAT_SECONDS:
            last_heartbeat = now
            if not enabled:
                _log("Heartbeat — no enabled jobs (edit ppg_schedule.json or the Scheduler tab)")
            else:
                for job in enabled:
                    row = state.get(job.id) if isinstance(state.get(job.id), dict) else {}
                    try:
                        nxt = job_next_run(job, row, now=now)
                        due = job_is_due(job, row, now=now)
                        lock_s = " locked" if _lock_path(job.id).is_file() else ""
                        _log(
                            f"Heartbeat — {job.id} ({job.script}): "
                            f"next {nxt.strftime('%Y-%m-%d %H:%M:%S') if nxt else '?'}"
                            f"{' DUE NOW' if due else ''}{lock_s}"
                        )
                    except ValueError as e:
                        _log(f"Heartbeat — {job.id}: invalid schedule ({e})")
        for job in enabled:
            row = state.get(job.id) if isinstance(state.get(job.id), dict) else {}
            try:
                nxt = job_next_run(job, row, now=now)
                due = job_is_due(job, row, now=now)
            except ValueError as e:
                _log(f"[{job.id}] schedule error: {e}")
                continue
            if not due:
                if nxt and nxt < next_wake:
                    next_wake = nxt
                continue
            if not _try_acquire_lock(job.id):
                _log(
                    f"[{job.id}] skip — lock file present ({_lock_path(job.id).name}); "
                    "remove it if no run is active"
                )
                continue
            started = datetime.now().isoformat(timespec="seconds")
            state[job.id] = {**(state.get(job.id) or {}), "last_started": started}
            _save_state(state)
            code = run_job(job)
            finished = datetime.now().isoformat(timespec="seconds")
            state[job.id] = {
                "last_started": started,
                "last_finished": finished,
                "last_exit_code": code,
            }
            _save_state(state)
            _release_lock(job.id)
            try:
                nxt = next_run_after(job.schedule, datetime.now())
                _log(f"[{job.id}] next run {nxt.strftime('%Y-%m-%d %H:%M:%S')}")
            except ValueError:
                pass

        _interruptible_sleep(next_wake, cache)


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description="PPG scheduled script runner")
    parser.add_argument(
        "--schedule",
        type=Path,
        default=None,
        help="Path to schedule JSON (default: PPG_SCHEDULE_FILE or ppg_schedule.json)",
    )
    parser.add_argument("--list", action="store_true", help="List jobs and next run times")
    parser.add_argument("--once", metavar="JOB_ID", help="Run one job immediately")
    args = parser.parse_args()
    path = args.schedule or default_schedule_path()
    if args.list or args.once:
        try:
            jobs, _meta = load_schedule_file(path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
            _log(f"Failed to load schedule: {e}")
            return 1
        if args.list:
            return cmd_list(jobs)
        return cmd_once(jobs, args.once.strip())
    try:
        daemon_loop(path)
    except KeyboardInterrupt:
        _log("Stopped.")
        return 0
    except Exception as e:
        import traceback

        _log(f"FATAL scheduler crash: {e}")
        for line in traceback.format_exc().splitlines():
            _log(line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
