package com.zovexapp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

// ── שירות חזית שמחזיק את ההעלאה בחיים ────────────────────────────────────────
// כשיוצאים מהאפליקציה אנדרואיד רשאי להרוג את התהליך, ואיתו את ההעלאה. שירות
// חזית עם התראה הוא המנגנון שמונע את זה — כל עוד הוא רץ, התהליך נשאר.
//
// ההעלאה עצמה יושבת ב-UploadModule ולא כאן, כי היא צריכה גישה ל-ReactContext
// כדי לדווח התקדמות ל-JS. שניהם באותו תהליך, ולכן השירות הזה מגן גם עליה.
//
// מאנדרואיד 14 שירות חזית חייב להצהיר על סוג. "dataSync" הוא הסוג המתאים
// להעברת קבצים, והוא דורש הרשאה נפרדת שמוצהרת במניפסט.
class UploadService : Service() {

    companion object {
        const val CHANNEL_ID = "zovex_upload"
        const val NOTIF_ID = 0x2050
        const val EXTRA_TEXT = "text"

        fun start(ctx: Context, text: String) {
            val i = Intent(ctx, UploadService::class.java).putExtra(EXTRA_TEXT, text)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                ctx.startForegroundService(i)
            } else {
                ctx.startService(i)
            }
        }

        fun stop(ctx: Context) {
            try {
                ctx.stopService(Intent(ctx, UploadService::class.java))
            } catch (_: Exception) {
            }
        }

        /** בונה את ההתראה. משמש גם לעדכוני ההתקדמות מתוך UploadModule. */
        fun notification(ctx: Context, text: String, pct: Int): Notification {
            ensureChannel(ctx)
            val open = PendingIntent.getActivity(
                ctx, 0,
                Intent(ctx, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                Notification.Builder(ctx, CHANNEL_ID)
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(ctx)
            }
            b.setContentTitle("ZOVEX — מעלה סרטון")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_upload)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(open)
            if (pct in 0..100) b.setProgress(100, pct, false)
            else b.setProgress(0, 0, true)
            return b.build()
        }

        private fun ensureChannel(ctx: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
            if (nm.getNotificationChannel(CHANNEL_ID) != null) return
            val ch = NotificationChannel(
                CHANNEL_ID, "העלאות",
                NotificationManager.IMPORTANCE_LOW      // בלי צליל, זו התקדמות
            )
            ch.setShowBadge(false)
            nm.createNotificationChannel(ch)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "מתחיל…"
        val n = notification(this, text, -1)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else {
                startForeground(NOTIF_ID, n)
            }
        } catch (_: Exception) {
            // אם המערכת סירבה (מדיניות רקע נוקשה), ההעלאה עדיין תרוץ כל עוד
            // האפליקציה בחזית. עדיף מלהקריס.
        }
        // START_NOT_STICKY: אם המערכת בכל זאת הרגה את התהליך, אין טעם להחיות
        // שירות בלי ההעלאה שהוא שמר עליה.
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                stopForeground(STOP_FOREGROUND_REMOVE)
            } else {
                @Suppress("DEPRECATION")
                stopForeground(true)
            }
        } catch (_: Exception) {
        }
        super.onDestroy()
    }
}
