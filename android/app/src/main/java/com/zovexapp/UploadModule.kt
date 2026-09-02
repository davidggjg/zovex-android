package com.zovexapp

import android.app.NotificationManager
import android.net.Uri
import android.provider.OpenableColumns
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.ReadableMap
import com.facebook.react.bridge.WritableMap
import com.facebook.react.modules.core.DeviceEventManagerModule
import java.io.BufferedOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

// ── העלאת הקובץ לשרת ─────────────────────────────────────────────────────────
// למה נייטיבי ולא ה-XHR של React Native, שהוא מה שהיה כאן קודם:
//
// המסלול של RN שולח גוף מסוג uri דרך RequestBodyUtil.create, וזה קובע את אורך
// הגוף כך:
//
//     public long contentLength() { return inputStream.available(); }
//
// available() מחזיר int, שתקרתו 2,147,483,647. הזרם עצמו מחמיר: הבנאי של
// AssetFileDescriptor.AutoCloseInputStream ב-AOSP כותב
//
//     mRemaining = (int)fd.getLength();
//
// כלומר long נחתך ל-int. קובץ של 3.34GB יוצא ממנו מספר שלילי. התוצאה היא
// שהאורך שמוצהר לשרת אינו האורך האמיתי, החיבור נשבר באמצע, ו-JS רואה רק
// "כשל רשת" בלי שום רמז לסיבה. כל העלאה מעל 2GB במסלול הזה שבורה מעצם הגדרתה.
//
// כאן האורך מגיע מעמודת SIZE של ContentResolver — long אמיתי — ונמסר ל-
// setFixedLengthStreamingMode(long), שהוא הגרסה שנועדה בדיוק לגדלים האלה.
//
// ההעלאה רצה ב-thread נפרד, ולצידה שירות חזית שמונע מאנדרואיד להרוג את
// התהליך כשיוצאים מהאפליקציה. המצב נשמר גם כאן, כדי שמסך שנבנה מחדש יוכל
// להתחבר חזרה להעלאה שכבר רצה במקום להתחיל מאפס.
class UploadModule(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx) {

    companion object {
        private const val EVENT = "zovexUpload"
        // 256KB. גדול מספיק כדי שחוצץ השליחה של השקע יישאר מלא, וקטן מספיק
        // כדי לא להחזיק זיכרון מיותר לאורך העלאה של שעה.
        private const val BUF = 256 * 1024
        private const val PROGRESS_MS = 250L
        private const val NOTIF_MS = 1000L
    }

    @Volatile private var running = false
    @Volatile private var cancelRequested = false
    @Volatile private var sent = 0L
    @Volatile private var total = 0L
    @Volatile private var stage = "idle"     // idle|sending|done|error
    @Volatile private var job = ""
    @Volatile private var lastError = ""

    override fun getName() = "ZovexUploader"

    // נדרשים כדי ש-NativeEventEmitter בצד JS לא יתלונן. הפליטה עצמה עוברת
    // ב-DeviceEventEmitter ואינה תלויה בהם.
    @ReactMethod fun addListener(eventName: String) = Unit
    @ReactMethod fun removeListeners(count: Int) = Unit

    @ReactMethod
    fun getState(promise: Promise) = promise.resolve(snapshot())

    @ReactMethod
    fun cancel(promise: Promise) {
        cancelRequested = true
        promise.resolve(true)
    }

    @ReactMethod
    fun start(opts: ReadableMap, promise: Promise) {
        if (running) {
            promise.reject("BUSY", "כבר רצה העלאה")
            return
        }
        val uriStr = opts.getString("uri")
        val url = opts.getString("url")
        if (uriStr.isNullOrEmpty() || url.isNullOrEmpty()) {
            promise.reject("BAD_ARGS", "חסר קובץ או כתובת")
            return
        }
        val uri = Uri.parse(uriStr)
        val code = opts.getString("code") ?: ""
        val type = opts.getString("type") ?: "application/octet-stream"
        val name = opts.getString("name") ?: "video.mp4"
        val hinted = if (opts.hasKey("size")) opts.getDouble("size").toLong() else 0L

        running = true
        cancelRequested = false
        sent = 0L
        stage = "sending"
        job = ""
        lastError = ""
        total = if (hinted > 0) hinted else resolveSize(uri)

        UploadService.start(ctx, name)
        Thread({ doUpload(uri, url, code, type) }, "zovex-upload").start()
        promise.resolve(snapshot())
    }

