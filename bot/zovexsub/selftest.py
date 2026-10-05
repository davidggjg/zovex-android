"""בדיקה עצמית: מריצה את כל חלקי הצינור ומדווחת מה עובד ומה לא.

הבעיה שהכלי הזה פותר: אין שום דרך לבדוק שינוי מול טלגרם האמיתי חוץ
מלשלוח סרטון ולראות מה קורה. לכן כל תקלה התגלתה רק באמצע עבודה אמיתית,
אחרי שהמשתמש כבר חיכה. כאן כל חלק נבדק בנפרד, על קבצים זעירים שהכלי
יוצר בעצמו, ומדווח בשורה אחת אם הוא חי.

הרצה:  /opt/zovexsub/venv/bin/python -m zovexsub.selftest
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

logging.basicConfig(level=logging.ERROR, format="%(message)s")

from . import config  # noqa: E402

OK, BAD, WARN = "✅", "❌", "⚠️"
results: list[tuple[str, str, str]] = []


def report(mark: str, name: str, detail: str = "") -> None:
    results.append((mark, name, detail))
    print(f"{mark} {name}" + (f" — {detail}" if detail else ""), flush=True)


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def check_environment() -> None:
    print("\n── סביבה ──")
    cores = os.cpu_count() or 0
    report(OK if cores >= 2 else WARN, "ליבות", f"{cores}")

    for tool in ("ffmpeg", "ffprobe"):
        report(OK if _which(tool) else BAD, tool,
               "מותקן" if _which(tool) else "חסר!")

    try:
        __import__("cryptg")
        report(OK, "cryptg", "הצפנה בקוד C")
    except ImportError:
        report(BAD, "cryptg", "חסר — ההעברות יהיו איטיות פי עשרות. "
                              "pip install cryptg")

    try:
        font = subprocess.run(["fc-match", "Noto Sans Hebrew"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        good = "noto" in font.lower() and "hebrew" in font.lower()
        report(OK if good else WARN, "גופן עברי", font or "לא נמצא")
    except (OSError, subprocess.SubprocessError) as exc:
        report(WARN, "גופן עברי", str(exc))

    from . import vad
    if vad.available():
        report(OK, "זיהוי דיבור", "Silero VAD פעיל")
    else:
        report(WARN, "זיהוי דיבור",
               f"מודל חסר ב-{config.VAD_MODEL} — זיהוי לפי עוצמה, "
               "מוזיקת רקע תיחשב כדיבור")

    try:
        config.WORK_DIR.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(config.WORK_DIR).free / 1024 ** 3
        report(OK if free > 20 else WARN, "מקום פנוי", f"{free:.0f}GB")
    except OSError as exc:
        report(BAD, "מקום פנוי", str(exc))


def check_config() -> None:
    print("\n── הגדרות ──")
    problems = config.validate() or []
    report(OK if not problems else BAD, "קובץ ההגדרות",
           "תקין" if not problems else " · ".join(problems))
    report(OK if config.GROQ_API_KEYS else BAD, "מפתחות Groq",
           f"{len(config.GROQ_API_KEYS)}")
    report(OK if config.GEMINI_API_KEYS else BAD, "מפתחות Gemini",
           f"{len(config.GEMINI_API_KEYS)}")
    cores = os.cpu_count() or 2
    report(OK, "חלוקת צריבה",
           f"{config.burn_slots(cores)} מקומות × {config.BURN_SEGMENT_THREADS} חוטים "
           f"· עד {config.BURN_JOBS} צריבות במקביל")
    report(OK, "חיבורי טלגרם",
           f"{config.TG_CONNECTIONS}" +
           (" (מסלול מהיר כבוי)" if config.TG_CONNECTIONS <= 1 else ""))


async def check_keys() -> None:
    """מוודא שכל מפתח באמת עונה, בלי לבזבז מכסת תמלול או תרגום."""
    print("\n── מפתחות ──")
    import httpx

    async with httpx.AsyncClient(timeout=30) as http:
        alive = 0
        for key in config.GROQ_API_KEYS:
            try:
                r = await http.get("https://api.groq.com/openai/v1/models",
                                   headers={"Authorization": f"Bearer {key}"})
                alive += r.status_code == 200
            except httpx.HTTPError:
                pass
        report(OK if alive == len(config.GROQ_API_KEYS) else
               (WARN if alive else BAD), "Groq עונים",
               f"{alive}/{len(config.GROQ_API_KEYS)}")

        alive = 0
        for key in config.GEMINI_API_KEYS:
            try:
                r = await http.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key})
                alive += r.status_code == 200
            except httpx.HTTPError:
                pass
        report(OK if alive == len(config.GEMINI_API_KEYS) else
               (WARN if alive else BAD), "Gemini עונים",
               f"{alive}/{len(config.GEMINI_API_KEYS)}")


async def check_burn(work: Path) -> None:
    """צריבה אמיתית מקצה לקצה, כולל קטע שאין בו אף כתובית."""
    print("\n── צריבה ──")
    from . import media

    work.mkdir(parents=True, exist_ok=True)
    src, srt, dst = work / "t.mp4", work / "t.srt", work / "t.out.mp4"
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "lavfi",
             "-i", "testsrc2=s=320x180:r=15:d=30", "-f", "lavfi",
             "-i", "sine=f=440:d=30", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", "-shortest", str(src)],
            capture_output=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        report(BAD, "יצירת וידאו לבדיקה", str(exc)[:120])
        return

    # שורה בהתחלה ושורה בסוף, כך שהקטע האמצעי יוצא בלי שום כתובית —
    # בדיוק המקרה שהפיל את הצריבה המקבילית למסלול האיטי בשקט
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nשורה ראשונה לבדיקה\n\n"
        "2\n00:00:26,000 --> 00:00:29,000\nשורה אחרונה לבדיקה\n",
        encoding="utf-8")

    chunk, minimum, credit = (config.BURN_CHUNK_SECONDS,
                              config.BURN_PARALLEL_MIN_MINUTES, config.CREDIT_TEXT)
    config.BURN_CHUNK_SECONDS, config.BURN_PARALLEL_MIN_MINUTES = 10, 0
    config.CREDIT_TEXT = ""
    fell_back = []
    real_single = media._burn_single

    async def watched(*args, **kwargs):
        fell_back.append(True)
        return await real_single(*args, **kwargs)

    media._burn_single = watched
    started = time.monotonic()
    try:
        await media.burn(src, srt, dst)
        took = time.monotonic() - started
        if fell_back:
            report(BAD, "צריבה מקבילית",
                   "נפלה למסלול היחיד — הכתוביות או הקטעים שבורים")
        else:
            report(OK, "צריבה מקבילית",
                   f"{30 / took:.1f}x · קטע בלי כתוביות עבר")
        info = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-select_streams", "a", "-show_entries", "stream=codec_name",
             "-of", "default=nw=1", str(dst)],
            capture_output=True, text=True).stdout
        length = next((float(l.split("=")[1]) for l in info.splitlines()
                       if l.startswith("duration")), 0.0)
        report(OK if abs(length - 30) < 2 else BAD, "אורך הפלט",
               f"{length:.1f} שניות")
        report(OK if "codec_name" in info else BAD, "האודיו נשמר",
               "כן" if "codec_name" in info else "אבד!")
    except Exception as exc:  # noqa: BLE001
        report(BAD, "צריבה", f"{type(exc).__name__}: {str(exc)[:150]}")
    finally:
        media._burn_single = real_single
        (config.BURN_CHUNK_SECONDS, config.BURN_PARALLEL_MIN_MINUTES,
         config.CREDIT_TEXT) = chunk, minimum, credit


async def check_telegram(work: Path, megabytes: int) -> None:
    """מעלה קובץ להודעות השמורות, מוריד אותו בחזרה, ומשווה בייט־בייט."""
    print("\n── טלגרם ──")
    from telethon import TelegramClient
    from . import fastio

    work.mkdir(parents=True, exist_ok=True)
    src = work / "tg.bin"
    src.write_bytes(os.urandom(megabytes * 1024 * 1024))
    digest = hashlib.sha256(src.read_bytes()).hexdigest()

    # עותק של ה-session, לא המקור. הבוט הרץ מחזיק את הקובץ פתוח
    # ו-SQLite נועל אותו — בדיקה שמנסה לכתוב אליו נופלת על
    # "database is locked". עותק נותן את אותה התחברות בלי להתנגש
    origin = Path(f"{config.TG_SESSION}.session")
    session = work / "probe.session"
    if origin.exists():
        shutil.copy2(origin, session)
    else:
        report(BAD, "טלגרם", f"אין קובץ session ב-{origin}")
        return

    client = TelegramClient(str(session.with_suffix("")),
                            config.TG_API_ID, config.TG_API_HASH)
    sent = None
    try:
        # בלי session קיים, start מבקש מספר טלפון וממתין לנצח. בדיקה
        # אמורה להיכשל ולדווח, לא להיתקע
        await asyncio.wait_for(client.connect(), timeout=30)
        if not await client.is_user_authorized():
            report(BAD, "טלגרם", "אין התחברות — הרץ את הבוט פעם אחת כדי להתחבר")
            return
        me = await client.get_me()
        report(OK, "מחובר", f"{me.username or me.first_name}")

        started = time.monotonic()
        handle = await fastio.upload(client, src)
        sent = await client.send_file("me", handle or src,
                                      force_document=True, caption="zovexsub selftest")
        up = megabytes / max(0.001, time.monotonic() - started)
        report(OK if up > 0.5 else WARN, "העלאה",
               f"{up:.1f}MB/ש׳" + ("" if handle else " (מסלול טלתון)"))

        back = work / "tg.back.bin"
        started = time.monotonic()
        await fastio.download(client, sent, back)
        down = megabytes / max(0.001, time.monotonic() - started)
        same = hashlib.sha256(back.read_bytes()).hexdigest() == digest
        report(OK if same else BAD, "הקובץ חזר שלם",
               "זהה בייט־בייט" if same else "שונה מהמקור!")
        report(OK if down > 0.5 else WARN, "הורדה", f"{down:.1f}MB/ש׳")
    except Exception as exc:  # noqa: BLE001
        report(BAD, "טלגרם", f"{type(exc).__name__}: {str(exc)[:150]}")
    finally:
        try:
            if sent:
                await client.delete_messages("me", [sent.id])
        except Exception:  # noqa: BLE001
            pass
        await client.disconnect()


async def main() -> int:
    megabytes = int(os.getenv("SELFTEST_MB") or 20)
    # לא בתוך WORK_DIR: הבוט מוחק אותה במלואה כשהוא עולה, ו-restart
    # בזמן הבדיקה היה מוחק את הקבצים שלה באמצע
    work = Path(tempfile.mkdtemp(prefix="zovexsub-selftest-"))

    print("בדיקה עצמית של zovexsub")
    try:
        check_environment()
        check_config()
        await check_keys()
        await check_burn(work)
        try:
            await asyncio.wait_for(check_telegram(work, megabytes),
                                   timeout=float(os.getenv("SELFTEST_TG_TIMEOUT") or 300))
        except asyncio.TimeoutError:
            report(BAD, "טלגרם", "הבדיקה עברה את תקרת הזמן")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    bad = sum(1 for mark, _, _ in results if mark == BAD)
    warn = sum(1 for mark, _, _ in results if mark == WARN)
    print("\n" + "─" * 40)
    if bad:
        print(f"{BAD} {bad} תקלות" + (f", {warn} אזהרות" if warn else ""))
        for mark, name, detail in results:
            if mark == BAD:
                print(f"   • {name}: {detail}")
    elif warn:
        print(f"{WARN} הכול עובד, {warn} אזהרות")
    else:
        print(f"{OK} הכול עובד")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
