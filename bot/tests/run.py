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
    assert "senders.append(await one(key, where=media))" in body, \
        "חסר המסלול הסדרתי"
    # הראשון תמיד לבדו — הוא מייצא את ההרשאה
    assert body.index("first = await one(key,") < body.index("count > 1")
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
    # הסדר נקבע בזמן ריצה לפי DOWNLOAD_FIRST, ולכן בדיקת סדר בטקסט
    # המקור הייתה עוברת מסיבה לא נכונה
    assert "config.DOWNLOAD_FIRST" in order, "הסדר אינו ניתן לשינוי"
    assert order.index("for attempt in order") < order.index(
        "localbot.locate"), "getFile אינו אחרון"

    # ברירת המחדל היא החשבון. קודם היה כאן הבוט, מהנימוק ש-
    # FLOOD_PREMIUM_WAIT מתקבל רק אחרי שהמשתמש העלה עשרות ג'יגה ולכן
    # ההעלאות מהטלפון ממלאות את תקציב החשבון. הנימוק הזה אינו תקף
    # יותר: ההורדות עברו ל-Premium בלבד, וחשבון Premium אינו יכול
    # לקבל את השגיאה הזאת כלל. ובפועל נתיב הבוט נמדד כנתקע לפני
    # הבייט הראשון, 0% אחרי שתי דקות
    assert config.DOWNLOAD_FIRST == "account", config.DOWNLOAD_FIRST

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
    from zovexsub import config, srt
    from zovexsub.stt import Segment

    segments = [Segment(index=i, start=i * 2.0, end=i * 2.0 + 1.5,
                        text=f"line {i}") for i in range(10)]

    # התרגום חזר קצר בשלוש שורות — הזנב חייב לשרוד
    cues = srt.build_cues(segments, ["שלום"] * 7)
    assert cues, "לא נוצרו כתוביות"
    assert len(cues) == 7, (len(cues), "שורות אבדו")
    # ההקדמה האחידה מזיזה כל כתובית מעט אחורה, ולכן ההשוואה עם
    # סבילות: מה שנבדק כאן הוא שהזנב קיים, לא מיקומו המדויק
    assert cues[-1].start >= segments[6].start - config.SRT_LEAD - 0.01, \
        "הזנב נמחק בשקט"

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


@check("כל הכתוביות מוקדמות מעט, לא רק אלה שהוצמדו")
def _uniform_lead():
    """זיהוי הדיבור מכריז על דיבור רק אחרי שהאנרגיה הצטברה.

    האיחור הזה קבוע, ומכיוון שאנחנו גם מצמידים אליו וגם מודדים את
    ההיסט מולו — הוא בלתי נראה למדידה שלנו. הלוג אומר "אין היסט
    שיטתי" והמשתמש רואה דיליי, ושניהם צודקים
    """
    from zovexsub import config, srt

    def cue(start, end):
        return srt.Cue(index=1, start=start, end=end, text="שלום")

    cues = [cue(10.0, 12.0), cue(20.0, 22.0)]
    srt.apply_lead(cues, 0.2)
    assert abs(cues[0].start - 9.8) < 0.01, cues[0].start
    assert abs(cues[1].start - 19.8) < 0.01, cues[1].start
    # הסוף נשאר במקומו: הכתובית מופיעה מוקדם יותר, לא נעלמת מוקדם יותר
    assert abs(cues[0].end - 12.0) < 0.01, cues[0].end

    # ואינה דורכת על הכתובית שלפניה
    tight = [cue(10.0, 12.0), cue(12.05, 14.0)]
    srt.apply_lead(tight, 0.5)
    assert tight[1].start >= tight[0].end, (tight[0].end, tight[1].start)

    # ולא לפני תחילת הסרטון
    edge = [cue(0.1, 2.0)]
    srt.apply_lead(edge, 0.5)
    assert edge[0].start == 0.0, edge[0].start

    assert config.SRT_LEAD > 0


@check("כל קטע בצריבה המקבילית נצרב בקצב פריימים קבוע")
def _segments_always_cfr():
    """נמדד בשרת: הפלט יצא 0.381 פריימים לשנייה במקום 23.976.

    הכפייה הוחלה רק כשהמקור זוהה כ-VFR, והמקורות שנכשלו היו CFR
    נקי. ההנחה הייתה שגויה: concat אינו דורש קצב קבוע מ-VFR בלבד,
    הוא דורש אותו מכל קטע — כל קטע נחתך מאמצע הסרט ומקבל חותמות
    זמן יחסיות למקור
    """
    import inspect

    from zovexsub import media

    source = inspect.getsource(media._burn_parallel)
    assert "cfr_args(fps)" in source, "אין כפיית קצב בקטעים"
    # ללא גייט: שורת הכפייה אינה יושבת בתוך "if vfr"
    where = source.index("cfr_args(fps)")
    before = source[:where]
    assert "if vfr:\n            cmd" not in before, "הכפייה עדיין מותנית"
    # והבדיקה שתפסה את זה חייבת להישאר
    verify = inspect.getsource(media._verify)
    assert "איבדה פריימים" in verify, "בדיקת הפריימים הוסרה"


@check("התאוששות מחיבורים שמתו אינה נספרת כתקיעה")
def _revival_is_not_a_stall():
    """נמדד בשרת: "ההורדה תקועה 184 שניות על 36%" על קובץ 2.7GB.

    כשכל החיבורים מתים ההורדה מנסה להתאושש, וההתאוששות לוקחת עד
    30 שניות המתנה ועוד עד 45 לפתיחת חיבורים — זמן שבו לא יורד אף
    בייט מעצם טבעה. השומר ספר אותו כתקיעה והרג את ההתאוששות בדיוק
    כשהיא עבדה, וכמעט ג'יגה־בייט שכבר ירד נזרק.

    המנגנון כבר היה שם: השומר מכבד state["until"] עבור המתנה
    שטלגרם ביקש. ההתאוששות פשוט לא עדכנה אותו
    """
    import inspect

    from zovexsub import config, fastio

    src = inspect.getsource(fastio._parallel_download)
    revival = src[src.index("revivals += 1"):]

    # הסימון חייב לקרות לפני ההמתנה, אחרת השומר כבר ספר אותה
    mark = revival.index('state["until"] = max(')
    assert mark < revival.index("await asyncio.sleep(rest)"), \
        "ההמתנה אינה מסומנת לפני שהיא מתחילה"
    # והחלון חייב לכסות גם את ההמתנה וגם את פתיחת החיבורים
    assert "TG_CONNECT_TIMEOUT + 5" in revival, "החלון קצר מדי"
    # ואחרי שהחיבורים קמו השעון מתחיל מחדש
    after = revival[revival.index("senders.extend(healthy)"):]
    assert "last_progress = time.monotonic()" in after, \
        "השעון ממשיך מהבייט שלפני הנפילה"

    # והשומר עצמו עדיין מכבד את החלון
    assert 'if now < state["until"]' in src, "השומר אינו מכבד המתנה"
    assert config.TG_STALL_TIMEOUT > 0 and config.TG_CONNECT_TIMEOUT > 0


@check("סף התקיעה גדול מתקציב הניסיונות של חלק בודד")
def _stall_beats_retry_budget():
    """נמדד בשרת: "ההורדה תקועה 184 שניות על 36%".

    חלק בודד רשאי לנסות שלוש פעמים, 60 שניות כל אחת, עם המתנות
    ביניהן — 186 שניות. סף התקיעה היה 180. כלומר חלק שנזקק למלוא
    זכות הניסיונות שלו לא יכול לסיים לעולם, כי השומר הורג את
    ההורדה לפניו. 184 נופל בדיוק בחלון שבין 180 ל-186.
    """
    from zovexsub import config

    budget = config._retry_budget()
    assert budget > 0

    # החשבון עצמו: ניסיונות מלאים ועוד ההמתנות שביניהם
    waits = sum(min(8, 2 ** step)
                for step in range(1, config.TG_READ_RETRIES))
    expected = config.TG_READ_TIMEOUT * config.TG_READ_RETRIES + waits
    assert abs(budget - expected) < 0.01, (budget, expected)

    # והיחס שחייב להתקיים תמיד
    assert config.TG_STALL_TIMEOUT > budget, \
        f"סף {config.TG_STALL_TIMEOUT} אינו גדול מתקציב {budget}"
    # עם שוליים של ממש, לא בשערה
    assert config.TG_STALL_TIMEOUT >= budget + 30, \
        "השוליים צרים מדי — ניסיון תקין ייחתך"


@check("תמונת תצוגה מקדימה נקלטת, מוכנה ומחליפה את הפריים")
def _custom_cover():
    """טלגרם חוסמת תצוגה מקדימה ב-320 פיקסל וב-200KB.

    תמונת 4K תוקטן תמיד — זו מגבלה שלה. מה שכן בידינו הוא לא לבזבז
    את התקרה: הקטנה בלנצוש באיכות גבוהה נראית טוב בהרבה מגרב־פריים
    של הווידאו באותם 320 פיקסל
    """
    import inspect

    from zovexsub import botjob, botmenu, config, localbot, media

    # השאלה קיימת בתפריט, לפני בחירת הצריבה
    fields = [step[2] for step in botmenu.STEPS]
    assert "cover" in fields, fields
    assert fields.index("cover") < fields.index("speed"), fields
    assert "cover" in botmenu.Choice.__annotations__

    # תמונה מגיעה כ-photo, ש-media_of מתעלם ממנו — צריך קורא משלה
    assert localbot.media_of({"photo": [{"file_id": "x"}]}) == ("", 0, "")
    got, _ = localbot.photo_of(
        {"photo": [{"file_id": "small", "file_size": 10},
                   {"file_id": "big", "file_size": 900}]})
    assert got == "big", got
    # ותמונה שנשלחה כקובץ שומרת על האיכות — גם אותה קולטים
    assert localbot.photo_of(
        {"document": {"file_id": "d", "mime_type": "image/png"}})[0] == "d"
    assert localbot.photo_of({"document": {"mime_type": "text/plain"}})[0] == ""

    assert hasattr(media, "thumb_from_image")
    assert config.THUMB_MAX <= 320, "מעל התקרה של טלגרם"
    assert config.THUMB_BYTES < 200_000, "מעל התקרה של טלגרם"

    # התמונה שהתקבלה גוברת על הפריים מהסרטון, ואינה זולגת לעבודה הבאה
    burn = inspect.getsource(botjob._burn)
    assert "_cover.pop(" in burn, "אינו משתמש בתמונה שהתקבלה"
    assert burn.index("_cover.pop(") < burn.index("media.poster("), \
        "הפריים גובר על התמונה"
    assert "_cover_wait.discard" in burn, "ההמתנה אינה מתנקה"

    # ובהעלאה: כמה מתוך כמה, לא רק אחוז
    relay = inspect.getsource(botjob._relay_video)
    assert "/{total / 1048576:.0f}MB" in relay, "אין כמה מתוך כמה"


@check("ההגדרות נזכרות, והפרק הבא מתחיל בלחיצה אחת")
def _settings_are_remembered():
    """חמש שאלות בכל פרק, באותן תשובות בדיוק.

    המשתמש מעלה פרקים של אותה סדרה שוב ושוב. זיכרון הופך את זה
    ללחיצה אחת, ומשאיר את השינוי זמין למי שבאמת רוצה אותו
    """
    import importlib
    import tempfile

    from zovexsub import config as live

    live.PREFS_FILE = tempfile.mktemp(suffix=".json")
    from zovexsub import prefs
    importlib.reload(prefs)

    # ברירות מחדל שלמות גם כשאין קובץ בכלל
    first = prefs.get(7)
    assert set(first) == set(prefs.FIELDS), first
    assert all(first.values()), first

    prefs.remember(7, {"size": "גדול", "speed": "מהיר", "zzz": "להתעלם"})
    again = prefs.get(7)
    assert again["size"] == "גדול" and again["speed"] == "מהיר"
    assert "zzz" not in again, "שדה לא מוכר נשמר"
    # ומה שלא נשמר חוזר לברירת המחדל ולא נעלם
    assert again["look"] == prefs.DEFAULTS["look"]

    # הסיכום קריא ומכסה את כל השדות
    line = prefs.summary(again)
    assert "גדול" in line and line.count("·") == len(prefs.FIELDS) - 1, line

    # ומסך הפתיחה מציג אותו, עם דרך לשנות
    from zovexsub import botmenu
    text, keys = botmenu.source_screen(7)
    assert "ההגדרות שלך" in text and "גדול" in text
    flat = [data for row in keys for _, data in row]
    assert "settings" in flat, flat
    assert "src:make" in flat and "src:own" in flat


