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
    # גבול עליון ולא תחתון, וזה היפוך של מה שהנחתי. הלקוח הרשמי של
    # טלגרם מגביל את עצמו לארבעה עובדים ל-DC, והתיעוד של Telethon
    # אומר שמקביליות רק מקרבת את FLOOD_WAIT. עשרים חיבורים נתנו
    # 7.5MB/s בהתחלה, ואחרי שימוש ממושך שמונה שניות ללחיצת יד
    # ו-0.5MB/s — חניקה, לא איטיות
    # עשרים נמדדו כמהירים משמעותית אצל המשתמש, והוא ביקש אותם
    # במפורש. זה מעל הארבעה של הלקוח הרשמי ומזמין FLOOD_WAIT — אבל
    # עכשיו יש רשת ביטחון: חיבורים שמתו נפתחים מחדש וההורדה ממשיכה
    # במקום להיזרק. בלי TG_REVIVALS הערך הזה מסוכן
    assert config.TG_CONNECTIONS <= 24, config.TG_CONNECTIONS
    assert config.TG_REVIVALS >= 2, (
        "מספר חיבורים גבוה בלי פתיחה מחדש מאבד הורדות שלמות")



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
    fine = media._settings_for(Path(__file__), 600.0, 1080, "fast265")
    assert fine["codec"] == "libx265", fine
    # ה-preset הוא מנוף המהירות הגדול. נמדד על 1080p עם כתוביות באותו
    # CRF 23: superfast 1.40x מול veryfast 1.06x. "איכותי" חייב להישאר
    # על superfast, אחרת שליש מהמהירות הולך על הפרש שאינו נראה
    assert fine["preset"] == "superfast", fine



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



@check("ההרכבה המקבילית אינה מאבדת פריימים, והאימות תופס אם כן")
def _frames_survive():
    """תפס פלט של 0.374 פריימים לשנייה במקום 23.976.

    מכולת MP4 אינה תומכת בקצב משתנה, ולכן ffmpeg מנחש קצב לכל קטע
    בנפרד. במקור VFR הניחושים נבדלים, צירי הזמן אינם תואמים,
    וה-concat מפיק חותמות זמן שבורות — 2,800 פריימים במקום 181,000.

    האימות לא תפס את זה כי הוא בדק רק אורך: הקובץ ההרוס נמשך 02:06:15
    מול 02:06:07, סטייה של עשירית האחוז, והוא נשלח למשתמש בשקט.
    """
    import inspect

    from zovexsub import media

    # קצב אחיד נכפה על כל קטע
    body = inspect.getsource(media._burn_parallel)
    assert "video_fps(video)" in body, "קצב המקור לא נקרא"
    assert "cfr_args(fps)" in body, "הקטעים אינם מקבלים קצב קבוע"
    # ורק כשצריך: על מקור CFR הדגלים מיותרים, וכבר הפילו צריבה שלמה
    assert "if vfr:" in body, "הדגלים נוספים גם למקור CFR"
    assert "is_vfr(video)" in body

    # והאימות בודק פריימים ולא רק שניות
    check_body = inspect.getsource(media._verify)
    assert "avg_frame_rate" in check_body, "האימות עדיין עיוור לפריימים"
    assert "source_fps" in inspect.signature(media._verify).parameters
    assert "_verify(dst, duration, fps)" in body, "קצב המקור לא מועבר לאימות"

    # פענוח קצב משבר אמיתי
    assert media.video_fps.__doc__



@check("כתוביות שנשלחו תוך כדי ההורדה נקלטות ולא נזרקות")
def _early_subtitle():
    """תפס את המקרה הרגיל, לא את החריג.

    ההודעה "שלח עכשיו את קובץ הכתוביות" מופיעה מיד עם הלחיצה, אבל
    _waiting נרשם רק אחרי שההורדה מסתיימת — דקות אחר כך. הקובץ
    שהמשתמש שולח תוך כדי נפל בין הכיסאות בלי שום תשובה.
    """
    import inspect

    from zovexsub import botjob

    body = inspect.getsource(botjob.run)
    assert '_waiting[int(chat_id)] = None' in body, \
        "ההמתנה עדיין נרשמת רק אחרי ההורדה"
    assert body.index('_waiting[int(chat_id)] = None') < body.index('_fetch('), \
        "הרישום חייב לקדום להורדה"
    assert "_given.pop" in body, "קובץ שהגיע מוקדם אינו נאסף"

    take = inspect.getsource(botjob.take_subtitle)
    # ההבחנה הקריטית: "אין עבודה" מול "ההורדה עדיין רצה"
    assert "not in _waiting" in take, "שני המצבים עדיין מזוהים כ-None"
    assert "_given[chat]" in take, "הקובץ המוקדם אינו נשמר"
    assert take.count("קיבלתי את הכתוביות") >= 2, "אין אישור קבלה למשתמש"

    # ומצב ההמתנה נכון גם כשהערך None
    botjob._waiting.clear()
    botjob._waiting[5] = None
    assert botjob.waiting_for(5) and botjob.waiting_for("5")
    assert not botjob.waiting_for(6)
    botjob._waiting.clear()



