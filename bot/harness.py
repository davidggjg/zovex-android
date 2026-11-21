"""לולאת שיפור לפרומפט התרגום: הצע ← בדוק ← שלב.

הבעיה שזה פותר: שינוי בפרומפט לוקח דקה, אבל לדעת אם הוא שיפר או
הרס דרש להריץ סרט שלם של תשעים דקות ולהסתכל בעיניים. זו לולאה של
שעתיים, ולכן בפועל לא בדקנו כלום — פשוט שינינו וקיווינו.

כאן הלולאה רצה על קטע קבוע: כל הווריאציות מתרגמות **בדיוק את אותן
שורות**, עם אותו מסמך חקר, ומקבלות ציון מאותם מדדים. מה שלא השתנה
בין הריצות הוא מה שמאפשר להשוות.

    python harness.py מקור.srt --language en
    python harness.py מקור.srt --language en --only base,gender
    python harness.py מקור.srt --lines 120 --repeat 2

מה שזה **לא** מודד: האם התרגום נכון במשמעות. לזה צריך תשובה ידועה
מראש. מה שכן: שורות שלא תורגמו, סתירות מגדר, מיזוגים, אותיות זרות
ואנגלית שנשארה — כלומר בדיוק הפגמים שהפרומפט אחראי להם.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit                                    # noqa: E402
from zovexsub import hebrew, srt, stt           # noqa: E402

RECORD = Path(__file__).resolve().parent / "harness_record.md"

# כמה כל פגם שווה בציון. אלה לא מספרים שרירותיים: שורה שלא תורגמה
# היא אנגלית על המסך, הפגם החמור ביותר שהצופה רואה. סתירת מגדר היא
# שגיאה ודאית. מיזוג גורם לטקסט להופיע לפני שנאמר
WEIGHT = {
    "לא תורגם": 10.0,
    "אותיות ערביות": 8.0,
    "מגדר מתנגש": 6.0,
    "מיזוג כפול": 4.0,
    "אנגלית שנשארה": 3.0,
    "בלי עברית": 3.0,
    "מילה חוזרת": 1.0,
    "כתובית כפולה": 1.0,
}


# ── הווריאציות ────────────────────────────────────────────────────
# כל ווריאציה היא תוספת לפרומפט הבסיס, לא החלפה שלו. ככה ההשוואה
# מודדת את התוספת עצמה ולא שכתוב שלם שמשנה עשרה דברים בבת אחת
VARIANTS: dict[str, str] = {
    "base": "",

    # ‏APGC 2.0 ומאמר מיקרוסופט על ערבית מתייגים את מגדר הדובר ואת
    # מגדר הנמען כ**שני משתנים בלתי תלויים**. הדוגמה שלהם: "אני רופא
    # ואת אחות" — משפט אחד, שני מגדרים. הפרומפט שלנו לא אומר את זה
    "two_genders": """
חשוב במיוחד — מגדר הוא שני משתנים נפרדים בכל שורה:
  1. מגדר הדובר (משפיע על "אני אומר" מול "אני אומרת")
  2. מגדר הנמען (משפיע על "אתה הולך" מול "את הולכת")
השניים בלתי תלויים לחלוטין. במשפט אחד ייתכן דובר זכר ונמענת נקבה,
למשל "אני רופא ואת אחות". אל תגזור אחד מהשני, ואל תאחיד ביניהם.
כשאינך יודע את מגדר הנמען — הסתמך על הסצנה, לא על ברירת מחדל זכר.""",

    # נמדד בקובץ של סרט שלם: שני חלונות שנפלו הפכו ל-189 כתוביות
    # בשפת המקור. חלק מזה הוא המודל שמוותר על שורה קשה
    "never_skip": """
