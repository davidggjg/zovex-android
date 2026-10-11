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
@check("אין פונקציה שקוראת לעצמה בלי תנאי עצירה")
def _no_runaway_recursion():
    """תפס רקורסיה אינסופית אמיתית ב-pipeline.make.

    החלפה גורפת של קריאה אחת בשמה של הפונקציה העוטפת פגעה גם בגוף
    שלה, והפכה את הנפילה-לאחור לקריאה עצמית. זה לא התפוצץ עד שהגיע
    מסלול שלא העביר את הפרמטר שעוקף אותה
    """
    import ast
    root = Path(__file__).resolve().parents[1] / "zovexsub"
    bad = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                target = getattr(inner, "func", None)
                # רק קריאה בשם חשוף. x.name() הוא מודול אחר ולא רקורסיה
                if getattr(target, "id", None) != node.name:
                    continue
                # רקורסיה מכוונת מותרת כשיש בפונקציה חסם עומק מפורש
                body = ast.unparse(node)
                if "depth" in body or "limit" in body:
                    continue
                bad.append(f"{path.name}:{inner.lineno} {node.name}")
    assert not bad, "רקורסיה בלי חסם: " + ", ".join(bad)


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
@check("היסט גלובלי: מזוהה נכון, ונחסם כשאין בו טעם")
def _offset():
    speech = [(i * 5.0, i * 5.0 + 2.5) for i in range(40)]

    def cues(shift, jitter=0.0):
        import random
        random.seed(7)
        return [srt.Cue(i, a + shift + random.uniform(-jitter, jitter),
                        a + shift + 2.3, f"שורה {i}")
                for i, (a, _) in enumerate(speech)]

    # דיליי שיטתי — הסימן והגודל חייבים להיות מדויקים. גרסה קודמת
    # זיהתה +3 כ--2, כלומר תיקון שמחמיר פי שניים
    got = srt.global_offset(cues(3.0), speech)
    assert abs(got - 3.0) < 0.1, f"דיליי 3ש זוהה כ-{got}"
    got = srt.global_offset(cues(-1.2), speech)
    assert abs(got + 1.2) < 0.1, f"הקדמה 1.2ש זוהתה כ-{got}"
    # תזמונים תקינים, רועשים, או מעט מדי — אסור לגעת
    assert abs(srt.global_offset(cues(0.0), speech)) < config.OFFSET_MIN
    assert srt.global_offset(cues(0.0, jitter=3.0), speech) == 0.0
    assert srt.global_offset(cues(3.0)[:5], speech) == 0.0


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
        # התקרה גדלה יחד עם קצב הסיביות של הפרופילים אחרי הורדת
        # ה-CRF. ערך נמוך מדי מפיל את כל הסולם לדרגה האחרונה,
        # ואז הבדיקה לא בודקת כלום
        config.UPLOAD_CEILING_MB = 1000
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


@check("פענוח file_id למיקום MTProto")
def _fileid():
    """המסלול שמחליף את ההורדה הסדרתית של שרת הבוט."""
    from zovexsub import fileid

    sample = fileid.Located(dc_id=2, id=5295129377295024127,
                            access_hash=-7126845109898138049,
                            file_reference=bytes(range(1, 19)), file_type=4)
    packed = fileid.encode(sample)
    assert packed.startswith("BAACAgI"), packed
    assert fileid.decode(packed) == sample

    bare = fileid.Located(dc_id=5, id=1, access_hash=2,
                          file_reference=b"", file_type=5)
    assert fileid.decode(fileid.encode(bare)) == bare

    raw = bytes(300) + b"ab" + bytes(5)
    assert fileid.rle_decode(fileid.rle_encode(raw)) == raw

    for bad in ("", "!!!!", "AAAA"):
        try:
            fileid.decode(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} היה אמור להידחות")

    # תמונה אינה מסמך ואין לה מיקום כזה — חייב ליפול לגיבוי
    photo = fileid.Located(dc_id=2, id=1, access_hash=2,
                           file_reference=b"", file_type=2)
    try:
        fileid.decode(fileid.encode(photo))
    except ValueError:
        pass
    else:
        raise AssertionError("סוג תמונה לא נדחה")


