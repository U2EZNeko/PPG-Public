"""Parse ppg_schedule.json and compute next run times (stdlib; optional cron via croniter)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# script id -> (argv builder uses repo-relative path or -m module)
SCRIPT_ENTRIES: dict[str, dict[str, Any]] = {
    "daily": {"argv": ["PPG-Daily.py"]},
    "weekly": {"argv": ["PPG-Weekly.py"]},
    "moods": {"argv": ["PPG-Moods.py"]},
    "genres": {"argv": ["PPG-Genres.py"]},
    "liked_artists": {"argv": ["PPG-LikedArtists.py"]},
    "liked_artists_collection": {"argv": ["PPG-LikedArtistsCollection.py"]},
    "fetch_liked": {"argv": ["fetch-liked-artists.py"]},
}

WEEKDAY_NAMES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass
class ScheduledJob:
    id: str
    script: str
    schedule: dict[str, Any]
    enabled: bool = True
    env: dict[str, str] | None = None

    def build_command(self, python_exe: str, repo_root: Path) -> list[str]:
        entry = SCRIPT_ENTRIES.get(self.script)
        if not entry:
            raise ValueError(f"Unknown script id {self.script!r}")
        if "module" in entry:
            return [python_exe, "-m", str(entry["module"])]
        rel = entry["argv"][0]
        return [python_exe, str(repo_root / rel)]


def _parse_time(at: str) -> tuple[int, int]:
    m = _TIME_RE.match((at or "").strip())
    if not m:
        raise ValueError(f"Invalid time {at!r}; use HH:MM (24h)")
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid time {at!r}")
    return hour, minute


def _weekday_index(raw: Any) -> int:
    if isinstance(raw, int):
        if 0 <= raw <= 6:
            return raw
        raise ValueError(f"weekday must be 0–6 (Mon–Sun), got {raw}")
    key = str(raw or "").strip().lower()
    if key.isdigit():
        return _weekday_index(int(key))
    if key not in WEEKDAY_NAMES:
        raise ValueError(f"Unknown weekday {raw!r}")
    return WEEKDAY_NAMES[key]


def next_run_after(schedule: dict[str, Any], after: datetime) -> datetime:
    """Return the first run time strictly after ``after`` (naive local time)."""
    stype = str(schedule.get("type") or "").strip().lower()
    if not stype:
        raise ValueError("schedule.type is required")

    if stype == "interval":
        minutes = int(schedule.get("every_minutes") or schedule.get("minutes") or 0)
        if minutes < 1:
            raise ValueError("interval schedule needs every_minutes >= 1")
        return after + timedelta(minutes=minutes)

    if stype == "hourly":
        minute = int(schedule.get("at_minute", schedule.get("minute", 0)))
        if not 0 <= minute <= 59:
            raise ValueError("hourly at_minute must be 0–59")
        candidate = after.replace(second=0, microsecond=0, minute=minute)
        if candidate <= after:
            candidate += timedelta(hours=1)
        return candidate

    if stype == "daily":
        hour, minute = _parse_time(str(schedule.get("at") or schedule.get("time") or "00:00"))
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    if stype == "weekly":
        wd = _weekday_index(schedule.get("weekday", schedule.get("day", "mon")))
        hour, minute = _parse_time(str(schedule.get("at") or schedule.get("time") or "00:00"))
        days_ahead = (wd - after.weekday()) % 7
        candidate = after.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ) + timedelta(days=days_ahead)
        if candidate <= after:
            candidate += timedelta(days=7)
        return candidate

    if stype == "cron":
        expr = str(schedule.get("expression") or schedule.get("cron") or "").strip()
        if not expr:
            raise ValueError("cron schedule needs expression")
        try:
            from croniter import croniter
        except ImportError as e:
            raise ValueError(
                "cron schedules require croniter (pip install croniter)"
            ) from e
        base = after.replace(second=0, microsecond=0)
        itr = croniter(expr, base)
        nxt = itr.get_next(datetime)
        if nxt <= after:
            nxt = itr.get_next(datetime)
        return nxt

    raise ValueError(f"Unknown schedule.type {stype!r}")


def parse_schedule_document(raw: Any) -> tuple[list[ScheduledJob], dict[str, Any]]:
    """Validate and parse an in-memory schedule document."""
    if not isinstance(raw, dict):
        raise ValueError("Schedule file must be a JSON object")
    jobs_raw = raw.get("jobs")
    if not isinstance(jobs_raw, list):
        raise ValueError("Schedule file must contain a jobs array")
    jobs: list[ScheduledJob] = []
    for i, item in enumerate(jobs_raw):
        if not isinstance(item, dict):
            raise ValueError(f"jobs[{i}] must be an object")
        jid = str(item.get("id") or "").strip()
        if not jid:
            raise ValueError(f"jobs[{i}] needs id")
        script = str(item.get("script") or "").strip()
        if script not in SCRIPT_ENTRIES:
            raise ValueError(
                f"jobs[{i}] unknown script {script!r}; "
                f"known: {', '.join(sorted(SCRIPT_ENTRIES))}"
            )
        sched = item.get("schedule")
        if not isinstance(sched, dict):
            raise ValueError(f"jobs[{i}] needs schedule object")
        next_run_after(sched, datetime.now())  # validate
        env = item.get("env")
        if env is not None and not isinstance(env, dict):
            raise ValueError(f"jobs[{i}].env must be an object")
        jobs.append(
            ScheduledJob(
                id=jid,
                script=script,
                schedule=sched,
                enabled=bool(item.get("enabled", True)),
                env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else None,
            )
        )
    meta = {k: v for k, v in raw.items() if k != "jobs"}
    return jobs, meta


def load_schedule_file(path: Path) -> tuple[list[ScheduledJob], dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Schedule file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_schedule_document(raw)


def _parse_state_timestamp(raw: Any, *, fallback: datetime) -> datetime:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def schedule_after_for_state(
    state_row: dict[str, Any] | None,
    schedule: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Base instant for next_run_after (last run end, or start of today if never run)."""
    now = now or datetime.now()
    row = state_row if isinstance(state_row, dict) else {}
    last_end = row.get("last_finished")
    if last_end:
        return _parse_state_timestamp(last_end, fallback=now)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sch = schedule if isinstance(schedule, dict) else {}
    if (
        str(sch.get("type") or "").strip().lower() == "daily"
        and sch.get("first_run_tomorrow") in (True, "true", "yes", 1, "1")
    ):
        hour, minute = _parse_time(str(sch.get("at") or sch.get("time") or "00:00"))
        slot_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= slot_today:
            return now
    return start_today - timedelta(seconds=1)


def job_next_run(
    job: ScheduledJob,
    state_row: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Next run time for display; None when disabled."""
    if not job.enabled:
        return None
    now = now or datetime.now()
    return next_run_after(
        job.schedule, schedule_after_for_state(state_row, job.schedule, now=now)
    )


def job_is_due(
    job: ScheduledJob,
    state_row: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    """True when the job should run now (next scheduled time is not in the future)."""
    if not job.enabled:
        return False
    now = now or datetime.now()
    nxt = job_next_run(job, state_row, now=now)
    return nxt is not None and nxt <= now


def default_schedule_path() -> Path:
    raw = (os.getenv("PPG_SCHEDULE_FILE") or "ppg_schedule.json").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p
