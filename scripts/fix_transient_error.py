#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# תקלת רשת רגעית גוררת החלפת מפענח מלאה.
#
# ## מה הקוד עושה היום
#
#     // מנסים על כל שגיאה ולא לפי קוד מסוים: מיפוי קודי ExoPlayer שביר
#     if (!vtSrc) { setVtSrc(vtFallbackSrc(src)); ... }
#
# ההערה כנה, וההחלטה הייתה סבירה כשהבעיה הייתה "AVI לא נפתח בכלל". אבל
# ‎onError‎ של ExoPlayer נורה גם על דברים חולפים לגמרי — timeout, חיבור
# שנקטע, 5xx רגעי — וכשמזרימים מטלגרם דרך השרת שלנו זה קורה באמצע סרטים
# תקינים.
#
# התוצאה: הנגן מדווח תקלה רגעית, האפליקציה מסיקה "הקובץ אינו ניתן
# לפענוח", עוברת להמרה בשרת, ומרכיבה את הנגן מחדש. זה מה שנראה כמו
# "מתנגן ואז קופץ להתחלה ומתחיל להיטען".
#
# ## ההבחנה
#
# ל-PlaybackException של ExoPlayer יש קודים מקובצים לפי משפחה:
#
#   2xxx  — קלט/פלט: רשת, timeout, סטטוס HTTP.  **חולף.**
#   3xxx  — ניתוח מכולה/מניפסט.                   **אמיתי.**
#   4xxx  — מפענח: אתחול, פורמט לא נתמך.          **אמיתי.**
#   1003  — timeout כללי.                          **חולף.**
#
# כשל חולף → ניסיון חוזר על **אותו מקור, מאותו מיקום**, עד שלוש פעמים.
# כשל אמיתי → נפילה להמרה בשרת, בדיוק כמו היום.
#
# מונה הניסיונות מתאפס אחרי 30 שניות נגינה רצופה, אחרת סרט של שעתיים היה
# מוגבל לשלוש תקלות רשת לכל אורכו.
#
# ## ובלי זה הניסיון החוזר היה מתחיל מאפס
#
# ‎onLoad‎ מדלג ל-‎startTime‎ — המיקום מהכניסה למסך. אחרי שעה של צפייה זה
# המקום הלא נכון, ולכן נוסף ‎resumeFromRef‎ שנושא את המיקום האמיתי.
#
#   python3 scripts/fix_transient_error.py [נתיב ל-NativePlayer.js]
#   python3 scripts/fix_transient_error.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import shutil
import sys

P = "src/components/NativePlayer.js"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "transientError"
BAK = P + ".before_transient"

OLD_STATE = '''  const [retryKey, setRetryKey] = useState(0);'''
NEW_STATE = '''  const [retryKey, setRetryKey] = useState(0);

  // [transientError] ניסיונות חוזרים על תקלת רשת, והמיקום לחזור אליו.
  //
  // onError נורה גם על דברים חולפים — timeout, חיבור שנקטע, סטטוס HTTP
  // רגעי — וכשמזרימים מטלגרם דרך השרת זה קורה באמצע סרטים תקינים. עד כה
  // כל שגיאה כזו נחשבה "הקובץ אינו ניתן לפענוח" והפעילה החלפת מפענח.
  const ioRetries = useRef(0);
  const lastErrPos = useRef(0);
  const resumeFromRef = useRef(0);
  const MAX_IO_RETRIES = 3;

  // קוד השגיאה של ExoPlayer מגיע לפעמים כמספר ולפעמים בתוך המחרוזת;
  // נלקח הראשון שנמצא.
  const errCode = e => {
    const x = (e && (e.error || e)) || {};
    const n = Number(x.errorCode);
    if (!Number.isNaN(n) && n > 0) return n;
    const m = String(x.errorString || x.errorException || '').match(/\\b([1-4]\\d{3})\\b/);
    return m ? Number(m[1]) : 0;
  };

  // 2xxx הוא משפחת הקלט/פלט של ExoPlayer — רשת, timeout, סטטוס HTTP —
  // ו-1003 הוא timeout כללי. 3xxx (ניתוח מכולה) ו-4xxx (מפענח) הם כשל
  // אמיתי בקובץ, ורק הם מצדיקים החלפת מסלול.
  const isTransient = code => code === 1003 || (code >= 2000 && code < 3000);'''