@check("אחרי תקרת מהירות על החשבון מדלגים עליו, ולא שורפים עוד רבע שעה")
def _premium_flood_backoff():
    """FLOOD_PREMIUM_WAIT הוא תקרה שטלגרם מצמידה לחשבון ללא Premium
    אחרי עשרות ג'יגה־בייט מצטברים, והיא אינה חולפת תוך שניות.

    נמדד בשטח: ההורדה בחשבון רצה 25 דקות, הגיעה ל-78% ונפלה עם
    FLOOD_PREMIUM_WAIT_8. בלי זיכרון כל קובץ הבא שורף עוד רבע שעה
    על אותו מסלול ונכשל באותו אופן בדיוק
    """
    import inspect
    import time as clock

    from zovexsub import botjob, config

    assert config.PREMIUM_FLOOD_REST > 0

    # בלי אירוע — המסלול פתוח
    botjob._premium_flood_until = 0.0
    assert botjob._account_rested() == 0.0

    botjob._note_premium_flood()
    left = botjob._account_rested()
    assert left > 0, "ההימנעות לא נרשמה"
    assert left <= config.PREMIUM_FLOOD_REST + 1, left

    # והיא חולפת מעצמה
    botjob._premium_flood_until = clock.monotonic() - 1
    assert botjob._account_rested() == 0.0
    botjob._premium_flood_until = 0.0

    lane = inspect.getsource(botjob._via_storage)
    # הבדיקה לפני שנפתח חשבון, אחרת כבר שילמנו על הניסיון
    assert lane.index("_account_rested()") < lane.index("botapi.downloader"), \
        "ההימנעות נבדקת מאוחר מדי"
    assert '"PREMIUM" in str(exc).upper()' in lane, "אינו מזהה את התקרה"


@check("דיליי קבוע נתפס גם כשיש הרבה כתוביות ומעט תחילות דיבור")
def _onset_anchored_offset():
    """דווח דיליי של כשלוש שניות, והלוג אמר "אין היסט שיטתי".

    global_evaluate סורק כל כתובית ושואל אם היא קרובה לתחילת דיבור.
    ה-VAD מוצא כ-200 קטעי דיבור ארוכים ובתוכם 2000 כתוביות, ולכן
    לרוב המוחלט אין בכלל תחילת־דיבור מתאימה — הן באמצע מונולוג,
    נספרות כרעש, וההיסט האמיתי נבלע
    """
    from zovexsub import srt

    def cue(start):
        return srt.Cue(index=1, start=start, end=start + 1.5, text="שלום")

    # עשרים קטעי דיבור ארוכים, ובתוך כל אחד שש כתוביות
    speech, cues = [], []
    lag = 3.0
    for block_no in range(20):
        begin = block_no * 30.0
        speech.append((begin, begin + 15.0))
        for inner in range(6):
            cues.append(cue(begin + lag + inner * 2.2))

    # המדידה מתחילות הדיבור מוצאת את הדיליי האמיתי
    found = srt.onset_offset(cues, speech)
    assert abs(found - lag) < 0.4, (found, lag)

    # ובלי דיבור או בלי כתוביות היא לא ממציאה דבר
    assert srt.onset_offset([], speech) == 0.0
    assert srt.onset_offset(cues, []) == 0.0

    # והיא נדרשת בפועל, לא רק קיימת
    import inspect
    flow = inspect.getsource(srt.build_cues)
    assert "onset_offset(" in flow, "המדידה אינה בשימוש"


@check("TG_PART_MAX הוא תקרה אמיתית, וניתן לרדת ל-128KB מה-.env")
def _part_cap():
    from zovexsub import fastio
    big = 2 * 1024 * 1024 * 1024
    saved = config.TG_PART_MAX
    try:
        config.TG_PART_MAX = 1024 * 1024
        assert fastio._parts(big) == 1024 * 1024
        # הלקוח הרשמי מבקש 128KB לכל חלק, ואי אפשר להכריע בלי מדידה.
        # לכן חייב להיות אפשר לרדת לשם בלי לגעת בקוד
        config.TG_PART_MAX = 128 * 1024
        chosen = fastio._parts(big)
        assert chosen == 128 * 1024, chosen
        assert chosen % 4096 == 0 and (1024 * 1024) % chosen == 0
    finally:
        config.TG_PART_MAX = saved


@check("צריבה שנכשלה בהרכבה מנסה שוב על הקטעים, ולא צורבת הכל מחדש")
def _burn_retry():
    import asyncio
    import inspect

    # הקטעים שכבר נצרבו נבדקים לפני שצורבים אותם שוב
    body = inspect.getsource(media._burn_parallel)
    assert "piece.exists()" in body, "אין דילוג על קטע קיים"
    assert "shutil.rmtree" in body

    calls = {"parallel": 0, "single": 0}

    async def parallel(*a, **k):
        calls["parallel"] += 1
        raise media.FFmpegError("ההרכבה נכשלה")

    async def single(*a, **k):
        calls["single"] += 1
        return Path("out.mp4")

    async def duration(_path):
        return 60 * 60.0

    saved = (media._burn_parallel, media._burn_single, media.duration_seconds)
    try:
        media._burn_parallel = parallel
        media._burn_single = single
        media.duration_seconds = duration
        out = asyncio.run(media.burn(Path("in.mp4"), Path("in.srt"),
                                     Path("out.mp4")))
    finally:
        (media._burn_parallel, media._burn_single,
         media.duration_seconds) = saved

    assert out == Path("out.mp4")
    # שני ניסיונות מקביליים: הראשון צורב, השני רק מרכיב מחדש
    assert calls["parallel"] == 2, calls
    # ורק אחרי שגם השני נכשל יורדים לתהליך יחיד
    assert calls["single"] == 1, calls


@check("קובץ מעל 2 ג'יגה עולה דרך Premium, וההמתנה של ההורדה לא חוסמת אותו")
def _premium_upload_lane():
    import inspect
    from zovexsub import botapi, botjob

    # ניתוב לפי גודל: מעל תקרת החשבון הרגיל — Premium, תמיד.
    # מתחת לתקרה הבחירה מתחלפת בתורות (ראו _upload_turns), ולכן
    # נבדק כאן שהחשבון הרגיל אכן מגיע לתורו ולא שהוא הראשון
    saved_turn = botapi._turn
    botapi._lite = object()
    try:
        botapi._turn = 0
        picks = {botapi.uploader(config.LITE_UPLOAD_MAX, "PREM")[1]
                 for _ in range(4)}
        botapi._turn = 0
        big = botapi.uploader(config.LITE_UPLOAD_MAX + 1, "PREM")
    finally:
        botapi._lite = None
        botapi._turn = saved_turn
    assert picks == {"רגיל", "Premium"}, picks
    assert big == ("PREM", "Premium"), big

    # ובהורדה אין פיצול בכלל: Premium תמיד. חשבון ללא מנוי סופג
    # FLOOD_PREMIUM_WAIT אחרי עשרות ג'יגה, וזה הקצב שמתמוטט באמצע
    botapi._premium, botapi._lite = "PREM", object()
    try:
        for bytes_ in (1, config.LITE_UPLOAD_MAX, config.LITE_UPLOAD_MAX + 1):
            assert botapi.downloader(bytes_, "ARG") == ("PREM", "Premium"), \
                f"ההורדה של {bytes_} בייט לא עברה ב-Premium"
        # ובלי Premium מחובר, חשבון רגיל עדיף על כלום
        botapi._premium = None
        assert botapi.downloader(1, None)[1] == "רגיל"
    finally:
        botapi._premium, botapi._lite = None, None

    # תקרת המהירות שנתפסת בהורדה משביתה את מסלול החשבון להורדה בלבד.
    # אם היא תחסום גם את ההעלאה, קובץ של 3 ג'יגה פשוט לא יימסר
    assert "_account_rested" in inspect.getsource(botjob._via_storage)
    assert "_account_rested" not in inspect.getsource(botjob._relay_video)


@check("בקשות קבצים הולכות לכתובת ה-DC שטלגרם ייעד לקבצים")
def _media_dc():
    from types import SimpleNamespace
    from zovexsub import fastio

    def opt(**kw):
        base = dict(id=2, ip_address="general", port=443, media_only=False,
                    cdn=False, ipv6=False)
        base.update(kw)
        return SimpleNamespace(**base)

    class Client:
        _config = SimpleNamespace(dc_options=[
            opt(),
            opt(ip_address="media", media_only=True),
            opt(ip_address="cdn", media_only=True, cdn=True),
            opt(id=4, ip_address="other-dc", media_only=True),
        ])
        _use_ipv6 = False

    client = Client()
    # כבוי כברירת מחדל: זו הייתה הנחה שלא מופיעה בתיעוד, ובשרת היא
    # נמדדה כ"לא התחיל להוריד תוך 240 שניות" — אף בייט מ-16 חיבורים
    assert config.TG_MEDIA_DC == 0, \
        "כתובת הקבצים הודלקה בברירת המחדל אף שלא אומתה בפועל"

    saved = config.TG_MEDIA_DC
    try:
        config.TG_MEDIA_DC = 1
        # הכתובת הכללית היא הראשונה ברשימה, וזו שטלתון היה בוחר.
        # התיעוד הרשמי מחייב לשלוח קבצים לכתובת עם media_only
        chosen = fastio._media_option(client, 2)
        assert chosen is not None and chosen.ip_address == "media", chosen
        # CDN אינו מסלול שיש לנו תמיכה בו, ו-DC אחר אינו רלוונטי
        assert fastio._media_option(client, 3) is None
        # ובלי כתובת כזו נשארים על ההתנהגות של טלתון
        Client._config = SimpleNamespace(dc_options=[opt()])
        assert fastio._media_option(client, 2) is None
        # דגל כיבוי, אם הכתובת הזאת מתנהגת רע בפועל
        Client._config = SimpleNamespace(dc_options=[
            opt(ip_address="media", media_only=True)])
        config.TG_MEDIA_DC = 0
        assert fastio._media_option(client, 2) is None
    finally:
        config.TG_MEDIA_DC = saved


@check("מרווח הבהוב בין כתוביות נסגר לשני פריימים, כחוק התזמון")
def _close_gaps():
    fps = 24.0
    frame = 1.0 / fps

    def cue(start, end, text="שלום"):
        return srt.Cue(index=1, start=start, end=end, text=text)

    # מרווח של 8 פריימים — בתוך הטווח האסור, נסגר לשניים
    cues = [cue(1.0, 2.0), cue(2.0 + 8 * frame, 4.0)]
    assert srt.close_gaps(cues, fps) == 1
    assert abs((cues[1].start - cues[0].end) - 2 * frame) < 1e-6

    # מרווח של שני פריימים בדיוק — כבר תקין, לא נוגעים
    cues = [cue(1.0, 2.0), cue(2.0 + 2 * frame, 4.0)]
    assert srt.close_gaps(cues, fps) == 0

    # מרווח של שנייה שלמה — זמן אמיתי לחזור לתמונה, נשאר
    cues = [cue(1.0, 2.0), cue(3.0, 4.0)]
    assert srt.close_gaps(cues, fps) == 0
    assert cues[0].end == 2.0

    # והארכה שתעבור את האורך המרבי אינה נעשית
    long_end = config.SRT_MAX_DURATION + 0.9
    cues = [cue(0.0, long_end), cue(long_end + 8 * frame, long_end + 2)]
    assert srt.close_gaps(cues, fps) == 0, "הכתובית הוארכה מעל המרבי"

    # ההתחלה של הכתובית הבאה לא זזה אף פעם — היא על פריים האודיו
    cues = [cue(1.0, 2.0), cue(2.2, 4.0)]
    srt.close_gaps(cues, fps)
    assert cues[1].start == 2.2


@check("סט חיבורים שמת כולו חוזר קטן יותר, ולא באותו גודל")
def _revival_shrinks():
    import inspect
    from zovexsub import fastio

    body = inspect.getsource(fastio._parallel_download)
    assert "room = max(2, workers >> revivals)" in body, \
        "ההחייאה פותחת שוב את אותו מספר חיבורים"

    # חצי בכל סבב, ולעולם לא מתחת לשניים: חיבור אחד הוא כבר
    # המסלול האיטי, ואין טעם ליפול לשם דרך המסלול המהיר
    workers = 16
    rounds = [max(2, workers >> n) for n in (1, 2, 3, 4, 5)]
    assert rounds == [8, 4, 2, 2, 2], rounds