@check("yt-dlp מתעדכן ל-nightly כשיוטיוב שוברת את הנגן")
def _ytdlp_nightly():
    """יוטיוב משנה את הנגן כל כמה ימים.

    התיקון נכנס לערוץ nightly תוך שעות וליציב רק אחרי שבועות, ולכן
    nightly הוא הערוץ שהתיעוד של yt-dlp ממליץ עליו. קודם ההודעה רק
    ביקשה מהמשתמש להריץ pip ביד, וכל הורדה נכשלה עד שעשה את זה.
    """
    import asyncio
    import inspect

    from zovexsub import config, fetch

    stale = fetch._stale_player
    assert stale("ERROR: unable to extract nsig function")
    assert stale("Failed to extract any player response")
    assert stale("Please report this issue on https://github.com/yt-dlp")
    # חסימה אינה גרסה ישנה, ואין טעם לעדכן בגללה
    assert not stale("Sign in to confirm you're not a bot")
    assert not stale("HTTP Error 429: Too Many Requests")
    assert not stale("Private video")

    # ניסיון אחד נוסף בלבד, ורק אחרי עדכון שהצליח
    body = inspect.getsource(fetch.download)
    assert "except StalePlayer" in body, "אין ניסיון חוזר אחרי עדכון"
    assert body.count("_ytdlp(") == 2, "הניסיון החוזר חייב להיות יחיד"
    assert issubclass(fetch.StalePlayer, fetch.FetchError)

    # והמרווח נאכף: קריאה שנייה מיד אחרי הראשונה מדלגת
    was, config.YTDLP_AUTO_UPDATE = config.YTDLP_AUTO_UPDATE, 0
    try:
        assert asyncio.run(fetch.update_nightly()) is False
    finally:
        config.YTDLP_AUTO_UPDATE = was



@check("בשליחה יש דופק ולא הודעה קפואה")
def _upload_heartbeat():
    """ההודעה "שולח…" נשארה ללא שינוי דקות ארוכות.

    השליחה היא קריאה אחת לשרת המקומי ואין ממנה דיווח בייטים, אבל
    קובץ של כמה ג'יגה לוקח דקות — והודעה קפואה אינה נבדלת משירות שמת.
    """
    import inspect

    from zovexsub import botjob

    body = inspect.getsource(botjob._burn)
    assert "שולח {megabytes:.0f}MB" in body, "הגודל אינו מוצג"
    assert body.count("async def beat") == 1, "אין דופק בשליחה"
    assert "pulse.cancel()" in body, "הדופק אינו נעצר"
    # הדופק חייב להיעצר גם כששליחה נכשלת
    send = body[body.index("pulse = asyncio.create_task(beat())"):]
    assert "finally:" in send[:send.index("✅ הסתיים")], \
        "ביטול הדופק אינו ב-finally"



@check("קישור נשאל על איכות לפני ההורדה, והעבודה יוצאת לרקע")
def _link_job():
    """שני באגים באותו מסלול.

    קישור שנשלח לבוט לא עשה כלום: _incoming בדק רק מדיה. וכשהוא כן
    התחיל, שלב האיכות ישב בטעות בתפריט הצריבה — שמופיע רק אחרי
    שהכתוביות כבר נוצרו, כלומר אחרי ההורדה.
    """
    import inspect

    from zovexsub import botjob, botmenu, fetch

    body = inspect.getsource(botmenu._incoming)
    assert "fetch.find_url" in body, "הטקסט לא נבדק לקישור"
    assert "greet_link" in body

    assert "QUALITY" in inspect.getsource(botmenu.greet_link)
    assert not any(st[2] == "quality" for st in botmenu.STEPS), \
        "האיכות חזרה לתפריט הצריבה, שהוא אחרי ההורדה"

    press = inspect.getsource(botmenu._press)
    assert press.index('data.startswith("q:")') < press.index('data.startswith("src:")'), \
        "האיכות חייבת לקדום לבחירת המקור"
    assert "_detach(on_choice(choice)" in press, "await ישיר על העבודה"
    assert "await on_choice(choice)" not in press

    for row in botmenu.QUALITY_KEYS:
        for _, data in row:
            if not data.startswith("q:"):
                continue
            value = data.split(":", 1)[1]
            fmt = fetch.format_for(value)
            assert "bestvideo" in fmt, (value, fmt)
            if value.isdigit():
                assert f"height<={value}" in fmt, fmt
    assert "height<=" not in fetch.format_for("best")

    assert "fmt" in inspect.signature(fetch.download).parameters
    assert "fmt=want" in inspect.getsource(botjob._from_link)


@check("איכויות הקישור אמיתיות, וההתקדמות מראה כמה מתוך כמה ומתי יסתיים")
def _link_progress():
    """רשימת איכויות קבועה היא הבטחה שאי אפשר לעמוד בה.

    לסרטון אחד יש 1080p ולאחר רק 360p. וההתקדמות הראתה אחוז בלבד,
    בלי כמה ירד מתוך כמה ובלי זמן משוער.
    """
    import inspect

    from zovexsub import botjob, botmenu, config, fetch

    # הכפתורים נבנים מהרזולוציות שהתקבלו
    rows = botmenu.quality_keys([1080, 720, 480, 360, 240, 144])
    sent = [d for row in rows for _, d in row if d.startswith("q:")]
    assert sent == ["q:1080", "q:720", "q:480", "q:360", "q:240", "q:144",
                    "q:best"], sent
    assert all(len(row) <= 2 for row in rows[:-2]), "יותר משניים בשורה"
    # רשימה ריקה נופלת לגיבוי במקום להשאיר תפריט ללא כפתורים
    assert botmenu.quality_keys([]) is botmenu.QUALITY_KEYS

    # הבדיקה עצמה מתעלמת ממסלולי שמע נקיים
    body = inspect.getsource(fetch.heights)
    assert 'vcodec' in body and '"none"' in body, "מסלול שמע ייספר כרזולוציה"
    assert "reverse=True" in body, "הסדר אינו מהגבוה לנמוך"

    # ETA עובר מ-yt-dlp עד המסך
    assert "progress.eta" in fetch.TEMPLATE
    shown = inspect.getsource(botjob._from_link)
    assert "נותרו" in shown and "/{total / 1048576" in shown, \
        "אין כמה מתוך כמה או זמן משוער"
    # והמקביליות אינה שמרנית מדי
    assert config.FETCH_CONNECTIONS >= 8, config.FETCH_CONNECTIONS



