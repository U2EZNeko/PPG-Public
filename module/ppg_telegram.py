"""
Optional Telegram notifications when a generator script finishes.

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment (e.g. .env).
If either is missing, nothing is sent. Set TELEGRAM_NOTIFICATIONS=false to
disable sends while keeping credentials. Uses the Bot API sendMessage endpoint.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests

_TELEGRAM_MAX_MESSAGE_LEN = 4096


def telegram_notifications_enabled() -> bool:
    """True when TELEGRAM_NOTIFICATIONS is unset or truthy (not false/0/no/off)."""
    v = (os.environ.get("TELEGRAM_NOTIFICATIONS") or "true").strip().lower()
    return v not in ("0", "false", "no", "off")


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


def _build_summary_text(rec: Any, *, had_exception: bool) -> str:
    script_name = getattr(rec, "script_name", "?")
    run_id = getattr(rec, "run_id", "")
    t0 = float(getattr(rec, "_t0", time.time()))
    duration = time.time() - t0
    ok_count = int(getattr(rec, "ok_count", 0))
    failures: list[tuple[str, str]] = list(getattr(rec, "failures", []) or [])
    timing: list[tuple[str, float, bool, str]] = list(
        getattr(rec, "playlist_timing", []) or []
    )

    result = "crashed (uncaught exception)" if had_exception else "completed"
    lines = [
        "PPG run finished",
        f"Script: {script_name}",
    ]
    if run_id:
        lines.append(f"Run: {run_id}")
    lines.extend(
        [
            f"Duration: {_format_duration(duration)}",
            f"Result: {result}",
            f"Playlists updated successfully: {ok_count}",
        ]
    )

    if timing:
        lines.append("")
        lines.append("Per-playlist:")
        for pl, sec, ok, note in timing:
            status = "ok" if ok else "failed"
            dur = _format_duration(sec)
            if ok:
                lines.append(f"• {pl}: {dur} ({status})")
            else:
                tail = f" — {note}" if note else ""
                lines.append(f"• {pl}: {dur} ({status}){tail}")

    lines.append("")
    if failures:
        lines.append("Failures:")
        for pl, reason in failures:
            lines.append(f"• {pl}: {reason}" if reason else f"• {pl}")
    else:
        lines.append("Failures: none")

    return "\n".join(lines)


def maybe_notify_run_finished(rec: Any, had_exception: bool) -> None:
    if not telegram_notifications_enabled():
        return
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_raw = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_raw:
        return

    text = _build_summary_text(rec, had_exception=had_exception)
    if len(text) > _TELEGRAM_MAX_MESSAGE_LEN:
        text = text[: _TELEGRAM_MAX_MESSAGE_LEN - 20] + "\n… (truncated)"

    # Numeric chat IDs must be sent as int for some clients; Telegram accepts str too.
    chat_id: str | int
    if chat_raw.lstrip("-").isdigit():
        chat_id = int(chat_raw)
    else:
        chat_id = chat_raw

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if not r.ok:
            err = ""
            try:
                err = r.text[:500]
            except Exception:
                pass
            print(
                f"Telegram notify failed: HTTP {r.status_code} {err}",
                file=sys.stderr,
            )
    except requests.RequestException as e:
        print(f"Telegram notify failed: {e}", file=sys.stderr)


def _mask_token(token: str) -> str:
    t = token.strip()
    if len(t) <= 12:
        return "(too short to mask)"
    return f"{t[:6]}…{t[-4:]}"


def run_self_test() -> int:
    """Load repo .env, print why sends are skipped or call Telegram API. Exit code 0 = OK."""
    from pathlib import Path

    try:
        from dotenv import load_dotenv
    except ImportError:
        print("error: python-dotenv is required for self-test (pip install python-dotenv)", file=sys.stderr)
        return 1

    repo = Path(__file__).resolve().parent.parent
    env_path = repo / ".env"
    load_dotenv(env_path)
    print(f"Loaded env from: {env_path} (exists={env_path.is_file()})")

    if not telegram_notifications_enabled():
        print("skip: TELEGRAM_NOTIFICATIONS is false/off/no/0")
        return 2

    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_raw = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token:
        print("skip: TELEGRAM_BOT_TOKEN is empty")
        return 3
    if not chat_raw:
        print("skip: TELEGRAM_CHAT_ID is empty")
        return 4

    print(f"Token (masked): {_mask_token(token)}")
    print(f"Chat id: {chat_raw!r}")

    url_base = f"https://api.telegram.org/bot{token}"
    try:
        r = requests.get(f"{url_base}/getMe", timeout=15)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not r.ok or not body.get("ok"):
            print(f"getMe failed: HTTP {r.status_code} {r.text[:400]}", file=sys.stderr)
            return 5
        u = body.get("result") or {}
        print(f"getMe OK: @{u.get('username', '?')} ({u.get('first_name', '')})")
    except requests.RequestException as e:
        print(f"getMe request failed: {e}", file=sys.stderr)
        return 5

    chat_id: str | int
    if chat_raw.lstrip("-").isdigit():
        chat_id = int(chat_raw)
    else:
        chat_id = chat_raw

    test_text = "PPG Telegram self-test: if you see this, sendMessage works."
    try:
        r = requests.post(
            f"{url_base}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": test_text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        body = {}
        try:
            body = r.json()
        except Exception:
            pass
        if not r.ok or not body.get("ok"):
            desc = body.get("description") if isinstance(body, dict) else ""
            print(
                f"sendMessage failed: HTTP {r.status_code} {desc or r.text[:500]}",
                file=sys.stderr,
            )
            return 6
        print("sendMessage OK — check your Telegram chat for the test line.")
        return 0
    except requests.RequestException as e:
        print(f"sendMessage request failed: {e}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(run_self_test())
