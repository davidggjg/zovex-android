"""בדיקות ליבה — רצות בלי שום תלות חיצונית.

    /opt/zovexsub/venv/bin/python bot/tests/run.py

חובה להריץ עם הפייתון של הסביבה הווירטואלית — פייתון של המערכת לא רואה
את הספריות של הבוט.

נכתבו אחרי שרגרסיה אמיתית הגיעה למשתמש: החלפת פרמטר בחתימה של burn
עודכנה במימוש ולא בעוטפת שמעליו, וכל צריבה נפלה. בדיקה אחת הייתה תופסת
את זה בשנייה, ולכן הראשונה כאן היא בדיוק זו.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from zovexsub import config, fetch, hebrew, media, pipeline, srt   # noqa: E402
    from zovexsub.keypool import AllKeysBusy, KeyPool                  # noqa: E402
except ModuleNotFoundError as missing:                                 # noqa: E402
    # הבוט רץ מתוך סביבה וירטואלית, ופייתון של המערכת לא רואה את
    # הספריות שלו. בלי ההודעה הזאת השגיאה נראית כמו תקלה בקוד
    print(f"חסרה הספרייה '{missing.name}'.\n"
          f"הבדיקות חייבות לרוץ עם הפייתון של הבוט:\n"
          f"    /opt/zovexsub/venv/bin/python {Path(__file__).name}\n"
          f"(או הנתיב המלא: /opt/zovexsub/venv/bin/python "
          f"/opt/zovexsub/repo/bot/tests/run.py)")
    raise SystemExit(2)

CHECKS: list = []


def check(name: str):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


# ---------------------------------------------------------------- חתימות
@check("חתימות שרשרת הצריבה תואמות")
def _signatures():
    for fn in (pipeline.burn, media.burn):
        params = inspect.signature(fn).parameters
        assert "style" in params, f"{fn.__qualname__} בלי style"
        assert "size" not in params, f"{fn.__qualname__} עדיין עם size"
    # והעוטפת באמת מעבירה הלאה, לא רק מקבלת
    body = inspect.getsource(pipeline.burn)
    assert "style=style" in body, "pipeline.burn מקבל style ולא מעביר אותו"


# ---------------------------------------------------------------- תזמונים
@check("תזמונים: אין חפיפות ואין אורך שלילי")
def _timing_overlaps():
    cues = srt._fix_timing([srt.Cue(i, i * 0.25, i * 0.25 + 1.5, f"שורה {i}")
                            for i in range(12)])
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start, f"חפיפה בין {a.index} ל-{b.index}"
    for c in cues:
        assert c.end > c.start, f"אורך לא חיובי בכתובית {c.index}"


@check("תזמונים: המינימום והמקסימום נאכפים")
def _timing_bounds():
    long_text = "מילה " * 40
    out = srt._fix_timing([srt.Cue(1, 0.0, 0.2, long_text)])[0]
    assert out.end - out.start <= config.SRT_MAX_DURATION + 1e-6
    out = srt._fix_timing([srt.Cue(1, 0.0, 0.1, "קצר")])[0]
    assert out.end - out.start >= config.SRT_MIN_DURATION - 1e-6


@check("הצמדה לדיבור חסומה לפי דיוק המקור")
def _snap_bounded():
    speech = [(14.0, 18.0)]                      # זיהוי רחוק, כנראה שגוי
    for accurate in (False, True):
        out = srt._snap_to_speech([srt.Cue(1, 2.0, 16.0, "טקסט")],
                                  speech, accurate)[0]
        assert out.start == 2.0, "כתובית נזרקה למקום אחר בגלל זיהוי שווא"


# ---------------------------------------------------------------- שבירה
@check("שבירת שורות: אף שורה לא חורגת, ואין אובדן טקסט")
def _wrap():
    limit = config.SRT_MAX_CHARS_PER_LINE
    for text in ("מילה " * 30, "א" * 100, "שלום עולם",
                 "מילהארוכהמאודבלירווחים" * 4,
                 "זו שורה בינונית שאמורה להישבר יפה לשתי שורות מאוזנות"):
        lines = srt.wrap(text).split("\n")
        assert all(len(l) <= limit for l in lines), f"שורה ארוכה מדי: {text[:20]}"
        assert "".join(text.split()) == "".join("".join(lines).split()), "טקסט אבד"


# ---------------------------------------------------------------- מפתחות
@check("מאגר מפתחות: סבב שווה, דלי אסימונים וקירור")
def _keypool():
    keys = [f"AQ.key{i}abcdefgh{i}" for i in range(3)]

    pool = KeyPool("t", keys)
    got = [asyncio.run(pool.acquire()) for _ in range(9)]
    assert {k: got.count(k) for k in keys} == {k: 3 for k in keys}, "סבב לא שווה"

    pool = KeyPool("t", keys, rpm=2)
    for _ in range(6):
        asyncio.run(pool.acquire())
    try:
        asyncio.run(pool.acquire())
        raise AssertionError("הדלי נתן בקשה מעבר למכסה")
    except AllKeysBusy:
        pass

    pool = KeyPool("t", keys)
    pool.penalize(keys[0], 30)
    assert keys[0] not in {asyncio.run(pool.acquire()) for _ in range(6)}


# ---------------------------------------------------------------- פרופילים
@check("פרופילים: הסולם האוטומטי הוא HEVC בלבד")
def _ladder():
    for megabytes in (100, 800, 2000, 4000):
        chosen = config.profile_for(megabytes * 1024 ** 2, 6360)
        assert chosen["codec"] == "libx265", f"{megabytes}MB נתן {chosen['codec']}"


@check("פרופילים: הערכת הגודל מתחשבת ברזולוציה")
def _mbps_scales():
    ceiling = config.UPLOAD_CEILING_MB
    try:
        config.UPLOAD_CEILING_MB = 500
        low = config.profile_name(config.profile_for(2000 * 1024 ** 2, 6360, 720))
        high = config.profile_name(config.profile_for(2000 * 1024 ** 2, 6360, 1080))
        assert low != high, "הרזולוציה לא השפיעה על בחירת הפרופיל"
    finally:
        config.UPLOAD_CEILING_MB = ceiling


@check("ליבות: הקצאת־יתר ותקרת זיכרון")
def _slots():
    slots = config.burn_slots(18)
    assert slots == 18 * config.BURN_OVERSUBSCRIBE // config.BURN_SEGMENT_THREADS
    assert media._memory_cap(slots) <= slots
    assert media._memory_cap(slots) >= 1


@check("בריכת הליבות משנה גודל תוך כדי ריצה")
def _resize():
    async def body():
        pool = media.CorePool(8)
        async with pool.job() as token:
            held = []
            for _ in range(5):
                cm = pool.slot(token)
                await cm.__aenter__()
                held.append(cm)
            await pool.resize(3)
            assert pool.free < 0, "צמצום לא הקטין את המקום הפנוי"
            try:
                await asyncio.wait_for(pool.slot(token).__aenter__(), timeout=0.6)
                raise AssertionError("נתן מקום למרות הצמצום")
            except asyncio.TimeoutError:
                pass
            for cm in held:
                await cm.__aexit__(None, None, None)
    asyncio.run(body())


# ---------------------------------------------------------------- עברית
@check("טבלת המגדר מחולצת ונעוצה בפרומפטים")
def _gender():
    notes = "הנחיות כלשהן\n@מגדר: A=זכר, B=נקבה"
    assert hebrew.gender_table(notes) == "A=זכר, B=נקבה"
    assert hebrew.gender_table("בלי שורה") == ""
    built = hebrew._quality_prompt(notes, "[0] מקור: hi\n[0] עברית: היי")
    assert built.startswith("מגדר הדוברים"), "הטבלה לא נעוצה בבקרת האיכות"
    assert hebrew._quality_prompt(notes, "") == ""


# ---------------------------------------------------------------- הורדה
@check("מפסק הזרם של יוטיוב נסגר ונפתח")
def _breaker():
    fetch._note_success()
    assert fetch._breaker_open() == 0
    assert fetch._is_block("Sign in to confirm you are not a bot")
    assert not fetch._is_block("ERROR: Private video")
    for _ in range(config.FETCH_BREAKER_FAILS):
        fetch._note_failure()
    assert fetch._breaker_open() > 0, "המפסק לא נסגר"
    fetch._note_success()
    assert fetch._breaker_open() == 0, "הצלחה לא פתחה את המפסק"


def main() -> int:
    failed = 0
    for name, fn in CHECKS:
        started = time.monotonic()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}\n      {type(exc).__name__}: {exc}")
        else:
            print(f"  ✓ {name}  ({time.monotonic() - started:.2f}ש)")
    total = len(CHECKS)
    print(f"\n{total - failed}/{total} עברו" + (f" · {failed} נכשלו" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