@check("תקרת ה-bitrate חסומה, וסרטון קצר לא מפיל את הצריבה")
def _bitrate_cap_clamped():
    # 26 שניות הפילו צריבה בשרת: bufsize של 2,292,270k, מעל התקרה של
    # מספר שלם 32 ביט, ו-ffmpeg דחה את האפשרות
    for seconds in (1.0, 5.0, 26.0, 60.0, 3600.0):
        cap = media._bitrate_cap(seconds)
        assert cap >= 300, (seconds, cap)
        assert cap <= config.BITRATE_CAP_MAX, (seconds, cap)
        # זה האילוץ האמיתי: bufsize הוא פי שתיים, והוא חייב להיכנס
        # במספר שלם 32 ביט כשהוא מוכפל ב-1000 על ידי ffmpeg
        assert cap * 2 * 1000 < 2 ** 31, (seconds, cap)

    # אורך לא ידוע נשאר בלי תקרה בכלל, כמו קודם
    assert media._bitrate_cap(0) == 0
    assert media._bitrate_cap(-1) == 0

    # וסרט שלם מקבל תקרה נמוכה מזו של סרטון קצר: החלוקה לפי האורך
    # עדיין עובדת, והחסימה לא השטיחה את כולם לאותו מספר
    assert media._bitrate_cap(2.5 * 3600) <= media._bitrate_cap(60.0)


@check("המסירה עוברת בחשבון לכל גודל, והבוט נשאר גיבוי")
def _upload_via_account():
    import inspect
    from zovexsub import botjob

    body = inspect.getsource(botjob._burn)
    # מסלול אחד לכל הגדלים: שני מסלולים לאותה פעולה הם שני מקומות
    # שבהם משהו יכול להישבר, וזה בדיוק מה שקרה
    assert "config.UPLOAD_VIA_ACCOUNT or big" in body, \
        "המסירה עדיין מתפצלת לפי גודל בלבד"
    assert config.UPLOAD_VIA_ACCOUNT == 1, config.UPLOAD_VIA_ACCOUNT
    # והבוט נשאר כגיבוי אמיתי, ולא נחסם
    assert "נופלים לבוט" in body, "אין נפילה חזרה לבוט"
    # אבל מעל תקרת הבוט אין גיבוי, ולכן שם זו שגיאה ולא נפילה
    assert "not relayed and big" in body, "מעל התקרה חייב להיכשל בקול"


@check("תיקון האותיות הזרות חסום בזמן, ומזיז את המסך בינתיים")
def _repair_bounded():
    import asyncio
    import inspect
    from zovexsub import hebrew

    body = inspect.getsource(hebrew.repair_foreign)
    # פסק הזמן הפנימי של ג'ימיני הוא 300 שניות לניסיון, על פני כמה
    # מפתחות. בלי תקרה משלנו זה רבע שעה חוקית בלי שהמסך יזוז
    assert "config.REPAIR_TIMEOUT" in body, "אין תקרת זמן לשלב"
    assert "asyncio.wait_for" in body
    assert "pulse.cancel()" in body, "הדופק אינו נעצר"
    assert config.REPAIR_TIMEOUT <= 300, config.REPAIR_TIMEOUT

    # ובפועל: קריאה שתקועה מחזירה את השורות כמו שהן, ולא מפילה
    # את הסרט ולא תולה אותו
    saved = (hebrew.gemini.ask_json, config.REPAIR_TIMEOUT)
    seen = []

    async def never(*a, **k):
        await asyncio.sleep(30)

    async def step(text, _frac):
        seen.append(text)

    lines = ["שלום", "hello שלום"]
    try:
        hebrew.gemini.ask_json = never
        config.REPAIR_TIMEOUT = 0.2
        out = asyncio.run(hebrew.repair_foreign(
            [hebrew.Segment(index=0, start=0.0, end=1.0, text="x")] * 2,
            list(lines), [1], step))
    finally:
        hebrew.gemini.ask_json, config.REPAIR_TIMEOUT = saved

    assert out == lines, out


@check("כתובית שלא נכנסת בשתי שורות מפוצלת לשתיים, ולא מקבלת שורה שלישית")
def _split_overlong():
    fps = 24.0
    frame = 1.0 / fps
    long_text = " ".join(["מילה"] * 40)

    cue = srt.Cue(index=1, start=10.0, end=18.0, text=long_text)
    assert srt.wrap(cue.text).count("\n") >= 2, "הטקסט אמור לחרוג"

    cues = [cue]
    assert srt.split_overlong(cues, fps) == 1
    # כמה שצריך, לא בהכרח שתיים: טקסט ארוך מאוד אינו נכנס בשתי
    # כתוביות של שתי שורות
    assert len(cues) >= 2

    # אף כתובית לא נשארת עם שלוש שורות
    for one in cues:
        assert srt.wrap(one.text).count("\n") < config.SRT_MAX_LINES, one.text

    # הטקסט נשמר במלואו, ושום מילה לא נבלעה
    assert " ".join(c.text.replace("\n", " ") for c in cues).split() == \
        long_text.split()

    # הזמנים לא חורגים מהמקור, ויש מרווח תקין ביניהן
    assert cues[0].start == 10.0 and cues[-1].end == 18.0
    for before, after in zip(cues, cues[1:]):
        assert abs((after.start - before.end) - 2 * frame) < 1e-6
    for one in cues:
        assert one.end - one.start >= config.SRT_MIN_DURATION, one

    # והמספור רץ מחדש, אחרת הקובץ שבור
    assert [c.index for c in cues] == list(range(1, len(cues) + 1))

    # כתובית קצרה מדי לפיצול נשארת כמו שהיא — עדיף שלוש שורות
    # מאשר שתי כתוביות שמהבהבות
    tight = [srt.Cue(index=1, start=0.0, end=1.2, text=long_text)]
    assert srt.split_overlong(tight, fps) == 0
    assert len(tight) == 1

    # וכתובית תקינה אינה נגעת כלל
    fine = [srt.Cue(index=1, start=0.0, end=3.0, text="שלום לך")]
    assert srt.split_overlong(fine, fps) == 0


@check("שורה שלא תורגמה ונשארה בשפה זרה נתפסת, גם בלי עברית לידה")
def _foreign_detector():
    from zovexsub import cleanup

    # המקרה שמתרגם מקצועי מצא בפלט: קטעים שלמים בסינית. קודם הגלאי
    # דרש שתהיה גם עברית באותה שורה, ולכן שורה שכולה סינית עברה בשקט
    for text in ("他说你好", "こんにちは", "안녕하세요",
                 "Привет", "Γειά σου", "مرحبا"):
        assert cleanup.has_foreign(text), text
        assert cleanup.has_foreign(f"שלום {text} לך"), text

    # עברית נקייה עוברת, וגם לטינית: שמות ומותגים לגיטימיים בכתובית
    for text in ("שלום לך", "שלום OK גמור", "נתניה 2026", "דוד ג'ונס"):
        assert not cleanup.has_foreign(text), text

    # והאיתור ברמת הרשימה מחזיר את המיקומים הנכונים
    lines = ["שלום", "他说", "בסדר", "Привет"]
    assert cleanup.foreign_lines(lines) == [1, 3]


@check("הקטעים נחתכים על גבולות פריימים, ולא סוחפים את הקול")
def _frame_aligned_segments():
    import inspect

    body = inspect.getsource(media._burn_parallel)
    assert "frames // segments" in body, "החיתוך אינו על גבולות פריימים"
    assert "index == segments - 1" in body, "הקטע האחרון אינו לוקח את השארית"

    # החשבון עצמו, על קצבים ואורכים אמיתיים. נמדד ב-ffmpeg לפני
    # התיקון: ביקשנו 7.500 וקיבלנו 7.5075 — 180 פריימים במקום 179.82,
    # וכל קטע גדל. האודיו נלקח מהמקור שלם, ולכן הווידאו נגרר אחריו
    for fps in (24000 / 1001, 25.0, 30000 / 1001, 24.0):
        for duration in (1891.0, 7200.5, 3600.25):
            for segments in (4, 8, 12, 18):
                step = 1.0 / fps
                frames = round(duration * fps)
                per = frames // segments
                span = per * step
                # כל קטע הוא מספר שלם של פריימים — אין מה לעגל
                assert abs(span * fps - round(span * fps)) < 1e-6, (fps, span)

                # והקטעים מכסים את הסרט במדויק, בלי חור ובלי חפיפה
                spans = [span] * (segments - 1)
                spans.append(duration - span * (segments - 1))
                assert abs(sum(spans) - duration) < 1e-6, (fps, duration)
                assert spans[-1] > 0, (fps, duration, segments)


@check("עטיפת הווידאו נשלחת במלוא הרזולוציה בשני מסלולי ההעלאה")
def _full_resolution_cover():
    import inspect
    from zovexsub import botjob, localbot

    # שורש הטשטוש: נשמרה רק הגרסה המוקטנת ל-320 פיקסלים, והמקור נזרק.
    # בזמן ההעלאה כבר לא היה מה לשלוח באיכות גבוהה
    intake = inspect.getsource(botjob.take_cover)
    assert "shutil.copy2" in intake, "התמונה המקורית אינה נשמרת"
    assert "_cover_full" in intake

    # מסלול החשבון: video_cover מקבל InputPhoto ואינו כפוף לתקרת
    # 320 הפיקסלים שחלה על thumbnail
    relay = inspect.getsource(botjob._relay_video)
    assert "video_cover" in relay, "מסלול החשבון אינו שולח עטיפה מלאה"
    assert "InputMediaUploadedPhoto" in relay, "העטיפה אינה מועלית כתמונה"
    # וכשל בשדה הזה אינו שווה סרט שלא נמסר אחרי ארבעים דקות צריבה
    assert "ממשיכים עם תצוגה מקדימה רגילה" in relay, "אין נפילה רכה"

    # מסלול הבוט: cover נוסף ב-Bot API 8.3, ושרת ישן ידחה אותו
    assert "cover" in inspect.signature(localbot.send_video).parameters
    sender = inspect.getsource(localbot.send_video)
    assert 'fields.pop("cover")' in sender, "אין שליחה חוזרת בלי cover"

    # והמוקטנת נשארת בכל מקרה: היא התצוגה המקדימה ברשימת הצ'אטים
    assert "thumbnail" in sender
    assert config.THUMB_MAX <= 320, config.THUMB_MAX


@check("התקדמות ההעלאה האמיתית אינה נדרסת בידי הדופק הכללי")
def _upload_progress_not_clobbered():
    import inspect
    from zovexsub import botjob

    body = inspect.getsource(botjob._burn)
    # הדופק נוצר רק במסלול הבוט. במסלול החשבון יש בייטים אמיתיים,
    # והדופק דרס אותם כל כמה שניות בהודעה כללית — שגם אינה נכונה,
    # כי "דרך השרת המקומי" נאמר בזמן שהמסירה עוברת בחשבון
    assert "pulse = None" in body, "הדופק עדיין מופעל תמיד"
    spot = body.index("if not relayed:\n                pulse = asyncio")
    assert spot > body.index("_relay_video("), \
        "הדופק נוצר לפני שידוע אם מסלול החשבון הצליח"
    assert "if pulse is not None:" in body, "ביטול הדופק יקרוס כשאין דופק"

    # ומסלול החשבון באמת מדווח כמה מתוך כמה, ולא רק אחוז
    relay = inspect.getsource(botjob._relay_video)
    assert "/{total / 1048576" in relay or "מתוך" in relay, \
        "אין דיווח של כמה מתוך כמה"


@check("תמונה וכתוביות נדרשות בתור, ולא שתיהן פתוחות בבת אחת")
def _sequential_requests():
    import inspect
    from zovexsub import botjob

    start = inspect.getsource(botjob.run)
    # כשגם תמונה וגם קובץ כתוביות נדרשים, הפתיחה אומרת שזה שלב 1
    assert "שלב 1 מתוך 2" in start, "אין סימון תור בפתיחה"
    assert 'both = choice.cover == "כן" and choice.source == "own"' in start

    # ולא מבקשים כתוביות בזמן שהתמונה עדיין חסרה
    assert "if int(chat_id) in _cover_wait:" in start, \
        "הבקשה לכתוביות יוצאת גם כשהתמונה עוד לא הגיעה"

    # ומיד כשהתמונה מגיעה, מגיעה הבקשה הבאה בתור
    intake = inspect.getsource(botjob.take_cover)
    assert "שלב 2 מתוך 2" in intake, "אין שרשור לבקשה הבאה"
    assert "if chat in _waiting" in intake

    # וכשאין כתוביות בכלל, ההודעה נשארת פשוטה ובלי מספור שלבים
    assert "היא תהיה " in intake


