#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# נפילה בין נגנים מחזירה את הסרט להתחלה.
#
# ## התסמין
#
# הסרט מתנגן, ואחרי כמה דקות קופץ חזרה ל-0 ומתחיל להיטען מחדש. באתר אין
# את זה — כלומר השרת מגיש כרגיל, והבעיה בקוד האפליקציה.
#
# ## מה קורה
#
# שרשרת הנפילה היא VLC → ExoPlayer → המרה בשרת → WebView, וכל מדרגה
# נדרכת על ‎onError‎. המעבר עצמו תקין; מה שאבד הוא **המיקום**.
#
# ‎progressRef‎ מתעדכן בכל ‎onProgress‎ ויודע תמיד איפה הצופה נמצא, אבל
# נקודות הנפילה אינן קוראות אותו:
#
#   · ‎const at = nativeAudio.at‎ — המיקום שבו הנגינה *התחילה*
#   · ‎setVtFix({at: startTime || 0})‎ — המיקום מהכניסה למסך
#   · אפקט הדילוג של ה-WebView תלוי רק ב-‎resumeAt‎
#
# ולכן אחרי עשרים דקות צפייה, ‎at‎ הוא עדיין 0.
#
# ## ובאג שני באותו מקום
#
# אפקט הדילוג רץ רק כש-‎resumeAt‎ משתנה. נפילה מגדילה את ‎wvKey‎ ומרכיבה
# WebView חדש — ‎resumeAt‎ לא השתנה, האפקט לא נורה, ו**איש לא מקפיץ את
# הנגן החדש קדימה בכלל**. אפילו המיקום הישן לא היה חוזר.
#
# ## התיקון
#
# ‎resumePoint()‎ — המיקום האחרון הידוע, מ-‎progressRef‎ או מ-‎resumeAt‎,
# הגדול מביניהם. כל נקודת נפילה קוראת אותו, ואפקט הדילוג תלוי גם ב-
# ‎wvKey‎ כדי שיירה בכל הרכבה מחדש.
#
#   python3 scripts/fix_resume_on_fallback.py [נתיב ל-PlayerScreen.js]
#   python3 scripts/fix_resume_on_fallback.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import shutil
import sys

P = "src/screens/PlayerScreen.js"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "resumePoint"
BAK = P + ".before_resume"

OLD_REF = '''  const progressRef = useRef({position: startTime, duration: 0});'''
NEW_REF = '''  const progressRef = useRef({position: startTime, duration: 0});

  // [resumePoint] המיקום האחרון הידוע.
  //
  // שרשרת הנפילה (VLC → ExoPlayer → המרה בשרת → WebView) העבירה הלאה את
  // המיקום שבו הנגינה *התחילה*, לא את זה שבו הצופה נמצא. אחרי עשרים דקות
  // צפייה זה היה 0, ולכן כל נפילה החזירה את הסרט להתחלה.
  //
  // progressRef מתעדכן בכל onProgress ויודע תמיד איפה אנחנו; resumeAt הוא
  // נקודת ההחלטה בכניסה. הגדול מביניהם הוא התשובה הנכונה בכל מצב.
  const resumePoint = () =>
    Math.max(progressRef.current.position || 0, resumeAt || 0);'''

OLD_SEEK = '''    if (!resumeAt || !webViewRef.current) return;
    progressRef.current.position = resumeAt;
    webViewRef.current.injectJavaScript(
      `window._seekTo&&window._seekTo(${Math.floor(resumeAt)});true;`,
    );
  }, [resumeAt]);'''
NEW_SEEK = '''    // [resumePoint] תלוי גם ב-wvKey.
    //
    // האפקט רץ קודם רק כש-resumeAt משתנה. נפילה מגדילה את wvKey ומרכיבה
    // WebView חדש בלי ש-resumeAt זז — ולכן האפקט לא נורה, ואיש לא הקפיץ
    // את הנגן החדש קדימה בכלל.
    const at = resumePoint();
    if (!at || !webViewRef.current) return;
    progressRef.current.position = at;
    webViewRef.current.injectJavaScript(
      `window._seekTo&&window._seekTo(${Math.floor(at)});true;`,
    );
  }, [resumeAt, wvKey]);'''

OLD_VT = '''              setVtFix({src: alt, at: isLive ? 0 : (startTime || 0)});'''
NEW_VT = '''              // [resumePoint] מהמיקום הנוכחי, לא מהכניסה למסך
              setVtFix({src: alt, at: isLive ? 0 : resumePoint()});'''

OLD_AT = '''            const at = nativeAudio.at;'''
NEW_AT = '''            // [resumePoint] nativeAudio.at הוא המיקום שבו הנגינה התחילה;
            // אחרי צפייה ארוכה הוא כבר לא המקום שבו הצופה נמצא.
            const at = isLive ? 0 : resumePoint();'''

PAIRS = [(OLD_REF, NEW_REF, 1), (OLD_SEEK, NEW_SEEK, 1), (OLD_VT, NEW_VT, 1),
         # שני מופעים: אותה נפילה בדיוק בשני נגנים שונים בשרשרת
         (OLD_AT, NEW_AT, 2)]


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
    for i, (old, _, n) in enumerate(PAIRS, 1):
        if s.count(old) != n:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} נמצא {s.count(old)} פעמים "
                     f"(צפוי {n}). לא נגעתי בכלום.")
    shutil.copy(P, BAK)
    out = s
    for old, new, n in PAIRS:
        out = out.replace(old, new, n)
    io.open(P, "w", encoding="utf-8").write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print("  המיקום עובר בין כל מדרגות השרשרת")


if __name__ == "__main__":
    main()
