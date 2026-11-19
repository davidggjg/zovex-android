package com.zovexapp

import android.content.Context
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * רישום קריסות, כדי להפסיק לנחש.
 *
 * דווח שהאפליקציה מקריסה את הטלוויזיה ביציאה וחזרה. בלי adb אין דרך
 * לראות מה קרה, וכל תיקון הוא ניחוש — ולכן הדבר הראשון הוא לגרום
 * לאפליקציה לספר בעצמה.
 *
 * מה זה **כן** תופס: כל חריגה לא-מטופלת ב-Java/Kotlin, כולל אלה שמגיעות
 * מ-React Native עצמו, מ-ExoPlayer, מה-WebView וממודולים נייטיביים. זה
 * רוב המקרים שבהם "האפליקציה נסגרת לבד".
 *
 * מה זה **לא** תופס: קריסת signal נייטיבית (SIGSEGV במפענח וידאו,
 * קריסת renderer של WebView בתהליך נפרד). לאלה צריך breakpad/NDK, וזו
 * תלות גדולה בהרבה. אם יתברר שזה המקרה, הקובץ הזה פשוט יישאר ריק אחרי
 * קריסה — וגם זה מידע.
 *
 * הכתיבה היא לקובץ ולא לרשת: ברגע הקריסה אין זמן לבקשת רשת, והתהליך
 * נהרג מיד אחרי ה-handler. הקובץ נקרא בהפעלה הבאה ומוצג בהגדרות.
 */
class CrashLog(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx) {

    override fun getName() = "CrashLog"

    companion object {
        private const val FILE = "zovex_last_crash.txt"
        private const val MAX_CHARS = 8000

        fun file(c: Context) = File(c.filesDir, FILE)

        /**
         * נרשם פעם אחת ב-MainApplication.onCreate. חשוב: שומרים את
         * ה-handler הקודם וקוראים לו בסוף — אחרת אנחרוג את התנהגות
         * הקריסה של אנדרואיד עצמו, והאפליקציה הייתה נתקעת במקום להיסגר.
         */
        fun install(app: android.app.Application) {
            val prev = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { thread, err ->
                try {
                    val sw = StringWriter()
                    err.printStackTrace(PrintWriter(sw))
                    val when_ = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                        .format(Date())
                    val text = buildString {
                        append("ZOVEX crash\n")
                        append("מתי: ").append(when_).append('\n')
                        append("גרסה: ").append(BuildConfig.VERSION_NAME)
                            .append(" (").append(BuildConfig.VERSION_CODE).append(")\n")
                        append("מכשיר: ").append(android.os.Build.MANUFACTURER)
                            .append(' ').append(android.os.Build.MODEL)
                            .append(" / Android ").append(android.os.Build.VERSION.RELEASE)
                            .append(" (API ").append(android.os.Build.VERSION.SDK_INT).append(")\n")
                        append("thread: ").append(thread.name).append('\n')
                        append("זיכרון: ").append(memLine()).append('\n')
                        append("---\n")
                        append(sw.toString().take(MAX_CHARS))
                    }
                    file(app).writeText(text)
                } catch (_: Throwable) {
                    // אסור שרישום הקריסה יקריס בעצמו.
                }
                prev?.uncaughtException(thread, err)
            }
        }

        private fun memLine(): String = try {
            val r = Runtime.getRuntime()
            val usedMb = (r.totalMemory() - r.freeMemory()) / 1048576
            val maxMb = r.maxMemory() / 1048576
            "$usedMb/$maxMb MB"
        } catch (_: Throwable) {
            "?"
        }
    }

    /** מחזיר את הקריסה האחרונה, או מחרוזת ריקה אם אין. */
    @ReactMethod
    fun getLastCrash(promise: Promise) {
        try {
            val f = file(ctx)
            promise.resolve(if (f.exists()) f.readText() else "")
        } catch (e: Throwable) {
            promise.resolve("")
        }
    }

    @ReactMethod
    fun clearLastCrash(promise: Promise) {
        try {
            file(ctx).delete()
        } catch (_: Throwable) {
        }
        promise.resolve(true)
    }

    /**
     * רישום של שגיאת JS שלא נתפסה. קריסת JS אינה מגיעה ל-handler של
     * Java, ולכן היא נרשמת מצד ה-JS דרך כאן ונקראת באותו מקום.
     */
    @ReactMethod
    fun recordJsError(text: String, promise: Promise) {
        try {
            file(ctx).writeText(text.take(MAX_CHARS))
        } catch (_: Throwable) {
        }
        promise.resolve(true)
    }
}