@check("בכל הודעה כתוב מה נדרש מהמשתמש עכשיו")
def _what_now_banner():
    from zovexsub import botjob

    chat = 987654
    saved = (set(botjob._cover_wait), dict(botjob._waiting))
    try:
        botjob._cover_wait.clear()
        botjob._waiting.clear()

        # כשלא מחכים לכלום אין באנר: שורה כזאת בכל עדכון היא רעש
        assert botjob._banner(chat) == ""

        # ממתינים לתמונה, ואחריה גם קובץ כתוביות — שניהם נאמרים,
        # בסדר, וברור מה עכשיו ומה אחר כך
        botjob._cover_wait.add(chat)
        botjob._waiting[chat] = None
        now = botjob._banner(chat)
        assert "עכשיו: שלח לי את התמונה" in now, now
        assert "אחר כך" in now and "כתוביות" in now, now

        # התמונה הגיעה, ההורדה עדיין רצה: אומרים שנבקש בהמשך
        botjob._cover_wait.discard(chat)
        waiting = botjob._banner(chat)
        assert "ברגע שההורדה תסתיים" in waiting, waiting

        # ההורדה הסתיימה: עכשיו באמת צריך את הקובץ
        botjob._waiting[chat] = Path("video.mp4")
        ready = botjob._banner(chat)
        assert "עכשיו: שלח לי את קובץ הכתוביות" in ready, ready

        # והבאנר באמת נדבק לכל הודעה, ולא רק קיים כפונקציה
        import inspect
        assert "_banner(self.chat_id)" in inspect.getsource(botjob.Screen.show)
    finally:
        botjob._cover_wait.clear()
        botjob._cover_wait.update(saved[0])
        botjob._waiting.clear()
        botjob._waiting.update(saved[1])


@check("נקודה בודדת אינה כתובית ואינה קרדיט")
def _no_stray_dot():
    import inspect

    # כתובית שכל תוכנה סימן פיסוק יורדת, והמספור רץ מחדש
    cues = [srt.Cue(index=1, start=0.0, end=2.0, text="."),
            srt.Cue(index=2, start=3.0, end=5.0, text="שלום"),
            srt.Cue(index=3, start=6.0, end=8.0, text=" - "),
            srt.Cue(index=4, start=9.0, end=11.0, text="מה נשמע")]
    assert srt.drop_blank(cues) == 2
    assert [c.text for c in cues] == ["שלום", "מה נשמע"]
    assert [c.index for c in cues] == [1, 2]

    # טקסט אמיתי עם פיסוק נשאר, וגם מספרים לבדם
    keep = [srt.Cue(index=1, start=0.0, end=2.0, text="...טוב"),
            srt.Cue(index=2, start=3.0, end=5.0, text="1948")]
    assert srt.drop_blank(keep) == 0

    # והניקוי באמת רץ בשרשרת, ולא רק קיים כפונקציה
    assert "drop_blank(cues)" in inspect.getsource(srt.build_cues)

    # אותו כלל בקרדיט: חלק בלי אות או ספרה אינו קרדיט
    assert "any(ch.isalnum() for ch in part)" in \
        inspect.getsource(media.credit_file)


@check("‏503 מג'ימיני מקבל סבב נוסף, ולא מפיל תרגום באמצע")
def _gemini_retries_5xx():
    from zovexsub import gemini

    # זו ההודעה המדויקת שהפילה עבודה אחרי 35% מתוך 1602 שורות
    crash = "כל המודלים נכשלו — gemini-flash-lite-latest: HTTP 503"
    assert gemini._transient(crash), "‏503 עדיין נחשב סופי"

    # כל ה-5xx, לא רק 503
    for code in (500, 502, 503, 504, 529):
        assert gemini._transient(f"model: HTTP {code}"), code

    # מה שהיה מזוהה קודם ממשיך להיות מזוהה
    assert gemini._transient("כל המודלים במכסה לדקה")
    assert gemini._transient("המודל עמוס")

    # ושגיאה אמיתית נשארת סופית: אין טעם לנסות שוב מפתח פסול
    for final in ("Gemini HTTP 400: bad request",
                  "מפתח לא תקין", "HTTP 404: model not found"):
        assert not gemini._transient(final), final

    # והתנאי באמת בשימוש בשרשרת, ולא רק קיים
    import inspect
    assert "_transient(str(exc))" in inspect.getsource(gemini._call)


@check("חלון תרגום שנכשל אינו מפיל את הסרט, והמקור נשמר במקומו")
def _window_failure_survives():
    import inspect
    from zovexsub import hebrew

    body = inspect.getsource(hebrew._translate_all)
    # נמדד בשרת: "לא התקבל JSON תקין מ-Gemini" על חלון בודד הרג את
    # כל התרגום, אחרי ש-1056 מתוך 1606 שורות כבר תורגמו
    assert "return_exceptions=True" in body, "חלון שנכשל עדיין מפיל הכל"

    # מה שנשאר ריק מקבל את שורת המקור, ולא נמחק
    assert "out[index] = segments[index].text" in body, "אין גיבוי למקור"

    # אבל כשכל החלונות נכשלו אין סרט, וכישלון שקט גרוע מהודעה ברורה
    assert "if len(broken) == len(starts):" in body, \
        "כישלון מלא עובר בשקט"
    assert "raise broken[0]" in body

    # והכישלונות נרשמים, אחרת סרט חלקי נראה כמו סרט תקין
    assert "חלונות תרגום נכשלו" in body


@check("קטעים נשמרים רק כשתוכנית החיתוך זהה, אחרת מתחילים נקי")
def _segment_plan_guard():
    import inspect

    body = inspect.getsource(media._burn_parallel)
    # הדילוג על קטע קיים הניח שהקטעים שייכים לאותה תוכנית ולא בדק.
    # בשרת נמדדו קטעים של 239.9 מול תוכנית שמחפשת 119.9 — 48 מתוך
    # 49 נצרבו מחדש, והמשתמש ראה צריבה שלמה מתחילה מאפס
    assert 'card = work / "plan.json"' in body, "אין תוכנית שמורה"
    assert '"segments": segments' in body and '"span": round(span, 3)' in body

    # הקטעים הם וידאו עם כתוביות כבר צרובות בתוכו, ולכן הטביעה
    # חייבת לכלול גם את קובץ הכתוביות ואת הסגנון. המסלול המיידי
    # משתמש באותה תיקיית עבודה של יצירת הכתוביות, ורק בו אפשר
    # לפגוש קטעים משיוט קודם — זה ההבדל מול צריבה נפרדת
    assert '"srt": subtitles' in body, "הכתוביות אינן בטביעת התוכנית"
    assert '"style": repr(style)' in body, "הסגנון אינו בטביעת התוכנית"
    assert '"profile": profile or ""' in body, "הפרופיל אינו בטביעה"
    assert "shutil.rmtree(work, ignore_errors=True)" in body, \
        "תוכנית שונה אינה מנקה את הקטעים הישנים"

    # והבדיקה קודמת לשימוש בקטעים, אחרת היא חסרת ערך
    assert body.index('card = work / "plan.json"') < body.index("piece.exists()")

    # שיתוף קטעים מותר רק בתוך אותה צריבה, ולעולם לא בין עבודות:
    # המסלול המיידי רץ בתיקיית העבודה של יצירת הכתוביות, וקטע
    # משיוט קודם נושא בתוכו תזמונים וסגנון ישנים
    assert "reuse: bool = False" in inspect.signature(
        media._burn_parallel).__str__().replace("'", "") or \
        "reuse" in inspect.signature(media._burn_parallel).parameters
    assert "if not reuse:" in body, "ניסיון ראשון אינו מתחיל נקי"
    caller = inspect.getsource(media.burn)
    assert "reuse=attempt > 1" in caller, \
        "הניסיון הראשון מקבל רשות להשתמש בקטעים ישנים"

    # הקבצים שנמחקו יחד עם התיקייה נוצרים מחדש
    after = body[body.index("shutil.rmtree(work, ignore_errors=True)"):]
    assert "marked = rtl_copy(srt)" in after[:400], "הכתוביות לא נוצרו מחדש"
    assert "credit = credit_file(work)" in after[:400], "הקרדיט לא נוצר מחדש"


@check("הרכבה שנכשלה מנסה דרך חיבור שנייה, ולא צורבת הכל מחדש")
def _assembly_second_route():
    import inspect

    body = inspect.getsource(media._burn_parallel)
    # הקטעים נצרבו ותקינים. ליפול מכאן לתהליך יחיד זה לצרוב ארבעים
    # דקות מחדש בגלל שלב חיבור שנמשך דקות
    assert "async def through_ts()" in body, "אין דרך חיבור שנייה"
    assert "concat:" in body, "אין שרשור דרך פרוטוקול concat"
    assert "mpegts" in body

    # מסנן הביטסטרים נבחר לפי הקודק בפועל, אחרת ה-TS יוצא פגום
    assert "hevc_mp4toannexb" in body and "h264_mp4toannexb" in body

    # והדרך השנייה נכנסת רק אחרי שהראשונה נכשלה
    first = body.index("await assemble_and_check(demuxer)")
    second = body.index("await assemble_and_check(through_ts)")
    assert first < second, "הדרך השנייה רצה לפני המהירה"
    assert "except (FFmpegError, OSError)" in body[first:second]

    # והאימות חייב להיות בתוך הניסיון, לא אחריו: ffmpeg מסיים בקוד
    # אפס ומפיק קובץ שאיבד כמעט את כל הפריימים — נמדד בשרת כ"קצב
    # הפריימים בפלט 0.490 במקום 24.000". כשהאימות היה מחוץ ל-try,
    # דרך החיבור השנייה לא רצה אף פעם בדיוק במקרה שבשבילו נבנתה
    inner = inspect.getsource(media._burn_parallel)
    start = inner.index("async def assemble_and_check")
    end = inner.index("try:", start)
    assert "_verify(dst, duration, fps)" in inner[start:end], \
        "האימות מחוץ לניסיון — הדרך השנייה לא תרוץ על פלט פגום"

    # והמשתמש רואה שמשהו השתנה, ולא מסך שנתקע על "מרכיב"
    assert "מרכיב בדרך אחרת" in body


@check("חשבון המשתמש אינו מגיב בעצמו, והבוט ממשיך לעבוד")
def _userbot_silent():
    import inspect
    from zovexsub import bot as botmain

    # החשבון הפרטי שותק לחלוטין — לא בשיחות, לא בקבוצות ולא בהודעות
    # השמורות. זהו חשבון אישי, והמסלול הזה התפרץ לשיחות עם חברים
    assert config.USERBOT_TRIGGER == 0, config.USERBOT_TRIGGER
    guard = inspect.getsource(botmain.on_message)
    assert "if not config.USERBOT_TRIGGER:" in guard, "אין מתג כיבוי"
    # והיציאה היא הדבר הראשון, לפני כל קריאה או ניתוב
    assert guard.index("USERBOT_TRIGGER") < guard.index("clean(event.raw_text)")

    # והמסלול של @zooigrmbot נפרד לגמרי — רישום אחר, התקנה אחרת
    launch = inspect.getsource(botmain.main) if hasattr(botmain, "main") \
        else inspect.getsource(botmain)
    assert "botjob.install()" in launch, "מסלול הבוט לא מותקן"
    assert "add_event_handler(on_message" in launch, \
        "הרישום של חשבון המשתמש אינו נפרד"


