package com.zovexapp

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.OpenableColumns
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap

// ── בחירת סרטון מהמכשיר עצמו ──────────────────────────────────────────────────
// הבורר הקודם (react-native-image-picker) פתח את גוגל תמונות, שמציג גם פריטים
// שיושבים בענן ולא במכשיר. שתי בעיות בזה: סרט שהורדת יושב ב"הורדות" ובכלל לא
// מופיע שם, ופריט מהענן אינו קובץ מקומי — לבחור אותו פירושו להוריד אותו קודם.
//
// ACTION_OPEN_DOCUMENT פותח את בורר הקבצים של המערכת: הורדות, אחסון פנימי,
// כרטיס זיכרון. יחד עם EXTRA_LOCAL_ONLY, שהתיעוד של אנדרואיד מגדיר כ"an
// implementation should only allow the user to select data that is already on
// the device, not requiring it be downloaded from a remote service when
// opened", נשארים רק קבצים שכבר נמצאים על המכשיר.
//
// המודול גם מחזיר אורך ומידות. הן נשלחות לשרת ומשם לטלגרם — בלעדיהן ההודעה
// בטלגרם מציגה 0:00 ותצוגה מקדימה שחורה, כי טלגרם שומר בדיוק את מה שנמסר לו.
//
// אין כאן העתקה של הקובץ לתיקייה מקומית, בכוונה: ההעלאה שולחת את ה-content://
// כפי שהוא, ואנדרואיד פותח אותו דרך ContentResolver. העתקה של סרט שלם הייתה
// כופלת את הזמן ואת מקום האחסון בלי להוסיף דבר.
class VideoPickerModule(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx), ActivityEventListener {

    companion object {
        private const val REQ = 0x5A01
    }

    private var pending: Promise? = null

    init {
        ctx.addActivityEventListener(this)
    }

    override fun getName() = "VideoPicker"

    @ReactMethod
    fun pick(promise: Promise) {
        val act = currentActivity
        if (act == null) {
            promise.reject("NO_ACTIVITY", "האפליקציה אינה בחזית")
            return
        }
        // בקשה קודמת שלא נסגרה (המשתמש יצא בדרך שלא מחזירה תוצאה) לא נשארת
        // תלויה — אחרת ה-Promise שלה לעולם לא ייפתר וכפתור הבחירה ייתקע.
        pending?.resolve(cancelled())
        pending = promise

        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "video/*"
            putExtra(Intent.EXTRA_LOCAL_ONLY, true)
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false)
            addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
            )
        }
        try {
            act.startActivityForResult(intent, REQ)
        } catch (e: ActivityNotFoundException) {
            pending = null
            promise.reject("NO_PICKER", "אין במכשיר בורר קבצים", e)
        } catch (e: Exception) {
            pending = null
            promise.reject("PICK_FAILED", e.message, e)
        }
    }

    override fun onActivityResult(
        activity: Activity?,
        requestCode: Int,
        resultCode: Int,
        data: Intent?
    ) {
        if (requestCode != REQ) return
        val promise = pending ?: return
        pending = null

        val uri = data?.data
        if (resultCode != Activity.RESULT_OK || uri == null) {
            promise.resolve(cancelled())
            return
        }
        // קריאת המטא־דאטה פותחת את הקובץ ומפענחת ממנו פריים. על סרט זה לוקח
        // רגע, ואנחנו כאן על thread הממשק — ולכן היא עוברת ל-thread נפרד.
        Thread {
            try {
                promise.resolve(describe(uri))
            } catch (e: Exception) {
                promise.reject("READ_FAILED", e.message, e)
            }
        }.start()
    }

    override fun onNewIntent(intent: Intent?) = Unit

    private fun cancelled(): WritableMap =
        Arguments.createMap().apply { putBoolean("cancelled", true) }

    private fun describe(uri: Uri): WritableMap {
        // הרשאה מתמשכת, כדי שההעלאה תשרוד גם אם המסך נבנה מחדש. לא כל ספק
        // תומך בזה, ומי שלא — ההרשאה הזמנית של הבחירה מספיקה לנו.
        try {
            ctx.contentResolver.takePersistableUriPermission(
                uri, Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
        } catch (_: Exception) {
        }

        var name = "video.mp4"
        var size = 0.0
        try {
            ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (ni >= 0 && !c.isNull(ni)) name = c.getString(ni)
                    val si = c.getColumnIndex(OpenableColumns.SIZE)
                    if (si >= 0 && !c.isNull(si)) size = c.getLong(si).toDouble()
                }
            }
        } catch (_: Exception) {
        }

        var duration = 0.0
        var width = 0
        var height = 0
        val r = MediaMetadataRetriever()
        try {
            r.setDataSource(ctx, uri)
            duration = (r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L) / 1000.0
            width = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull() ?: 0
            height = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull() ?: 0
            // סרטון שצולם בטלפון נשמר לרוחב עם סימון סיבוב נפרד. טלגרם מצפה
            // למידות התצוגה, ולכן בסיבוב של רבע סיבוב מחליפים ביניהן — אחרת
            // סרטון אנכי היה מוצג כמלבן שכוב.
            val rot = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)
                ?.toIntOrNull() ?: 0
            if (rot == 90 || rot == 270) {
                val t = width
                width = height
                height = t
            }
        } catch (_: Exception) {
            // קובץ שאי אפשר לפענח עדיין ניתן להעלאה. נשארים באפסים, והשרת
            // ינסה להוציא את המטא־דאטה בעצמו עם ffprobe.
        } finally {
            try {
                r.release()
            } catch (_: Exception) {
            }
        }

        return Arguments.createMap().apply {
            putBoolean("cancelled", false)
            putString("uri", uri.toString())
            putString("name", name)
            putDouble("size", size)
            putDouble("duration", duration)
            putInt("width", width)
            putInt("height", height)
            putString("type", ctx.contentResolver.getType(uri) ?: "video/mp4")
        }
    }
}