חובה מוחלטת: כל שורה שביקשתי חייבת לחזור מתורגמת לעברית.
שורה שאינך בטוח בה — תרגם אותה בכל זאת לפי מיטב הבנתך.
אסור להחזיר את המקור, אסור להחזיר מחרוזת ריקה, ואסור לדלג.
אם שורה היא רעש, מלמול או ג'יבריש — החזר את מה שנשמע בעברית.""",

    # אותיות ערביות שורדות לקובץ כי המודל מערבב כתבים שמיים
    "hebrew_only": """
הפלט חייב להיות באותיות עבריות בלבד.
אסור לחלוטין להשתמש באותיות ערביות (ي ك ح ه ة) — הן נראות דומות
לעבריות אך הן כתב אחר, והן יוצאות כג'יבריש אצל הצופה.
שמות לועזיים נכתבים בתעתיק עברי, לא באותיות לטיניות.""",
}


@dataclass
class Score:
    name: str
    points: float
    counts: dict[str, int]
    lines: int
    seconds: float

    def row(self) -> str:
        worst = sorted(self.counts.items(), key=lambda kv: -kv[1])[:3]
        detail = " · ".join(f"{k} {v}" for k, v in worst if v) or "נקי"
        return (f"  {self.name:<14} {self.points:>7.1f}  "
                f"{self.seconds:>5.0f}ש   {detail}")


def load_segments(path: Path, limit: int) -> list[stt.Segment]:
    """קורא SRT בשפת המקור והופך אותו לסגמנטים לתרגום."""
    cues = srt.parse(srt.read_subtitle(path))
    if not cues:
        raise SystemExit(f"❌ לא הצלחתי לקרוא כתוביות מ-{path}")
    return [stt.Segment(index=i, start=c.start, end=c.end,
                        text=" ".join(c.text.split()))
            for i, c in enumerate(cues[:limit])]


def grade(segments: list[stt.Segment], lines: list[str]) -> Score:
    """נותן ציון לתרגום. ציון נמוך = טוב יותר."""
    cues = [srt.Cue(index=i + 1, start=s.start, end=s.end,
                    text=lines[i] if i < len(lines) else "")
            for i, s in enumerate(segments)]

    counts: dict[str, int] = {}
    for found in (audit.check_language(cues) + audit.check_gender(cues)
                  + audit.check_content(cues)):
        counts[found.kind] = counts.get(found.kind, 0) + 1

    # שורה שחזרה זהה למקור לא תורגמה, גם אם היא "תקינה" טכנית
    same = sum(1 for seg, line in zip(segments, lines)
               if line.strip() and line.strip() == seg.text.strip())
    if same:
        counts["לא תורגם"] = same

    points = sum(WEIGHT.get(kind, 1.0) * n for kind, n in counts.items())
    # מנרמל למאה שורות, כדי שאפשר יהיה להשוות בין קטעים שונים
    points = points / max(1, len(segments)) * 100
    return Score("", round(points, 1), counts, len(segments), 0.0)


async def run_variant(name: str, extra: str, segments: list[stt.Segment],
                      language: str, notes: str) -> Score:
    original = hebrew.TRANSLATE_SYSTEM
    hebrew.TRANSLATE_SYSTEM = original + extra
    started = time.monotonic()
    try:
        lines = await hebrew._translate_all(segments, language, notes)
    finally:
        hebrew.TRANSLATE_SYSTEM = original
    score = grade(segments, lines)
    score.name = name
    score.seconds = time.monotonic() - started
    return score


def remember(best: Score, baseline: Score, sample: str) -> None:
    """רשומת השיפור — מה נבדק, מה ניצח, ובכמה.

    זה החלק שהופך ריצה בודדת ללמידה: בלעדיו נבדוק שוב את אותן
    וריאציות בעוד חודש בלי לדעת שכבר נבדקו
    """
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    gain = baseline.points - best.points
    verdict = (f"**{best.name}** ניצח ב-{gain:.1f} נקודות"
               if gain > 0 else "אף ווריאציה לא שיפרה — הבסיס נשאר")
    entry = (f"\n## {when} · {sample}\n\n"
             f"{verdict} (בסיס {baseline.points:.1f} ⇠ "
             f"{best.points:.1f}, {baseline.lines} שורות)\n\n"
             f"פגמים שנשארו: "
             f"{json.dumps(best.counts, ensure_ascii=False) or 'אין'}\n")
    with RECORD.open("a", encoding="utf-8") as fh:
        if fh.tell() == 0:
            fh.write("# רשומת שיפור — פרומפט התרגום\n")
        fh.write(entry)


