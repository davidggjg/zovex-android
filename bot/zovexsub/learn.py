"""קליטת כתוביות אולפנים: קובץ בודד, או ZIP עם מלא קבצים.

המנוע משותף לשני המסלולים — פקודת שורת פקודה על תיקייה, וקובץ
שנשלח לבוט מהטלפון. ה-ZIP הוא העיקר: הוא הדרך היחידה להכניס
עשרות קבצים בלי מחשב.

הזיווג בתוך חבילה נעשה לפי **שם הקובץ**, אחרי הסרת כל מה שמפיצי
כתוביות מדביקים (שפה, קודק, רזולוציה, שם הקבוצה). שני קבצים שנשארו
עם אותו גלעין הם אותו סרט, ואז ההצמדה עצמה היא לפי הזמן — ראו
studio.align
"""
from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path

from . import idiom, memory, srt, studio

log = logging.getLogger(__name__)

SUFFIXES = (".srt", ".vtt", ".sub", ".ass", ".ssa")
# מה שמפיצי כתוביות מדביקים לשם, ואינו חלק משם הסרט
_NOISE = re.compile(
    r"\b(1080p|2160p|720p|480p|4k|x264|x265|h264|h265|hevc|avc|"
    r"bluray|blu-ray|brrip|bdrip|webrip|web-dl|webdl|hdtv|dvdrip|"
    r"aac|ac3|dts|dd5|5\.1|7\.1|10bit|8bit|hdr|sdr|repack|proper|"
    r"heb|hebrew|eng|english|he|en|forced|sdh|cc|hi)\b",
    re.IGNORECASE)
_BRACKETS = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]")


def stem_of(name: str) -> str:
    """גלעין שם הקובץ: מה שנשאר כשמורידים את הרעש."""
    base = Path(name).name
    for suffix in SUFFIXES:
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    base = _BRACKETS.sub(" ", base)
    base = re.sub(r"[._\-+]+", " ", base)
    base = _NOISE.sub(" ", base)
    # שנת יציאה נשארת: היא מבדילה בין גרסאות של אותו שם
    return " ".join(base.split()).lower()


_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _tokens(stem: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]+", stem) if len(w) > 1}


def same_film(one: str, two: str) -> bool:
    """האם שני גלעיני שמות הם אותו סרט.

    השוואת שמות מלאה אינה עובדת, ונמדד כאן בבדיקה: הקובץ האנגלי
    והעברי של אותו סרט מגיעים כמעט תמיד מקבוצות הפצה שונות, ושם
    הקבוצה נשאר בגלעין. ‏"the movie 2019 grp" מול "the movie 2019"
    הם אותו סרט, ושם זהה לגמרי הוא המקרה הנדיר.

    לכן ההשוואה היא לפי מילים משותפות מתוך הקטן מהשניים, ועם תנאי
    נוסף: שנה שמופיעה בשניהם חייבת להיות זהה. בלעדיו, סדרה שכל
    פרקיה נקראים אותו דבר הייתה מתמזגת לסרט אחד
    """
    if one == two:
        return True
    full_one = {m.group() for m in _YEAR.finditer(one)}
    full_two = {m.group() for m in _YEAR.finditer(two)}
    if full_one and full_two and not (full_one & full_two):
        return False
    a, b = _tokens(one), _tokens(two)
    if not a or not b:
        return False
    shared = len(a & b)
    return shared >= 2 and shared / min(len(a), len(b)) >= 0.75


def family_of(stem: str) -> list[Path]:
    """כל קבצי הספרייה שהם אותו סרט כמו הגלעין הזה."""
    folder = library()
    if not folder.exists():
        return []
    return [p for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in SUFFIXES
            and same_film(stem_of(p.name), stem)]


def _read(path: Path) -> list[srt.Cue]:
    try:
        cues = srt.parse(srt.read_subtitle(path))
    except Exception as exc:  # noqa: BLE001 — קובץ פגום אינו מפיל חבילה
        log.warning("לא הצלחתי לקרוא %s (%s)", path.name, exc)
        return []
    srt.clean_auto_captions(cues)
    return [c for c in cues if (c.text or "").strip()]