@check("גודל הכתוביות תואם למדידה מול קובץ מקצועי")
def _subtitle_size():
    """נמדד בצילום מסך של נגן אמיתי עם כתוביות של מקודד מקצועי.

    המדד היציב הוא המרחק בין ראש שורה לראש השורה הבאה, כאחוז מגובה
    אזור הווידאו: הוא אינו תלוי בהחלקת קצוות או בדחיסת התמונה.
    מקצועי 8.40%; FontSize 20 נתן 7.04% ו-22 נתן 8.70%.
    """
    from zovexsub import media

    small = media.SUB_SIZES["קטן"]
    assert small["font"] == 22, (
        f"קטן הוא {small['font']} ולא 22 — המדידה נתנה 21.6")
    # הסולם עולה, וקו המתאר עולה איתו
    fonts = [media.SUB_SIZES[k]["font"] for k in ("קטן", "בינוני", "גדול")]
    assert fonts == sorted(fonts) and len(set(fonts)) == 3, fonts
    lines = [media.SUB_SIZES[k]["outline"] for k in ("קטן", "בינוני", "גדול")]
    assert lines == sorted(lines), lines

    # MarginV אחיד: 28 הרחיק את הכתוביות לעשרה אחוזים מהתחתית
    # במקום 7.11 שנמדדו אצל המקצוענים
    margins = {media.SUB_SIZES[k]["margin"] for k in media.SUB_SIZES}
    assert margins == {20}, margins

    # והערכים באמת מגיעים ל-force_style
    style = media.sub_style("קטן", "dejavu", "קו")
    assert "FontSize=22" in style and "MarginV=20" in style, style



@check("דגל הקצב הקבוע מותאם לגרסת ffmpeg המותקנת")
def _cfr_flag_portable():
    """תפס צריבה מקבילית שנפלה על כל סרט.

    -fps_mode נוסף ב-ffmpeg 5.0. על 4.x, שהיא הגרסה ב-Ubuntu 22.04,
    הוא אופציה לא מוכרת ו-ffmpeg נופל מיד — כלומר הדגל שנועד לתקן
    אובדן פריימים הפיל את המסלול המקבילי כולו.
    """
    import asyncio
    import inspect

    from zovexsub import media

    body = inspect.getsource(media.cfr_args)
    assert '"-vsync"' in body and '"-fps_mode"' in body, \
        "אין נפילה אחורה לשם הישן"

    args = asyncio.run(media.cfr_args(23.976024))
    assert args[0] in ("-fps_mode", "-vsync"), args
    assert args[1] == "cfr" and "-r" in args, args
    assert "23.976024" in " ".join(args), args
    # קצב לא ידוע לא מוסיף דגלים בכלל
    assert asyncio.run(media.cfr_args(0)) == []

    # והכישלון מדווח את הסיבה ולא רק את שם המחלקה. הנפילה למסלול
    # היחיד יושבת ב-burn, לא ב-_burn_parallel
    outer = inspect.getsource(media.burn)
    assert "{tail}" in outer and "tail = why[-1]" in outer, \
        "ההודעה עדיין מציגה שם מחלקה במקום את הסיבה"



@check("סיבת הנפילה למסלול האיטי נשלחת בהודעה נפרדת")
def _fast_failure_visible():
    """הסיבה מעולם לא הגיעה לעיניים.

    _fast הציג אותה בעריכה של אותה הודעה, ודופק הגיבוי מתחיל תוך
    שניות ודורס כל עריכה. התוצאה: המשתמש רואה רק "השרת מוריד" ואין
    שום רמז למה המסלול המהיר לא עבד.
    """
    import inspect

    from zovexsub import botjob

    body = inspect.getsource(botjob._fast)
    assert "localbot.say(chat_id_of(screen)" in body, \
        "הסיבה עדיין נכתבת בעריכה שנדרסת"
    assert "screen.show(f\"⚠️" not in body, "נשארה עריכה עם אזהרה"
    # שני המסלולים מדווחים: פענוח שנכשל וגם הורדה שנכשלה
    assert body.count("localbot.say(chat_id_of(screen)") >= 2, \
        "רק אחד משני מצבי הכישלון מדווח"
    assert botjob.chat_id_of(botjob.Screen(777, 1)) == 777



@check("חיבורי ההורדה נפתחים בזה אחר זה, כפי שנמדד כמהיר")
def _senders_parallel():
    """שתי מדידות שסותרות את האינטואיציה.

    ראשית, TimeoutError ריק הפיל כל הורדה לגיבוי: הקמה סדרתית של
    עשרים חיבורים חצתה את פסק הזמן לבייט הראשון. התיקון הנכון היה
    להרחיב את פסק הזמן, לא להאיץ את ההקמה.

    שנית, פתיחה מקבילית נראתה כשיפור מובן מאליו — ונמדדה איטית פי
    שמונה: 7.5MB/s בזה אחר זה מול 0.9MB/s יחד. היא נשארת מאחורי מתג
    כבוי, כי ההשערה סבירה אך המדידה גוברת עליה.
    """
    import inspect

    from zovexsub import config, fastio

    body = inspect.getsource(fastio._open_senders)
    # הפתיחה סדרתית כברירת מחדל. המקבילית נראתה נכונה אבל נמדדה
    # גרועה: 7.5MB/s בזה אחר זה מול 0.9MB/s יחד
    assert config.TG_OPEN_PARALLEL == 0, \
        "הפתיחה המקבילית חזרה לברירת המחדל אף שנמדדה איטית פי שמונה"
    assert "config.TG_OPEN_PARALLEL" in body, "אין מתג בין שתי הדרכים"
    assert "senders.append(await one(key))" in body, "חסר המסלול הסדרתי"
    # הראשון תמיד לבדו — הוא מייצא את ההרשאה
    assert body.index("first = await one(key)") < body.index("count > 1")
    assert "ExportAuthorizationRequest" in body

    # פסק הזמן לבייט הראשון חייב להכיל הקמה סדרתית מלאה
    assert config.FAST_START_TIMEOUT >= 180, config.FAST_START_TIMEOUT

    # מספר החיבורים שקמו בפועל מגיע למסך, אחרת קצב נמוך נראה בלתי מוסבר
    par = inspect.getsource(fastio._parallel_download)
    assert "workers = max(1, len(senders))" in par, \
        "התקרה מחושבת מהמספר המבוקש ולא מזה שקם"
    assert '"senders": len(senders)' in par
    assert "רק {got} מתוך {asked} חיבורים" in inspect.getsource(fastio._note)

    # והתקרה גדולה דיה להקמה מקבילית של מלוא החיבורים
    assert config.TG_CONNECT_TIMEOUT >= 30, config.TG_CONNECT_TIMEOUT
    assert config.FAST_START_TIMEOUT >= config.TG_CONNECT_TIMEOUT, (
        "פסק הזמן לבייט הראשון קצר מפסק הזמן להקמת החיבורים")



