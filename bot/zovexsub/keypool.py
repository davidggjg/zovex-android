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
    def __init__(self, name: str, keys: list[str], cooldown: float = 60.0):
        self.name = name
        self._keys = list(keys)
        self._cooldown = cooldown
        self._until: dict[str, float] = {}
        self._i = 0
        self._lock = asyncio.Lock()

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
                if self._until.get(key, 0.0) <= now:
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
                soonest = min(self._until.values(), default=0.0)
                await asyncio.sleep(max(1.0, min(10.0, soonest - time.monotonic())))

    def penalize(self, key: str, seconds: float | None = None) -> None:
        wait = self._cooldown if seconds is None else max(1.0, seconds)
        self._until[key] = time.monotonic() + wait
        log.warning("%s: מפתח %s בקירור ל-%.0f שניות", self.name, self.mask(key), wait)

    def report_ok(self, key: str) -> None:
        self._until.pop(key, None)