class Report:
    """מה נלמד בפועל. נבנה כאן כדי שגם הבוט וגם ה-CLI יציגו אותו."""

    def __init__(self) -> None:
        self.pairs = 0
        self.paired_files: list[str] = []
        self.style_blocks = 0
        self.style_files: list[str] = []
        self.skipped: list[str] = []
        # קובץ מקור שממתין לעברית שלו. לא כשל, ולכן לא ב-skipped
        self.waiting: list[str] = []
        # קובץ שכבר נלמד בעבר. גם זה לא כשל
        self.already: list[str] = []
        self.profiles: list[dict] = []
        # אורך מדריך העברית שנבנה בסוף הקליטה, לדיווח
        self.guide_chars = 0
        self.gender_chars = 0

    @property
    def learned(self) -> bool:
        return bool(self.pairs or self.style_blocks)

    def text(self) -> str:
        rows = []
        if self.pairs:
            rows.append(f"🎯 <b>{self.pairs} זוגות</b> מקור→עברית "
                        f"נכנסו לזיכרון המובחר "
                        f"({len(self.paired_files)} סרטים)")
        if self.style_blocks:
            rows.append(f"✍️ <b>{self.style_blocks} קטעי סגנון</b> עבריים "
                        f"({len(self.style_files)} קבצים)")
        if not rows and not (self.waiting or self.already):
            rows.append("לא נלמד דבר מהקבצים האלה.")
        if self.waiting:
            rows.append(f"\n⏳ ממתין בספרייה לעברית שלו: "
                        f"{', '.join(self.waiting[:4])}\n"
                        f"<i>שלח את הקובץ העברי של אותו סרט ואצמיד "
                        f"אותם לזוגות.</i>")
        if self.already:
            rows.append(f"\nℹ️ נלמד כבר: {', '.join(self.already[:4])}")
        if self.skipped:
            shown = ", ".join(self.skipped[:4])
            more = f" ועוד {len(self.skipped) - 4}" if len(self.skipped) > 4 else ""
            rows.append(f"\n⚠️ דילגתי על: {shown}{more}")
        if self.guide_chars or self.gender_chars:
            rows.append(f"\n🧠 <b>מדריך העברית נבנה מחדש</b> · "
                        f"{self.guide_chars} תווים של כתיב, לקסיקון "
                        f"וסימני פיסוק, ועוד {self.gender_chars} של "
                        f"צורות פנייה.\n<i>מחושב פעם אחת כאן, ולא "
                        f"בזמן תרגום — זה לא מוסיף שנייה לעבודה.</i>")
        merged = merge_profiles(self.profiles)
        if merged:
            rows.append("\n<b>מה שמדדתי בקבצים האולפניים:</b>\n"
                        + profile_text(merged))
        return "\n".join(rows)


def merge_profiles(profiles: list[dict]) -> dict:
    """ממצע את המדידות על כל הקבצים, משוקלל לפי מספר הכתוביות."""
    profiles = [p for p in profiles if p.get("cues")]
    if not profiles:
        return {}
    total = sum(p["cues"] for p in profiles)
    out: dict = {"cues": total, "files": len(profiles)}
    for key in ("span_median", "cps_median", "cps_p90", "chars_median",
                "line_p90", "two_lines", "gap_median"):
        out[key] = round(sum(p.get(key, 0) * p["cues"] for p in profiles)
                         / total, 2)
    out["line_max"] = max(p.get("line_max", 0) for p in profiles)
    out["three_lines"] = sum(p.get("three_lines", 0) for p in profiles)
    return out


def profile_text(merged: dict) -> str:
    from . import config
    return (
        f"· משך חציוני {merged['span_median']:.2f}ש "
        f"(אצלנו המינימום {config.SRT_MIN_DURATION}ש)\n"
        f"· קצב קריאה חציוני {merged['cps_median']:.1f} תווים/ש, "
        f"אחוזון 90 הוא {merged['cps_p90']:.1f} "
        f"(אצלנו התקרה {config.SRT_READ_SPEED})\n"
        f"· אורך שורה: אחוזון 90 הוא {merged['line_p90']:.0f} תווים, "
        f"המקסימום {merged['line_max']} "
        f"(אצלנו התקרה {config.SRT_MAX_CHARS_PER_LINE})\n"
        f"· {merged['two_lines']:.0f}% מהכתוביות בשתי שורות, "
        f"{merged['three_lines']} בשלוש\n"
        f"· רווח חציוני בין כתוביות {merged['gap_median']:.3f}ש\n"
        f"· מתוך {merged['cues']:.0f} כתוביות ב-{merged['files']} קבצים")