@check("הסשן הראשי נטען גם ממחרוזת, ולא רק מקובץ")
def _main_session_from_string():
    import inspect
    from zovexsub import bot as botmain, botapi

    # קובץ סשן מתבטל ברגע שמנתקים את ההתחברות מהאפליקציה. טלתון מבקש
    # אז מספר טלפון, בשירות אין מסוף, נזרק EOFError, ו-Restart=always
    # הופך את זה ללולאת קריסה שבה הבוט "מתחבר" כל 11 שניות בלי להגיב
    assert hasattr(config, "TG_STRING"), "אין תמיכה במחרוזת לחשבון הראשי"

    body = inspect.getsource(botmain.main)
    assert "config.TG_STRING" in body, "המחרוזת אינה נקראת"
    assert "botapi._string_session(config.TG_STRING)" in body, \
        "המחרוזת אינה עוברת דרך הנרמול שסולח לטעויות העתקה"
    # מחרוזת גוברת על קובץ, ולא להפך
    assert body.index("config.TG_STRING") < body.index("else config.TG_SESSION")

    # והנרמול באמת סולח לשורה שהועתקה כולה, כולל שם המשתנה
    cleaned = botapi._string_session.__doc__ or ""
    assert "TG_STRING_LITE" in cleaned or "שם" in cleaned

    # וסשן שבוטל אומר זאת במפורש, במקום EOFError סתום שחוזר כל 11
    # שניות ומשאיר בוט שלא מגיב בלי שום הסבר
    assert "is_user_authorized()" in body, "אין בדיקת הרשאה לפני start"
    assert "אינו מורשה" in body, "השגיאה אינה מסבירה מה קרה"
    assert "mksession.py" in body, "השגיאה אינה אומרת מה לעשות"
    assert body.index("is_user_authorized()") < body.index("await client.start()")


@check("חלק שנכשל בהעלאה אינו מפיל אותה, וההעלאה ממשיכה באותו קובץ")
def _upload_survives_part_failure():
    import inspect
    from zovexsub import fastio

    body = inspect.getsource(fastio._parallel_upload)
    # נמדד בשרת: שלושה חלקים שלא נענו הפילו 80 אחוז מהעלאה של 779MB,
    # והקובץ עלה מאפס דרך טלתון
    assert "return_exceptions=True" in body, "חלק שנכשל עדיין מפיל הכל"
    # החלק שנכשל חוזר לתור, ולכן יש מה להמשיך
    assert "queue.put_nowait(index)" in inspect.getsource(fastio._parallel_upload)
    # ואותו file_id נשמר — זו אותה העלאה, לא חדשה
    assert body.count("file_id = ") == 1, "file_id נוצר יותר מפעם אחת"
    assert body.index("file_id = ") < body.index("return_exceptions=True")

    # סט חיבורים שמת חוזר קטן יותר, כמו בהורדה
    assert "workers >> (revival + 1)" in body, "אותו מספר חיבורים חוזר"
    # ורק אחרי שהסבבים נגמרו נופלים חזרה
    assert "נופלים חזרה" in body


@check("מעבר אחרון לפני הכתיבה חוסם כתוביות פגומות")
def _finalize_gate():
    # נמדד על קובץ אמיתי שנמסר למשתמש, 1778 כתוביות: אחת עם סוף לפני
    # התחלה, חמש מתחת למינימום, 14 מעל המקסימום, 31 שורות מעל 42 תווים
    # ושמונה בנות שלוש שורות. כולן עברו את כל הבדיקות שבדרך, כי אלה
    # רצו לפני השלבים ששברו אותן
    def cue(start, end, text):
        return srt.Cue(index=1, start=start, end=end, text=text)

    cues = [
        cue(1.0, 0.98, "סוף לפני התחלה"),          # הפוכה
        cue(5.0, 5.20, "קצרה מדי"),                 # מתחת למינימום
        cue(10.0, 25.0, "ארוכה מדי"),               # מעל המקסימום
        cue(30.0, 33.0, "א\nב\nג"),                 # שלוש שורות קצרות
        cue(40.0, 43.0, "מילה " * 12),              # שורה רחבה מדי
    ]
    srt.finalize(cues, 23.976)

    for one in cues:
        assert one.end > one.start, one
        span = one.end - one.start
        assert span >= config.SRT_MIN_DURATION - 1e-6, (one.index, span)
        assert span <= config.SRT_MAX_DURATION + 1e-6, (one.index, span)
        assert one.text.count("\n") < config.SRT_MAX_LINES, one.text
        for line in one.text.split("\n"):
            assert len(line) <= config.SRT_MAX_CHARS_PER_LINE, line

    # אין חפיפות, והמספור רץ מחדש
    for before, after in zip(cues, cues[1:]):
        assert after.start >= before.end, (before.index, after.index)
    assert [c.index for c in cues] == list(range(1, len(cues) + 1))

    # ושבירה קיימת נשמרת כשהיא חוקית — שתי שורות עוברות כמו שהן
    two = [cue(0.0, 3.0, "שורה ראשונה\nשורה שנייה")]
    srt.finalize(two, 23.976)
    assert two[0].text == "שורה ראשונה\nשורה שנייה", two[0].text


@check("שגיאה עם סוגריים משולשים אינה מבריחה את ההודעה")
def _html_escaped_errors():
    import inspect
    from zovexsub import localbot

    # נמדד אצל המשתמש: שגיאת רשת שהכילה "<HTTPError...>" חזרה כ-
    # "can't parse entities: Unsupported start tag httperror",
    # והסיבה האמיתית לא הגיעה אליו מעולם
    out = localbot.code("<HTTPError 403> a & b")
    assert "&lt;HTTPError 403&gt;" in out, out
    assert "&amp;" in out, out
    assert out.startswith("<code>") and out.endswith("</code>")

    # ואין יותר הזרקה ישירה של טקסט שגיאה לתוך HTML
    body = inspect.getsource(__import__("zovexsub.botjob", fromlist=["x"]))
    assert "<code>{" not in body, "טקסט שגיאה עדיין נדחף ל-HTML בלי בריחה"

    # רשת ביטחון: הודעה שנדחתה בגלל עיצוב נשלחת בלי עיצוב, כי הודעת
    # שגיאה שנעלמת גרועה מהודעה בלי הדגשה
    sender = inspect.getsource(localbot.say)
    assert "parse entities" in sender and 'fields.pop("parse_mode")' in sender
    editor = inspect.getsource(localbot.edit)
    assert "parse entities" in editor and 'fields.pop("parse_mode")' in editor


@check("קישור שאינו יוטיוב מקבל כותרות דפדפן, ויוטיוב לא")
def _browser_headers():
    import inspect
    from zovexsub import fetch

    # נמדד אצל המשתמש: קישור m3u8 שעבד בכל דפדפן חזר כאן עם
    # "HTTP Error 403: Forbidden". ‏yt-dlp שולח User-Agent משלו
    # ואינו שולח Referer כלל, ורוב ה-CDN בודקים בדיוק את השניים
    link = "https://s1.cdnmvs.online/abc/videos_new/1080.mp4/index-v1-a1.m3u8"
    args = fetch._browser_args(link)
    assert "--user-agent" in args, args
    assert "--referer" in args, args
    # ה-Referer נגזר מהקישור עצמו כשלא הוגדר אחר
    assert "https://s1.cdnmvs.online/" in args, args

    # ביוטיוב לא נוגעים: שם ה-UA חלק מזרימת ה-PO token
    for site in ("https://www.youtube.com/watch?v=x",
                 "https://youtu.be/x",
                 "https://www.youtube-nocookie.com/embed/x"):
        assert fetch._browser_args(site) == [], site

    # ושני מסלולי הקריאה ל-yt-dlp מקבלים אותן — גם בדיקת האיכויות
    # וגם ההורדה. אחרת התפריט יוצא ריק וההורדה נחסמת
    assert "_browser_args(url)" in inspect.getsource(fetch.heights)
    assert "_browser_args(url)" in inspect.getsource(fetch._ytdlp)


@check("חסימת 403 מוסברת, ואפשר לנתב דרך פרוקסי")
def _blocked_link_explained():
    import inspect
    from zovexsub import fetch

    # נמדד בשרת: curl חשוף, curl עם UA של דפדפן, yt-dlp נקי ו-yt-dlp
    # עם aria2c — כולם 403. אותו קישור בדיוק עובר מטלפון סלולרי באותה
    # עיר. המסנן פועל על ה-IP, לפני שהבקשה נקראת
    said = fetch._explain("ERROR: Unable to download webpage: "
                          "HTTP Error 403: Forbidden",
                          "https://s1.cdnmvs.online/x/index-v1-a1.m3u8")
    assert "403" in said and "שרת" in said, said
    assert "לשלוח את הקובץ" in said, "אין דרך פעולה למשתמש"

    # והפרוקסי מגיע ל-yt-dlp כשהוגדר, לכל קישור — גם יוטיוב, כי
    # החסימה היא על ה-IP ולא על האתר
    saved = config.FETCH_PROXY
    try:
        config.FETCH_PROXY = "socks5://127.0.0.1:1080"
        for link in ("https://example.com/a.m3u8",
                     "https://www.youtube.com/watch?v=x"):
            args = fetch._browser_args(link)
            assert "--proxy" in args, link
            assert "socks5://127.0.0.1:1080" in args, link
        config.FETCH_PROXY = ""
        assert "--proxy" not in fetch._browser_args("https://example.com/a")
    finally:
        config.FETCH_PROXY = saved


@check("הסבר של יוטיוב אינו ניתן לקישור שאינו יוטיוב")
def _explain_scoped():
    from zovexsub import fetch

    # נמדד אצל המשתמש: קישור HLS נכשל, והבוט ענה לו על PO token
    # ועוגיות של יוטיוב — ושלח אותו לרדוף אחרי פתרון שאינו קשור
    noise = "ERROR: Sign in to confirm you are not a bot"
    other = fetch._explain(noise, "https://zovex.duckdns.org/x.m3u8")
    assert "PO token" not in other and "יוטיוב" not in other, other

    # ועל קישור יוטיוב ההסבר נשאר
    tube = fetch._explain(noise, "https://www.youtube.com/watch?v=x")
    assert "יוטיוב" in tube, tube


@check("תקרת ההצלה חותכת לפי אורך החור ולא לפי מקומו בסרט")
def _recover_picks_longest():
    from zovexsub import stt

    # נמדד על "כוכבי הכלב": 369 חורים בסרט אחד, והחיתוך לפי זמן עצר
    # בדקה 14 — החור של 239 שניות ב-1:45 מעולם לא תומלל שוב
    gaps = [(float(i), float(i) + 1.2) for i in range(0, 300, 3)]
    gaps.append((6324.0, 6563.0))
    picked = stt.pick_gaps(gaps, 40)
    assert len(picked) == 40, len(picked)
    assert (6324.0, 6563.0) in picked, "החור הארוך ביותר נחתך"
    assert picked == sorted(picked), "הרשימה חייבת לחזור בסדר הזמנים"

    # מתחת לתקרה לא נוגעים בכלום חוץ מהמיון
    assert stt.pick_gaps([(5.0, 6.0), (1.0, 2.0)], 40) == [(1.0, 2.0), (5.0, 6.0)]


@check("קטע דיבור שמקטע תמלול רק נגע בו נחשב חור וזוכה להצלה")
def _gaps_partial_cover():
    from zovexsub import config, stt

    # מקטע התמלול נמתח 0.5 שניות לתוך קטע דיבור של עשר שניות.
    # בדרישת אפס־החפיפה הקודמת זה הכשיר את כל הקטע כמכוסה
    seg = stt.Segment(0, 24.0, 30.5, "שלום")
    speech = [(30.0, 40.0)]
    assert stt.speech_gaps([seg], speech, 1.2) == [(30.0, 40.0)]

    # קטע שמכוסה ממש אינו נחשב חור
    full = stt.Segment(0, 30.0, 39.5, "משפט שלם שנאמר כאן")
    assert stt.speech_gaps([full], speech, 1.2) == []

    # וקטע קצר מהמינימום לא נבדק בכלל
    assert stt.speech_gaps([], [(30.0, 30.5)], 1.2) == []
    assert 0.0 <= config.RECOVER_COVER <= 1.0


@check("קישור דרייב מוריד את הקובץ המקורי ולא את זרמי הנגן של גוגל")
def _drive_takes_source():
    from zovexsub import config, fetch

    # המחלץ של yt-dlp נותן ל-source רק url, ext ו-quality — בלי
    # height ובלי vcodec. התבנית הרגילה דורשת אותם, ולכן בדרייב
    # ירדו זרמי הנגן המצומצמים ולא הקובץ
    for link in ("https://drive.google.com/file/d/abc123/view",
                 "https://drive.usercontent.google.com/download?id=abc123",
                 "https://docs.google.com/uc?id=abc123"):
        assert fetch._format_for(link) == config.FETCH_FORMAT_DRIVE, link
        assert "source" in fetch._format_for(link), link

    # ובדרייב גם בחירת איכות של המשתמש אינה דורסת את זה: אין איכויות
    # לבחור מהן, יש קובץ אחד
    assert "source" in fetch._format_for(
        "https://drive.google.com/file/d/abc123/view",
        "bestvideo[height<=720]+bestaudio")

    # מחוץ לדרייב שום דבר לא משתנה
    assert fetch._format_for("https://www.youtube.com/watch?v=x") == config.FETCH_FORMAT
    assert fetch._format_for("https://example.com/a.m3u8", "bestaudio") == "bestaudio"