async def main() -> int:
    ap = argparse.ArgumentParser(description="לולאת שיפור לפרומפט התרגום")
    ap.add_argument("source", type=Path, help="SRT בשפת המקור")
    ap.add_argument("--language", default="en", help="שפת המקור")
    ap.add_argument("--lines", type=int, default=100,
                    help="כמה שורות לבדוק (ברירת מחדל 100)")
    ap.add_argument("--only", default="",
                    help="רשימת ווריאציות מופרדת בפסיקים")
    ap.add_argument("--repeat", type=int, default=1,
                    help="כמה פעמים להריץ כל ווריאציה ולמצע")
    args = ap.parse_args()

    chosen = ([v.strip() for v in args.only.split(",") if v.strip()]
              or list(VARIANTS))
    unknown = [v for v in chosen if v not in VARIANTS]
    if unknown:
        raise SystemExit(f"❌ לא מוכר: {', '.join(unknown)}. "
                         f"קיימות: {', '.join(VARIANTS)}")
    if "base" not in chosen:
        chosen.insert(0, "base")

    segments = load_segments(args.source, args.lines)
    print(f"📐 {len(segments)} שורות מ-{args.source.name} · "
          f"{len(chosen)} ווריאציות · {args.repeat} ריצות כל אחת")
    print("   (אותן שורות, אותו מסמך חקר — רק הפרומפט משתנה)\n")

    # החקר רץ פעם אחת ומשותף לכולן. אחרת כל ווריאציה הייתה מקבלת
    # מסמך אחר, והשוואה בין ווריאציות הייתה מודדת גם אותו
    print("⏳ מכין מסמך חקר אחד לכל הווריאציות…", flush=True)
    notes = await hebrew.research_notes(hebrew._numbered(segments),
                                        args.language, title="")

    results: list[Score] = []
    for name in chosen:
        runs: list[Score] = []
        for turn in range(args.repeat):
            tag = f"{name} ({turn + 1}/{args.repeat})" if args.repeat > 1 \
                else name
            print(f"⏳ {tag}…", flush=True)
            runs.append(await run_variant(name, VARIANTS[name], segments,
                                          args.language, notes))
        best = min(runs, key=lambda r: r.points)
        best.points = round(sum(r.points for r in runs) / len(runs), 1)
        best.seconds = sum(r.seconds for r in runs) / len(runs)
        results.append(best)
        print(f"   {best.points:.1f} נקודות\n")

    print("═" * 58)
    print("  ווריאציה            ציון    זמן   פגמים עיקריים")
    print("─" * 58)
    for score in sorted(results, key=lambda s: s.points):
        print(score.row())
    print("═" * 58)

    baseline = next(s for s in results if s.name == "base")
    winner = min(results, key=lambda s: s.points)
    if winner.name == "base":
        print("\n🟡 אף ווריאציה לא ניצחה את הבסיס. אל תשנה כלום.")
    else:
        gain = baseline.points - winner.points
        print(f"\n🟢 \"{winner.name}\" משפר ב-{gain:.1f} נקודות "
              f"({baseline.points:.1f} ⇠ {winner.points:.1f}).")
        if args.repeat < 2:
            print("   ⚠️ ריצה אחת. הרץ עם --repeat 3 לפני ששומרים —")
            print("      המודל אינו דטרמיניסטי וההפרש עלול להיות רעש.")
    remember(winner, baseline, args.source.name)
    print(f"\n💾 נרשם ב-{RECORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