@check("הורדה שחיבוריה מתו ממשיכה במקום להיזרק")
def _download_revives():
    """תפס אובדן של יותר מגיגה־בייט וחצי.

    הורדה של שני ג'יגה הגיעה ל-69 אחוזים, כל החיבורים מתו, והלולאה
    יצאה אף שנשארו חלקים — מה שהסתיים בשגיאה והכל נזרק. הקובץ כתוב
    לפי היסטים בתוך שטח שהוקצה מראש, ולכן חיבורים חדשים יכולים פשוט
    להמשיך מאיפה שנעצרו.
    """
    import inspect

    from zovexsub import config, fastio

    body = inspect.getsource(fastio._parallel_download)
    assert "while not pending.empty()" in body, \
        "הלולאה עדיין יוצאת כשהחיבורים מתים"
    assert "revivals" in body and "config.TG_REVIVALS" in body
    assert "_open_senders(client, dc_id, fresh)" in body, \
        "אין פתיחה מחדש של חיבורים"
    # והמספר חסום, אחרת הורדה אבודה תסתובב לנצח
    assert "revivals >= config.TG_REVIVALS" in body, "אין תקרה לסבבים"
    assert 2 <= config.TG_REVIVALS <= 10, config.TG_REVIVALS



@check("קובץ כתוביות נקרא בכל קידוד, לא רק UTF-8")
def _subtitle_encoding():
    """תפס "codec can't decode byte 0xbb" שהפיל צריבה שלמה.

    קובצי כתוביות בעברית מופצים לרוב ב-cp1255. קריאה עיוורת כ-UTF-8
    נכשלת עליהם בשגיאה שאינה אומרת למשתמש דבר.
    """
    import inspect
    import tempfile

    from zovexsub import media
    from zovexsub import srt as S

    body = "1\n00:00:01,000 --> 00:00:04,000\nשלום עולם\n"
    with tempfile.TemporaryDirectory() as room:
        room = Path(room)
        for name, enc in (("u.srt", "utf-8"), ("b.srt", "utf-8-sig"),
                          ("w.srt", "cp1255"), ("i.srt", "iso-8859-8")):
            (room / name).write_bytes(body.encode(enc))
            got = S.read_subtitle(room / name)
            assert "שלום עולם" in got, (name, enc, got[:40])
            assert len(S.parse(got)) == 1, name

        # הבייט שהפיל בפועל, בתוך קובץ שאינו UTF-8 תקין
        broken = room / "x.srt"
        broken.write_bytes(body.encode("utf-8")[:62] + b"\xbb" +
                           body.encode("utf-8")[62:])
        assert S.read_subtitle(broken), "קובץ פגום לא החזיר טקסט"

        # והנורמליזציה כותבת UTF-8 ודאי
        out = S.normalize(room / "w.srt", room / "out.srt")
        assert out.read_bytes().decode("utf-8")

    # ושני הקוראים משתמשים בה
    assert "read_subtitle" in inspect.getsource(media.rtl_copy), \
        "rtl_copy עדיין קורא UTF-8 בלבד"
    assert "read_subtitle(source)" in inspect.getsource(S.slice_file)



@check("התקדמות מדווחת מהדיסק כשהמוריד החיצוני שותק")
def _fetch_disk_progress():
    """aria2c הוא תת-תהליך, ו-yt-dlp אינו מדווח עליו כלל.

    בלי קריאה מהדיסק המסך קופא על "מוריד" לאורך כל ההורדה, וזה
    נראה למשתמש כמו תקיעה אף שהקובץ יורד בפועל
    """
    import tempfile

    from zovexsub import fetch

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        assert fetch.disk_bytes(work) == 0
        (work / "source.mp4.part").write_bytes(b"x" * 5000)
        (work / "source.f140.m4a").write_bytes(b"y" * 1200)
        (work / "notes.txt").write_bytes(b"z" * 9999)   # לא קובץ הורדה
        got = fetch.disk_bytes(work)
        assert got == 6200, got

    source = inspect.getsource(fetch._ytdlp)
    assert "disk_bytes(work)" in source, "אין שעון דיסק ב-_ytdlp"
    assert "FETCH_STALL" in source, "אין זיהוי תקיעה"

    # המקבל חייב לדעת לקבל הערה, אחרת הדיווח מהדיסק יפיל אותו
    from zovexsub import botjob
    inner = inspect.getsource(botjob._from_link)
    assert "note: str" in inner, "on_progress של הקישור אינו מקבל הערה"