    /** גודל הקובץ מ-ContentResolver. long, ולכן נכון גם מעל 2GB. */
    private fun resolveSize(uri: Uri): Long {
        try {
            ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val i = c.getColumnIndex(OpenableColumns.SIZE)
                    if (i >= 0 && !c.isNull(i)) return c.getLong(i)
                }
            }
        } catch (_: Exception) {
        }
        return 0L
    }

    private fun doUpload(uri: Uri, url: String, code: String, type: String) {
        var conn: HttpURLConnection? = null
        var input: InputStream? = null
        try {
            val stream = ctx.contentResolver.openInputStream(uri)
                ?: throw IOException("לא ניתן לפתוח את הקובץ")
            input = stream

            val c = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                useCaches = false
                connectTimeout = 30_000
                // 0 = בלי מגבלה. השרת עונה רק אחרי שקלט את כל הקובץ, וקובץ של
                // גיגה־בייטים לוקח זמן שאין טעם להגביל מראש.
                readTimeout = 0
                setRequestProperty("Content-Type", type)
                setRequestProperty("x-upload-code", code)
                setRequestProperty("Connection", "close")
                if (total > 0) {
                    // הגרסה שמקבלת long — זו שמעל 2GB עובדת בה.
                    setFixedLengthStreamingMode(total)
                } else {
                    // גודל לא ידוע: מוותרים על Content-Length ומשדרים בנתחים.
                    setChunkedStreamingMode(BUF)
                }
            }

            conn = c
            val out = BufferedOutputStream(c.outputStream, BUF)
            val buf = ByteArray(BUF)
            var lastProgress = 0L
            var lastNotif = 0L
            val started = System.currentTimeMillis()

            while (true) {
                if (cancelRequested) throw IOException("ההעלאה בוטלה")
                val n = stream.read(buf)
                if (n < 0) break
                if (n == 0) continue
                out.write(buf, 0, n)
                sent += n

                val now = System.currentTimeMillis()
                if (now - lastProgress >= PROGRESS_MS) {
                    lastProgress = now
                    emitProgress()
                }
                if (now - lastNotif >= NOTIF_MS) {
                    lastNotif = now
                    updateNotification(now - started)
                }
            }
            out.flush()

            val status = c.responseCode
            val body = try {
                (if (status in 200..299) c.inputStream else c.errorStream)
                    ?.bufferedReader()?.readText() ?: ""
            } catch (_: Exception) {
                ""
            }

            if (status == 200) {
                job = Regex("\"job\"\\s*:\\s*\"([^\"]+)\"").find(body)?.groupValues?.get(1) ?: ""
                stage = "done"
                emit("done") { it.putString("body", body); it.putString("job", job) }
            } else {
                stage = "error"
                lastError = detail(body) ?: "השרת החזיר $status"
                emit("error") { it.putString("error", lastError) }
            }
        } catch (e: Exception) {
            stage = if (cancelRequested) "idle" else "error"
            // כשהשרת דוחה מוקדם — קובץ גדול מהמותר, אין מקום בדיסק — הוא עונה
            // וסוגר בעוד אנחנו באמצע השליחה, והכתיבה נכשלת. בלי לקרוא כאן את
            // התשובה, ההסבר של השרת היה הולך לאיבוד והמשתמש היה רואה רק
            // "כשל רשת" — בדיוק הבלבול שהיה כאן קודם.
            val explained = try {
                conn?.let { k ->
                    val st = k.responseCode
                    val txt = k.errorStream?.bufferedReader()?.readText() ?: ""
                    detail(txt) ?: if (st > 0) "השרת החזיר $st" else null
                }
            } catch (_: Exception) {
                null
            }
            // אם אין הסבר מהשרת — ההודעה האמיתית של החריגה, ולא טקסט כללי:
            // כשזה נשבר שוב, מה שיופיע על המסך יהיה הסיבה ולא ניחוש.
            lastError = explained ?: (e.message ?: e.toString())
            emit("error") { it.putString("error", lastError) }
        } finally {
            try { input?.close() } catch (_: Exception) {}
            try { conn?.disconnect() } catch (_: Exception) {}
            running = false
            UploadService.stop(ctx)
        }
    }

    private fun detail(body: String): String? =
        Regex("\"detail\"\\s*:\\s*\"([^\"]*)\"").find(body)?.groupValues?.get(1)

    private fun updateNotification(elapsedMs: Long) {
        try {
            val pct = if (total > 0) ((100.0 * sent) / total).toInt() else -1
            val mb = { v: Long -> String.format(Locale.US, "%.1f", v / 1048576.0) }
            val speed = if (elapsedMs > 500) sent * 1000.0 / elapsedMs else 0.0
            val text = if (total > 0) {
                "$pct% · ${mb(sent)} מתוך ${mb(total)} MB" +
                    (if (speed > 0) " · ${String.format(Locale.US, "%.1f", speed / 1048576.0)} MB/שנ׳" else "")
            } else {
                "${mb(sent)} MB"
            }
            val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
            nm.notify(UploadService.NOTIF_ID,
                UploadService.notification(ctx, text, pct))
        } catch (_: Exception) {
        }
    }

    private fun emitProgress() {
        emit("progress") {}
    }

    private fun snapshot(): WritableMap = Arguments.createMap().apply {
        putBoolean("running", running)
        putString("stage", stage)
        putDouble("sent", sent.toDouble())
        putDouble("total", total.toDouble())
        putString("job", job)
        putString("error", lastError)
    }

    private fun emit(type: String, extra: (WritableMap) -> Unit) {
        try {
            val map = snapshot()
            map.putString("type", type)
            extra(map)
            if (ctx.hasActiveReactInstance()) {
                ctx.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
                    .emit(EVENT, map)
            }
        } catch (_: Exception) {
            // JS עשוי להיות מושהה כשהאפליקציה ברקע. ההעלאה לא תלויה בו —
            // המצב נשמר כאן, והמסך שואב אותו כשהוא חוזר.
        }
    }
}
