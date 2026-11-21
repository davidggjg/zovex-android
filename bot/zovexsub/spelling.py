"""בדיקת איות עברית: מוצא מילים שאינן מילים, ושולח רק אותן לתיקון.

המודל כותב לפעמים מילה שאינה קיימת — "לסייום", "נשעפת", "בבבקשה" —
ובקרת האיכות שלו אינה רואה אותה, כי מי שכתב את השגיאה קורא אותה
כתקינה. מילון אינו טועה כך. המילון הוא Hspell (בפורמט hunspell),
והוא מכיר הטיות ותחיליות: "וכשהלכתי" מוכרת לו.

נמדד על שני קבצים שהבוט הוציא: מתוך כ-2000 מילים שונות בסרט, 36 עד
56 אינן מוכרות ומופיעות פעם אחת בלבד, ובהן כל שגיאות הכתיב שנמצאו
ביד. השאר שמות ומילים לועזיות — ולכן המילון רק **מסמן**, והתיקון
נעשה מול המקור, עם הוראה להשאיר שמות.

מילה לא מוכרת שחוזרת בסרט היא שם של דמות ואינה מסומנת כלל.

המילון רץ בתהליך נפרד וקצר: הוא תופס כ-400MB בזיכרון, ואין סיבה
שהבוט יחזיק אותם בין סרט לסרט.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

# מילה עם גרש בתוכה ("פיג'מה", "ג'ינס") נקראת שלמה — ואז מדולגת,
# כי היא לועזית ואין למילון מה לומר עליה. בלי זה "בפיג" סומנה כשגיאה
WORD = re.compile(r"[א-ת]+(?:['׳][א-ת]+)*['׳]?")
SHORTEST = 3


def dictionary() -> Path:
    """הנתיב בלי סיומת: לידו יושבים he_IL.aff ו-he_IL.dic."""
    return Path(config.SPELL_DICT)


def available() -> bool:
    base = dictionary()
    if not (base.with_suffix(".aff").exists()
            and base.with_suffix(".dic").exists()):
        return False
    try:
        import spylls.hunspell  # noqa: F401
    except ImportError:
        return False
    return True


def candidates(lines: list[str], known: str = "") -> dict[str, list[int]]:
    """המילים שכדאי לשאול עליהן את המילון, ובאילו שורות כל אחת.

    רק מילה שמופיעה פעם אחת בכל הסרט: מילה לא מוכרת שחוזרת היא שם.
    ‏known הוא טקסט שכל מילה בו מוכרת מראש — מסמך הדמויות
    """
    seen: Counter = Counter()
    where: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        for word in WORD.findall(line or ""):
            seen[word] += 1
            where.setdefault(word, []).append(index)
    names = set(WORD.findall(known or ""))
    return {word: where[word] for word, count in seen.items()
            if count == 1 and len(word) >= SHORTEST and word not in names
            and "'" not in word and "׳" not in word}


async def unknown(words: list[str]) -> list[str] | None:
    """המילים שהמילון אינו מכיר, או None כשהבדיקה אינה זמינה."""
    if not words:
        return []
    if not config.SPELL_CHECK or not available():
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "zovexsub.spelling", str(dictionary()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parent.parent))
        out, err = await asyncio.wait_for(
            proc.communicate(json.dumps(words).encode("utf-8")), timeout=90)
    except (asyncio.TimeoutError, OSError) as exc:
        log.warning("בדיקת האיות נכשלה (%s)", exc)
        return None
    if proc.returncode != 0:
        log.warning("בדיקת האיות נכשלה: %s",
                    err.decode("utf-8", "replace").strip()[-200:])
        return None
    try:
        return list(json.loads(out.decode("utf-8")))
    except ValueError:
        return None


async def suspects(lines: list[str], known: str = "") -> dict[int, list[str]]:
    """שורה → המילים החשודות שבה. ריק כשאין, או כשהבדיקה אינה זמינה."""
    asked = candidates(lines, known)
    bad = await unknown(sorted(asked))
    if not bad:
        return {}
    out: dict[int, list[str]] = {}
    for word in bad:
        for index in asked.get(word, []):
            out.setdefault(index, []).append(word)
    return out


def _main() -> int:
    from spylls.hunspell import Dictionary
    book = Dictionary.from_files(sys.argv[1])
    words = json.loads(sys.stdin.read() or "[]")
    json.dump([w for w in words if not book.lookup(w)], sys.stdout,
              ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