OLD_LOAD = '''          if (startTime > 1) seekTo(startTime);'''
NEW_LOAD = '''          // [transientError] המיקום האמיתי קודם ל-startTime: אחרי ניסיון
          // חוזר באמצע סרט, startTime הוא המיקום מהכניסה למסך ולא מהמקום
          // שבו הצופה נמצא.
          const wantAt = Math.max(resumeFromRef.current || 0, startTime || 0);
          if (wantAt > 1) seekTo(wantAt);'''

OLD_PROG = '''          posRef.current = p.currentTime || 0;'''
NEW_PROG = '''          posRef.current = p.currentTime || 0;
          // [transientError] נגינה רצופה מאפסת את מונה הניסיונות. בלעדיו
          // סרט של שעתיים היה מוגבל לשלוש תקלות רשת לכל אורכו.
          if (ioRetries.current &&
              (posRef.current - lastErrPos.current) > 30) {
            ioRetries.current = 0;
          }'''

OLD_ERR = '''          // ניסיון אחד למסלול ההמרה לפני שמדווחים כשלון. מנסים על כל
          // שגיאה ולא לפי קוד מסוים: מיפוי קודי ExoPlayer שביר, והמחיר
          // של ניסיון מיותר הוא שנייה אחת, בזמן שהמחיר של פספוס הוא
          // סרט שלא נפתח בכלל.
          if (!vtSrc) {'''
NEW_ERR = '''          // [transientError] תקלה חולפת — אותו מקור, אותו מיקום.
          //
          // זה הכשל שנראה כמו "מתנגן ואז קופץ להתחלה": timeout או חיבור
          // שנקטע באמצע סרט תקין הפעילו החלפת מפענח, כאילו הקובץ עצמו
          // פגום. כאן מנסים שוב את אותו הדבר לפני שמסיקים משהו על הקובץ.
          const _code = errCode(e);
          if (isTransient(_code) && ioRetries.current < MAX_IO_RETRIES) {
            ioRetries.current += 1;
            lastErrPos.current = posRef.current || 0;
            resumeFromRef.current = posRef.current || 0;
            if (debug) {
              setDiag(d => `${d}\\nתקלת רשת (${_code}) — ניסיון ` +
                `${ioRetries.current}/${MAX_IO_RETRIES} מ-` +
                `${Math.floor(resumeFromRef.current)}ש'`);
            }
            setReady(false);
            setRetryKey(k => k + 1);
            return;
          }
          // כשל אמיתי בקובץ (3xxx ניתוח, 4xxx מפענח) או שנגמרו הניסיונות:
          // ניסיון אחד למסלול ההמרה לפני שמדווחים כשלון. המחיר של ניסיון
          // מיותר הוא שנייה אחת, בזמן שהמחיר של פספוס הוא סרט שלא נפתח.
          if (!vtSrc) {'''

PAIRS = [(OLD_STATE, NEW_STATE), (OLD_LOAD, NEW_LOAD), (OLD_PROG, NEW_PROG),
         (OLD_ERR, NEW_ERR)]


def main():
    if REVERT:
        if not os.path.exists(BAK):
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(BAK, P)
        print("✓ שוחזר")
        return
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")
    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return
    for i, (old, _) in enumerate(PAIRS, 1):
        if s.count(old) != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} נמצא {s.count(old)} פעמים. "
                     f"לא נגעתי בכלום.")
    shutil.copy(P, BAK)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print("  2xxx/1003 → ניסיון חוזר · 3xxx/4xxx → החלפת מסלול")


if __name__ == "__main__":
    main()
