package com.zovexapp

import android.app.NotificationManager
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.ReadableMap
import com.facebook.react.bridge.WritableMap
import com.facebook.react.modules.core.DeviceEventManagerModule
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.FileInputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

// ── העלאת הקובץ לשרת ─────────────────────────────────────────────────────────
// שתי בעיות נפרדות הובילו לקוד הזה.
//
// ① קבצים מעל 2GB פשוט לא עבדו. המסלול של React Native קובע את אורך הגוף לפי
//    `inputStream.available()`, שמחזיר int; והזרם עצמו גרוע יותר, כי הבנאי של
//    AssetFileDescriptor.AutoCloseInputStream ב-AOSP כותב
//    `mRemaining = (int)fd.getLength()` — long שנחתך ל-int, ולקובץ של 3.34GB
//    יוצא משם מספר שלילי. האורך שהוצהר לשרת לא היה האורך האמיתי, החיבור
//    נשבר, וכל מה שהגיע ל-JS היה "כשל רשת".
//
// ② חיבור בודד לא מילא את הקו: 3GB ב-56 דקות, כלומר 7.7 מגהביט, בזמן שהקו
//    אמור לתת כפול. זו החתימה של חלון TCP שמוגבל בהשהיה ובאיבוד חבילות — לא
//    של קו שנגמר לו הרוחב. הפתרון המקובל הוא כמה חיבורים במקביל, בדיוק כמו
//    מנהלי הורדות ו-S3 multipart.
//
// לכן הקובץ נשלח בחלקים, ב-PARALLEL חיבורים בו-זמנית, כשכל חלק נכתב בשרת
// ישירות להיסט שלו. הגודל נלקח מעמודת SIZE של ContentResolver — long אמיתי —
// ונמסר ל-setFixedLengthStreamingMode(long).
//
// חלק שנכשל נשלח שוב לבדו, ולא הקובץ כולו. בהעלאה של שעה זה ההבדל בין תקלה
// לבין אסון.
//
// אם השרת אינו מכיר את המסלול הזה (גרסה ישנה), נופלים בחזרה להעלאה בבקשה
// אחת — כך שאפליקציה חדשה מול שרת ישן עדיין עובדת.
class UploadModule(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx) {

    companion object {
        private const val EVENT = "zovexUpload"
        private const val BUF = 256 * 1024
        // נמדד: עם 4 חיבורים ההעלאה הגיעה ל-9.2 מגהביט, ובמקביל אליה
        // Speedtest הוציא מאותו קו עוד 5.55 — כלומר הקו נותן ~14.75 ורק 62%
        // ממנו נוצלו. כל חיבור נחנק בנפרד סביב 2.3 מגהביט, ולכן התשובה היא
        // עוד חיבורים ולא חיבורים מהירים יותר.
        private const val PARALLEL = 8
        private const val PART_RETRIES = 4
        private const val PROGRESS_MS = 250L
        private const val NOTIF_MS = 1000L
    }

    @Volatile private var running = false
    @Volatile private var cancelRequested = false
    @Volatile private var total = 0L
    @Volatile private var stage = "idle"     // idle|sending|done|error
    @Volatile private var job = ""
    @Volatile private var lastError = ""
    @Volatile private var mode = ""          // parallel|single
    @Volatile private var activeWorkers = 0
    private val sentBytes = AtomicLong(0)
    @Volatile private var startedAt = 0L

    override fun getName() = "ZovexUploader"

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
        val base = opts.getString("base")
        if (uriStr.isNullOrEmpty() || base.isNullOrEmpty()) {
            promise.reject("BAD_ARGS", "חסר קובץ או כתובת")
            return
        }
        val uri = Uri.parse(uriStr)
        val code = opts.getString("code") ?: ""
        val type = opts.getString("type") ?: "application/octet-stream"
        val name = opts.getString("name") ?: "video.mp4"
        val caption = opts.getString("caption") ?: ""
        val hinted = if (opts.hasKey("size")) opts.getDouble("size").toLong() else 0L
        val duration = if (opts.hasKey("duration")) opts.getDouble("duration").toLong() else 0L
        val width = if (opts.hasKey("width")) opts.getInt("width") else 0
        val height = if (opts.hasKey("height")) opts.getInt("height") else 0

