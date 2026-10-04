"""דיווח התקדמות: אחוזים, פס, קצב וזמן משוער לסיום, לכל שלב."""
from __future__ import annotations

import time
from typing import Awaitable, Callable

Edit = Callable[[str], Awaitable[None]]

FULL, EMPTY = "▓", "░"
WIDTH = 12
MIN_INTERVAL = 5.0  # טלגרם חוסם עריכות תכופות מדי


def bar(fraction: float) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * WIDTH)
    return FULL * filled + EMPTY * (WIDTH - filled)


def size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f}{unit}" if unit != "GB" else f"{num_bytes:.1f}GB"
        num_bytes /= 1024
    return ""


def clock(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds or seconds > 86400:
        return "—"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class Stage:
    """עוקב אחרי שלב אחד ומעדכן את הודעת הסטטוס."""

    def __init__(self, edit: Edit, title: str, *, total_bytes: int = 0):
        self.edit = edit
        self.title = title
        self.total_bytes = total_bytes
        self.started = time.monotonic()
        self.last_edit = 0.0
        self.last_text = ""

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def eta(self, fraction: float) -> float:
        """כמה זמן נשאר, לפי הקצב שנמדד עד כה."""
        if fraction <= 0.01:
            return 0.0
        return self.elapsed * (1 - fraction) / fraction

    async def show(self, fraction: float, *, done_bytes: int = 0,
                   note: str = "", force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_edit < MIN_INTERVAL:
            return

        parts = [f"{self.title}", bar(fraction), f"{fraction * 100:.0f}%"]
        if self.total_bytes:
            parts.append(f"{size(done_bytes)}/{size(self.total_bytes)}")
            if self.elapsed > 1:
                parts.append(f"{size(done_bytes / self.elapsed)}/ש׳")
        if note:
            parts.append(note)
        remaining = self.eta(fraction)
        if remaining > 1:
            parts.append(f"נותרו ~{clock(remaining)}")

        text = " · ".join(parts)
        if text == self.last_text:
            return
        self.last_text = text
        self.last_edit = now
        await self.edit(text)

    async def finish(self, note: str = "") -> None:
        self.last_edit = 0.0
        await self.show(1.0, done_bytes=self.total_bytes,
                        note=note or f"הושלם ב-{clock(self.elapsed)}", force=True)