@check("לולאת העדכונים של הבוט לא ממתינה לעבודה ארוכה")
def _pump_stays_free():
    """תפס בוט שהפסיק להגיב מרגע הלחיצה על הכפתור האחרון.

    _pump קרא לעבודה ב-await ישיר, ולכן הורדה, תרגום וצריבה החזיקו את
    הלולאה היחידה שמושכת עדכונים מטלגרם.
    """
    import inspect

    from zovexsub import botmenu

    body = inspect.getsource(botmenu)
    assert "_detach(choice.done(choice)" in body, \
        "העבודה מהכפתור חזרה להיקרא בתוך הלולאה"
    assert "await choice.done(" not in body, "await ישיר על עבודה ארוכה"
    assert "await on_subtitle(" not in body, "await ישיר על קובץ כתוביות"



@check("שמע לא תואם מומר ל-AAC ולא מועתק כמו שהוא")
def _audio_converted():
    """תפס סרטון שיצא אילם ברוב המכשירים.

    EAC3 הועתק פנימה ב--c:a copy, הווידאו התנגן והקול שתק. רצועת
    השמע גם שקלה יותר מהווידאו, כי 640kbps עברו ללא נגיעה.
    """
    import inspect

    from zovexsub import media

    body = inspect.getsource(media)
    assert '"-c:a", "copy", "-movflags"' not in body, "העתקה עיוורת חזרה"
    assert "_audio_args" in body

    async def pick(streams):
        async def fake(_path):
            return {"streams": streams}
        real, media.probe = media.probe, fake
        try:
            return await media._audio_args(Path("x.mp4"))
        finally:
            media.probe = real

    aac = asyncio.run(pick([{"codec_type": "audio", "codec_name": "aac",
                             "channels": 2}]))
    assert aac == ["-c:a", "copy"], aac

    eac3 = asyncio.run(pick([{"codec_type": "audio", "codec_name": "eac3",
                              "channels": 6}]))
    assert "aac" in eac3 and "-ac" in eac3, eac3
    assert eac3[eac3.index("-ac") + 1] == "2", "5.1 לא עורבל לסטריאו"

    silent = asyncio.run(pick([{"codec_type": "video"}]))
    assert silent == ["-an"], silent


@check("ערכי ה-CRF בטווח שמתאים לצפייה ולא רק לגודל")
def _crf_sane():
    for name, settings in config.PROFILES.items():
        crf = settings["crf"]
        top = 24 if settings["codec"] == "libx265" else 21
        assert crf <= top, f"{name}: CRF{crf} גבוה מדי ל-{settings['codec']}"



@check("בקשה אחת לכל חיבור — יותר מזה מנתק את ההורדה")
def _one_request_per_connection():
    """תפס Server disconnected without sending a response.

    16 חיבורים כפול 8 בקשות הם 128 באוויר, וטלגרם סגר את החיבורים בלי
    לענות. המימוש שבוטי ההעברה המהירים משתמשים בו מחזיק בקשה אחת
    לכל חיבור ומגיע לקצב דרך מספר החיבורים בלבד.
    """
    assert config.TG_PIPELINE == 1, (
        f"TG_PIPELINE={config.TG_PIPELINE} — ערימת בקשות על חיבור אחד "
        "היא בדיוק מה שגרם לניתוקים")
    assert config.TG_INFLIGHT_MAX <= config.TG_CONNECTIONS, (
        "התקרה גבוהה ממספר החיבורים, כלומר יותר מבקשה אחת לכל אחד")
    assert config.TG_CONNECTIONS >= 16, "מעט מדי חיבורים לקובץ גדול"



@check("לקוח הבוט אינו מבקש עדכונים — רק שרת ה-Bot API עושה זאת")
def _bot_client_silent():
    """תפס לולאת התחברות מחדש וניתוקים באמצע הורדה.

    טלגרם מתיר צרכן עדכונים אחד לכל טוקן. שרת ה-Bot API המקומי הוא
    הצרכן, ולקוח Telethon שני שביקש עדכונים לאותו טוקן נאבק איתו.
    """
    import inspect

    from zovexsub import botapi

    body = inspect.getsource(botapi._connect)
    assert "receive_updates" in body, "לקוח הבוט שוב מבקש עדכונים"
    assert "if bot_token else" in body, \
        "ההשתקה חלה גם על חשבונות המשתמש, שכן צריכים עדכונים"