def from_folder(folder: Path) -> Report:
    """לומד מתיקייה על השרת. אותו מנוע בדיוק כמו ממה שנשלח לבוט."""
    files = [p for p in sorted(folder.rglob("*"))
             if p.is_file() and p.suffix.lower() in SUFFIXES]
    report = Report()
    kept = []
    for path in files:
        try:
            kept.append(keep(path, path.name))
        except Exception as exc:  # noqa: BLE001
            log.warning("%s לא נשמר לספרייה (%s)", path.name, exc)
    for stem in _films(kept):
        _learn_group(stem, family_of(stem), report)
    _refresh_guide(report)
    return report


# ───────── הספרייה: קבצים שנשלחו לבוט בלי וידאו ─────────
#
# המשתמש שולח כתוביות אולפן מהטלפון, בלי סרטון, והן נשמרות כאן כדי
# שהבוט יתאמן עליהן. הקבצים נשמרים ולא רק נקראים, משתי סיבות: קובץ
# מקור שהגיע לבד ממתין לעברית שלו (ולהיפך), ואם נשנה את שיטת הלימוד
# אפשר ללמוד מחדש מכל מה שנאסף בלי לבקש ממנו לשלוח שוב


def library() -> Path:
    from . import config
    return Path(config.MEMORY_PATH).parent / "library"


def _ledger_path() -> Path:
    return library() / "learned.json"


def _ledger() -> dict:
    store = _ledger_path()
    if not store.exists():
        return {"style": [], "paired": []}
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"style": [], "paired": []}
    return {"style": list(data.get("style", [])),
            "paired": list(data.get("paired", []))}


def _write_ledger(data: dict) -> None:
    try:
        _ledger_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("רישום הספרייה לא נשמר (%s)", exc)


def keep(source: Path, name: str) -> Path:
    """שומר קובץ שנשלח לספרייה, בשם נקי ובלי לדרוך על קודם."""
    folder = library()
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\s.()\[\]-]", "_", Path(name).name) or "subtitle.srt"
    if Path(safe).suffix.lower() not in SUFFIXES:
        safe += ".srt"
    target = folder / safe
    if target.exists():
        # אותו שם שוב הוא כמעט תמיד אותו קובץ. מחליפים ולא מכפילים
        target.unlink()
    srt.normalize(source, target)
    return target


def absorb(given: Path, name: str) -> Report:
    """קולט קובץ אחד לספרייה ולומד ממנו כל מה שאפשר כרגע.

    קובץ מקור שהגיע לבד אינו מלמד דבר ואינו נזרק: הוא ממתין בספרייה,
    ואם העברית שלו תגיע מתישהו — אפילו בעוד שבוע — הזוגות ייווצרו אז
    """
    kept = keep(given, name)
    stem = stem_of(kept.name)
    report = _learn_group(stem, family_of(stem))
    _refresh_guide(report)
    return report


def absorb_zip(archive: Path, work: Path) -> Report:
    """קולט חבילת ZIP: כל הקבצים נכנסים לספרייה, ואז נלמדים יחד."""
    work.mkdir(parents=True, exist_ok=True)
    taken: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if item.is_dir():
                continue
            name = Path(item.filename).name
            if not name or Path(name).suffix.lower() not in SUFFIXES:
                continue
            if item.file_size > 8 * 1024 * 1024:
                continue
            raw = work / f"{len(taken)}{Path(name).suffix.lower()}"
            with bundle.open(item) as src:
                raw.write_bytes(src.read())
            try:
                taken.append(keep(raw, name))
            except Exception as exc:  # noqa: BLE001
                log.warning("קובץ %s מה-ZIP לא נשמר (%s)", name, exc)
    log.info("נקלטו %d קבצים מתוך %s", len(taken), archive.name)
    report = Report()
    for stem in _films(taken):
        _learn_group(stem, family_of(stem), report)
    _refresh_guide(report)
    return report