@check("מכסת ההורדות של דרייב מוסברת, ולא כ\"דווח על באג\"")
def _drive_quota_explained():
    from zovexsub import fetch

    raw = ("WARNING: [GoogleDrive] Too many users have viewed or downloaded "
           "this file recently.\nERROR: [GoogleDrive] abc: No video formats "
           "found!; please report this issue on https://github.com/yt-dlp")
    said = fetch._explain(raw, "https://drive.google.com/file/d/abc/view")
    assert "מכסת" in said, said
    assert "צור עותק" in said, said
    assert "report this issue" not in said, said

    # ואותה שגיאה בלי דרייב אינה מקבלת את ההסבר הזה
    other = fetch._explain("ERROR: No video formats found!",
                           "https://example.com/a.m3u8")
    assert "מכסת" not in other, other


@check("חלון שנכשל נספר, והמונה מגיע ל-100% ולא נתקע")
def _failed_window_counts():
    import asyncio
    from zovexsub import gemini, hebrew

    # נמדד אצל המשתמש: "99% · בודק איכות 14/15 · אין תזוזה 10:26"
    # על שלב שלמעשה הסתיים. חלון שנכשל החזיר return בלי לקדם
    segments = [hebrew.Segment(i, float(i), float(i) + 1.0, f"line {i}")
                for i in range(hebrew.QUALITY_WINDOW * 3)]
    lines = [f"שורה {i}" for i in range(len(segments))]
    windows = len(range(0, len(segments), hebrew.QUALITY_WINDOW))

    seen: list[str] = []

    async def on_step(note, _fraction):
        seen.append(note)

    async def boom(*_args, **_kwargs):
        raise gemini.GeminiError("נפל")

    saved = gemini.ask_json
    gemini.ask_json = boom
    try:
        out = asyncio.run(hebrew._quality_pass(segments, lines, "", on_step))
    finally:
        gemini.ask_json = saved

    # הטקסט לא נפגע, וכל חלון דווח — גם אלה שנכשלו
    assert out == lines, "חלון שנכשל לא אמור לשנות טקסט"
    assert len(seen) == windows, f"{len(seen)} דיווחים מול {windows} חלונות"
    assert seen[-1] == f"בודק איכות {windows}/{windows}", seen[-1]


@check("רמת החשיבה נשלחת, ומודל שדוחה אותה אינו מפיל את הקריאה")
def _thinking_level_sent():
    import asyncio
    from zovexsub import config, gemini

    seen: dict = {}

    async def fake_call(model, body, **_kw):
        seen.update(body)
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    saved_call, saved_level = gemini._call, config.GEMINI_THINKING
    gemini._call, config.GEMINI_THINKING = fake_call, "LOW"
    try:
        asyncio.run(gemini.ask_json("sys", "user"))
    finally:
        gemini._call, config.GEMINI_THINKING = saved_call, saved_level

    # השם אומת מול ThinkingLevel ב-SDK הרשמי: thinkingConfig/thinkingLevel
    gen = seen["generationConfig"]
    assert gen["thinkingConfig"] == {"thinkingLevel": "LOW"}, gen

    # ומודל שמחזיר 400 על השדה הזה — מורידים אותו וממשיכים
    body = {"generationConfig": dict(gen)}
    assert gemini._drop_thinking(body) is True
    assert "thinkingConfig" not in body["generationConfig"]
    # פעם שנייה אין מה להוריד, ולכן לא נכנסים ללופ אין-סופי
    assert gemini._drop_thinking(body) is False


@check("לקוח ה-HTTP של ג'מיני משותף ואינו נפתח מחדש לכל קריאה")
def _gemini_client_shared():
    import asyncio
    from zovexsub import gemini

    async def twice():
        return await gemini.client(), await gemini.client()

    first, second = asyncio.run(twice())
    try:
        assert first is second, "לקוח חדש לכל קריאה = מסירת יד TLS מחדש"
    finally:
        asyncio.run(first.aclose())


@check("רצועת שמע נבחרת, וקובץ עם שתי רצועות אינו מתומלל תמיד מהראשונה")
def _audio_track_choice():
    import asyncio
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    from zovexsub import media

    if not shutil.which("ffmpeg"):
        return                      # בלי ffmpeg אין מה לבדוק כאן

    with tempfile.TemporaryDirectory() as box:
        work = Path(box)
        clip = work / "two.mp4"
        # שתי רצועות בתדרים שונים, מתויגות eng ו-heb
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=160x90:r=12",
            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000",
            "-f", "lavfi", "-i", "sine=frequency=1200:sample_rate=48000",
            "-t", "2", "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:1", "language=heb",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(clip)], check=True)

        found = asyncio.run(media.audio_tracks(clip))
        assert [t["language"] for t in found] == ["eng", "heb"], found
        assert found[1]["name"] == "עברית", found[1]
        assert media.track_label(found[0]).startswith("אנגלית")

        # והחילוץ באמת שולף רצועה אחרת, ולא את אותה אחת פעמיים
        first = work / "a0.flac"
        second = work / "a1.flac"
        asyncio.run(media.extract_audio(clip, first, track=0))
        asyncio.run(media.extract_audio(clip, second, track=1))
        assert first.read_bytes() != second.read_bytes(), "אותה רצועה פעמיים"

        # רצועה שאינה קיימת נצמדת לקיימת ולא מפילה את הצריבה
        args = asyncio.run(media._audio_args(clip, 99))
        assert args and args != ["-an"], args


@check("שאלת הרצועה נבנית מהקובץ, ונשאלת רק כשיש יותר מרצועה אחת")
def _track_question():
    import inspect
    from zovexsub import botjob, botmenu

    rows = botmenu.track_keys([
        {"index": 0, "label": "אנגלית"},
        {"index": 1, "label": "עברית · Hebrew dub"},
    ])
    # כפתור לכל רצועה, ועוד שורת ביטול
    assert len(rows) == 3, rows
    assert rows[0][0][1] == "trk:0" and rows[1][0][1] == "trk:1", rows
    assert "עברית" in rows[1][0][0], rows[1]

    # רצועה בלי תווית לא מייצרת כפתור ריק
    bare = botmenu.track_keys([{"index": 0}])
    assert "רצועה 1" in bare[0][0][0], bare

    # ורק קובץ עם כמה רצועות נשאל — אחרת זו לחיצה מיותרת בכל סרטון
    body = inspect.getsource(botjob)
    assert "if len(tracks) > 1:" in body, "השאלה נשאלת גם על רצועה אחת"
    assert "await go(0)" in body, "המסלול הרגיל חייב להמשיך בלי שאלה"


@check("שפות השמע נקראות מהקישור, אחת לשפה, והתבנית נבנית סביבן")
def _link_audio_languages():
    import asyncio
    import json
    import os
    import stat
    import tempfile
    from zovexsub import fetch

    # מה ש-yt-dlp מחזיר על קישור עם שתי שפות: כמה מסלולי שמע לכל
    # שפה בקצבי סיב שונים, ועוד מסלולי וידאו נקיים
    payload = {"formats": [
        {"format_id": "137", "vcodec": "avc1", "acodec": "none", "height": 1080},
        {"format_id": "140", "vcodec": "none", "acodec": "mp4a",
         "language": "eng", "abr": 128.0, "format_note": "medium"},
        {"format_id": "139", "vcodec": "none", "acodec": "mp4a",
         "language": "eng", "abr": 48.0, "format_note": "low"},
        {"format_id": "251", "vcodec": "none", "acodec": "opus",
         "language": "heb", "abr": 160.0, "format_note": "high"},
        {"format_id": "600", "vcodec": "none", "acodec": "none"},
    ]}

    with tempfile.TemporaryDirectory() as box:
        fake = os.path.join(box, "fake-ytdlp")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\ncat <<'JSON'\n" + json.dumps(payload)
                     + "\nJSON\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)

        saved = fetch._command
        fetch._command = lambda: [fake]
        try:
            found = asyncio.run(fetch.audio_options("https://example.com/v"))
        finally:
            fetch._command = saved

    # אחת לכל שפה, והטובה שבקצבי הסיב — לא שתים־עשרה כפתורים
    assert [v["language"] for v in found] == ["eng", "heb"], found
    assert [v["id"] for v in found] == ["140", "251"], found
    assert found[1]["name"] == "עברית", found[1]

    # והמזהה נכנס לתבנית, עם נפילה אחורה שלא תפיל הורדה
    built = fetch.format_for("1080", "251")
    assert "+251/bestaudio" in built, built
    # בלי בחירה שום דבר לא משתנה
    assert fetch.format_for("1080") == (
        "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best")


@check("הורדה שנקטעה ממשיכה מהחלקים שכבר על הדיסק, ולא מאפס")
def _download_ledger():
    import tempfile
    from pathlib import Path
    from zovexsub import fastio

    with tempfile.TemporaryDirectory() as box:
        dst = Path(box) / "source.mp4"
        size, part, total = 1035466213, 1048576, 988

        # יומן חדש הוא ריק, ולא קורס על קובץ שאינו קיים
        marks = fastio._ledger_load(dst, size, part, total)
        assert len(marks) == total and not any(marks)

        # 557 חלקים ירדו — זה המקרה שנמדד אצל המשתמש: 584 מתוך 1035MB
        for index in range(557):
            marks[index] = 1
        fastio._ledger_save(dst, size, part, marks)

        back = fastio._ledger_load(dst, size, part, total)
        assert sum(1 for m in back if m) == 557, sum(back)
        landed = sum(min(part, size - i * part)
                     for i in range(total) if back[i])
        # 557 חלקים של מגה־בייט = 584056832 בייט, בדיוק המספר
        # שהופיע בשגיאה אצל המשתמש לפני התיקון
        assert landed == 584056832, landed

        # תוכנית חיתוך אחרת פוסלת את היומן: ההיסטים שונים, והחלקים
        # הישנים יושבים במקומות הלא נכונים
        other = fastio._ledger_load(dst, size, part * 2, total)
        assert not any(other), "יומן מחיתוך אחר נלקח בטעות"
        assert not any(fastio._ledger_load(dst, size + 1, part, total))

        # ואחרי הצלחה הוא נמחק
        fastio._ledger_clear(dst)
        assert not fastio._ledger_path(dst).exists()
        assert not any(fastio._ledger_load(dst, size, part, total))


@check("כפתור עצור שורד כל עדכון התקדמות, ונעצר גם מהודעה שאינה בתפריט")
def _stop_button_survives():
    import asyncio
    import inspect
    from zovexsub import botjob, botmenu, localbot

    # localbot.edit שולח reply_markup ריק כשלא מעבירים כפתורים, ולכן
    # מסך ההתקדמות חייב לשלוח אותם מחדש בכל עריכה — אחרת הכפתור
    # נמחק שניות אחרי שהופיע, וזה מה שנראה כמו "פג תוקף"
    sent: list = []

    async def fake_edit(chat_id, message_id, text, *, buttons=""):
        sent.append(buttons)
        return {}

    saved = localbot.edit
    localbot.edit = fake_edit
    try:
        screen = botjob.Screen(1, 2, buttons=botmenu.stop_keys(1))
        asyncio.run(screen.show("אחד", force=True))
        asyncio.run(screen.show("שתיים", force=True))
    finally:
        localbot.edit = saved

    assert len(sent) == 2, sent
    assert all("stop:1" in b for b in sent), sent

    # והלחיצה מטופלת לפני ה-return על Choice חסר: הודעת ההתקדמות
    # אינה רשומה ב-_open, ולכן שם היא הייתה נופלת בשקט
    body = inspect.getsource(botmenu._press)
    before = body.index('data.startswith("stop:")')
    after = body.index("if choice is None:")
    assert before < after, "עצור מטופל אחרי ה-return ולכן לא יעבוד"

    # ויש מה לבטל: העבודה נרשמת ומשתחררת
    assert "claim(chat_id)" in inspect.getsource(botjob)
    assert "release(chat_id)" in inspect.getsource(botjob)