@check("ההורדה מנסה חשבון משתמש דרך האחסון לפני הבוט")
def _storage_download_lane():
    """תקרת ההורדה של טוקן בוט אינה ניתנת לכוונון מסביבה.

    חשבון משתמש אינו כפוף לה, אבל אינו רואה את הצ'אט שבין האדם
    לבוט. ערוץ האחסון — שעד כה שימש רק להעלאה — הוא הדרך לתת לו
    לראות את הקובץ, וזה הסדר שחייב להתקיים
    """
    import inspect

    from zovexsub import botjob, botmenu, localbot

    assert hasattr(localbot, "forward"), "אין העברת הודעה לאחסון"
    assert hasattr(botjob, "_via_storage"), "אין מסלול דרך האחסון"

    order = inspect.getsource(botjob._fetch)
    first = order.index("_via_storage")
    assert first < order.index("_fast("), "מסלול החשבון אינו ראשון"
    assert first < order.index("localbot.locate"), "getFile אינו אחרון"

    lane = inspect.getsource(botjob._via_storage)
    assert "botapi.premium()" in lane, "אינו משתמש בחשבון משתמש"
    assert "return False" in lane, "אינו נופל אחורה בכשל"

    # בלי מזהה ההודעה המקורית אין מה להעביר, וכל המסלול מתבטל
    assert "source_message" in botmenu.Choice.__annotations__
    greet = inspect.signature(botmenu.greet).parameters
    assert "source_message" in greet, "greet אינו מקבל את ההודעה המקורית"


@check("מגדר הדוברים נקבע מהתמלול ומייתר סריקה שלמה")
def _speaker_gender_table():
    """המגדר נשרף קודם ממסמך החקר בביטוי רגולרי שחיפש "@מגדר:".

    כשהמסמך ניסח אחרת לא ננעץ דבר, והתרגום חזר לנחש מגדר מהטקסט —
    בדיוק הנקודה שבה זכר ונקבה מתהפכים. התמלול כבר מחזיר מי אמר כל
    מילה, ולכן אפשר להכריע פעם אחת ולנעוץ
    """
    import inspect

    from zovexsub import config, hebrew
    from zovexsub.stt import Segment

    assert hasattr(hebrew, "speaker_genders"), "אין טבלת מגדר מהדוברים"

    # בלי זיהוי דוברים נשארים על מסמך החקר ולא נופלים
    bare = [Segment(index=i, start=i, end=i + 1, text="שלום") for i in range(3)]
    row, sure = asyncio.run(hebrew.speaker_genders(bare, "en", "@מגדר: דן זכר"))
    assert row == "דן זכר", row
    assert sure is False, "בלי דוברים אי אפשר להיות ודאי"

    # הטבלה נעוצה בחלון התרגום, ואינה נשרפת שם מחדש מהפרוזה
    window = inspect.getsource(hebrew._translate_all)
    assert "genders: str" in window, "הטבלה אינה מועברת לתרגום"
    assert "gender_table(notes)" not in window, "עדיין שורף מהפרוזה בכל חלון"

    # מעבר התיקון מדולג כשהטבלה ודאית, אלא אם נדרש במפורש
    flow = inspect.getsource(hebrew.build_hebrew)
    assert "speaker_genders" in flow, "הטבלה אינה נבנית"
    assert "ADDRESSEE_ALWAYS" in flow, "אין דילוג על מעבר התיקון"
    assert config.ADDRESSEE_ALWAYS == 0, "ברירת המחדל אמורה לדלג"


@check("כתוביות מורחקות מחיתוכי צילום")
def _snap_to_shot_changes():
    """נטפליקס אוסרת על כתובית לחצות חיתוך צילום.

    הנימוק מתועד: כתובית שמופיעה רגע לפני חיתוך נקראת פעמיים, כי
    החיתוך מחזיר את העין אל הטקסט. זו אריתמטיקה בלבד — אפס קריאות
    מודל ואפס המתנה
    """
    from zovexsub import config, srt

    def cue(start, end, text="שלום"):
        return srt.Cue(index=1, start=start, end=end, text=text)

    # חיתוך ממש אחרי סוף הכתובית: הסוף נמשך אליו
    cues = [cue(1.0, 3.0)]
    assert srt.snap_to_cuts(cues, [3.2], 24.0) == 1
    assert cues[0].end == 3.2, cues[0].end

    # חיתוך ממש בהתחלה: הכתובית מתחילה עליו ולא לפניו
    cues = [cue(1.0, 5.0)]
    assert srt.snap_to_cuts(cues, [1.3], 24.0) == 1
    assert cues[0].start == 1.3, cues[0].start

    # חיתוך באמצע כתובית ארוכה נשאר כמו שהוא — פיצול שובר את הטקסט
    cues = [cue(1.0, 6.0)]
    assert srt.snap_to_cuts(cues, [3.5], 24.0) == 0
    assert (cues[0].start, cues[0].end) == (1.0, 6.0)

    # הזזה לא תקצר כתובית מתחת למינימום
    cues = [cue(1.0, 1.0 + config.SRT_MIN_DURATION)]
    before = cues[0].end
    srt.snap_to_cuts(cues, [1.2], 24.0)
    assert cues[0].end == before, "קיצר מתחת למינימום"

    # ובלי חיתוכים כלום לא זז
    cues = [cue(1.0, 3.0)]
    assert srt.snap_to_cuts(cues, [], 24.0) == 0