def _refresh_guide(report: "Report") -> None:
    """בונה מחדש את מדריך העברית, פעם אחת בסוף הקליטה.

    כאן ולא בזמן התרגום, וזו ההחלטה המרכזית: ספירת הצירופים היא על
    עשרות אלפי שורות, וחלון תרגום נקרא עשרות פעמים לכל סרט. אם זה
    היה רץ שם, כל סרט היה משלם על החישוב הזה שוב ושוב בלי שום
    תמורה — הקורפוסים אינם משתנים באמצע עבודה
    """
    if not report.learned:
        return
    try:
        report.guide_chars, report.gender_chars = idiom.build_guide()
    except Exception as exc:  # noqa: BLE001 — מדריך הוא שיפור, לא תנאי
        log.warning("בניית מדריך הסגנון נכשלה (%s)", exc)


def _films(paths: list[Path]) -> list[str]:
    """גלעין אחד לכל סרט בקבוצת קבצים. שני צדדים אינם נלמדים פעמיים."""
    out: list[str] = []
    for path in sorted(paths):
        stem = stem_of(path.name)
        if not any(same_film(stem, taken) for taken in out):
            out.append(stem)
    return out


def _learn_group(stem: str, family: list[Path],
                 report: Report | None = None) -> Report:
    """לומד מכל הקבצים של סרט אחד, ורושם מה כבר נלמד.

    הרישום הוא העיקר: בלי הוא, קובץ שנשלח פעמיים היה מכניס את אותם
    קטעי סגנון שוב — ודוגמה שמופיעה פעמיים בבנק מקבלת משקל כפול
    בלי שאיש החליט על כך. ‏memory.add מגן על עצמו מכפילויות, ובנק
    הסגנון אינו, ולכן הוא זקוק לשער הזה
    """
    report = report or Report()
    ledger = _ledger()
    read = {path: _read(path) for path in family}
    read = {path: cues for path, cues in read.items() if cues}
    if not read:
        report.skipped.append(f"{stem or '?'} (לא נקרא)")
        return report

    hebrew = [(p, c) for p, c in read.items()
              if studio.language_of(c) == "he"]
    other = [(p, c) for p, c in read.items()
             if studio.language_of(c) == "other"]
    if not hebrew:
        # לא דילוג ולא שגיאה: הקובץ ממתין בספרייה לעברית שלו
        report.waiting.append(stem or "?")
        return report

    heb_path, heb_cues = max(hebrew, key=lambda item: len(item[1]))
    report.profiles.append(studio.profile(heb_cues))

    if other and heb_path.name not in ledger["paired"]:
        src_path, src_cues = max(other, key=lambda item: len(item[1]))
        pairs = studio.align(src_cues, heb_cues)
        if studio.aligned_well(pairs, len(heb_cues)):
            report.pairs += memory.add(pairs, source=heb_path.name)
            report.paired_files.append(stem)
            ledger["paired"].append(heb_path.name)
            _write_ledger(ledger)
            return report
        log.warning("ההצמדה של %s נכשלה — %d זוגות מתוך %d",
                    stem, len(pairs), len(heb_cues))
        report.skipped.append(f"{stem} (הקבצים לא הסתדרו בזמן)")

    if heb_path.name in ledger["style"] or heb_path.name in ledger["paired"]:
        report.already.append(stem or "?")
        return report
    blocks = studio.add_style(heb_cues, heb_path.name)
    if blocks:
        report.style_blocks += blocks
        report.style_files.append(stem)
        ledger["style"].append(heb_path.name)
        _write_ledger(ledger)
    return report


def shelf() -> str:
    """מה יש בספרייה כרגע — לדיווח למשתמש."""
    folder = library()
    if not folder.exists():
        return "הספרייה ריקה"
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in SUFFIXES]
    if not files:
        return "הספרייה ריקה"
    stems = {stem_of(p.name) for p in files}
    return f"{len(files)} קבצים · {len(stems)} סרטים"
