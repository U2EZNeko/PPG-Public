"""Retry transient Plex HTTP errors (5xx) on playlist mutations."""

from __future__ import annotations

import re
import time
from typing import Callable, TypeVar

from plexapi.exceptions import BadRequest

T = TypeVar("T")

_STATUS_PREFIX = re.compile(r"^\((\d+)\)")


def is_retryable_plex_bad_request(exc: BaseException) -> bool:
    """Plex often returns 500 internal_server_error on /playlists/.../items/...; safe to retry."""
    if not isinstance(exc, BadRequest):
        return False
    m = _STATUS_PREFIX.match(str(exc).strip())
    if not m:
        return False
    try:
        code = int(m.group(1))
    except ValueError:
        return False
    return code in (500, 502, 503, 504)


def call_plex_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    sleep_seconds: float = 1.0,
    log_fn: Callable[[str], None] | None = None,
    op_label: str = "Plex request",
) -> T:
    """Run ``fn``; on retryable :class:`~plexapi.exceptions.BadRequest`, wait and retry up to ``max_attempts``."""
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except BadRequest as e:
            last = e
            if attempt < max_attempts and is_retryable_plex_bad_request(e):
                if log_fn:
                    log_fn(
                        f"{op_label}: {e!s} — retry {attempt + 1}/{max_attempts} after {sleep_seconds:g}s"
                    )
                time.sleep(sleep_seconds)
                continue
            raise
    assert last is not None
    raise last
