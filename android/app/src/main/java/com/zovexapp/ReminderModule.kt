package com.zovexapp

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationManagerCompat
import com.facebook.react.bridge.*

/**
 * "הזכר לי" לתוכנית בלוח השידורים.
 *
 * למה נייטיב ולא ספרייה: אין בפרויקט ספריית התראות, והוספת אחת כאן דורשת
 * קישור ידני ב-settings.gradle (הפרויקט מקשר מודולים ידנית, וכבר נשברה בגלל
 * זה בנייה בעבר). למה לא דרך השרת: התראה שנשלחת מבחוץ דורשת אינטרנט ברגע
 * המדויק ועוד שרת שיחזיק תור. AlarmManager עושה את זה מקומית, עובד גם במטוס,
 * ולא מוסיף שום תלות — בדיוק כמו PipModule ו-ApkInstallerModule שכבר כאן.
 *
 * ההתראה נורית דקה *לפני* תחילת התוכנית, כדי שיהיה זמן להגיע לטלוויזיה.
 * משתמשים ב-setWindow ולא ב-setExact: החל מאנדרואיד 12 התראה מדויקת דורשת
 * הרשאה מיוחדת שהמשתמש צריך לאשר בהגדרות, וחלון של דקה הוא בדיוק אותה
 * תועלת בלי המחסום הזה.
 */
class ReminderModule(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx) {

    override fun getName() = "ReminderModule"

    companion object {
        const val CHANNEL_ID = "zovex_reminders"
        const val EXTRA_TITLE = "title"
        const val EXTRA_BODY = "body"
        const val EXTRA_ID = "id"
        private const val LEAD_MS = 60_000L      // דקה לפני ההתחלה
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "תזכורות לשידורים", NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "תזכורת לפני שתוכנית מתחילה" }
        )
    }

    private fun intentFor(id: String, title: String, body: String): PendingIntent {
        val i = Intent(ctx, ReminderReceiver::class.java).apply {
            putExtra(EXTRA_ID, id)
            putExtra(EXTRA_TITLE, title)
            putExtra(EXTRA_BODY, body)
        }
        // FLAG_IMMUTABLE חובה מאנדרואיד 12; בלעדיו המערכת זורקת חריגה.
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        return PendingIntent.getBroadcast(ctx, id.hashCode(), i, flags)
    }

    /** האם התראות מותרות בכלל (המשתמש יכול לכבות אותן להתקנה כולה). */
    @ReactMethod
    fun canNotify(promise: Promise) {
        promise.resolve(NotificationManagerCompat.from(ctx).areNotificationsEnabled())
    }

    /** מבקש את ההרשאה באנדרואיד 13 ומעלה. בגרסאות ישנות אין מה לבקש. */
    @ReactMethod
    fun requestPermission() {
        if (Build.VERSION.SDK_INT < 33) return
        val act = currentActivity ?: return
        ActivityCompat.requestPermissions(
            act, arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 7311
        )
    }

    /**
     * @param atSeconds מתי התוכנית מתחילה (epoch שניות, כמו בלוח השידורים).
     * מחזיר false אם הזמן כבר עבר — כדי שהממשק לא יסמן תזכורת שלא תגיע.
     */
    @ReactMethod
    fun schedule(id: String, atSeconds: Double, title: String, body: String, promise: Promise) {
        try {
            val fireAt = (atSeconds * 1000).toLong() - LEAD_MS
            if (fireAt <= System.currentTimeMillis()) { promise.resolve(false); return }
            ensureChannel()
            val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            am.setWindow(
                AlarmManager.RTC_WAKEUP, fireAt, 60_000L, intentFor(id, title, body)
            )
            promise.resolve(true)
        } catch (e: Exception) {
            promise.reject("schedule_failed", e)
        }
    }

    @ReactMethod
    fun cancel(id: String, promise: Promise) {
        try {
            val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            am.cancel(intentFor(id, "", ""))
            promise.resolve(true)
        } catch (e: Exception) {
            promise.resolve(false)
        }
    }
}