@check("לשלב החקר יש תקרת זמן, ומה שהספיק נכנס")
def _research_budget():
    """החקר הוא שיפור ולא תנאי: הוא שומר על עקביות שמות לאורך פרק.

    חיפוש אחד איטי החזיק עד כה את כל השלב, והמשתמש חיכה בלי לקבל
    דבר. מסמך חלקי עדיף על התחלה מאוחרת
    """
    import inspect

    from zovexsub import config, hebrew

    source = inspect.getsource(hebrew.research_notes)
    assert "RESEARCH_BUDGET" in source, "אין תקרת זמן לחקר"
    assert "asyncio.wait(" in source, "עדיין ממתין לכל הקריאות"
    assert "job.cancel()" in source, "קריאה שחרגה אינה מבוטלת"
    # קריאה שנפלה או בוטלה אינה מפילה את השלב
    assert 'parts.append("")' in source, "כשל בקריאה אינו מדולג"
    assert config.RESEARCH_BUDGET > 0

    # הדליפה שנמדדה: שלב שתוקצב ל-150 שניות נמדד ב-510, כי קריאת
    # אימות הרשת רצה אחרי התקרה ולא בתוכה
    assert "deadline" in source, "אין מועד סיום משותף לכל השלב"
    assert source.count("deadline") >= 3, "האימות אינו חולק את התקרה"
    assert "asyncio.wait_for(" in source, "האימות עדיין מחוץ לתקרה"
    assert "VERIFY_MIN_SECONDS" in source, "אין רצפה לפתיחת חיפוש"
    # הזמן שנותר מהתקרה, ולא תקרה חדשה משל עצמו
    assert "deadline - time.monotonic()" in source, "האימות מקבל תקרה נפרדת"

    # ושתיקת התמלול: בלי סיבה בלוג אי אפשר לדעת למה רץ יישור כפוי
    from zovexsub import gemini_stt
    why = inspect.getsource(gemini_stt.transcribe)
    assert "GEMINI_STT" in why, "אינו אומר שהתמלול כבוי"
    assert why.count("log.warning") >= 2, "עדיין מחזיר None בשקט"


@check("מכסת ג'ימיני משותפת לכל המפתחות ומתכווצת על 429")
def _shared_rate_budget():
    """התיעוד של גוגל: המכסה היא לפי פרויקט ולא לפי מפתח.

    כל ההנחה שמפתח נוסף הוא מכסה נוספת שגויה כששני המפתחות באותו
    פרויקט, ואז ירי מקבילי מחזיר 429 ותו לא. ובנוסף היו שני מאגרים
    נפרדים על אותם מפתחות, וכל אחד ספר לעצמו
    """
    from zovexsub import gemini, gemini_stt
    from zovexsub.keypool import Budget

    # שני המאגרים חייבים לחלוק מופע אחד, אחרת הם יורים כפול
    assert gemini._pool.shared is gemini_stt._pool.shared, \
        "המאגרים אינם חולקים תקציב"

    budget = Budget(ceiling=8, floor=2)
    now = 1000.0
    for _ in range(8):
        assert budget.room(now), "נחסם בתוך התקרה"
        budget.charge(now)
    assert not budget.room(now), "לא נחסם בתקרה"

    # 429 מחצי את הקצב, אבל לא מתחת לרצפה
    budget.throttle(now)
    assert budget.rate == 4.0, budget.rate
    budget.throttle(now + 10)
    assert budget.rate == 2.0, budget.rate
    budget.throttle(now + 20)
    assert budget.rate == 2.0, "ירד מתחת לרצפה"

    # גל אחד של 429 אינו מכווץ פעמיים
    fresh = Budget(ceiling=8)
    fresh.throttle(now)
    fresh.throttle(now + 1)
    assert fresh.rate == 4.0, fresh.rate

    # ודקה נקייה מחזירה בקשה אחת
    fresh._sent = []
    assert fresh.room(now + 70)
    assert fresh.rate == 5.0, fresh.rate


@check("שלב שעומד במקום אומר זאת, ולא נראה פשוט כמו אפס")
def _stage_stall_is_announced():
    """"0%" לבדו אינו מבדיל בין קריאה ארוכה לבין תהליך מת.

    זו הייתה התלונה החוזרת ביותר: המסך עומד על אפס דקות ארוכות
    ואין דרך לדעת אם לחכות או להרוג. עכשיו זה נאמר במפורש, גם על
    המסך וגם בלוג
    """
    import time as clock_mod

    from zovexsub import progress

    seen = []

    async def edit(text):
        seen.append(text)

    async def drive():
        stage = progress.Stage(edit, "🇮🇱 מתרגם")
        # רגע לפני הסף — עוד לא מכריזים
        stage.step_started = clock_mod.monotonic() - (progress.STALL_AFTER - 5)
        await stage._flush(force=True)
        assert "אין תזוזה" not in seen[-1], seen[-1]

        # ואחריו — כן, ועם שעון
        stage.step_started = clock_mod.monotonic() - (progress.STALL_AFTER + 60)
        stage.last_edit = 0.0
        await stage._flush(force=True)
        assert "אין תזוזה" in seen[-1], seen[-1]
        assert stage._said_stalled is True

        # תזוזה אמיתית מנקה את ההכרזה, אחרת היא נדבקת לנצח
        await stage.show(0.4)
        assert stage._said_stalled is False
        stage.last_edit = 0.0
        await stage._flush(force=True)
        assert "אין תזוזה" not in seen[-1], seen[-1]

    asyncio.run(drive())


@check("התמלול מדווח מה קורה בתוך חלק, ומעלה בסיומת הנכונה")
def _stt_live_reporting():
    """חלק הוא 20 דקות, והאחוז זז רק כשהוא נגמר במלואו.

    עד כה פירוש הדבר היה "0%" לאורך 13 דקות, שנראה זהה לתהליך מת.
    ובדרך התגלה שהקובץ נקרא .wav אבל תוכנו FLAC, וה-SDK גוזר את
    mime_type מהסיומת — כלומר הצהרנו audio/wav על בייטים של FLAC
    """
    import inspect

    from zovexsub import gemini_stt, pipeline

    src = inspect.getsource(gemini_stt.transcribe)
    assert '.flac"' in src, "עדיין מעלה בסיומת wav"
    assert '.wav"' not in src, "נשארה סיומת wav"
    assert '"חותך"' in src and '"מתמלל"' in src, "אין דיווח על שלב בתוך חלק"
    assert "ticker()" in src, "אין דופק בזמן חלק ארוך"
    # הדופק נעצר גם כשחלק נופל, אחרת הוא נשאר חי אחרי השלב
    tail = src[src.index("finally:", src.index("pulse =")):]
    assert "pulse.cancel()" in tail, "הדופק אינו מבוטל ב-finally"

    # והמקבל חייב להסכים לקבל הערה, אחרת כל דיווח יפיל את השלב
    got = inspect.signature(pipeline.run).parameters
    assert got is not None
    inner = inspect.getsource(pipeline.run)
    assert "note: str = \"\"" in inner, "on_chunk אינו מקבל הערה"


