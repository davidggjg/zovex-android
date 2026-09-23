package com.zovexapp

import android.app.NotificationManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.Build
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
import java.io.ByteArrayOutputStream
import java.io.FileInputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
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
        // ── לשרוד WiFi גרוע ─────────────────────────────────────────────
        // קודם: 4 ניסיונות לחלק, עם המתנות של 1+2+4 שניות. כלומר נפילה של
        // ה-WiFi ליותר משבע שניות הפילה את **כל** ההעלאה, כולל הג'יגות
        // שכבר עלו, ומתחילים מאפס. בבית עם WiFi גרוע זה כמעט ודאי באמצע
        // קובץ של 3GB.
        //
        // עכשיו חלק ממתין לרשת במקום לוותר: המתנה שגדלה עד 30 שניות, ומוותרים
        // רק אם אותו חלק נכשל ברצף עשר דקות. סירוב אמיתי של השרת (קובץ גדול
        // מדי, אין מקום) עדיין עוצר מיד.
        private const val PART_GIVE_UP_MS = 10 * 60_000L
        private const val BACKOFF_CAP_MS = 30_000L
        // חיבור שלא זז כך וכך שניות נחשב מת ונסגר. ‎readTimeout = 0 פירושו
        // "חכה לנצח", ו-WiFi שנופל בלי ניתוק מסודר השאיר חוט תקוע לתמיד —
        // ההעלאה קפאה על אחוז מסוים ולא זזה יותר.
        private const val STALL_MS = 45_000L
        private const val PART_READ_TIMEOUT_MS = 90_000
        private const val PROGRESS_MS = 250L
        private const val NOTIF_MS = 1000L

        // ── התאמה לרשת שמשתנה ────────────────────────────────────────────
        // מספר החיבורים נקבע פעם אחת בהתחלה ולא זז. מי שהתחיל להעלות
        // בקליטה גרועה ואחר כך עבר למקום עם קליטה טובה נשאר תקוע על מה
        // שהתאים לרשת הישנה. עכשיו מוסיפים חיבור כל כמה שניות כל עוד זה
        // באמת עוזר, ועוצרים ברגע שזה מפסיק לעזור או שמתחילות תקלות.
        private const val MAX_PARALLEL = 16
        private const val PROBE_MS = 12_000L    // כל כמה זמן בודקים אם לעלות
        private const val RATE_WINDOW_MS = 10_000L

        // ── פוסטר שבחרת ──────────────────────────────────────────────────
        // מוקטן בטלפון לפני השליחה: תמונה ערוכה יכולה לשקול 10MB, וב-WiFi
        // גרוע זה עוד חלק שלם של המתנה. 2000 פיקסלים זה גם מה שהשרת שומר,
        // והוא נבחר כך שתמונה טיפוסית (1024×1536) תעבור בלי הקטנה בכלל —
        // הקטנה מרככת טקסט על פוסטר, וזה נראה בדיוק כמו טשטוש.
        private const val POSTER_MAX_PX = 2000
        // 95 ולא 92: הפרש של כמה עשרות קילובייט, והילה סביב אותיות נעלמת
        private const val POSTER_QUALITY = 95
        private const val POSTER_GIVE_UP_MS = 3 * 60_000L
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
    // דגימות (זמן, בייטים) לחישוב הקצב הנוכחי. הממוצע מתחילת ההעלאה לא
    // מתאים כאן: אחרי חצי שעה בקליטה גרועה הוא ננעל נמוך ולא מזיז גם
    // כשהרשת השתפרה — וזה גם מה שהוצג למשתמש וגם מה שהיינו מחליטים לפיו.
    private val rateSamples = ArrayDeque<Pair<Long, Long>>()
    // תקלות רשת מאז הבדיקה האחרונה. תקלות הן הסימן שהרשת נחנקה.
    private val recentErrors = AtomicInteger(0)
    // כמה חלקים ממתינים עכשיו לרשת. ההעלאה לא נכשלה — היא מחכה — והמסך
    // צריך לדעת להגיד את זה במקום להיראות תקוע.
    private val waitingParts = AtomicInteger(0)
    // מה קרה לפוסטר שבחרת: ""=לא נבחר | sending | sent | failed | old_server
    @Volatile private var posterState = ""
    @Volatile private var posterError = ""

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
        val posterUri = (if (opts.hasKey("posterUri")) opts.getString("posterUri") else null)
            ?.takeIf { it.isNotEmpty() }?.let { Uri.parse(it) }
        val hinted = if (opts.hasKey("size")) opts.getDouble("size").toLong() else 0L
        val duration = if (opts.hasKey("duration")) opts.getDouble("duration").toLong() else 0L
        val width = if (opts.hasKey("width")) opts.getInt("width") else 0
        val height = if (opts.hasKey("height")) opts.getInt("height") else 0

        // ברירת המחדל של אנדרואיד היא לשמור חמישה חיבורי-סרק לכל שרת, ולכן
        // מעבר לחמישה עובדים כל חלק פתח חיבור חדש ועשה לחיצת יד TLS מחדש.
        try { System.setProperty("http.maxConnections", "64") } catch (_: Exception) {}

        running = true
        cancelRequested = false
        sentBytes.set(0)
        stage = "sending"
        job = ""
        lastError = ""
        mode = ""
        posterState = if (posterUri != null) "sending" else ""
        posterError = ""
        startedAt = System.currentTimeMillis()
        total = if (hinted > 0) hinted else resolveSize(uri)

        UploadService.start(ctx, name)
        Thread({
            drive(uri, base, code, type, name, caption, duration, width, height, posterUri)
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
        name: String, caption: String, duration: Long, width: Int, height: Int,
        posterUri: Uri?
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
                // השרת קובע כמה חיבורים לפתוח. כך אפשר למדוד 12/16/20 בשינוי
                // משתנה סביבה, בלי לבנות ולהתקין APK חדש לכל ניסיון.
                val want = begun.optInt("workers", PARALLEL).coerceIn(1, 32)
                // הפוסטר לפני הסרט: הוא קטן, והשרת מקבל אותו רק עד finish.
                // כישלון שלו לא עוצר את ההעלאה — הסרט חשוב ממנו.
                if (posterUri != null) sendPoster(base, code, job, posterUri)
                uploadParts(uri, base, code, partSize, nParts, want)
                if (cancelRequested) throw IOException("ההעלאה בוטלה")
                finish(base, code, job)
            } else {
                mode = "single"
                // המסלול הישן אינו מכיר פוסטר — ואומרים את זה במקום לשתוק
                if (posterUri != null) posterState = "old_server"
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

    /** הקצב בחלון האחרון, בייטים לשנייה. אפס עד שיש מספיק דגימות. */
    @Synchronized private fun currentRate(): Double {
        val now = System.currentTimeMillis()
        rateSamples.addLast(Pair(now, sentBytes.get()))
        while (rateSamples.size > 2 &&
               now - rateSamples.first().first > RATE_WINDOW_MS) {
            rateSamples.removeFirst()
        }
        if (rateSamples.size < 2) return 0.0
        val dt = now - rateSamples.first().first
        val db = rateSamples.last().second - rateSamples.first().second
        return if (dt > 500) db * 1000.0 / dt else 0.0
    }

    private fun uploadParts(
        uri: Uri, base: String, code: String, partSize: Long, nParts: Int,
        wanted: Int
    ) {
        val next = AtomicInteger(0)
        val failure = AtomicReference<Exception?>(null)
        val start = minOf(wanted, nParts)
        activeWorkers = start
        val threads = java.util.Collections.synchronizedList(ArrayList<Thread>())

        fun spawn(w: Int) {
            val t = Thread(Runnable {
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
            threads.add(t)
            t.start()
        }

        for (w in 0 until start) spawn(w)

        // ── מגשש ─────────────────────────────────────────────────────────
        // מוסיף חיבור אחד כל PROBE_MS, אבל רק אם התוספת הקודמת באמת שיפרה
        // ולא היו תקלות. כשההוספה מזיקה — הפוגה ואז ניסיון נוסף, ולא ויתור
        // סופי: הרשת משתנה תוך כדי (מעבר בין מקומות, עומס שמתפנה), ומי
        // שוויתר פעם אחת היה נשאר תקוע על מה שהתאים לרשת הישנה. וזה בדיוק
        // מה שקרה — התחלה בקליטה גרועה, מעבר למקום טוב, והקצב לא זז.
        //
        // עלייה בלבד: הורדת חיבור באמצע דורשת לקטוע חלק שכבר רץ, וזה עולה
        // יותר ממה שהוא חוסך. במקום זה פשוט לא מוסיפים.
        //
        // ה-best דועך לאט, אחרת שיא שנקבע ברשת טובה היה חוסם כל ניסיון
        // אחרי מעבר לרשת אחרת.
        val prober = Thread(Runnable {
            var best = 0.0
            var cooldownUntil = 0L
            while (failure.get() == null && !cancelRequested) {
                try { Thread.sleep(PROBE_MS) } catch (_: InterruptedException) { break }
                if (next.get() >= nParts) break          // נגמרו החלקים
                val rate = currentRate()
                if (rate <= 0.0) continue
                val errs = recentErrors.getAndSet(0)
                val now = System.currentTimeMillis()
                best *= 0.98
                if (errs > 0) {
                    // הרשת מתלוננת. נותנים לה דקה לנשום ואז בודקים שוב.
                    cooldownUntil = now + 60_000L
                    best = rate
                } else if (now < cooldownUntil) {
                    best = maxOf(best, rate)
                } else if (rate >= best * 0.97) {
                    best = maxOf(best, rate)
                    if (activeWorkers < MAX_PARALLEL &&
                        nParts - next.get() > activeWorkers) {
                        spawn(activeWorkers)
                        activeWorkers += 1
                    }
                } else {
                    // ההוספה האחרונה הרעה את המצב. הפוגה, ואז ננסה שוב.
                    cooldownUntil = now + 60_000L
                    best = rate
                }
            }
        }, "zovex-probe")
        prober.isDaemon = true
        prober.start()

        // רשימת החוטים גדלה תוך כדי, ולכן ממתינים בלולאה ולא במעבר אחד.
        while (true) {
            val alive = synchronized(threads) { threads.filter { it.isAlive } }
            if (alive.isEmpty()) break
            alive.forEach { it.join() }
        }
        prober.interrupt()
        failure.get()?.let { throw it }
        if (cancelRequested) throw IOException("ההעלאה בוטלה")
    }

    private fun sendPartWithRetry(
        uri: Uri, base: String, code: String, index: Int, offset: Long, len: Long
    ) {
        var attempt = 0
        var firstFailAt = 0L
        var last: Exception? = null
        while (!cancelRequested) {
            val sentNow = AtomicLong(0)
            try {
                sendPart(uri, base, code, index, offset, len, sentNow)
                return
            } catch (e: ServerRefusal) {
                throw e                       // הסבר מהשרת — אין טעם לחזור
            } catch (e: Exception) {
                last = e
                // מחזירים רק את מה ש**החלק הזה** שלח בניסיון שנכשל. קודם המונה
                // אופס לערך שנקרא לפני הניסיון, ובכך נמחקה גם ההתקדמות של
                // כל שאר החוטים שעבדו בינתיים — ההתקדמות קפצה אחורה.
                sentBytes.addAndGet(-sentNow.get())
                // סימן לרשת חנוקה. המגשש קורא את זה ומפסיק להוסיף חיבורים.
                recentErrors.incrementAndGet()
                val now = System.currentTimeMillis()
                if (firstFailAt == 0L) firstFailAt = now
                if (now - firstFailAt > PART_GIVE_UP_MS) break
                attempt++
                val wait = minOf(BACKOFF_CAP_MS, 1000L * (1L shl minOf(attempt - 1, 5)))
                waitingParts.incrementAndGet()
                tick()
                try {
                    sleepUnlessCancelled(wait)
                } finally {
                    waitingParts.decrementAndGet()
                }
            }
        }
        if (cancelRequested) throw IOException("ההעלאה בוטלה")
        throw last ?: IOException("חלק $index נכשל")
    }

    /** שינה שמתעוררת מיד כשמבטלים — המתנה של 30 שניות לא תעכב ביטול. */
    private fun sleepUnlessCancelled(ms: Long) {
        val until = System.currentTimeMillis() + ms
        while (!cancelRequested) {
            val left = until - System.currentTimeMillis()
            if (left <= 0) return
            try { Thread.sleep(minOf(left, 500L)) } catch (_: InterruptedException) { return }
        }
    }

    private fun sendPart(
        uri: Uri, base: String, code: String, index: Int, offset: Long, len: Long,
        sentNow: AtomicLong
    ) {
        var pfd: ParcelFileDescriptor? = null
        var conn: HttpURLConnection? = null
        val lastMove = AtomicLong(System.currentTimeMillis())
        val done = AtomicBoolean(false)
        var dog: Thread? = null
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
            c.readTimeout = PART_READ_TIMEOUT_MS
            c.setFixedLengthStreamingMode(len)
            // כלב שמירה: אם החיבור לא זז STALL_MS, סוגרים אותו מבחוץ. סגירה
            // משחררת כתיבה שנתקעה על שקע מת, זו נזרקת, והחלק עובר לניסיון
            // חוזר — במקום לחכות לנצח לרשת שכבר לא שם.
            dog = Thread({
                while (!done.get()) {
                    try { Thread.sleep(5_000) } catch (_: InterruptedException) { break }
                    if (!done.get() &&
                        System.currentTimeMillis() - lastMove.get() > STALL_MS) {
                        try { c.disconnect() } catch (_: Exception) {}
                        break
                    }
                }
            }, "zovex-dog-$index").apply { isDaemon = true; start() }
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
                sentNow.addAndGet(n.toLong())
                lastMove.set(System.currentTimeMillis())
                val now = System.currentTimeMillis()
                if (now - lastTick >= PROGRESS_MS) {
                    lastTick = now
                    tick()
                }
            }
            out.flush()
            // התשובה מקבלת חלון שמירה מלא משלה, מרגע שהבית האחרון יצא
            lastMove.set(System.currentTimeMillis())

            val status = c.responseCode
            val body = readBody(c, status)
            if (status != 200) {
                val d = detail(body) ?: "השרת החזיר $status"
                // 413/507 הם החלטות של השרת ולא תקלות רשת.
                if (status == 413 || status == 507 || status == 403) {
                    throw ServerRefusal(d)
                }
                // המשימה כבר לא קיימת בשרת (404) או כבר לא מקבלת חלקים (409) —
                // למשל כי השרת הופעל מחדש באמצע. עכשיו, כשחלק ממתין לרשת עד
                // עשר דקות, בלי זה ההמתנה הייתה מבוזבזת כולה על משימה שאיננה.
                if (status == 404 || status == 409) {
                    throw ServerRefusal("$d — צריך להתחיל את ההעלאה מחדש")
                }
                throw IOException(d)
            }
            tick()
        } finally {
            done.set(true)
            dog?.interrupt()
            try { conn?.disconnect() } catch (_: Exception) {}
            try { pfd?.close() } catch (_: Exception) {}
        }
    }

    // ── פוסטר שבחרת ─────────────────────────────────────────────────────────

    /** התמונה כ-JPEG עד POSTER_MAX_PX בצד. null אם אי אפשר לפענח אותה. */
    private fun posterJpeg(uri: Uri): ByteArray? {
        return try {
            val bmp: Bitmap = if (Build.VERSION.SDK_INT >= 28) {
                // ImageDecoder גם מסובב לפי EXIF וגם קורא HEIC
                ImageDecoder.decodeBitmap(
                    ImageDecoder.createSource(ctx.contentResolver, uri)
                ) { dec, info, _ ->
                    val w = info.size.width
                    val h = info.size.height
                    val big = maxOf(w, h)
                    if (big > POSTER_MAX_PX) {
                        val k = POSTER_MAX_PX.toDouble() / big
                        dec.setTargetSize(maxOf(1, (w * k).toInt()), maxOf(1, (h * k).toInt()))
                    }
                    dec.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                }
            } else {
                val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                ctx.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, o) }
                var sample = 1
                while (maxOf(o.outWidth, o.outHeight) / (sample * 2) >= POSTER_MAX_PX) sample *= 2
                ctx.contentResolver.openInputStream(uri)?.use {
                    BitmapFactory.decodeStream(it, null,
                        BitmapFactory.Options().apply { inSampleSize = sample })
                } ?: return null
            }
            val out = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, POSTER_QUALITY, out)
            bmp.recycle()
            out.toByteArray()
        } catch (_: Throwable) {
            null     // כולל OutOfMemoryError על תמונה ענקית
        }
    }

    /**
     * שולח את הפוסטר. לא זורק: פוסטר שלא עבר לא מפיל העלאה של סרט.
     * ב-WiFi שנופל מנסה שוב עד שלוש דקות, כמו החלקים.
     */
    private fun sendPoster(base: String, code: String, jobId: String, uri: Uri) {
        val bytes = posterJpeg(uri)
        if (bytes == null) {
            posterState = "failed"
            posterError = "לא הצלחתי לקרוא את התמונה"
            return
        }
        val giveUpAt = System.currentTimeMillis() + POSTER_GIVE_UP_MS
        var wait = 1_000L
        while (!cancelRequested) {
            var c: HttpURLConnection? = null
            try {
                val conn = open("$base/panel/saved-upload/poster?job=" + enc(jobId), code,
                    "image/jpeg")
                c = conn
                conn.readTimeout = PART_READ_TIMEOUT_MS
                conn.setFixedLengthStreamingMode(bytes.size)
                conn.outputStream.use { it.write(bytes) }
                val status = conn.responseCode
                val body = readBody(conn, status)
                when {
                    status == 200 -> posterState = "sent"
                    // שרת שעוד לא עודכן: FastAPI עונה על מסלול שאינו קיים
                    // "Not Found". משימה שלא נמצאה עונה בעברית.
                    status == 404 && (detail(body) ?: "Not Found") == "Not Found" ->
                        posterState = "old_server"
                    else -> {
                        posterState = "failed"
                        posterError = detail(body) ?: "השרת החזיר $status"
                    }
                }
                emit("progress") {}
                return
            } catch (_: IOException) {
                if (System.currentTimeMillis() > giveUpAt) {
                    posterState = "failed"
                    posterError = "הרשת לא אפשרה לשלוח את הפוסטר"
                    return
                }
                sleepUnlessCancelled(wait)
                wait = minOf(wait * 2, BACKOFF_CAP_MS)
            } catch (e: Exception) {
                // כל תקלה אחרת — הפוסטר נופל, הסרט ממשיך
                posterState = "failed"
                posterError = e.message ?: "שגיאה"
                return
            } finally {
                try { c?.disconnect() } catch (_: Exception) {}
            }
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
            // אותו חלון שהמגשש משתמש בו, ולא ממוצע מתחילת ההעלאה: אחרת
            // ההתראה מציגה את הרשת הישנה עוד הרבה אחרי שהיא השתנתה.
            val el = System.currentTimeMillis() - startedAt
            val speed = currentRate().let {
                if (it > 0) it else if (el > 500) sent * 1000.0 / el else 0.0
            }
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
        putInt("waiting", waitingParts.get())
        putString("poster", posterState)
        putString("posterError", posterError)
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