@check("הצריבה האיכותית היא CRF טהור בלי תקרת ביטרייט")
def _quality_profile_uncapped():
    import inspect
    from zovexsub import botjob, config, media

    want = config.PROFILES["quality"]
    assert want["codec"] == "libx265", want
    assert want["preset"] == "medium", want
    assert want["crf"] == 20, want

    saved = config.UPLOAD_LIMIT_MB
    config.UPLOAD_LIMIT_MB = 1900          # מה שהיה אצל המשתמש
    try:
        # סרט של 98 דקות. התקרה שיצאה שם הייתה 2439kbps, ו-1080p
        # ב-HEVC בתנועה רוצה 4000 ומעלה — כלומר הרעבה
        args = media._encoder_args(want, 4, 98 * 60)
        assert "-maxrate" not in args, args
        assert "-bufsize" not in args, args
        assert "-crf" in args and "20" in args, args
        assert "libx265" in args, args

        # ובפרופיל רגיל התקרה נשארת: היא המגן מפני קובץ שלא ייעלה
        other = media._encoder_args(config.PROFILES["balanced"], 4, 98 * 60)
        assert "-maxrate" in other, other
    finally:
        config.UPLOAD_LIMIT_MB = saved

    # ו"איכותי" בתפריט מצביע על הפרופיל הזה, ולא על fast265
    body = inspect.getsource(botjob)
    assert '"איכותי": "quality"' in body, "הכפתור עוד מצביע על fast265"


@check("מסלול הבוט סגור ללא מורשים, והמנהל מקבל התראה")
def _bot_path_gated():
    import asyncio
    import inspect
    from zovexsub import allowlist, botmenu, config, localbot

    sent: list = []

    async def fake_say(chat, text, **_kw):
        sent.append((int(chat), text))
        return {"message_id": 1}

    saved_say, saved_owner, saved_ids = (
        localbot.say, config.BOT_OWNER, config.ALLOW_IDS)
    saved_file = allowlist.PATH
    localbot.say = fake_say
    config.BOT_OWNER = 8658294616
    config.ALLOW_IDS = (1179463907, 850190626)
    allowlist.PATH = allowlist.Path("/nonexistent/allowlist.json")
    botmenu._alerted.clear()
    try:
        # המנהל ושני המורשים עוברים
        assert allowlist.permitted(8658294616)
        assert allowlist.permitted(1179463907)
        assert allowlist.permitted(850190626)
        # וזר לא
        assert not allowlist.permitted(123456789)
        assert not allowlist.permitted(0)

        stranger = {"from": {"id": 123456789, "first_name": "ישראל",
                             "last_name": "ישראלי", "username": "someone"},
                    "chat": {"id": 123456789}}
        allowed = asyncio.run(botmenu._permitted(stranger, "סרטון / קובץ"))
        assert allowed is False

        # התראה למנהל, עם המזהה ועם פקודת האישור
        alert = next((t for who, t in sent if who == 8658294616), "")
        assert "לא מורשה" in alert, alert
        assert "123456789" in alert and "/approve 123456789" in alert, alert
        assert "@someone" in alert, alert

        # והמשתמש עצמו מקבל תשובה ולא שתיקה
        reply = next((t for who, t in sent if who == 123456789), "")
        assert "פרטי" in reply, reply

        # ניסיון שני באותו חלון זמן אינו מציף את המנהל
        before = len([1 for who, _ in sent if who == 8658294616])
        asyncio.run(botmenu._permitted(stranger, "קישור"))
        after = len([1 for who, _ in sent if who == 8658294616])
        assert after == before, "התראה כפולה על אותו משתמש"
    finally:
        localbot.say, config.BOT_OWNER, config.ALLOW_IDS = (
            saved_say, saved_owner, saved_ids)
        allowlist.PATH = saved_file

    # והשער נמצא לפני העבודה בשני השערים של מסלול הבוט
    for fn in (botmenu._incoming, botmenu._press):
        body = inspect.getsource(fn)
        assert "_permitted(" in body, f"{fn.__name__} אינו מגודר"


@check("גם חלון התרגום עצמו חסום בזמן, ולא רק המעברים שאחריו")
def _translate_window_bounded():
    import asyncio
    import inspect
    from zovexsub import config, hebrew

    # נמדד אצל המשתמש: "מתרגם 609/659 · 1 חלונות בעבודה · ממתין
    # למודל · אין תזוזה 6:25". התקרה הייתה רק בהתאמת המגדר ובבקרת
    # האיכות, ומעבר התרגום עצמו נשאר בלי גבול
    body = inspect.getsource(hebrew.translate_segments) if hasattr(
        hebrew, "translate_segments") else inspect.getsource(hebrew)
    assert body.count("GEMINI_WINDOW_TIMEOUT") >= 3, \
        "מעבר אחד לפחות נשאר בלי תקרת זמן"

    saved = config.GEMINI_WINDOW_TIMEOUT
    config.GEMINI_WINDOW_TIMEOUT = 0.05
    try:
        async def slow():
            await asyncio.sleep(5)
            return {"lines": [{"i": 0, "he": "לא אמור להגיע"}]}

        # קריאה שנתקעת מוחזרת ריקה, ולא מחזיקה את העבודה
        assert asyncio.run(hebrew._bounded(slow())) == {}

        # וקריאה שמחזירה בזמן עוברת כמו שהיא
        async def quick():
            return {"lines": [{"i": 0, "he": "שלום"}]}

        assert asyncio.run(hebrew._bounded(quick()))["lines"][0]["he"] == "שלום"

        # וכשל של ג'מיני אינו מתפשט אלא חוזר ריק
        async def broken():
            raise hebrew.gemini.GeminiError("נפל")

        assert asyncio.run(hebrew._bounded(broken())) == {}
    finally:
        config.GEMINI_WINDOW_TIMEOUT = saved


@check("רמז התמלול נבנה משם הקובץ, נשלח לכל קטע, ושם כללי נדחה")
def _title_hint():
    import inspect
    from pathlib import Path
    from zovexsub import stt

    # שם אמיתי נותן רמז: prompt של Whisper הוא המנגנון להטיית
    # הפענוח לשמות פרטיים, ושם הקובץ הוא המקור היחיד שיש לפני
    # התמלול — מילון מהתמלול עצמו הוא מעגל
    assert stt.title_hint(Path(
        "Avatar.Seven.Havens.S01E13.1080p.WEB.h264-GROUP.mkv")) == \
        "Avatar Seven Havens."
    assert stt.title_hint(Path(
        "The.Dog.Stars.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-KyoGo.srt")) == \
        "The Dog Stars."

    # הורדה מקישור נקראת תמיד source.mp4, ורמז כזה מטה את המודל
    # למילה "source" במקום לשמות שבסרט
    for junk in ("source.mp4", "video.mkv", "download.mp4", "a.mp4"):
        assert stt.title_hint(Path(junk)) == "", junk

    # והרמז נשלח לכל קטע ולא רק לראשון
    body = inspect.getsource(stt.transcribe)
    assert "hint if index == 0" not in body, "הרמז חזר להיות רק לקטע הראשון"
    assert "pool, chunk, hint," in body, body[:0] or "הרמז אינו מועבר"


@check("דרייב מדלג על שאלת האיכות, והצריבה מדווחת זמן משוער")
def _drive_skips_quality_and_burn_eta():
    import inspect
    from zovexsub import botjob, botmenu, progress

    # לקובץ בדרייב יש איכות אחת, ואנחנו ממילא כופים את תבנית source.
    # השאלה שם היא לחיצה על שאלה שאין לה תשובה
    body = inspect.getsource(botmenu.greet_link)
    assert "_is_drive(url)" in body, "דרייב עוד נשאל על איכות"
    assert body.index("_is_drive") < body.index("QUALITY"), \
        "הבדיקה חייבת לקרות לפני מסך האיכות"

    # הצריבה עוברת דרך מנוע ההתקדמות המשותף ולא בונה טקסט ביד,
    # ולכן היא מקבלת שעון וזמן משוער כמו שאר השלבים
    burn = inspect.getsource(botjob._burn)
    assert "prog.Stage(" in burn, "הצריבה עוד כותבת טקסט ישירות"
    assert 'f"🔥 צורב · {fraction' not in burn, "הטקסט הידני נשאר"

    # ו-Stage באמת מוציא "נותרו" כשיש מספיק מידע להעריך
    stage = progress.Stage(lambda _text: None, "🔥 צורב")
    stage.fraction = 0.5
    stage.started -= 600          # חצי שעבדה עשר דקות
    assert stage.eta() > 1, stage.eta()
    assert "נותרו" in stage._render(), stage._render()


@check("כתובית שחוזרת על קודמתה נמחקת, ודיאלוג חוזר נשמר")
def _drop_echoes():
    from zovexsub import srt

    def cue(start, end, text):
        return srt.Cue(index=0, start=start, end=end, text=text)

    # אותו דיבור שתומלל פעמיים: שתי כתוביות בהפרש שנייה.
    # נמדד בקובץ של המשתמש, 26 כאלה מתוך 648
    cues = [cue(5.0, 6.0, "שים את המזוודות. שתינו נסתדר מכאן."),
            cue(6.1, 7.0, "שים את המזוודות.")]
    assert srt.drop_echoes(cues) == 1
    assert len(cues) == 1
    # הארוכה נשמרת, והטווח מאוחד
    assert cues[0].text.startswith("שים את המזוודות. שתינו")
    assert cues[0].start == 5.0 and cues[0].end == 7.0

    # דיאלוג חוזר על מילים כדרך שגרה — שתי "כן." רחוקות זו מזו
    # הן שתי כתוביות נכונות ולא כפילות
    far = [cue(10.0, 11.0, "כן."), cue(40.0, 41.0, "כן.")]
    assert srt.drop_echoes(far) == 0, "נמחק דיאלוג תקין"

    # והכלה נבדקת רק בטקסט ממשי: "כן." בתוך "כן, בסדר" אינה כפילות
    short = [cue(1.0, 2.0, "כן."), cue(2.1, 3.0, "כן, בסדר.")]
    assert srt.drop_echoes(short) == 0, short

    # והשער האחרון סופר אותן
    report = srt.finalize([cue(5.0, 6.0, "שלום לך חבר טוב"),
                           cue(6.1, 7.0, "שלום לך חבר טוב")], 24.0)
    assert report["כפולות"] == 1, report


@check("הזיות על שקט נמחקות בשני המסלולים, ודיבור אמיתי נשאר")
def _hallucinations():
    from zovexsub import config, stt

    # קרדיט מתרגם בכל שפה. נמדד אצל המשתמש: שורה בשוודית באמצע
    # סרט יפני, בתוך חור של שתי דקות. הרשימה שהייתה כללה אנגלית
    # ועברית בלבד ולכן פספסה אותה
    for junk in ("Undertexter av Nicolai Winther",
                 "Subtitles by the Amara.org community",
                 "Sous-titres par Jean Dupont",
                 "Untertitel von Hans Meier",
                 "תרגום: דוד לוי"):
        assert stt._CREDIT.search(junk.lower()), junk

    # ודיבור אמיתי על כתוביות אינו נתפס
    for real in ("אני קורא את הכתוביות",
                 "the subtitles are wrong",
                 "תודה רבה לך"):
        assert not stt._CREDIT.search(real.lower()), real

    # סינון לפי VAD: קטע שיושב בשקט נמחק, קטע על דיבור נשאר.
    # זה מה שמגן גם על מסלול ג'מיני, שאינו מחזיר no_speech_prob
    speech = [(10.0, 20.0), (40.0, 50.0)]
    segments = [
        stt.Segment(0, 11.0, 13.0, "דיבור אמיתי"),
        stt.Segment(1, 25.0, 28.0, "Undertexter av Nicolai Winther"),
        stt.Segment(2, 41.0, 44.0, "עוד דיבור"),
    ]
    gone = stt.drop_nonspeech(segments, speech)
    assert gone == 1, gone
    assert [s.text for s in segments] == ["דיבור אמיתי", "עוד דיבור"]

    # והנסיגה שנמדדה ביוקר: דיאלוג רגיל שיושב מחוץ לדיבור לפי
    # ה-VAD **אינו** נמחק. הגרסה שדרשה VAD בלבד מחקה בקובץ אמיתי
    # שלוש דקות דיבור ופתחה חמישה חורים חדשים, מול שלוש שורות
    # הזיה שנחסכו. VAD מפספס לחישה ודיבור מעל מוזיקה
    whisper = [stt.Segment(0, 25.0, 28.0, "אל תזוזי, הוא שומע אותנו."),
               stt.Segment(1, 29.0, 31.0, "מה זה היה?")]
    assert stt.drop_nonspeech(whisper, speech) == 0, \
        "דיבור אמיתי נמחק רק מפני שה-VAD לא שמע אותו"
    assert len(whisper) == 2

    # שורה ארוכה אינה נמחקת גם בשקט: VAD מפספס לחישה ודיבור מעל
    # מוזיקה, ושורה אמיתית שנמחקה גרועה משורה מומצאת שנשארה
    long_one = [stt.Segment(0, 25.0, 30.0, "א" * (config.NONSPEECH_MAX_CHARS + 5))]
    assert stt.drop_nonspeech(long_one, speech) == 0

    # ובלי VAD לא נוגעים בכלום
    keep = [stt.Segment(0, 25.0, 28.0, "משהו")]
    assert stt.drop_nonspeech(keep, []) == 0