@check("בחירת איכות הצריבה מגיעה עד הקודק בפועל")
def _speed_choice():
    import inspect

    from zovexsub import botjob, botmenu, media, pipeline

    fields = [step[2] for step in botmenu.STEPS]
    assert "speed" in fields, f"אין שלב בחירת איכות: {fields}"
    assert "speed" in botmenu.Choice.__dataclass_fields__

    # הכפתורים חייבים לשלוח בדיוק את הערכים שהמיפוי מכיר
    keys = next(step[1] for step in botmenu.STEPS if step[2] == "speed")
    sent = {data.split(":", 1)[1] for row in keys for _, data in row}
    assert sent == {"מהיר", "איכותי"}, sent

    body = inspect.getsource(botjob._burn)
    for value in sent:
        assert f'"{value}"' in body, f"{value} לא ממופה לפרופיל"
    assert "profile=profile" in body, "הבחירה לא מועברת ל-media.burn"

    # והשרשרת כולה מקבלת את הפרמטר
    for fn in (media.burn, pipeline.burn, media._burn_single,
               media._burn_parallel):
        assert "profile" in inspect.signature(fn).parameters, fn.__qualname__

    # בחירה מפורשת גוברת גם כשהסולם האוטומטי אוסר על H.264
    chosen = media._settings_for(Path(__file__), 600.0, 1080, "fast")
    assert chosen["codec"] == "libx264", chosen
    fine = media._settings_for(Path(__file__), 600.0, 1080, "balanced")
    assert fine["codec"] == "libx265", fine



@check("מספר שאבד בתרגום מזוהה ומתוקן")
def _numbers_survive():
    """תפס את "Not so fast, 511" שהפך ל"לא כל כך מהר, מטר עשרים".

    מספר טיסה פורש כמידת גובה. זו מחלקה שלמה — קודים, שנים ודגמים
    שמתורגמים במקום להיות מועתקים.
    """
    import inspect

    from zovexsub import hebrew

    lost = hebrew.lost_numbers
    assert lost("Not so fast, 511.", "לא כל כך מהר, מטר עשרים.") == ["511"]
    assert lost("Not so fast, 511.", "לא כל כך מהר, 511.") == []
    assert lost("A vintage 1969 Super Camaro.", "קמארו אספנות משנת 1969.") == []
    assert lost("It's also 2,000 miles away.", "זה גם 2000 קילומטר מכאן.") == []

    # מספרים קטנים נכתבים במילים בעברית, וזו כתיבה תקינה
    assert lost("nine miles out", "במרחק תשעה מייל") == []
    assert lost("Ten days.", "עשרה ימים.") == []

    # קלט ריק או חסר אינו מפיל כלום
    assert lost("", "") == [] and lost("511", "") == []

    # והתיקון באמת מחובר למסלול הניסיון החוזר
    body = inspect.getsource(hebrew._translate_all)
    assert "lost_numbers" in body, "הבדיקה לא מחוברת לתרגום"
    assert "damaged" in body



@check("קובץ כתוביות מזוהה גם כששמו חסר או מטעה")
def _subtitle_routing():
    """תפס מסלול "קובץ משלי" שלא עשה כלום.

    media_of ממציא "document.mp4" כש-file_name חסר, ואז בדיקת הסיומת
    נכשלה והבוט פתח עבודה שלמה חדשה במקום להשתמש בקובץ שנשלח.
    """
    import inspect

    from zovexsub import botjob, botmenu, localbot

    sub = localbot.looks_like_subtitle
    assert sub({"document": {"file_name": "a.srt"}})
    assert sub({"document": {"file_name": "A.ASS"}})
    assert sub({"document": {"mime_type": "text/plain", "file_size": 2048}})
    # שם חסר לגמרי, מסמך קטן — בדיוק המקרה שנשבר
    assert sub({"document": {"mime_type": "application/octet-stream",
                             "file_size": 1500}})
    # סרטון אינו כתוביות, וגם לא מסמך וידאו גדול
    assert not sub({"video": {"file_name": "x.mp4"}})
    assert not sub({"document": {"mime_type": "video/mp4",
                                 "file_size": 900_000_000}})
    assert not sub({})

    # ועבודה שממתינה גוברת על כל זיהוי
    body = inspect.getsource(botmenu._incoming)
    assert "on_waiting" in body, "מצב ההמתנה לא נבדק"
    assert hasattr(botjob, "waiting_for")
    assert "botmenu.on_waiting" in inspect.getsource(botjob.install)



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
