"""קליינט ל-Gemini: מצב JSON לתרגום, ומצב מחובר-לחיפוש למעבר החקר."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from . import config
from .keypool import KeyPool, shared_budget

log = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# קירור קצר: הגבלת הקצב של גוגל מתאפסת בתוך שניות, וקירור ארוך
# משבית את כל המפתחות בבת אחת ועוצר את העבודה לדקות
_pool = KeyPool("gemini", config.GEMINI_API_KEYS, cooldown=15.0,
                rpm=config.GEMINI_RPM_PER_KEY,
                shared=shared_budget("gemini", config.GEMINI_RPM_TOTAL))

# שמות מודלים אצל גוגל מתחלפים (2.5-pro הוסר, 3.1 נכנס). במקום לרדוף אחריהם
# בקוד, אנחנו שואלים את ה-API מה זמין ובוחרים את הטוב ביותר, פעם אחת.
_resolved: dict[str, str] = {}
_resolve_lock = asyncio.Lock()
# צמד מפתח-מודל שמיצה מכסה ארוכה. גוגל מגבילה לפי מפתח ולפי מודל
# בנפרד, ולכן קירור המפתח כולו היה פוסל אותו גם במודלים שעדיין פתוחים
_blocked: dict[tuple[str, str], float] = {}
# מעל זה מדובר במכסה יומית ולא בהגבלת קצב לדקה
LONG_WAIT = 120.0
# מודל שהשרת שלו עמוס. אין טעם להתעקש עליו כשיש חלופה זמינה
_overloaded: dict[str, float] = {}
OVERLOAD_REST = 90.0


def _retry_delay(payload: str) -> float:
    """כמה זמן גוגל מבקשת להמתין. היא מחזירה את זה במפורש בתשובה."""
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', payload)
    return float(match.group(1)) if match else 0.0


class GeminiError(RuntimeError):
    pass


# לקוח אחד לכל התהליך, ולא אחד לכל קריאה. קודם כל _chain_once פתח
# AsyncClient משלו, כלומר מסירת יד TCP ו-TLS חדשה לכל בקשה — בסרט
# אחד זה 56 קריאות תרגום ועוד עשרות של מגדר ובקרת איכות, כל אחת
# משלמת את הפתיחה מחדש ואף אחת לא מנצלת ריבוב HTTP/2. התיעוד של
# httpx אומר במפורש שהלקוח נועד לחיות לאורך זמן ולא לבקשה בודדת
_client: "httpx.AsyncClient | None" = None
_client_lock = asyncio.Lock()


async def client() -> "httpx.AsyncClient":
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                limits = httpx.Limits(
                    max_connections=config.GEMINI_CONNECTIONS,
                    max_keepalive_connections=config.GEMINI_CONNECTIONS,
                    keepalive_expiry=60.0)
                _client = httpx.AsyncClient(limits=limits)
    return _client


async def _list_models(key: str) -> list[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE}", params={"key": key, "pageSize": 200},
                                timeout=60.0)
    resp.raise_for_status()
    names = []
    for item in resp.json().get("models", []):
        if "generateContent" not in (item.get("supportedGenerationMethods") or []):
            continue
        names.append(str(item.get("name", "")).removeprefix("models/"))
    return names


def _score(name: str, family: str) -> tuple:
    """ככל שהציון גבוה יותר, המודל מועדף."""
    version = re.search(r"(\d+)\.(\d+)", name)
    major, minor = (int(version.group(1)), int(version.group(2))) if version else (0, 0)
    return (
        family in name,                     # pro / flash לפי מה שביקשנו
        "latest" in name,                   # כינוי יציב עדיף על גרסה מוקפאת
        major, minor,
        "preview" not in name and "exp" not in name,
    )


_BAD = ("embedding", "vision", "tts", "image", "audio", "live", "aqa", "learnlm")


async def _resolve(model: str) -> str:
    """מחזיר את שם המודל שבאמת קיים — זה שביקשנו, או החלופה הטובה ביותר."""
    if model in _resolved:
        return _resolved[model]
    async with _resolve_lock:
        if model in _resolved:
            return _resolved[model]
        family = "flash" if "flash" in model else "pro"
        key = await _pool.wait_for_free()
        try:
            names = [n for n in await _list_models(key)
                     if not any(bad in n for bad in _BAD)]
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("לא הצלחתי לקרוא את רשימת המודלים: %s", exc)
            return model
        if model in names:
            _resolved[model] = model
            return model
        candidates = [n for n in names if family in n] or names
        if not candidates:
            return model
        best = max(candidates, key=lambda n: _score(n, family))
        log.warning("המודל %s לא זמין — עובר ל-%s", model, best)
        _resolved[model] = best
        return best


# מודלים שהמפתח חסום מהם לגמרי (למשל pro בתוכנית החינמית, limit: 0)
# מודלים שחסומים לתוכנית הזו לצמיתות ("limit: 0") — אין טעם לנסות שוב
# צמדי (מודל, מפתח) שחסומים בתוכנית. קודם זו הייתה קבוצת שמות מודלים
# בלבד, ומפתח אחד בתוכנית מצומצמת היה פוסל מודל שעובד בכל השאר
# חשבונאות זמן: כמה מתוך השלב באמת עבר בהמתנה למפתח פנוי, לעומת
# המתנה לתשובה של המודל. בלי ההפרדה הזאת אי אפשר לדעת אם המכסות הן
# הצוואר או שהקריאות עצמן פשוט איטיות — וזו בדיוק השאלה הפתוחה
# כמה קריאות ממתינות ברגע זה למפתח פנוי. Tally כבר מפריד בין המתנה
# למכסה להמתנה למודל, אבל רק בסיכום שבסוף — וכשחלון יחיד רץ דקה
# המשתמש רואה מספר אחד ולא יודע אם אנחנו חנוקים או שהמודל פשוט איטי
_waiting_for_key = 0


def waiting_for_key() -> int:
    """כמה קריאות תקועות כרגע בהמתנה למפתח."""
    return _waiting_for_key


class Tally:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calls = 0
        self.quota_wait = 0.0     # שניות בהמתנה למפתח פנוי
        self.model_wait = 0.0     # שניות בהמתנה לתשובת המודל
        self.rate_limited = 0     # כמה פעמים חזר 429

    def report(self, label: str) -> str:
        if not self.calls:
            return f"{label}: אין קריאות"
        return (f"{label}: {self.calls} קריאות · "
                f"המתנה למפתח {self.quota_wait:.0f}ש · "
                f"המתנה למודל {self.model_wait:.0f}ש · "
                f"429: {self.rate_limited}")


tally = Tally()

_dead: set[tuple[str, str]] = set()
# מודלים שכל המפתחות מיצו אותם כרגע. זה זמני: מכסה לדקה מתאפסת תוך
# דקה, ולכן הרשימה מתרוקנת בין סבבים
_exhausted: set[str] = set()


def _chain(model: str) -> list[str]:
    """שרשרת ירידה: המודל שביקשנו, ואחריו החלופות החלשות יותר."""
    options = [model, config.GEMINI_FALLBACK_MODEL, config.GEMINI_LAST_RESORT_MODEL]
    seen, chain = set(), []
    for name in options:
        if name and name not in seen:
            seen.add(name)
            chain.append(name)
    return chain


def _transient(message: str) -> bool:
    """האם השגיאה שווה סבב נוסף על כל השרשרת.

    ‏503 הוא "השרת עמוס, נסה שוב" — השגיאה הזמנית ביותר שיש. ובכל
    זאת הוא היה היחיד שלא קיבל סבב נוסף: התנאי בדק אם ההודעה מכילה
    "מכסה לדקה" או "עמוס", וההודעה שנבנית על 5xx היא "HTTP 503"
    בלבד. התוצאה הייתה עבודה שמתה באמצע תרגום של 1602 שורות, אחרי
    שהמשתמש כבר המתין לה חצי שעה
    """
    if "מכסה לדקה" in message or "עמוס" in message:
        return True
    # כל 5xx: עומס, תחזוקה, או כשל זמני בצד של גוגל
    return any(f"HTTP {code}" in message for code in range(500, 600))


async def _call(model: str, body: dict, *, timeout: float = 300.0) -> dict:
    """שולח את הבקשה, ויורד למודל הבא כשהנוכחי חסום או עמוס.

    כשכל המודלים חסומים במכסה לדקה, ההרצה לא נכשלת: מכסה כזו מתאפסת
    תוך דקה, ולכן ממתינים ומנסים את כל השרשרת שוב. קודם העבודה כולה
    מתה בגלל המתנה של שישים שניות.
    """
    for attempt in range(1, config.GEMINI_ROUNDS + 1):
        try:
            return await _chain_once(model, body, timeout=timeout)
        except GeminiError as exc:
            if not _transient(str(exc)) or attempt == config.GEMINI_ROUNDS:
                raise
            _exhausted.clear()
            _overloaded.clear()
            log.warning("כל המודלים במכסה לדקה — ממתינים %.0f שניות (סבב %d/%d)",
                        config.GEMINI_COOLDOWN, attempt, config.GEMINI_ROUNDS)
            await asyncio.sleep(config.GEMINI_COOLDOWN)
    raise GeminiError("כל המודלים נכשלו")


async def _chain_once(model: str, body: dict, *, timeout: float = 300.0) -> dict:
    last_error = "לא ידוע"

    web = await client()
    chain = _chain(model)
    now = time.monotonic()
    available = [m for m in chain if _overloaded.get(m, 0.0) <= now]
    for wanted in (available or chain):
        name = await _resolve(wanted)
        if name in _exhausted or all(
                (name, k) in _dead for k in config.GEMINI_API_KEYS):
            continue

        # ארבעה ניסיונות קבועים לא הספיקו לסבב על שבעה מפתחות:
        # המודל ננטש לפני שחלקם בכלל נוסו. התקרה גדלה עם המאגר
        attempt, skipped = 0, 0
        budget = max(4, 2 * len(config.GEMINI_API_KEYS))
        while attempt < budget:
            global _waiting_for_key
            _waited = time.monotonic()
            _waiting_for_key += 1
            try:
                key = await _pool.wait_for_free()
            finally:
                _waiting_for_key -= 1
            tally.quota_wait += time.monotonic() - _waited
            if (_blocked.get((name, key), 0.0) > time.monotonic()
                    or (name, key) in _dead):
                # המפתח הזה מיצה את המודל הזה; ננסה מפתח אחר. דילוג
                # אינו ניסיון — קודם הוא שרף אחד מארבעת הניסיונות
                # בלי לשלוח בקשה, והמודל ננטש אף שהיה מפתח פנוי
                skipped += 1
                if skipped > len(config.GEMINI_API_KEYS):
                    break
                continue
            attempt += 1
            _sent = time.monotonic()
            tally.calls += 1
            try:
                resp = await web.post(
                    f"{BASE}/{name}:generateContent",
                    params={"key": key}, json=body,
                    timeout=httpx.Timeout(timeout, connect=30.0),
                )
            except httpx.HTTPError as exc:
                last_error = f"רשת: {exc}"
                await asyncio.sleep(min(2 ** attempt, 15))
                continue

            tally.model_wait += time.monotonic() - _sent

            if resp.status_code == 200:
                _pool.report_ok(key)
                return resp.json()

            text = resp.text[:400]

            if resp.status_code == 429:
                tally.rate_limited += 1
                # "limit: 0" = המודל חסום לתוכנית הזו, לא עומס רגעי
                if "limit: 0" in text:
                    _dead.add((name, key))
                    log.warning("%s חסום עבור %s — מנסה מפתח אחר",
                                name, _pool.mask(key))
                    if all((name, other) in _dead
                           for other in config.GEMINI_API_KEYS):
                        log.warning("%s חסום בכל המפתחות — למודל הבא", name)
                        last_error = f"{name} חסום בתוכנית"
                        break
                    last_error = f"{name} חסום במפתח אחד"
                    continue

                wait = _retry_delay(resp.text)
                if wait > LONG_WAIT:
                    # מכסה יומית של המפתח הזה במודל הזה. המפתח עצמו
                    # עדיין טוב למודלים אחרים, אז לא מקררים אותו כולו
                    _blocked[(name, key)] = time.monotonic() + wait
                    log.warning("%s מיצה את %s ל-%.0f דקות — מנסה מפתח אחר",
                                _pool.mask(key), name, wait / 60)
                    last_error = f"{name}: מכסה יומית"
                    continue

                # הגבלת קצב לדקה: גוגל אומרת כמה להמתין, ואין טעם
                # לקרר את המפתח הרבה מעבר לזה
                _pool.penalize(key, wait or 15)
                last_error = f"{name}: מכסה לדקה"
                # קודם ישנו כאן תמיד, גם כשמפתחות אחרים עמדו פנויים.
                # wait_for_free כבר ממתין רק כשאין אף מפתח זמין
                continue

            if resp.status_code >= 500:
                # השרת של המודל עמוס. במקום להתעקש, עוברים למודל
                # הבא ומסמנים את זה כעמוס לזמן קצר
                last_error = f"{name}: HTTP {resp.status_code}"
                if attempt >= 2:
                    _overloaded[name] = time.monotonic() + OVERLOAD_REST
                    log.warning("%s עמוס — מדלגים עליו לדקה וחצי", name)
                    break
                await asyncio.sleep(2)
                continue

            if resp.status_code == 404:
                _resolved.pop(wanted, None)
                refreshed = await _resolve(wanted)
                if refreshed != name:
                    name = refreshed
                    continue
                last_error = f"{name} לא קיים"
                break

            if (resp.status_code == 400 and "thinking" in text.lower()
                    and _drop_thinking(body)):
                # מודל שאינו מכיר את השדה מחזיר 400 "Unknown name".
                # זה לא שווה כשל: מורידים את השדה ושולחים שוב לאותו
                # מודל ואותו מפתח. אותה גישה כמו נפילת ה-cover
                # בשליחת וידאו, ששם הצילה את המסירה
                log.info("%s אינו מכיר thinkingConfig — ממשיכים בלעדיו", name)
                continue

            if resp.status_code in (400, 401, 403) and "API_KEY" in text.upper():
                _pool.penalize(key, 3600)
                last_error = "מפתח נדחה"
                continue

            raise GeminiError(f"Gemini HTTP {resp.status_code}: {text}")

        # אם כל המפתחות מיצו את המודל הזה, אין טעם לבדוק אותו שוב
        now = time.monotonic()
        if config.GEMINI_API_KEYS and all(
            _blocked.get((name, key), 0.0) > now for key in config.GEMINI_API_KEYS
        ):
            _exhausted.add(name)
            log.warning("כל המפתחות מיצו את %s כרגע", name)

        log.warning("עובר למודל הבא אחרי %s", last_error)

    raise GeminiError(f"כל המודלים נכשלו — {last_error}")


def _text_of(payload: dict) -> str:
    out = []
    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if isinstance(part.get("text"), str):
                out.append(part["text"])
    return "".join(out).strip()


def _drop_thinking(body: dict) -> bool:
    """מוציא את thinkingConfig מהבקשה. מחזיר אם היה שם מה להוציא."""
    gen = body.get("generationConfig")
    if isinstance(gen, dict) and "thinkingConfig" in gen:
        gen.pop("thinkingConfig", None)
        return True
    return False


async def ask_json(system: str, user: str, *, schema: dict | None = None,
                   model: str | None = None, temperature: float = 0.2,
                   thinking: str | None = None) -> object:
    """שאלה שהתשובה שלה חייבת להיות JSON תקין."""
    gen: dict = {"temperature": temperature, "response_mime_type": "application/json",
                 "maxOutputTokens": 65536}
    if schema:
        gen["response_schema"] = schema
    # רמת החשיבה. נמדד אצל המשתמש: 23 קריאות התאמת מגדר ו-1430 שניות
    # המתנה למודל, כלומר 62 שניות לקריאה — על משימה שכל כולה "קבע אל
    # מי פונים בשורה והחזר JSON". בכל מודלי Flash ו-Pro החשיבה דלוקה
    # כברירת מחדל, ואסימוני החשיבה נספרים כפלט. התיעוד של גוגל ממליץ
    # להנמיך את thinking_level כדי לקצר זמן ועלות, ולא לחתוך את
    # maxOutputTokens — חיתוך כזה מחזיר תשובה קטועה.
    #
    # שם השדה אומת מול ה-SDK הרשמי של גוגל ולא מול בלוג:
    #   GenerateContentConfig.thinking_config -> thinkingConfig
    #   ThinkingConfig.thinking_level         -> thinkingLevel
    #   ThinkingLevel: MINIMAL / LOW / MEDIUM / HIGH
    # רמת חשיבה לכל קריאה, ולא רק גלובלית: מעבר המגדר דורש הסקה
    # (מי מדבר אל מי) ונפגע קשות מחשיבה נמוכה, בעוד שאר הקריאות
    # לא. נמדד על אותו סרט: במעבר ל-3.8-flash עם LOW צורות הזכר
    # עלו מ-52 ל-76 בעוד שתי הדמויות נשים
    level = config.GEMINI_THINKING if thinking is None else thinking
    if level:
        gen["thinkingConfig"] = {"thinkingLevel": level}
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen,
    }
    for attempt in range(2):
        payload = await _call(model or config.GEMINI_MODEL, body)
        parsed = _loose_json(_text_of(payload))
        if parsed is not None:
            return parsed
        log.warning("התקבל JSON לא תקין, מנסה שוב (%d)", attempt + 1)
    raise GeminiError("לא התקבל JSON תקין מ-Gemini")


# מתי מכסת החיפוש נגמרה לאחרונה. למכסת החיפוש של ג'מיני יש מונה נפרד
# וקטן, וכשהיא אוזלת כל קריאת חקר משלמת את תקרת הזמן המלאה לפני
# שהיא מוותרת ועוברת למסלול המהיר. בשלב עם כמה קריאות זה מצטבר לדקות
# שנשרפות על ניסיון שידוע מראש שייכשל
_search_down_until = 0.0


# שער לקריאות מחוברות-חיפוש בלבד. המפסק למטה נסגר רק אחרי שקריאה
# חוזרת, ובירי מקבילי כולן כבר באוויר עד אז — ואז 65 מתוך 69 חוזרות
# עם 429 אף שהמפסק "עובד". השער מחזיק מעטות באוויר כדי שלכישלון
# הראשון יהיה זמן לסגור אותו בפני השאר
_search_gate = asyncio.Semaphore(max(1, config.SEARCH_PARALLEL))


def _search_usable() -> bool:
    return time.monotonic() >= _search_down_until


def _search_failed(reason: str) -> None:
    global _search_down_until
    _search_down_until = time.monotonic() + config.SEARCH_REST
    log.warning("חיפוש גוגל לא זמין (%s) — מדלגים עליו ל-%.0f דקות",
                reason, config.SEARCH_REST / 60)


async def research(system: str, user: str, *, grounded: bool = True) -> str:
    """מעבר חקר מחובר לחיפוש Google — לשמות, מונחים, ציטוטים ומושגים.

    לחיפוש יש מכסה חינמית נפרדת וקטנה. כשהיא נגמרת אנחנו חוזרים על אותה
    שאלה בלי החיפוש: אימות עובדתי של שמות אובד, אבל מיפוי הדוברים
    והמגדרים — החלק שמחזיק את כל דיוק התרגום — עדיין נוצר.
    """
    base = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }
    with_search = {**base, "tools": [{"google_search": {}}]}

    # חיפוש מאט מאוד — המודל יוצא לרשת וממתין. חלק מהמעברים לא צריכים
    # אותו בכלל, ואז מדלגים ישר על הניסיון האיטי
    want_search = grounded and _search_usable()
    attempts = [(with_search, "עם חיפוש")] if want_search else []
    attempts.append((base, "בלי חיפוש"))

    # המעבר הזה לא קריטי לתרגום, ולכן הוא לא מחזיק את התור יותר מדי זמן
    async def run(plan) -> str:
        for body, label in plan:
            try:
                text = _text_of(await asyncio.wait_for(
                    _call(config.GEMINI_MODEL, body),
                    timeout=config.RESEARCH_TIMEOUT))
                if text:
                    return text
                log.warning("החקר %s חזר ריק", label)
            except asyncio.TimeoutError:
                log.warning("החקר %s עבר את תקרת הזמן (%ds)",
                            label, config.RESEARCH_TIMEOUT)
                if body is with_search:
                    _search_failed("תקרת זמן")
            except GeminiError as exc:
                log.warning("החקר %s נכשל: %s", label, exc)
                if body is with_search:
                    _search_failed(str(exc)[:60])
        log.warning("ממשיכים בלי מסמך הנחיות")
        return ""

    if not want_search:
        return await run(attempts)
    async with _search_gate:
        # נבדק שוב בתוך השער: בזמן ההמתנה קריאה אחרת עשויה כבר
        # להיתקל ב-429 ולסגור את המפסק, ואז אין טעם לנסות בכלל
        if not _search_usable():
            log.info("המפסק נסגר בזמן ההמתנה — מדלגים על החיפוש")
            return await run(attempts[1:])
        return await run(attempts)


async def transcribe_audio(path, language_hint: str = "") -> dict | None:
    """תמלול אודיו ב-Gemini, כגיבוי לכישלון של Groq.

    נמדד מול אודיו עם זמנים ידועים: הסטייה כאן היא כשתי עשיריות שנייה,
    לעומת מאית אצל Whisper. לכן זה לא המסלול הראשי אלא רשת ביטחון —
    עדיף תמלול עם תזמון בינוני על פני חור בכתוביות. דיוק התזמונים
    משתפר אחר כך בהקשבה החוזרת ובהצמדה לדיבור.
    """
    import base64
    from pathlib import Path as _Path

    data = _Path(path).read_bytes()
    if len(data) > 18 * 1024 * 1024:
        log.warning("הקטע גדול מדי לתמלול ב-Gemini")
        return None

    hint = f" שפת המקור היא {language_hint}." if language_hint else ""
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "audio/flac",
                             "data": base64.b64encode(data).decode()}},
            {"text": "תמלל את האודיו בשפת המקור שלו, בלי לתרגם." + hint +
                     ' החזר JSON: {"segments":[{"start":<שניות>,"end":<שניות>,'
                     '"text":"..."}]} עם חותמות זמן מדויקות ככל האפשר, '
                     "ובלי להמציא טקסט בקטעים שאין בהם דיבור."},
        ]}],
        "generationConfig": {"temperature": 0, "response_mime_type": "application/json"},
    }

    try:
        payload = await _call(config.GEMINI_MODEL, body, timeout=600.0)
    except GeminiError as exc:
        log.warning("התמלול ב-Gemini נכשל: %s", exc)
        return None

    parsed = _loose_json(_text_of(payload))
    items = parsed.get("segments") if isinstance(parsed, dict) else parsed
    segments = []
    for item in items or []:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        try:
            segments.append({
                "start": float(item["start"]),
                "end": float(item.get("end", item["start"])),
                "text": str(item["text"]).strip(),
            })
        except (KeyError, TypeError, ValueError):
            continue

    if not segments:
        return None
    log.info("Gemini תמלל %d סגמנטים כגיבוי", len(segments))
    return {"segments": segments, "words": [], "language": language_hint or ""}


def _loose_json(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = raw.find(opener), raw.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(raw[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None