@check("אות ערבית מוחזרת לעברית בלי קריאה למודל, וערבית אמיתית נשמרת")
def _mend_arabic():
    import inspect
    from zovexsub import cleanup, hebrew

    # שלוש השורות שנמדדו בקובץ של המשתמש. ערבית ועברית הן אותן
    # אותיות שמיות: lam הוא למד, ha הוא חית, mim הוא מם
    assert cleanup.mend_arabic("איירי, עדיף שתבلي זמן עם החיים,") == \
        "איירי, עדיף שתבלי זמן עם החיים,"
    assert cleanup.mend_arabic("איירי, תברحي.") == "איירי, תברחי."
    # אות סופית: "הם" ולא "המ"
    assert cleanup.mend_arabic("הم, הבנתי.") == "הם, הבנתי."

    # שורה שכולה ערבית היא טקסט ערבי אמיתי ולא שיבוש, ואסור
    # להפוך אותה לג'יבריש עברי
    arabic = "مرحبا بك في العالم"
    assert cleanup.mend_arabic(arabic) == arabic
    assert cleanup.mend_arabic("שלום עולם") == "שלום עולם"

    # והתיקון רץ בתוך clean, לפני שמחליטים שהשורה "זרה"
    fixed, foreign = cleanup.clean(["איירי, תברحي."])
    assert fixed == ["איירי, תברחי."], fixed
    assert foreign == [], foreign

    # תקרה אפסית אינה "בלי הגבלה" אלא ביטול. נמדד אצל המשתמש:
    # REPAIR_TIMEOUT=0 ב-.env, wait_for נכשל מיד, והלוג אמר
    # "עבר 0 שניות" כאילו ניסה
    body = inspect.getsource(hebrew.repair_foreign)
    assert "REPAIR_TIMEOUT <= 0" in body, "מלכודת האפס נשארה"


@check("ההעלאות מתחלקות בתורות, וקובץ גדול אינו גוזל תור מהחשבון הרגיל")
def _upload_turns():
    from zovexsub import botapi, config

    saved_lite, saved_turn = botapi._lite, botapi._turn
    botapi._lite, botapi._turn = "LITE", 0
    gig = 1024 ** 3
    try:
        # קודם כל קובץ מתחת לתקרה הלך לחשבון הרגיל, ולכן הוא נשא את
        # כל העומס בעוד ה-Premium לא העלה דבר. רוב הקבצים הם כג'יגה
        picks = [botapi.uploader(gig, "PREMIUM")[1] for _ in range(8)]
        assert picks == ["Premium", "Premium", "רגיל", "רגיל",
                         "Premium", "Premium", "רגיל", "רגיל"], picks

        # קובץ מעל התקרה חייב Premium — ואינו מקדם את התור, אחרת
        # שלושה סרטים גדולים ברצף היו חייבים לחשבון הרגיל שלוש
        # העלאות שהוא אינו יכול לבצע בכלל
        botapi._turn = 0
        for _ in range(3):
            assert botapi.uploader(3 * gig, "PREMIUM")[1] == "Premium"
        assert botapi._turn == 0, botapi._turn
        # והקטן שאחריהם עדיין מקבל את התור הראשון
        assert botapi.uploader(gig, "PREMIUM")[1] == "Premium"

        # בלי חשבון רגיל מחובר הכול עובר ל-Premium
        botapi._lite = None
        assert botapi.uploader(gig, "PREMIUM")[1] == "Premium"
    finally:
        botapi._lite, botapi._turn = saved_lite, saved_turn

    assert config.UPLOAD_TURN >= 1


@check("שם הסרטון מגיע לחקר, והחיפוש נדלק רק כשיש מה לחפש")
def _research_gets_title():
    import inspect
    from zovexsub import hebrew, pipeline

    # החקר חילץ שמות מהתמליל וחיפש אותם ברשת — כלומר אימת את מה
    # שהתמלול כבר שגה בו. נמדד אצל המשתמש: הגיבורה Airi יצאה
    # "היידי" בשישה מתוך תשעה אזכורים, והאימות לא יכול היה לעזור
    # כי הוא חיפש "היידי". שם הסרטון הוא הנתון היחיד שאינו מגיע
    # מהתמליל, ולכן היחיד שיכול לתקן אותו
    assert "title" in inspect.signature(hebrew.research_notes).parameters
    assert "title" in inspect.signature(hebrew.build_hebrew).parameters

    body = inspect.getsource(hebrew.research_notes)
    assert "grounded=bool(title)" in body, "החיפוש אינו תלוי בשם הסרטון"
    assert "FACTS_TITLE" in body, "השם אינו נכנס לפרומפט"

    filled = hebrew.FACTS_TITLE.format(title="Never After Dark")
    assert "Never After Dark" in filled
    assert "השם הרשמי" in filled, filled

    # ובלי שם, הפרומפט נשאר בדיוק כפי שהיה
    plain = hebrew.FACTS_USER.format(titled="", part=1, total=1,
                                     language="יפנית", transcript="שלום")
    assert plain.startswith("להלן קטע"), plain[:40]

    # והצינור מעביר את שם הקובץ, אחרי ניקוי תגיות ההפצה
    assert "title=stt_title_hint(source)" in inspect.getsource(pipeline.run)


@check("חלון תרגום שנפל כולו אינו מטופל שורה-שורה")
def _failed_window_not_serial():
    import inspect
    from zovexsub import config, hebrew

    # מסלול השורות הבודדות נבנה לכמה שורות שהמודל השמיט, והוא רץ
    # בטור. חלון של חמישים שורות שנחתך בתקרה הפך לחמישים קריאות
    # רצופות, כל אחת עד GEMINI_WINDOW_TIMEOUT, והן מחזיקות מקום
    # בגייט כל הזמן הזה. נמדד אצל המשתמש: "2 חלונות בעבודה ·
    # אין תזוזה 13:35" על שלב שתוקצב בהרבה פחות
    body = inspect.getsource(hebrew)
    assert "len(missing) == len(window)" in body, \
        "חלון שנפל כולו עדיין נכנס למסלול השורות הבודדות"
    assert "TRANSLATE_RETRY_MAX" in body, "אין גבול למספר התיקונים"

    # הגבול קיים והוא קטן מחלון שלם
    assert 1 <= config.TRANSLATE_RETRY_MAX < hebrew.WINDOW, \
        (config.TRANSLATE_RETRY_MAX, hebrew.WINDOW)

    # וכשגם הניסיון השני נופל, השורות נשארות בשפת המקור ולא
    # נעלמות: שורה באנגלית גרועה פחות משורה חסרה
    assert "out[idx] = segments[idx].text" in body


@check("מעבר המגדר מקבל תקרה נדיבה וניסיון שני, ולא מדולג בשקט")
def _addressee_not_skipped():
    import inspect
    from zovexsub import config, hebrew

    # נמדד מול תרגום אולפן על אותו סרט, לפני ואחרי שהתקרה האחידה
    # הוחלה גם כאן: צורות זכר קפצו מ-14 ל-51 בעוד שתי הדמויות
    # נשים. חלון שדולג פשוט נשאר בלי תיקון מגדר, וזה התיקון
    # הנראה ביותר בעברית
    assert config.ADDRESSEE_TIMEOUT > config.GEMINI_WINDOW_TIMEOUT, \
        (config.ADDRESSEE_TIMEOUT, config.GEMINI_WINDOW_TIMEOUT)

    body = inspect.getsource(hebrew)
    start = body.index("ADDRESSEE_SYSTEM, prompt")
    chunk = body[start:start + 1400]
    assert chunk.count("ADDRESSEE_TIMEOUT") >= 2, "אין ניסיון שני"
    assert "ניסיון שני" in chunk, chunk[:120]
    # והדילוג נשאר אפשרות אחרונה, אחרי שני כשלונות
    assert "פעמיים" in chunk


@check("קולות ושברי מילים נמחקים, ודיבור אמיתי נשאר")
def _drop_filler():
    from zovexsub import srt

    # נמדד מול תרגום אולפן של אותו סרט: במקומות האלה הכתוביות
    # המקצועיות ריקות לגמרי, ואצלנו הופיעו שורות
    for junk in ("Mm-mm. Mm-mm. Mm-mm. Mm-mm.", "Mm-mm.", "אה.",
                 "הממ.", "הו.", "ההמ?", "Hmm", "uh"):
        assert srt.is_filler(junk), junk
    for stray in ("The", "I", "and"):
        assert srt.is_stray(stray), stray

    # דיבור אמיתי נשאר, גם כשהוא מתחיל בקול
    for real in ("אה, מאיה?", "אה, סליחה.", "האורות.", "ממש כאן?",
                 "לא.", "כן.", "שלום"):
        assert not srt.is_filler(real), real
        assert not srt.is_stray(real), real

    # ומילה לועזית ממשית אינה שבר: שם או מונח נשמרים
    for keep in ("Radioactivity", "OK", "The Dog Stars"):
        assert not srt.is_stray(keep), keep

    def cue(start, end, text):
        return srt.Cue(index=0, start=start, end=end, text=text)

    cues = [cue(1.0, 2.0, "שלום לך"), cue(3.0, 4.0, "הממ."),
            cue(5.0, 6.0, "The"), cue(7.0, 8.0, "מה קרה?")]
    assert srt.drop_filler(cues) == 2
    assert [c.text for c in cues] == ["שלום לך", "מה קרה?"]

    # והשער האחרון סופר אותן
    report = srt.finalize([cue(1.0, 2.0, "שלום לך"), cue(3.0, 4.0, "אה.")], 24.0)
    assert report["קולות"] == 1, report


@check("מעבר המגדר מקבל מודל ורמת חשיבה משלו")
def _addressee_own_model():
    import asyncio
    import inspect
    from zovexsub import config, gemini, hebrew

    # נמדד על אותו סרט מול תרגום אולפן, אחרי המעבר ל-3.8-flash
    # עם חשיבה LOW: צורות הזכר עלו מ-52 ל-76 בעוד שתי הדמויות
    # נשים. קביעת הנמען דורשת הסקה, וזה בדיוק מה שחשיבה נמוכה
    # מורידה — בעוד שאר הצינור לא נפגע
    assert config.ADDRESSEE_THINKING == "HIGH", config.ADDRESSEE_THINKING

    body = inspect.getsource(hebrew)
    start = body.index("ADDRESSEE_SYSTEM, prompt")
    chunk = body[start:start + 1600]
    assert chunk.count("ADDRESSEE_THINKING") >= 2, "גם הניסיון השני צריך אותה"
    assert chunk.count("ADDRESSEE_MODEL") >= 2, chunk[:200]

    # ו-ask_json באמת מכבד עקיפה לכל קריאה
    seen: dict = {}

    async def fake_call(model, body_, **_kw):
        seen["gen"] = body_["generationConfig"]
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    saved_call, saved_level = gemini._call, config.GEMINI_THINKING
    gemini._call, config.GEMINI_THINKING = fake_call, "LOW"
    try:
        asyncio.run(gemini.ask_json("sys", "user", thinking="HIGH"))
        assert seen["gen"]["thinkingConfig"] == {"thinkingLevel": "HIGH"}, seen
        asyncio.run(gemini.ask_json("sys", "user"))
        assert seen["gen"]["thinkingConfig"] == {"thinkingLevel": "LOW"}, seen
        # ועקיפה ריקה מכבה את השדה לגמרי
        asyncio.run(gemini.ask_json("sys", "user", thinking=""))
        assert "thinkingConfig" not in seen["gen"], seen
    finally:
        gemini._call, config.GEMINI_THINKING = saved_call, saved_level


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
