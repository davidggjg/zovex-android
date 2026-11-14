#!/usr/bin/env python3
"""משווה קובץ כתוביות שלנו לקובץ ייחוס אנושי של אותו פרק. בלי מודל.

    /opt/zovexsub/venv/bin/python bot/compare.py ours.he.srt reference.srt

שני מדדים, ושניהם נמדדים ולא מוערכים:

תזמון — כמה מהדיבור (לפי הייחוס) נשאר בלי כתובית, וכמה זמן כתובית
מוצגת כשאיש אינו מדבר.

מגדר פנייה — רק כשהייחוס בערבית, שמסמנת פנייה לאשה בכתב (كِ, أنتِ).
בשורות שבהן גם הערבית וגם העברית שלנו נושאות סימן פנייה חד-משמעי,
כמה פעמים הן מסכימות. זו היוריסטיקה על מדגם, לא ספירה מלאה: רוב
השורות אינן נושאות סימן ברור ואינן נספרות.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zovexsub import srt, studio   # noqa: E402

AR_F = re.compile(r"كِ|أنتِ|تِ(?![؀-ۿ])")
AR_SKIP = re.compile(r"ذلك|هناك|كذلك|هنالك|أولئك|تلك|شك|ملك|بنك")
AR_M = re.compile(r"(?<![؀-ۿ])أنت(?!ِ|م|ما|ن)"
                  r"|[؀-ۿ]ك(?![؀-ۿِ])")
HE_M = re.compile(
    r"(?<![א-ת])(אתה|תגיד|תראה|בוא|תסתכל|תקשיב|תירגע|תסביר|תן|קח|תשמע|"
    r"עזוב|חכה|תפסיק|תעצור|תישאר|שב|קום|תספר|תביא)(?![א-ת])")
HE_F = re.compile(
    r"(?<![א-ת])(תגידי|תראי|בואי|תסתכלי|תקשיבי|תירגעי|תסבירי|תני|קחי|"
    r"תשמעי|עזבי|חכי|תפסיקי|תעצרי|תישארי|שבי|קומי|תספרי|תביאי|לכי|"
    r"תיכנסי|תדאגי|את (?:יודעת|רוצה|יכולה|צריכה|הולכת|אומרת|עושה|"
    r"חושבת|מבינה|בסדר|לא|מדברת|באה|רואה))(?![א-ת])")


def _union(cues) -> list[list[float]]:
    out: list[list[float]] = []
    for start, end in sorted((c.start, c.end) for c in cues
                             if c.end > c.start):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def _minus(one, two) -> float:
    """כמה זמן יש ב-one ואין ב-two."""
    total = 0.0
    at = 0
    for start, end in one:
        cur = start
        while at < len(two) and two[at][1] <= cur:
            at += 1
        look = at
        while look < len(two) and two[look][0] < end:
            if two[look][0] > cur:
                total += two[look][0] - cur
            cur = max(cur, two[look][1])
            look += 1
        if cur < end:
            total += end - cur
    return total


def timing(ours, ref) -> dict:
    speech, shown = _union(ref), _union(ours)
    spoken = sum(e - s for s, e in speech)
    return {
        "speech": spoken,
        "unsubbed": _minus(speech, shown),
        "idle": _minus(shown, speech),
        "slivers": sum(1 for c in ours if c.end - c.start < 0.25),
    }


def _arabic(text: str) -> str:
    if AR_F.search(text):
        return "F"
    return "M" if AR_M.search(AR_SKIP.sub(" ", text)) else ""


def _hebrew(text: str) -> str:
    she, he = bool(HE_F.search(text)), bool(HE_M.search(text))
    return "F" if she and not he else "M" if he and not she else ""


def gender(ours, ref) -> dict:
    table: dict[tuple[str, str], int] = {}
    for theirs, mine in studio.align(ref, ours):
        a, h = _arabic(theirs), _hebrew(mine)
        if a and h:
            table[(a, h)] = table.get((a, h), 0) + 1
    return table


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    ours = srt.parse(srt.read_subtitle(Path(sys.argv[1])))
    ref = srt.parse(srt.read_subtitle(Path(sys.argv[2])))
    if not ours or not ref:
        print("אחד הקבצים לא נקרא")
        return 2
    t = timing(ours, ref)
    print(f"כתוביות: שלנו {len(ours)} · ייחוס {len(ref)}")
    print(f"דיבור בלי כתובית: {t['unsubbed']:.0f}ש "
          f"({100 * t['unsubbed'] / max(1, t['speech']):.0f}% מהדיבור)")
    print(f"כתובית בלי דיבור: {t['idle']:.0f}ש")
    print(f"כתוביות מתחת לרבע שנייה: {t['slivers']}")
    if not any("؀" <= ch <= "ۿ" for c in ref[:50] for ch in c.text):
        print("מגדר פנייה: הייחוס אינו בערבית — לא נמדד")
        return 0
    g = gender(ours, ref)
    total = sum(g.values())
    agree = g.get(("F", "F"), 0) + g.get(("M", "M"), 0)
    print(f"מגדר פנייה, {total} שורות עם סימן ברור בשני הצדדים:")
    print(f"  פנייה לאשה: נכון {g.get(('F', 'F'), 0)} · "
          f"יצא זכר {g.get(('F', 'M'), 0)}")
    print(f"  פנייה לגבר: נכון {g.get(('M', 'M'), 0)} · "
          f"יצא נקבה {g.get(('M', 'F'), 0)}")
    print(f"  הסכמה: {100 * agree // max(1, total)}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
