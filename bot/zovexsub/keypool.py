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


class Budget:
    """תקציב קצב משותף לכל המאגרים שחולקים אותה מכסה.

    התיעוד של גוגל אומר במפורש: "Rate limits are applied per project,
    not per API key". כל ההנחה שמפתח נוסף הוא מכסה נוספת שגויה כששני
    המפתחות יושבים באותו פרויקט — ואז ירי מקבילי על חמישה מפתחות הוא
    ירי מקבילי על מכסה אחת, וכל מה שמתקבל זה 429.

    נוסף על כך היו אצלנו שני מאגרים נפרדים על אותם מפתחות, וכל אחד
    ניהל דלי משלו בלי לדעת על השני.

    התקציב אדפטיבי בכוונה: אי אפשר לדעת מראש אם המפתחות באותו פרויקט
    או בחמישה, ואי אפשר לבקש מהמשתמש לדעת. לכן הוא מתחיל בתקרה,
    מתכווץ כשחוזרים 429 ומתאושש לאט כשהכל עובר — בדיוק כפי שבקרת
    עומס ברשת פותרת את אותה בעיה בלי לדעת את רוחב הפס
    """

    def __init__(self, ceiling: int, floor: int = 2):
        self.ceiling = max(1, ceiling)
        self.floor = max(1, min(floor, self.ceiling))
        self.rate = float(self.ceiling)
        self._sent: list[float] = []
        self._eased = 0.0

    def room(self, now: float) -> bool:
        self._sent = [t for t in self._sent if now - t < 60.0]
        # התאוששות הדרגתית: אחרי דקה נקייה מוסיפים בקשה אחת לדקה
        if self._eased and now - self._eased >= 60.0 and self.rate < self.ceiling:
            self.rate = min(self.ceiling, self.rate + 1.0)
            self._eased = now
            log.info("תקציב %s עלה ל-%.0f בקשות לדקה", "משותף", self.rate)
        return len(self._sent) < self.rate

    def charge(self, now: float) -> None:
        self._sent.append(now)

    def throttle(self, now: float) -> None:
        """חזר 429 — מחצית הקצב, אבל לא מתחת לרצפה."""
        if now - self._eased < 5.0:
            return                      # לא מכווצים פעמיים על אותו גל
        before = self.rate
        self.rate = max(self.floor, self.rate / 2.0)
        self._eased = now
        if self.rate != before:
            log.warning("429 — מצמצמים את הקצב המשותף מ-%.0f ל-%.0f לדקה",
                        before, self.rate)

    def report(self) -> str:
        return f"קצב משותף {self.rate:.0f}/{self.ceiling} לדקה"


class KeyPool:
    def __init__(self, name: str, keys: list[str], cooldown: float = 60.0,
                 rpm: int = 0, shared: "Budget | None" = None):
        self.shared = shared
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
        if self.shared is not None and not self.shared.room(now):
            return False
        return len(recent) < self._rpm

    def _charge(self, key: str, now: float) -> None:
        if self._rpm:
            self._sent.setdefault(key, []).append(now)
        if self.shared is not None:
            self.shared.charge(now)

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
        if self.shared is not None:
            self.shared.throttle(time.monotonic())
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


# תקציבים משותפים לפי שם ספק. שני מאגרים על אותם מפתחות חייבים לחלוק
# מופע אחד, אחרת כל אחד מהם סופר לעצמו ויחד הם יורים כפול
_budgets: dict[str, Budget] = {}


def shared_budget(name: str, ceiling: int) -> "Budget | None":
    if ceiling <= 0:
        return None
    if name not in _budgets:
        _budgets[name] = Budget(ceiling)
    return _budgets[name]
