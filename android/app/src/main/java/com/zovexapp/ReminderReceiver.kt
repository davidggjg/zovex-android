package com.zovexapp

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * מקבל את האזעקה שנקבעה ב-ReminderModule ומציג את ההתראה.
 *
 * לחיצה על ההתראה פותחת את האפליקציה; אין כאן ניווט לערוץ מסוים כי הכוונה
 * היא שהמשתמש פשוט יגיע למסך ויבחר, ולא לקפוץ אותו ישר לשידור.
 */
class ReminderReceiver : BroadcastReceiver() {

    override fun onReceive(ctx: Context, intent: Intent) {
        val id = intent.getStringExtra(ReminderModule.EXTRA_ID) ?: return
        val title = intent.getStringExtra(ReminderModule.EXTRA_TITLE) ?: "תזכורת"
        val body = intent.getStringExtra(ReminderModule.EXTRA_BODY) ?: ""

        val open = ctx.packageManager.getLaunchIntentForPackage(ctx.packageName)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        val tap = if (open != null)
            PendingIntent.getActivity(ctx, id.hashCode(), open, flags) else null

        val n = NotificationCompat.Builder(ctx, ReminderModule.CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .apply { if (tap != null) setContentIntent(tap) }
            .build()

        // notify עלול לזרוק אם המשתמש שלל את ההרשאה אחרי שהתזכורת נקבעה —
        // זו לא שגיאה שצריכה להפיל את התהליך, פשוט אין התראה.
        try {
            NotificationManagerCompat.from(ctx).notify(id.hashCode(), n)
        } catch (_: SecurityException) {
        }
    }
}
