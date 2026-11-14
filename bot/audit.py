"""בדיקת איכות לקובץ כתוביות עברי — דוח מדויק עם חותמות זמן.

נכתב כדי להפסיק לנחש. במקום "יש הזיות בטווח עשר דקות", הכלי מחזיר
רשימה ממוינת: איזו כתובית, באיזו שנייה, מה חשוד בה ולמה. אפשר לקפוץ
לכל שורה בנגן ולראות בעיניים.

כל הבדיקות דטרמיניסטיות: שום קריאת מודל, שום מפתח, שום רשת. אפשר
להריץ גם כשעבודה רצה ברקע — זה רק קורא קבצים.

    python audit.py כתוביות.srt
    python audit.py כתוביות.srt --video סרט.mkv     # + חיתוכי צילום
    python audit.py כתוביות.srt --cps 17            # תקרת קריאה אחרת
    python audit.py כתוביות.srt --csv דוח.csv

התקנים שהמספרים נגזרים מהם: נטפליקס/אמזון לעברית — 42 תווים לשורה,
שתי שורות, 17 תווים לשנייה למבוגרים (13 לילדים), מינימום 5/6 שנייה,
מקסימום 7 שניות, ורווח של שני פריימים בין כתוביות.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zovexsub import srt  # noqa: E402

# ── חומרה ─────────────────────────────────────────────────────────
BLOCKER, WARN, NOTE = "חוסם", "אזהרה", "הערה"
RANK = {BLOCKER: 0, WARN: 1, NOTE: 2}
MARK = {BLOCKER: "🔴", WARN: "🟡", NOTE: "🔵"}


@dataclass
class Finding:
    severity: str
    kind: str
    index: int
    start: float
    detail: str

    @property
    def at(self) -> str:
        return srt.stamp(self.start).replace(",", ".")[:-4]


# ── עברית: סימנים דטרמיניסטיים ────────────────────────────────────
# פנייה בלשון נקבה מול פנייה בלשון זכר באותה כתובית. זה לא מנחש מי
# הדובר — זה תופס **אי-עקביות פנימית**, שהיא תמיד שגיאה בלי קשר למי
# מדבר אל מי. "אתה הולכת" שגוי תמיד
_SHE_YOU = re.compile(r"\b(את|אותך|שלך|לך|איתך)\b(?!\s*ה)")
_HE_YOU = re.compile(r"\b(אתה|אותך|שלך)\b")
_SHE_VERB = re.compile(r"\b\w+ת\b")           # הולכת, אומרת
_HE_IMPER = re.compile(r"\b(בוא|תן|קח|שב|לך|עצור|חכה|תסתכל)\b")
_SHE_IMPER = re.compile(r"\b(בואי|תני|קחי|שבי|לכי|עצרי|חכי|תסתכלי)\b")

_SENTENCE_END = re.compile(r"[.!?…:]\s*$")
# מילות קישור וצירוף שאינן יכולות לסיים כתובית: אחריהן **חייבת** לבוא
# מילה. כתובית שנגמרת ב"של" או ב"את" נקרעה באמצע צירוף, תמיד.
# בעברית אין אות גדולה, ולכן "השורה הבאה מתחילה באות קטנה" — הכלל
# שעובד באנגלית — חסר כאן משמעות. זה התחליף הנכון
_DANGLING = re.compile(
    r"\b(של|את|אל|על|עם|בין|מול|אצל|בלי|לפני|אחרי|כדי|בגלל|למרות|"
    r"מפני|כי|אם|כאשר|אשר|אבל|או|וגם|ולא|גם|רק|כל|איזה|מה|מי)$")
_LATIN = re.compile(r"[A-Za-z]{2,}")
_ARABIC = re.compile(r"[؀-ۿ]")
_TAG = re.compile(r"</?[a-zA-Z]")


def _plain(text: str) -> str:
    """טקסט לצורך מניית תווים: בלי תגיות, בלי סימני כיווניות."""
    text = re.sub(r"<[^>]+>", "", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


def _cps(cue: srt.Cue) -> float:
    span = cue.end - cue.start
    body = _plain(cue.text).replace("\n", " ")
    return len(body) / span if span > 0 else 999.0


# ── הבדיקות ───────────────────────────────────────────────────────
def check_timing(cues: list[srt.Cue], *, cps_limit: float, fps: float,
                 min_dur: float, max_dur: float) -> list[Finding]:
    out: list[Finding] = []
    # שני פריימים, התקן המקצועי. הסבילות של אלפית נדרשת כי SRT שומר
    # באלפיות שנייה ופריים אינו מספר עגול באלפיות
    gap_floor = 2.0 / fps - 0.004
    for i, cue in enumerate(cues):
        span = cue.end - cue.start
        if span <= 0:
            out.append(Finding(BLOCKER, "זמן הפוך", cue.index, cue.start,
                               f"סוף {cue.end:.3f} לפני התחלה {cue.start:.3f}"))
            continue
        if span < min_dur:
            out.append(Finding(WARN, "קצרה מדי", cue.index, cue.start,
                               f"{span:.2f}ש — המינימום {min_dur:.2f}"))
        if span > max_dur:
            out.append(Finding(WARN, "ארוכה מדי", cue.index, cue.start,
                               f"{span:.2f}ש — המקסימום {max_dur:.1f}"))
        speed = _cps(cue)
        if speed > cps_limit * 1.5:
            out.append(Finding(BLOCKER, "מהירה לקריאה", cue.index, cue.start,
                               f"{speed:.1f} תווים/ש — התקרה {cps_limit:.0f}"))
        elif speed > cps_limit:
            out.append(Finding(WARN, "מהירה לקריאה", cue.index, cue.start,
                               f"{speed:.1f} תווים/ש — התקרה {cps_limit:.0f}"))
        if i + 1 < len(cues):
            gap = cues[i + 1].start - cue.end
            if gap < 0:
                out.append(Finding(BLOCKER, "חפיפה", cue.index, cue.start,
                                   f"חופפת לבאה ב-{-gap:.3f}ש"))
            elif gap < gap_floor:
                out.append(Finding(NOTE, "רווח צר", cue.index, cue.start,
                                   f"{gap * 1000:.0f} אלפיות — "
                                   f"המינימום {gap_floor * 1000:.0f}"))
    return out


def check_layout(cues: list[srt.Cue], *, line_limit: int,
                 max_lines: int) -> list[Finding]:
    out: list[Finding] = []
    for cue in cues:
        lines = _plain(cue.text).splitlines()
        if not any(line.strip() for line in lines):
            out.append(Finding(BLOCKER, "ריקה", cue.index, cue.start,
                               "אין טקסט"))
            continue
        if len(lines) > max_lines:
            out.append(Finding(BLOCKER, "יותר משתי שורות", cue.index,
                               cue.start, f"{len(lines)} שורות"))
        for line in lines:
            if len(line) > line_limit:
                out.append(Finding(WARN, "שורה ארוכה", cue.index, cue.start,
                                   f"{len(line)} תווים — התקרה {line_limit}: "
                                   f"{line[:30]}…"))
        if _TAG.search(cue.text):
            out.append(Finding(NOTE, "תגית בטקסט", cue.index, cue.start,
                               "נשארה תגית עיצוב"))
    return out


def check_language(cues: list[srt.Cue]) -> list[Finding]:
    """שאריות שפה שלא היו צריכות לשרוד לקובץ הסופי."""
    out: list[Finding] = []
    for cue in cues:
        body = _plain(cue.text)
        if _ARABIC.search(body):
            out.append(Finding(BLOCKER, "אותיות ערביות", cue.index, cue.start,
                               "המודל החזיר ערבית במקום עברית"))
        latin = _LATIN.findall(body)
        # שם לטיני בודד הוא לגיטימי; משפט שלם באנגלית אינו
        if latin and sum(len(w) for w in latin) > len(body) * 0.4:
            out.append(Finding(WARN, "אנגלית שנשארה", cue.index, cue.start,
                               f"{' '.join(latin[:4])}"))
        if not re.search(r"[א-ת]", body) and len(body) > 3:
            out.append(Finding(WARN, "בלי עברית", cue.index, cue.start,
                               body[:40]))
    return out


def check_gender(cues: list[srt.Cue]) -> list[Finding]:
    """אי-עקביות מגדרית **בתוך** כתובית אחת.

    זה לא מנסה לדעת מי הדובר — לזה צריך מודל. זה תופס את מה שאפשר
    לדעת בוודאות: שתי צורות פנייה סותרות באותה נשימה, כמו ציווי
    בזכר ליד ציווי בנקבה. שגיאה כזאת היא שגיאה תמיד
    """
    out: list[Finding] = []
    for cue in cues:
        body = _plain(cue.text).replace("\n", " ")
        he_cmd = _HE_IMPER.findall(body)
        she_cmd = _SHE_IMPER.findall(body)
        if he_cmd and she_cmd:
            out.append(Finding(BLOCKER, "מגדר מתנגש", cue.index, cue.start,
                               f"ציווי בזכר ({he_cmd[0]}) וציווי בנקבה "
                               f"({she_cmd[0]}) באותה כתובית"))
        if re.search(r"\bאתה\b", body) and re.search(r"\bאת\b(?!\s*ה)", body):
            out.append(Finding(WARN, "מגדר מתנגש", cue.index, cue.start,
                               "גם \"אתה\" וגם \"את\" באותה כתובית"))
    return out


def check_content(cues: list[srt.Cue]) -> list[Finding]:
    """כפילויות, הדים, וחיתוך באמצע מילה."""
    out: list[Finding] = []
    for i, cue in enumerate(cues):
        body = _plain(cue.text).replace("\n", " ").strip()
        if i + 1 < len(cues):
            nxt = _plain(cues[i + 1].text).replace("\n", " ").strip()
            if body and body == nxt:
                out.append(Finding(WARN, "כתובית כפולה", cue.index, cue.start,
                                   f"זהה לבאה: {body[:30]}…"))
            # חיתוך באמצע צירוף: הכתובית נגמרת במילת קישור שמחייבת
            # המשך. זה לא "אין נקודה בסוף" — משפט אפשר לפרוס על שתי
            # כתוביות, וזה תקין. "של" בסוף כתובית אינו תקין לעולם
            # כתובית שנגמרת בנקודה, בסימן שאלה או בקריאה היא שלמה.
            # "מה?" הוא שאלה מלאה, לא צירוף שנקרע — ולכן מסירים רק
            # מרכאות ורווחים, ולא את הפיסוק עצמו
            tail = body.rstrip(" \"'\u201d\u201c)»")
            if (body and nxt and not _SENTENCE_END.search(tail)
                    and _DANGLING.search(tail)):
                out.append(Finding(WARN, "חיתוך באמצע צירוף", cue.index,
                                   cue.start,
                                   f"נגמרת ב-\"{tail.split()[-1]}\" ⇢ "
                                   f"\"{nxt[:20]}…\""))
        # אותה מילה שלוש פעמים ברצף. בסרט זה לרוב דיבור אמיתי
        # ("תעצרי! תעצרי! תעצרי!"), ולכן זו אזהרה ולא חסימה — ובצעקה
        # עם שני סימני קריאה ומעלה היא יורדת להערה בלבד
        words = [w.strip(",.!?\u2026") for w in body.split()]
        shout = body.count("!") >= 2
        for a, b, c in zip(words, words[1:], words[2:]):
            if a == b == c and len(a) > 1:
                out.append(Finding(NOTE if shout else WARN, "מילה חוזרת",
                                   cue.index, cue.start,
                                   f"\"{a}\" שלוש פעמים — "
                                   + ("כנראה דיבור אמיתי" if shout
                                      else "לבדוק אם זו הזיה")))
                break
        # חתימת מיזוג: צירוף שלם שחוזר בתוך אותה כתובית. זה כמעט
        # תמיד הדבקה של שתי אמירות נפרדות, ולא דיבור — וזה בדיוק
        # הפגם שהמשתמש תיאר, מילה שנאמרה פעמיים שנדבקה לאמירה
        # שבאה עשר שניות אחר כך
        for size in (4, 3):
            chunks = [" ".join(words[i:i + size])
                      for i in range(len(words) - size + 1)]
            twice = next((c for c in chunks if chunks.count(c) > 1), None)
            if twice:
                out.append(Finding(BLOCKER, "מיזוג כפול", cue.index,
                                   cue.start,
                                   f"\"{twice}\" חוזר באותה כתובית"))
                break
    return out


def check_against_speech(cues: list[srt.Cue],
                         words: dict[int, list]) -> list[Finding]:
    """כתובית מול תזמוני המילים של המקור.

    אם המקור מסר שבכתובית הזאת דיברו 1.1 שניות והכתובית נמשכת 6,
    או שהטקסט ארוך פי כמה ממה שנאמר — זה סימן להזיה או למיזוג שגוי
    """
    out: list[Finding] = []
    for cue in cues:
        spoken = words.get(cue.index) or []
        if not spoken:
            continue
        voice = sum(end - start for start, end in spoken)
        span = cue.end - cue.start
        if span > 1.0 and voice / span < 0.25:
            out.append(Finding(WARN, "כמעט בלי דיבור", cue.index, cue.start,
                               f"דיבור {voice:.2f}ש מתוך {span:.2f}ש "
                               f"({voice / span * 100:.0f}%)"))
    return out


async def check_cuts(cues: list[srt.Cue], video: Path,
                     fps: float) -> list[Finding]:
    """כתובית שחוצה חיתוך צילום נקראת פעמיים — אסור בכל תקן."""
    from zovexsub import config, media
    cuts = await media.scene_cuts(video, config.SCENE_THRESHOLD)
    out: list[Finding] = []
    keep = 12.0 / fps      # 12 פריימים, החוק של נטפליקס
    for cue in cues:
        for cut in cuts:
            if cue.start + keep < cut < cue.end - keep:
                out.append(Finding(NOTE, "חוצה חיתוך צילום", cue.index,
                                   cue.start, f"חיתוך ב-{cut:.2f}ש"))
                break
    return out


# ── דוח ───────────────────────────────────────────────────────────
def summary(cues: list[srt.Cue], cps_limit: float) -> list[str]:
    if not cues:
        return ["אין כתוביות בקובץ."]
    spans = sorted(c.end - c.start for c in cues)
    speeds = sorted(_cps(c) for c in cues)
    chars = [len(_plain(c.text).replace("\n", " ")) for c in cues]
    mid = len(spans) // 2
    over = sum(1 for s in speeds if s > cps_limit)
    return [
        f"כתוביות: {len(cues)}",
        f"משך: חציון {spans[mid]:.2f}ש · הקצרה {spans[0]:.2f} · "
        f"הארוכה {spans[-1]:.2f}",
        f"קצב קריאה: חציון {speeds[mid]:.1f} תווים/ש · "
        f"{over} מעל התקרה ({over / len(cues) * 100:.0f}%)",
        f"אורך טקסט: חציון {sorted(chars)[mid]} תווים",
        f"כיסוי: מ-{srt.stamp(cues[0].start)[:8]} עד "
        f"{srt.stamp(cues[-1].end)[:8]}",
    ]


def report(findings: list[Finding], cues: list[srt.Cue],
           cps_limit: float, limit: int) -> str:
    lines = ["═" * 58, "📋 בדיקת איכות כתוביות", "═" * 58, ""]
    lines += [f"  {row}" for row in summary(cues, cps_limit)]
    lines += ["", "─" * 58, ""]

    if not findings:
        lines.append("🟢 לא נמצאה שום בעיה. הקובץ עומד בתקן.")
        return "\n".join(lines)

    counts: dict[tuple[str, str], int] = {}
    for found in findings:
        counts[(found.severity, found.kind)] = \
            counts.get((found.severity, found.kind), 0) + 1
    lines.append("לפי סוג:")
    for (severity, kind), total in sorted(
            counts.items(), key=lambda kv: (RANK[kv[0][0]], -kv[1])):
        lines.append(f"  {MARK[severity]} {kind:<22} {total}")
    lines += ["", "─" * 58, "", "מקומות לבדיקה בוידאו:", ""]

    findings.sort(key=lambda f: (RANK[f.severity], f.start))
    for found in findings[:limit]:
        lines.append(f"  {MARK[found.severity]} {found.at}  "
                     f"#{found.index:<5} {found.kind} — {found.detail}")
    if len(findings) > limit:
        lines.append(f"\n  …ועוד {len(findings) - limit}. "
                     f"להציג הכל: --limit 0")
    return "\n".join(lines)


def main() -> int:
    from zovexsub import config

    ap = argparse.ArgumentParser(
        description="בדיקת איכות לקובץ כתוביות עברי")
    ap.add_argument("subtitle", type=Path)
    ap.add_argument("--video", type=Path,
                    help="לבדיקת חיתוכי צילום (איטי: מפענח את כל הסרט)")
    ap.add_argument("--cps", type=float, default=config.SRT_READ_SPEED,
                    help=f"תקרת תווים לשנייה (ברירת מחדל {config.SRT_READ_SPEED:.0f}; "
                         "17 למבוגרים לפי נטפליקס, 13 לילדים)")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--limit", type=int, default=60,
                    help="כמה שורות להציג; 0 = הכל")
    ap.add_argument("--csv", type=Path, help="לשמור את הממצאים לטבלה")
    args = ap.parse_args()

    if not args.subtitle.exists():
        print(f"❌ אין קובץ: {args.subtitle}")
        return 1

    cues = srt.parse(srt.read_subtitle(args.subtitle))
    if not cues:
        print("❌ לא הצלחתי לקרוא כתוביות מהקובץ.")
        return 1

    findings = (check_timing(cues, cps_limit=args.cps, fps=args.fps,
                             min_dur=config.SRT_MIN_DURATION,
                             max_dur=config.SRT_MAX_DURATION)
                + check_layout(cues, line_limit=config.SRT_MAX_CHARS_PER_LINE,
                               max_lines=config.SRT_MAX_LINES)
                + check_language(cues)
                + check_gender(cues)
                + check_content(cues))

    if args.video and args.video.exists():
        print("⏳ מחפש חיתוכי צילום (מפענח את כל הסרט)…", flush=True)
        findings += asyncio.run(check_cuts(cues, args.video, args.fps))

    print(report(findings, cues, args.cps,
                 args.limit if args.limit > 0 else len(findings)))

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["חומרה", "סוג", "כתובית", "זמן", "פירוט"])
            for found in findings:
                writer.writerow([found.severity, found.kind, found.index,
                                 found.at, found.detail])
        print(f"\n💾 נשמר: {args.csv}")

    blockers = sum(1 for f in findings if f.severity == BLOCKER)
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
