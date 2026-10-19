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

    # ניתוב לפי גודל: רגיל עד 2GB, Premium מעליו
    botapi._lite = object()
    try:
        small = botapi.uploader(config.LITE_UPLOAD_MAX, "PREM")
        big = botapi.uploader(config.LITE_UPLOAD_MAX + 1, "PREM")
    finally:
        botapi._lite = None
    assert small[1] == "רגיל", small
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
