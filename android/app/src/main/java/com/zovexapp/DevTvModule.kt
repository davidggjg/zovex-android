package com.zovexapp

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.KeyEvent
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

/**
 * מצב "טלוויזיה" על הטלפון, לבדיקה.
 *
 * למה נייטיב ולא דגל ב-JS: ‎IS_TV‎ נקרא בזמן טעינת המודולים — ‎StyleSheet.create‎
 * רץ אז, ומספר קבועים (מספר העמודות, גובה הבאנר, המקדם) מחושבים אז. דגל
 * שנקרא מאוחר לא היה משנה דבר מהם. לכן הוא נשמר ב-SharedPreferences
 * ונחשף כ-**constant** של המודול, שנקרא סינכרונית עוד לפני שורת ה-JS
 * הראשונה. שינוי שלו דורש הפעלה מחדש, וזה מה ש-restart עושה.
 *
 * ‎sendKey‎ שולח KeyEvent אמיתי ל-Activity. זו הנקודה שהופכת את זה לבדיקה
 * אמיתית ולא לחיקוי: אנדרואיד מריץ את אותו חיפוש focus גאומטרי, אותה
 * גלילה, ואותו ‎requestRectangleOnScreen‎ שרץ על טלוויזיה — כלומר מה
 * שנראה על הטלפון הוא ההתנהגות האמיתית, לא הדמיה שלה.
 */
class DevTvModule(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx) {

    override fun getName() = "DevTv"

    companion object {
        private const val PREFS = "zovex_dev"
        private const val KEY = "tv_emulation"

        fun isEnabled(c: Context): Boolean = try {
            c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY, false)
        } catch (_: Throwable) {
            false
        }
    }

    override fun getConstants(): MutableMap<String, Any> =
        hashMapOf("tvEmulation" to isEnabled(ctx))

    @ReactMethod
    fun setTvEmulation(on: Boolean, promise: Promise) {
        try {
            ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putBoolean(KEY, on).commit()   // commit ולא apply: מיד אחרי זה מפעילים מחדש
            promise.resolve(true)
        } catch (e: Throwable) {
            promise.reject("set_failed", e.message, e)
        }
    }

    /**
     * מפעיל את האפליקציה מחדש. הדגל נקרא בטעינת המודולים, ולכן אין דרך
     * להחיל אותו בלי זה.
     */
    @ReactMethod
    fun restart(promise: Promise) {
        try {
            val act = currentActivity
            val intent = ctx.packageManager
                .getLaunchIntentForPackage(ctx.packageName)
                ?.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
            promise.resolve(true)
            Handler(Looper.getMainLooper()).postDelayed({
                try {
                    ctx.startActivity(intent)
                    act?.finish()
                    // הרג התהליך הוא מה שמבטיח שהמודולים ייטענו מחדש; בלעדיו
                    // ה-bundle נשאר בזיכרון עם הערכים הישנים.
                    android.os.Process.killProcess(android.os.Process.myPid())
                } catch (_: Throwable) {
                }
            }, 250)
        } catch (e: Throwable) {
            promise.reject("restart_failed", e.message, e)
        }
    }

    /** שולח לחיצת מקש אמיתית (KeyEvent) ל-Activity הנוכחית. */
    @ReactMethod
    fun sendKey(keyCode: Int, promise: Promise) {
        val act = currentActivity
        if (act == null) {
            promise.resolve(false)
            return
        }
        Handler(Looper.getMainLooper()).post {
            try {
                val t = SystemClock.uptimeMillis()
                // שני אירועים, DOWN ו-UP, כמו שלט אמיתי. ‎onKeyUp‎ ב-
                // TvFocusableView הוא מה שמזהה את מקש האישור, ולכן בלי
                // ה-UP כפתור "אישור" לא היה עושה כלום.
                act.dispatchKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_DOWN, keyCode, 0))
                act.dispatchKeyEvent(
                    KeyEvent(t, SystemClock.uptimeMillis(), KeyEvent.ACTION_UP, keyCode, 0))
            } catch (_: Throwable) {
            }
        }
        promise.resolve(true)
    }
}