        running = true
        cancelRequested = false
        sentBytes.set(0)
        stage = "sending"
        job = ""
        lastError = ""
        mode = ""
        startedAt = System.currentTimeMillis()
        total = if (hinted > 0) hinted else resolveSize(uri)

        UploadService.start(ctx, name)
        Thread({
            drive(uri, base, code, type, name, caption, duration, width, height)
        }, "zovex-upload").start()
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

    // ── הזרימה הראשית ────────────────────────────────────────────────────────

    private fun drive(
        uri: Uri, base: String, code: String, type: String,
        name: String, caption: String, duration: Long, width: Int, height: Int
    ) {
        try {
            var begun: JSONObject? = null
            if (total > 0) {
                begun = try {
                    begin(base, code, name, caption, total, duration, width, height)
                } catch (e: ServerRefusal) {
                    // השרת אמר לא מסיבה אמיתית (קובץ גדול מדי, אין מקום).
                    // אין טעם לנסות במסלול אחר.
                    throw e
                } catch (_: Exception) {
                    null      // שרת שאינו מכיר את המסלול — נופלים לבקשה אחת
                }
            }

            if (begun != null) {
                mode = "parallel"
                job = begun.optString("job", "")
                val partSize = begun.optLong("part_size", 8L * 1024 * 1024)
                val nParts = begun.optInt("n_parts", 0)
                if (job.isEmpty() || nParts <= 0) throw IOException("תשובת begin שגויה")
                uploadParts(uri, base, code, partSize, nParts)
                if (cancelRequested) throw IOException("ההעלאה בוטלה")
                finish(base, code, job)
            } else {
                mode = "single"
                singleUpload(uri, base, code, type, name, caption, duration, width, height)
            }

            stage = "done"
            emit("done") { it.putString("job", job) }
        } catch (e: Exception) {
            stage = if (cancelRequested) "idle" else "error"
            lastError = e.message ?: e.toString()
            emit("error") { it.putString("error", lastError) }
        } finally {
            running = false
            UploadService.stop(ctx)
        }
    }

    /** שגיאה שהשרת הסביר — לא מנסים מסלול אחר אחריה. */
    private class ServerRefusal(msg: String) : IOException(msg)

    // ── שלב 1: פתיחת משימה ───────────────────────────────────────────────────

    private fun begin(
        base: String, code: String, name: String, caption: String,
        size: Long, duration: Long, width: Int, height: Int
    ): JSONObject {
        val payload = JSONObject().apply {
            put("code", code)
            put("name", name)
            put("caption", caption)
            put("size", size)
            put("duration", duration)
            put("width", width)
            put("height", height)
        }.toString().toByteArray(Charsets.UTF_8)

        val c = open("$base/panel/saved-upload/begin", code, "application/json")
        c.setFixedLengthStreamingMode(payload.size)
        c.outputStream.use { it.write(payload) }
        val status = c.responseCode
        val body = readBody(c, status)
        c.disconnect()
        if (status == 404 || status == 405) throw IOException("המסלול אינו קיים בשרת")
        if (status != 200) throw ServerRefusal(detail(body) ?: "השרת החזיר $status")
        return JSONObject(body)
    }

    // ── שלב 2: החלקים, במקביל ────────────────────────────────────────────────

    private fun uploadParts(
        uri: Uri, base: String, code: String, partSize: Long, nParts: Int
    ) {
        val next = AtomicInteger(0)
        val failure = AtomicReference<Exception?>(null)
        val workers = minOf(PARALLEL, nParts)
        activeWorkers = workers

        val threads = (0 until workers).map { w ->
            Thread(Runnable {
                while (failure.get() == null && !cancelRequested) {
                    val i = next.getAndIncrement()
                    if (i >= nParts) break
                    val offset = i * partSize
                    val len = minOf(partSize, total - offset)
                    if (len <= 0) continue
                    try {
                        sendPartWithRetry(uri, base, code, i, offset, len)
                    } catch (e: Exception) {
                        failure.compareAndSet(null, e)
                        return@Runnable
                    }
                }
            }, "zovex-part-$w")
        }
        threads.forEach { it.start() }
        threads.forEach { it.join() }
        failure.get()?.let { throw it }
        if (cancelRequested) throw IOException("ההעלאה בוטלה")
    }

