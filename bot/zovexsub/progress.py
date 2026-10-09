"""דיווח התקדמות: אחוזים, פס, קצב וזמן משוער לסיום, לכל שלב."""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

Edit = Callable[[str], Awaitable[None]]

FULL, EMPTY = "▓", "░"
WIDTH = 12
MIN_INTERVAL = 5.0  # טלגרם חוסם עריכות תכופות מדי
HEARTBEAT = 5.0     # כל כמה שניות לרענן, גם כשהאחוז לא זז
# מאיזה רגע להציג את שעון השלב. זה גם מה שמבטיח שהטקסט באמת משתנה בכל
# רענון — טלגרם מחזיר שגיאה על עריכה לטקסט זהה, ובלי זה שלב שהאחוז בו
# עומד היה נראה קפוא גם כשהוא עובד
STEP_CLOCK_FROM = 10.0
# מתחת לאחוז הזה ההערכה מבוססת על מדגם זעיר ויוצאת מופרכת. שלב שמתחיל
# באחוז סמלי, כמו החקר שלפני התרגום, היה מייצר ממנה זמן דמיוני שרק גדל
ETA_FROM = 0.08


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


# סימני כיוון. בלי RLM שורה שמתחילה באימוג'י או במספר נשברת לסדר הפוך
# בטלגרם, ובלי LRM מספר עם נקודה או נקודתיים מתהפך בתוך שורה עברית
RLM, LRM = "\u200f", "\u200e"


def rtl(line: str) -> str:
    return RLM + line


def num(text: str) -> str:
    """עוטף מספר כך שלא יתהפך בתוך טקסט עברי."""
    return LRM + text + LRM


class Card:
    """כרטיס עבודה אחד שנערך במקום, עם היסטוריה של מה שכבר הסתיים.

    סעיף 8: עד כה כל שלב דרס את קודמו באותה הודעה, ולכן לא היה שום זכר
    למה שכבר רץ — אי אפשר היה לדעת כמה לקח התמלול, או אם היישור בכלל
    התבצע. הכרטיס שומר שורה לכל שלב שהסתיים, והשלב הפעיל מופיע מתחתיו.
    """

    def __init__(self, edit: Edit, title: str = ""):
        self._edit = edit
        self.title = title
        self.history: list[str] = []
        self.current = ""
        self.started = time.monotonic()

    def _render(self) -> str:
        lines = []
        if self.title:
            lines.append(rtl(f"**{self.title}**"))
        lines += [rtl(f"✅ {row}") for row in self.history]
        if self.current:
            lines.append(rtl(f"⏳ {self.current}"))
        return "\n".join(lines)

    async def write(self, current: str) -> None:
        self.current = current
        await self._edit(self._render())

    async def done(self, line: str) -> None:
        """מעביר שלב להיסטוריה."""
        self.history.append(line)
        self.current = ""
        await self._edit(self._render())

    def stage(self, title: str, *, total_bytes: int = 0) -> "Stage":
        """שלב חדש שכותב לתוך הכרטיס במקום לדרוס את ההודעה."""
        return Stage(self.write, title, total_bytes=total_bytes, card=self)


class Stage:
    """עוקב אחרי שלב אחד ומעדכן את הודעת הסטטוס.

    המצב מוחזק כאן ולא נתפס בתוך משימות רקע. כשכמה קטעים רצים במקביל
    הם קוראים ל-show מכיוון שונה, ודופק שזוכר אחוז ישן היה דורס את
    החדש — ומכאן קפיצות אחורה באחוזים. לכן יש דופק אחד בלבד, והוא
    קורא תמיד את המצב הנוכחי.
    """

    def __init__(self, edit: Edit, title: str, *, total_bytes: int = 0,
                 card: "Card | None" = None):
        self.edit = edit
        self.card = card
        self.title = title
        self.total_bytes = total_bytes
        self.started = time.monotonic()
        self.fraction = 0.0
        self.note = ""
        self.done_bytes = 0
        self.step_started = time.monotonic()
        self.last_edit = 0.0
        self.last_text = ""
        self._pulse: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def eta(self) -> float:
        """כמה זמן נשאר, לפי הקצב שנמדד עד כה."""
        if self.fraction < ETA_FROM:
            return 0.0
        return self.elapsed * (1 - self.fraction) / self.fraction

    def _render(self) -> str:
        parts = [self.title, bar(self.fraction), f"{self.fraction * 100:.0f}%"]
        if self.total_bytes:
            parts.append(f"{size(self.done_bytes)}/{size(self.total_bytes)}")
            if self.elapsed > 1:
                parts.append(f"{size(self.done_bytes / self.elapsed)}/ש׳")
        if self.note:
            parts.append(self.note)
        waiting = time.monotonic() - self.step_started
        if waiting > STEP_CLOCK_FROM:
            parts.append(clock(waiting))
        remaining = self.eta()
        if remaining > 1:
            parts.append(f"נותרו ~{clock(remaining)}")
        return " · ".join(parts)

    async def _flush(self, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self.last_edit < MIN_INTERVAL:
            return
        text = self._render()
        if text == self.last_text:
            return
        self.last_text = text
        self.last_edit = now
        await self.edit(text)

    async def show(self, fraction: float, *, done_bytes: int = 0,
                   note: str = "", force: bool = False) -> None:
        async with self._lock:
            # ההתקדמות לא חוזרת אחורה כשעדכונים מגיעים לא בסדר — אבל force
            # כן מאפס אותה, כי הוא מסמן שהעבודה באמת התחילה מחדש. בלי זה
            # max היה מקפיא את הפס על האחוז שהניסיון שנפל הספיק להגיע אליו
            if fraction > self.fraction or force:
                if fraction != self.fraction:
                    self.step_started = time.monotonic()
                self.fraction = fraction if force else max(self.fraction, fraction)
                if force:
                    self.started = time.monotonic()   # גם הזמן המשוער מתאפס
            if done_bytes:
                self.done_bytes = max(self.done_bytes, done_bytes)
            if note:
                self.note = note
            await self._flush(force)

    def pulse(self) -> None:
        """מפעיל דופק יחיד שמראה שהעבודה חיה גם כשהאחוז עומד."""
        if self._pulse:
            return

        async def tick() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT)
                async with self._lock:
                    self.last_edit = 0.0
                    await self._flush(force=False)

        self._pulse = asyncio.create_task(tick())

    def stop(self) -> None:
        if self._pulse:
            self._pulse.cancel()
            self._pulse = None

    async def finish(self, note: str = "") -> None:
        self.stop()
        if self.card is not None:
            # בכרטיס אין טעם להשאיר פס מלא: השלב עובר להיסטוריה בשורה
            # אחת קצרה, והמקום מתפנה לשלב הבא
            await self.card.done(f"{self.title} · {num(clock(self.elapsed))}"
                                 + (f" · {note}" if note else ""))
            return
        async with self._lock:
            self.fraction = 1.0
            self.done_bytes = self.total_bytes or self.done_bytes
            self.note = note or f"הושלם ב-{clock(self.elapsed)}"
            self.step_started = time.monotonic()
            self.last_edit = 0.0
            await self._flush(force=True)