@check("חלק תמלול תקוע או שנפל אינו מפיל את כל העבודה")
def _stt_chunk_isolation():
    """gather ממתין לאיטי שבחלקים, ובלי תקרה אין לזה גבול.

    וללא return_exceptions חלק אחד שנפל מחק גם את השבעה שהצליחו
    והעיף את כל התמלול ל-Groq מאפס
    """
    import inspect

    from zovexsub import config, gemini_stt

    src = inspect.getsource(gemini_stt.transcribe)
    assert "GEMINI_STT_TIMEOUT" in src, "אין תקרה לחלק בודד"
    assert "return_exceptions=True" in src, "חלק שנפל מפיל את כולם"
    assert "GEMINI_STT_MIN_GOOD" in src, "אין סף לתמלול מחורר"

    assert config.GEMINI_STT_TIMEOUT > 0
    assert 0 < config.GEMINI_STT_MIN_GOOD <= 1.0

    # והנפילה ל-Groq נשארת כשיותר מדי חלקים חסרים
    assert "return None" in src.split("GEMINI_STT_MIN_GOOD")[1][:400], \
        "לא נופל ל-Groq כשהתמלול מחורר"


@check("קריאות חיפוש נחסמות בשער, והתקציב המשותף כבוי כברירת מחדל")
def _search_gate_and_budget_default():
    """מפתחות מחשבונות שונים הם מכסות נפרדות באמת.

    תקרה משותפת רק תחנוק אותם ללא סיבה, ולכן היא כבויה כברירת
    מחדל. ה-429 שנמדדו היו של מכסת החיפוש — נפרדת וקטנה — ושם
    המפסק היה חסר אונים: בירי מקבילי כל הקריאות באוויר לפני
    שהראשונה חוזרת ומספיקה לסגור אותו
    """
    import inspect

    from zovexsub import config, gemini

    assert config.GEMINI_RPM_TOTAL == 0, "תקרה משותפת פעילה כברירת מחדל"
    assert config.SEARCH_PARALLEL >= 1
    assert gemini._pool.shared is None, "המאגר חנוק בלי סיבה"

    src = inspect.getsource(gemini.research)
    assert "_search_gate" in src, "אין שער לקריאות חיפוש"
    # נבדק שוב בתוך השער, אחרת ההמתנה מבזבזת את המפסק שכבר נסגר
    after = src[src.index("async with _search_gate"):]
    assert "_search_usable()" in after, "אינו נבדק שוב בתוך השער"
    # והקוד שמריץ בפועל חייב להישאר נגיש, לא אחרי return
    assert src.count("async def run(") == 1, "לולאת הניסיונות אינה פונקציה"
    assert "return await run(" in src


@check("תרגום קצר מהמקור אינו מוחק בשקט את זנב הסרט")
def _cue_length_mismatch():
    """zip עוצר ברשימה הקצרה ואינו אומר דבר.

    שורת תרגום אחת חסרה הייתה מוחקת את כל מה שאחריה — למשתמש זה
    נראה כמו "חור בכתוביות" בלי שום דרך לאבחן אותו
    """
    from zovexsub import srt
    from zovexsub.stt import Segment

    segments = [Segment(index=i, start=i * 2.0, end=i * 2.0 + 1.5,
                        text=f"line {i}") for i in range(10)]

    # התרגום חזר קצר בשלוש שורות — הזנב חייב לשרוד
    cues = srt.build_cues(segments, ["שלום"] * 7)
    assert cues, "לא נוצרו כתוביות"
    assert cues[-1].start >= segments[6].start, "הזנב נמחק בשקט"

    # ואורך זהה ממשיך לעבוד בדיוק כמו קודם
    same = srt.build_cues(segments, ["שלום"] * 10)
    assert len(same) >= len(cues), (len(same), len(cues))

    # וגם רשימה ארוכה מדי אינה מפילה
    srt.build_cues(segments, ["שלום"] * 14)


@check("פלט מעל תקרת הבוט נמסר דרך ערוץ האחסון ולא מסורב")
def _large_output_relay():
    """הבוט סירב "נדרש חשבון Premium" אחרי שהצריבה כבר הסתיימה.

    זו לא גזירה: חשבון משתמש מעלה לערוץ האחסון והבוט מעביר משם.
    העברה אינה העלאה, ולכן תקרת הבוט אינה חלה עליה — אותו מבנה
    שבנינו להורדה, בכיוון ההפוך. התשתית הייתה קיימת ולא מחוברת
    """
    import inspect

    from zovexsub import botjob, fastio, localbot

    assert hasattr(botjob, "_relay_video"), "אין מסירה דרך האחסון"

    burn = inspect.getsource(botjob._burn)
    assert "localbot.MAX_BYTES" in burn, "אינו בודק את תקרת הבוט"
    assert "_relay_video" in burn, "אינו עובר לאחסון מעל התקרה"
    # והקטנים ממשיכים בדרך הזולה, דרך השרת המקומי
    assert "localbot.send_video" in burn, "הקטנים אינם עוברים בשרת המקומי"

    relay = inspect.getsource(botjob._relay_video)
    assert "localbot.forward" in relay, "אינו מעביר מהאחסון למשתמש"
    assert "botapi.uploader" in relay, "אינו בוחר חשבון לפי גודל"
    assert "return False" in relay, "כשל אינו מדווח לקורא"

    # fastio.upload קורא עם שלושה ארגומנטים, טלתון עם שניים.
    # חתימה צרה מדי הייתה מפוצצת את ההעלאה אחרי צריבה שלמה
    got = [line for line in relay.splitlines() if "async def on_upload" in line]
    assert got and "note" in got[0], got