    private fun sendPartWithRetry(
        uri: Uri, base: String, code: String, index: Int, offset: Long, len: Long
    ) {
        var attempt = 0
        var last: Exception? = null
        while (attempt < PART_RETRIES && !cancelRequested) {
            val before = sentBytes.get()
            try {
                sendPart(uri, base, code, index, offset, len)
                return
            } catch (e: ServerRefusal) {
                throw e                       // הסבר מהשרת — אין טעם לחזור
            } catch (e: Exception) {
                last = e
                // מה שנשלח בניסיון שנכשל אינו נספר, אחרת ההתקדמות הייתה
                // מטפסת מעל 100% אחרי כל ניסיון חוזר.
                sentBytes.set(before)
                attempt++
                if (attempt < PART_RETRIES) {
                    try {
                        Thread.sleep(1000L * (1L shl (attempt - 1)))
                    } catch (_: InterruptedException) {
                    }
                }
            }
        }
        throw last ?: IOException("חלק $index נכשל")
    }

    private fun sendPart(
        uri: Uri, base: String, code: String, index: Int, offset: Long, len: Long
    ) {
        var pfd: ParcelFileDescriptor? = null
        var conn: HttpURLConnection? = null
        try {
            pfd = ctx.contentResolver.openFileDescriptor(uri, "r")
                ?: throw IOException("לא ניתן לפתוח את הקובץ")
            val fis = FileInputStream(pfd.fileDescriptor)
            // ערוץ משלו לכל עובד, ולכן ההיסטים אינם מתנגשים.
            fis.channel.position(offset)

            val c = open(
                "$base/panel/saved-upload/part?job=" + enc(job) + "&index=" + index,
                code, "application/octet-stream"
            )
            conn = c
            c.setFixedLengthStreamingMode(len)
            val out = BufferedOutputStream(c.outputStream, BUF)
            val buf = ByteArray(BUF)
            var left = len
            var lastTick = 0L
            while (left > 0) {
                if (cancelRequested) throw IOException("ההעלאה בוטלה")
                val want = minOf(BUF.toLong(), left).toInt()
                val n = fis.read(buf, 0, want)
                if (n < 0) throw IOException("הקובץ נגמר לפני הצפוי")
                if (n == 0) continue
                out.write(buf, 0, n)
                left -= n
                sentBytes.addAndGet(n.toLong())
                val now = System.currentTimeMillis()
                if (now - lastTick >= PROGRESS_MS) {
                    lastTick = now
                    tick()
                }
            }
            out.flush()

            val status = c.responseCode
            val body = readBody(c, status)
            if (status != 200) {
                val d = detail(body) ?: "השרת החזיר $status"
                // 413/507 הם החלטות של השרת ולא תקלות רשת.
                if (status == 413 || status == 507 || status == 403) {
                    throw ServerRefusal(d)
                }
                throw IOException(d)
            }
            tick()
        } finally {
            try { conn?.disconnect() } catch (_: Exception) {}
            try { pfd?.close() } catch (_: Exception) {}
        }
    }

    // ── שלב 3: סגירה ─────────────────────────────────────────────────────────

    private fun finish(base: String, code: String, jobId: String) {
        val c = open("$base/panel/saved-upload/finish?job=" + enc(jobId), code,
            "application/octet-stream")
        c.setFixedLengthStreamingMode(0)
        c.outputStream.use { }
        val status = c.responseCode
        val body = readBody(c, status)
        c.disconnect()
        if (status != 200) throw ServerRefusal(detail(body) ?: "השרת החזיר $status")
    }

    // ── מסלול הנפילה לאחור: בקשה אחת, כמו קודם ───────────────────────────────

