"""Detect whether the PPG scheduler daemon (ppg_scheduler.py / systemd) is running."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

SYSTEMD_UNIT = os.getenv("PPG_SCHEDULER_SYSTEMD_UNIT", "pvpg-scheduler.service").strip()
PROCESS_MARKER = "ppg_scheduler.py"


def _systemd_user_is_active(unit: str) -> bool | None:
    """True=active, False=inactive/failed, None=systemd unavailable or unit unknown."""
    if not unit:
        return None
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    state = (r.stdout or "").strip().lower()
    if r.returncode == 0 and state == "active":
        return True
    if state in ("inactive", "failed", "dead"):
        return False
    if r.returncode == 3:
        return False
    return None


def _command_line_looks_like_scheduler(cmdline: str, marker: str) -> bool:
    """True when cmdline is running ppg_scheduler.py (not our status probe)."""
    if not cmdline or marker not in cmdline:
        return False
    low = cmdline.casefold()
    if "get-ciminstance win32_process" in low or "wmic process" in low:
        return False
    if "powershell" in low or "pwsh" in low:
        return False
    return "python" in low


def _find_scheduler_process(marker: str) -> tuple[bool, int | None, str | None]:
    """Return (running, pid, command_line)."""
    if sys.platform == "win32":
        return _find_scheduler_process_windows(marker)
    return _find_scheduler_process_posix(marker)


def _find_scheduler_process_windows(marker: str) -> tuple[bool, int | None, str | None]:
    ps_cmd = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "$_.CommandLine -and "
        "($_.Name -match '^(?i)python(w)?\\.exe$') "
        f"-and ($_.CommandLine -like '*{marker}*') "
        "} | "
        "Select-Object ProcessId, CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except OSError:
        return False, None, None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return False, None, None
    try:
        data = json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return False, None, None
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        cmd = str(row.get("CommandLine") or "")
        if not _command_line_looks_like_scheduler(cmd, marker):
            continue
        pid = row.get("ProcessId")
        try:
            pid_int = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid_int = None
        return True, pid_int, cmd
    return False, None, None


def _find_scheduler_process_posix(marker: str) -> tuple[bool, int | None, str | None]:
    needle = marker.casefold()
    try:
        r = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except OSError:
        return False, None, None
    if r.returncode != 0:
        return False, None, None
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, comm, args = parts[0], parts[1], parts[2]
        if needle not in args.casefold():
            continue
        if not _command_line_looks_like_scheduler(args, marker):
            continue
        if comm.casefold() not in ("python", "python3", "python3.12") and not comm.casefold().startswith(
            "python"
        ):
            continue
        try:
            return True, int(pid_s), args
        except ValueError:
            return True, None, args
    return False, None, None


def _process_running(marker: str) -> bool:
    found, _, _ = _find_scheduler_process(marker)
    return found


def probe_scheduler_status() -> dict[str, Any]:
    """Return running state for the web UI scheduler indicator."""
    systemd = _systemd_user_is_active(SYSTEMD_UNIT)
    process, pid, cmdline = _find_scheduler_process(PROCESS_MARKER)

    detail_parts: list[str] = []
    if systemd is True:
        detail_parts.append(f"{SYSTEMD_UNIT} active")
    elif systemd is False:
        detail_parts.append(f"{SYSTEMD_UNIT} not active")
    if process:
        if pid is not None:
            detail_parts.append(f"python pid {pid}")
        else:
            detail_parts.append("ppg_scheduler.py process found")
        if cmdline:
            snippet = cmdline.strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            detail_parts.append(snippet)
    else:
        detail_parts.append("no python process running ppg_scheduler.py")

    if systemd is True or process:
        running: bool | None = True
        label = "Running"
    elif systemd is False or (not process and systemd is not True):
        running = False
        label = "Stopped"
    else:
        running = None
        label = "Unknown"

    return {
        "running": running,
        "label": label,
        "detail": "; ".join(detail_parts),
        "systemd_active": systemd,
        "process_running": process,
        "process_pid": pid,
        "systemd_unit": SYSTEMD_UNIT or None,
    }