@check("ערוץ האחסון נפתר לכל חשבון בנפרד")
def _storage_entity_per_account():
    """access_hash של ערוץ ייחודי לחשבון.

    peer שחשבון אחד פתר אינו תקף אצל אחר, וטלגרם עונה "invalid
    Peer". מטמון גלובלי יחיד גרם בדיוק לזה: ההורדה פתרה את הערוץ
    עם החשבון הרגיל, וההעלאה קיבלה את הישות שלו במקום של Premium
    """
    import inspect

    from zovexsub import botapi

    assert isinstance(botapi._storage, dict), "המטמון עדיין גלובלי יחיד"

    src = inspect.getsource(botapi.storage)
    assert "id(client)" in src, "המטמון אינו לפי חשבון"
    # וגם: חשבון שלא "ראה" את הערוץ בסשן הזה נכשל ב-get_input_entity
    assert "get_dialogs" in src, "אין מילוי מטמון כשהערוץ לא נפתר"
    assert "return None" in src, "כשל אינו מדווח לקורא"

    class Fake:
        def __init__(self, tag):
            self.tag = tag

        async def get_input_entity(self, want):
            return f"peer-{self.tag}"

    one, two = Fake("a"), Fake("b")
    got_one = asyncio.run(botapi.storage(one))
    got_two = asyncio.run(botapi.storage(two))
    if config.STORAGE_CHAT:
        assert got_one != got_two, "שני חשבונות קיבלו אותו peer"
    botapi._storage.clear()


@check("סחיפה שגדלה עם הזמן מתוקנת ליניארית, לא בהיסט אחד")
def _progressive_drift():
    """היסט קבוע אחד מיישר את האמצע ומשאיר את שני הקצוות שגויים.

    פרק של 20 דקות נראה תקין וסרט של שעתיים מתפרק — בדיוק הדפוס
    שדווח. התיקון חייב להיות ליניארי, ועם שמרנות: בקובץ קצר ההפרש
    בין שני החצאים הוא רעש מדידה ולא סחיפה
    """
    from zovexsub import config, srt

    def cue(start, text="שלום"):
        return srt.Cue(index=1, start=start, end=start + 1.2, text=text)

    # דיבור כל 10 שניות לאורך שעה
    speech = [(i * 10.0, i * 10.0 + 1.0) for i in range(360)]

    # כתוביות שמאחרות יותר ויותר: אפס בהתחלה, שתי שניות בסוף
    total = 3590.0
    cues = [cue(i * 10.0 + 2.0 * (i * 10.0) / total) for i in range(360)]
    base, rate, pivot = srt.drift_fit(cues, speech)
    assert rate > 0, (base, rate)
    srt.apply_drift(cues, base, rate, pivot)
    # אחרי התיקון שני הקצוות אמורים לשבת על תחילת דיבור
    for probe in (cues[5], cues[-5]):
        near = min(abs(probe.start - a) for a, _ in speech)
        assert near <= 0.6, (probe.start, near)

    # קליפ קצר: אין מספיק טווח, ואין להתערב
    short = [cue(i * 10.0) for i in range(12)]
    assert srt.drift_fit(short, speech[:12])[1] == 0.0, "התערב בקליפ קצר"

    assert config.DRIFT_MIN_SPAN > 0 and config.DRIFT_MAX_RATE > 0


@check("דיבור שהתמלול פספס מתומלל שוב ולא רק נרשם בלוג")
def _gap_recovery():
    """נמדד בשרת: 19 עד 45 שניות דיבור בכל פרק נשמעו ל-VAD וחזרו
    ריקות מהתמלול, וכל מה שקרה היה שורת אזהרה.

    וחור אינו נשאר חור: הכתוביות סביבו נמתחות לכסות אותו, וכתובית
    שנמתחה על פני עשר שניות מופיעה בזמן הלא נכון — ולכן מילים
    חסרות נראות למשתמש כבעיית תזמון
    """
    import inspect

    from zovexsub import config, pipeline, stt
    from zovexsub.stt import Segment

    # רק מה שגם זוהה כדיבור וגם אין לו תמלול, ורק מעל אורך מינימלי
    segments = [Segment(index=0, start=0.0, end=5.0, text="a"),
                Segment(index=1, start=30.0, end=35.0, text="b")]
    speech = [(0.0, 5.0), (10.0, 14.0), (30.0, 35.0), (40.0, 40.4)]
    gaps = stt.speech_gaps(segments, speech, 1.2)
    assert gaps == [(10.0, 14.0)], gaps

    # קטע קצר מהסף אינו נבחר, גם כשאין לו תמלול
    assert stt.speech_gaps(segments, [(40.0, 40.4)], 1.2) == []

    # והבנייה מתשובת תמלול מזיזה לזמן האמיתי בסרטון
    built = stt._segments_from(
        {"segments": [{"text": "שלום", "start": 1.0, "end": 2.0}],
         "words": [{"start": 1.0, "end": 2.0, "word": "שלום"}]}, offset=100.0)
    assert built and abs(built[0].start - 101.0) < 0.01, built[0].start

    flow = inspect.getsource(pipeline.run)
    assert "recover_gaps" in flow, "ההשלמה אינה רצה בצינור"
    # לפני התרגום, אחרת אין טעם — המילים כבר אבדו
    assert flow.index("recover_gaps") < flow.index("build_hebrew")
    assert config.RECOVER_GAPS == 1


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