    private fun singleUpload(
        uri: Uri, base: String, code: String, type: String,
        name: String, caption: String, duration: Long, width: Int, height: Int
    ) {
        val url = "$base/panel/saved-upload?name=" + enc(name) +
            "&caption=" + enc(caption) +
            "&duration=" + duration + "&width=" + width + "&height=" + height
        var input: InputStream? = null
        var conn: HttpURLConnection? = null
        try {
            val stream = ctx.contentResolver.openInputStream(uri)
                ?: throw IOException("לא ניתן לפתוח את הקובץ")
            input = stream
            val c = open(url, code, type)
            conn = c
            if (total > 0) c.setFixedLengthStreamingMode(total)
            else c.setChunkedStreamingMode(BUF)

            val out = BufferedOutputStream(c.outputStream, BUF)
            val buf = ByteArray(BUF)
            var lastTick = 0L
            while (true) {
                if (cancelRequested) throw IOException("ההעלאה בוטלה")
                val n = stream.read(buf)
                if (n < 0) break
                if (n == 0) continue
                out.write(buf, 0, n)
                sentBytes.addAndGet(n.toLong())
                val now = System.currentTimeMillis()
                if (now - lastTick >= PROGRESS_MS) {
                    lastTick = now
                    tick()
                }
            }
            out.flush()

            val status = c.responseCode
            val body = readBody(c, status)
            if (status != 200) throw ServerRefusal(detail(body) ?: "השרת החזיר $status")
            job = Regex("\"job\"\\s*:\\s*\"([^\"]+)\"").find(body)?.groupValues?.get(1) ?: ""
        } catch (e: Exception) {
            // כשהשרת דוחה מוקדם הוא עונה וסוגר בעוד אנחנו שולחים, והכתיבה
            // נכשלת. בלי לקרוא כאן את התשובה, ההסבר שלו היה הולך לאיבוד.
            val explained = try {
                conn?.let { k ->
                    detail(k.errorStream?.bufferedReader()?.readText() ?: "")
                }
            } catch (_: Exception) {
                null
            }
            throw if (explained != null) ServerRefusal(explained) else e
        } finally {
            try { input?.close() } catch (_: Exception) {}
            try { conn?.disconnect() } catch (_: Exception) {}
        }
    }

    // ── עזר ──────────────────────────────────────────────────────────────────

    private fun open(url: String, code: String, contentType: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            useCaches = false
            connectTimeout = 30_000
            // 0 = בלי מגבלה. חלק של מגה־בייטים על קו איטי לוקח זמן שאין טעם
            // להגביל מראש. הכותרת Connection נשארת פתוחה בכוונה, כדי
            // שהחיבורים יישמרו בין חלק לחלק.
            readTimeout = 0
            setRequestProperty("Content-Type", contentType)
            setRequestProperty("x-upload-code", code)
        }

    private fun readBody(c: HttpURLConnection, status: Int): String = try {
        (if (status in 200..299) c.inputStream else c.errorStream)
            ?.bufferedReader()?.readText() ?: ""
    } catch (_: Exception) {
        ""
    }

    private fun detail(body: String): String? =
        Regex("\"detail\"\\s*:\\s*\"([^\"]*)\"").find(body)?.groupValues?.get(1)

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

    @Volatile private var lastNotif = 0L

    private fun tick() {
        emit("progress") {}
        val now = System.currentTimeMillis()
        if (now - lastNotif >= NOTIF_MS) {
            lastNotif = now
            updateNotification()
        }
    }

    private fun updateNotification() {
        try {
            val sent = sentBytes.get()
            val pct = if (total > 0) ((100.0 * sent) / total).toInt() else -1
            val mb = { v: Long -> String.format(Locale.US, "%.1f", v / 1048576.0) }
            val el = System.currentTimeMillis() - startedAt
            val speed = if (el > 500) sent * 1000.0 / el else 0.0
            val text = if (total > 0) {
                "$pct% · ${mb(sent)} מתוך ${mb(total)} MB" +
                    (if (speed > 0) " · ${String.format(Locale.US, "%.1f", speed / 1048576.0)} MB/שנ׳" else "")
            } else {
                "${mb(sent)} MB"
            }
            val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
            nm.notify(UploadService.NOTIF_ID, UploadService.notification(ctx, text, pct))
        } catch (_: Exception) {
        }
    }

    private fun snapshot(): WritableMap = Arguments.createMap().apply {
        putBoolean("running", running)
        putString("stage", stage)
        putDouble("sent", sentBytes.get().toDouble())
        putDouble("total", total.toDouble())
        putString("job", job)
        putString("mode", mode)
        // כמה חיבורים באמת פתוחים. בלי זה נאלצנו להסיק את המסלול ממהירות
        // ההעלאה במקום פשוט לראות אותו.
        putInt("workers", if (mode == "parallel") activeWorkers else if (mode == "single") 1 else 0)
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
            // JS עשוי להיות מושהה כשהאפליקציה ברקע. ההעלאה אינה תלויה בו —
            // המצב נשמר כאן, והמסך שואב אותו כשהוא חוזר.
        }
    }
}
