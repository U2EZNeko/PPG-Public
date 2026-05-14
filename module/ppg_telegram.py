"""
Optional Telegram notifications when a generator script finishes.

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment (e.g. .env).
If either is missing, nothing is sent. Set TELEGRAM_NOTIFICATIONS=false to
disable sends while keeping credentials. Uses the Bot API sendMessage endpoint.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests

_TELEGRAM_MAX_MESSAGE_LEN = 4096

_TELEGRAM_RUNTIME_DEFAULTS: dict[str, bool] = {
    "enabled": True,
    "notify_run_success": True,
    "notify_run_failure": True,
}


def merge_telegram_runtime_prefs_dict(data: Mapping[str, Any] | None) -> dict[str, bool]:
    """Normalize Telegram runtime prefs from JSON or API payloads."""
    out = dict(_TELEGRAM_RUNTIME_DEFAULTS)
    if not data:
        return out
    for key in _TELEGRAM_RUNTIME_DEFAULTS:
        if key not in data:
            continue
        v = data[key]
        if isinstance(v, bool):
            out[key] = v
        elif isinstance(v, (int, float)):
            out[key] = bool(v)
        elif isinstance(v, str):
            s = v.strip().lower()
            if s in ("1", "true", "yes", "on"):
                out[key] = True
            elif s in ("0", "false", "no", "off"):
                out[key] = False
    return out


def read_telegram_runtime_prefs_file(path: Path) -> dict[str, bool]:
    """Load prefs from disk; missing or invalid file → defaults."""
    try:
        if not path.is_file():
            return dict(_TELEGRAM_RUNTIME_DEFAULTS)
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return dict(_TELEGRAM_RUNTIME_DEFAULTS)
        return merge_telegram_runtime_prefs_dict(parsed)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return dict(_TELEGRAM_RUNTIME_DEFAULTS)


def runtime_telegram_prefs_from_env() -> dict[str, bool] | None:
    """If PPG_TELEGRAM_RUNTIME_PREFS is set, return merged prefs for that path."""
    raw = (os.environ.get("PPG_TELEGRAM_RUNTIME_PREFS") or "").strip()
    if not raw:
        return None
    return read_telegram_runtime_prefs_file(Path(raw))


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

    if had_exception:
        result_emoji = "💥"
        result_text = "Crashed (uncaught exception)"
    else:
        result_emoji = "✅"
        result_text = "Completed"

    lines = [
        "🎵 PPG · run finished",
        f"🖥 Script: {script_name}",
    ]
    if run_id:
        lines.append(f"🆔 Run: {run_id}")
    lines.extend(
        [
            f"⏱ Duration: {_format_duration(duration)}",
            f"{result_emoji} Result: {result_text}",
            f"📊 Playlists updated successfully: {ok_count}",
        ]
    )

    timed_fail: list[tuple[str, float, str]] = []
    timed_ok: list[tuple[str, float, str]] = []
    for pl, sec, ok, note in timing:
        pl = (pl or "").strip()
        if not pl:
            continue
        n = (note or "").strip()
        if ok:
            timed_ok.append((pl, float(sec), n))
        else:
            timed_fail.append((pl, float(sec), n))

    timed_fail_pls = {pl for pl, _, _ in timed_fail}
    fail_reason: dict[str, str] = {}
    for pl, r in failures:
        pl = (pl or "").strip()
        if not pl:
            continue
        rr = (r or "").strip()
        if pl not in fail_reason or not fail_reason[pl]:
            fail_reason[pl] = rr

    extra_fail_only = [
        (pl, fail_reason[pl])
        for pl in sorted(fail_reason.keys(), key=str.lower)
        if pl not in timed_fail_pls
    ]
    # Longest duration first; playlist name as tie-breaker
    timed_fail.sort(key=lambda x: (-x[1], x[0].lower()))
    timed_ok.sort(key=lambda x: (-x[1], x[0].lower()))

    has_playlist_section = bool(
        extra_fail_only or timed_fail or timed_ok
    )
    if has_playlist_section:
        lines.append("")
        lines.append("📋 Playlists")
        n_bad = len(extra_fail_only) + len(timed_fail)
        n_ok = len(timed_ok)
        if n_bad:
            lines.append(f"❌ Failed ({n_bad})")
            for pl, sec, note in timed_fail:
                dur = _format_duration(sec)
                detail = (note or "").strip() or fail_reason.get(pl, "")
                if detail:
                    lines.append(f"  ❌ {pl}: {dur} — {detail}")
                else:
                    lines.append(f"  ❌ {pl}: {dur}")
            for pl, reason in extra_fail_only:
                if reason:
                    lines.append(f"  ❌ {pl} — {reason}")
                else:
                    lines.append(f"  ❌ {pl}")
        if n_ok:
            lines.append(f"✅ OK ({n_ok}) · longest first")
            for pl, sec, _note in timed_ok:
                dur = _format_duration(sec)
                lines.append(f"  ✅ {pl}: {dur}")

    lines.append("")
    if not timed_fail and not fail_reason:
        lines.append("✨ No recorded playlist failures.")

    return "\n".join(lines)


def maybe_notify_run_finished(rec: Any, had_exception: bool) -> None:
    if not telegram_notifications_enabled():
        return
    rt = runtime_telegram_prefs_from_env()
    if rt is not None:
        if not rt.get("enabled", True):
            return
        if had_exception and not rt.get("notify_run_failure", True):
            return
        if not had_exception and not rt.get("notify_run_success", True):
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
