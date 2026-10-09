"""מאגר מפתחות עם round-robin וקירור אוטומטי על 429/כשל.

כל קריאה לוקחת את המפתח הבא בתור. מפתח שחוזר עם rate-limit נכנס לקירור
ולא ייבחר עד שהקירור נגמר, כך שהעומס מתחלק בין כל המפתחות.
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)


class AllKeysBusy(RuntimeError):
    """כל המפתחות בקירור."""


class KeyPool:
    def __init__(self, name: str, keys: list[str], cooldown: float = 60.0,
                 rpm: int = 0):
        self.name = name
        self._keys = list(keys)
        self._cooldown = cooldown
        self._until: dict[str, float] = {}
        self._i = 0
        self._lock = asyncio.Lock()
        # מגביל קצב יזום לכל מפתח. בלעדיו אנחנו יורים בקשות עד שגוגל
        # עונה 429, ואז כבר שרפנו קריאה, קיבלנו קירור, ושילמנו בזמן.
        # עם דלי אסימונים הקריאות נפרשות מראש ו-429 כמעט לא מתרחש
        self._rpm = max(0, rpm)
        self._sent: dict[str, list[float]] = {}

    def _room(self, key: str, now: float) -> bool:
        """האם המפתח הזה עוד בתוך המכסה לדקה שלו."""
        if not self._rpm:
            return True
        recent = [t for t in self._sent.get(key, ()) if now - t < 60.0]
        self._sent[key] = recent
        return len(recent) < self._rpm

    def _charge(self, key: str, now: float) -> None:
        if self._rpm:
            self._sent.setdefault(key, []).append(now)

    def __len__(self) -> int:
        return len(self._keys)

    @staticmethod
    def mask(key: str) -> str:
        return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "key"

    async def acquire(self) -> str:
        """מחזיר את המפתח הפנוי הבא, או זורק AllKeysBusy."""
        async with self._lock:
            now = time.monotonic()
            for _ in range(len(self._keys)):
                key = self._keys[self._i % len(self._keys)]
                self._i += 1
                if self._until.get(key, 0.0) <= now and self._room(key, now):
                    self._charge(key, now)
                    return key
            raise AllKeysBusy(self.name)

    async def wait_for_free(self, timeout: float = 180.0) -> str:
        """כמו acquire, אבל ממתין עד שמפתח משתחרר."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return await self.acquire()
            except AllKeysBusy:
                if time.monotonic() >= deadline:
                    raise
                # ממתינים עד שמשהו באמת משתחרר: או סוף קירור, או
                # יציאה של בקשה ישנה מחלון הדקה. בלי החישוב השני
                # ההמתנה הייתה שרירותית גם כשהדלי עומד להתמלא מיד
                now = time.monotonic()
                waits = [t - now for t in self._until.values() if t > now]
                for stamps in self._sent.values():
                    if stamps and self._rpm and len(stamps) >= self._rpm:
                        waits.append(stamps[-self._rpm] + 60.0 - now)
                await asyncio.sleep(max(0.25, min(10.0, min(waits, default=1.0))))

    def penalize(self, key: str, seconds: float | None = None) -> None:
        wait = self._cooldown if seconds is None else max(1.0, seconds)
        self._until[key] = time.monotonic() + wait
        log.warning("%s: מפתח %s בקירור ל-%.0f שניות", self.name, self.mask(key), wait)

    def report_ok(self, key: str) -> None:
        self._until.pop(key, None)

    def stats(self) -> str:
        """שורה אחת ללוג: כמה מכל מפתח נשלח בדקה האחרונה."""
        now = time.monotonic()
        parts = []
        for key in self._keys:
            used = len([t for t in self._sent.get(key, ()) if now - t < 60.0])
            cold = max(0.0, self._until.get(key, 0.0) - now)
            parts.append(f"{self.mask(key)}={used}/{self._rpm or '∞'}"
                         + (f" (קירור {cold:.0f}s)" if cold else ""))
        return " · ".join(parts)
