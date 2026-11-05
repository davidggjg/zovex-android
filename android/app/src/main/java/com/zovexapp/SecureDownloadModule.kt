package com.zovexapp

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.Arguments
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.io.RandomAccessFile
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.security.KeyStore
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread

/**
 * הצפנת הורדות במנוחה, עם מפתח שנעול בחומרה.
 *
 * ── מה היה כאן קודם ──────────────────────────────────────────────────────
 * שתי גרסאות, ושתיהן לא הגנו על כלום:
 *   1. XOR בייט-בייט ב-JavaScript עם מפתח ששכב באותו מכשיר. ההערה בקוד
 *      עצמו הודתה ש"זה הרתעה, לא DRM". בנוסף הוא לקח ~30 דקות להצפין
 *      קובץ של 1GB ועוד ~30 לפענח לפני שאפשר היה בכלל להתחיל לנגן.
 *   2. אחרי שהוסר: הקובץ נשמר **גלוי** באחסון הפרטי של האפליקציה. על
 *      מכשיר לא-רוּט אף אפליקציה אחרת לא קוראת אותו, אבל מכשיר מרוּט,
 *      גיבוי adb, או כל מי שמוציא את האפליקציה מהמכשיר — מקבל MP4 שלם.
 *
 * ── מה יש כאן עכשיו ──────────────────────────────────────────────────────
 * הצפנה דו-שכבתית, בדיוק הארכיטקטורה של Jetpack Security / EncryptedFile:
 *
 *   • מפתח-על AES-256 ב-AndroidKeyStore. הוא **נוצר בתוך** החומרה
 *     (StrongBox כשיש, אחרת ה-TEE) ואין שום API שמוציא אותו — גם ל-root
 *     אין. כל מה שאפשר לעשות איתו זה לבקש מהחומרה לעטוף/לפרוש בייטים.
 *   • לכל הורדה מפתח נתונים אקראי משלה (AES-256). הוא נעטף ב-AES-GCM
 *     במפתח-העל ונשמר בכותרת הקובץ. בלי החומרה של אותו מכשיר אי אפשר
 *     לפרוש אותו, ולכן קובץ שהועתק החוצה הוא רעש.
 *   • גוף הווידאו מוצפן AES-256-CTR במפתח הנתונים, בקוד רגיל (AES-NI /
 *     ARMv8 crypto) ולא דרך ה-TEE. זה מה שמאפשר מהירות של מאות MB/s
 *     במקום הדקות של ה-XOR — וגם גישה אקראית, שבלעדיה אי אפשר לקפוץ
 *     באמצע סרט.
 *
 * ── הניגון ───────────────────────────────────────────────────────────────
 * אין שום רגע שבו קובץ מפוענח יושב על הדיסק. הפענוח קורה בזרם, מול
 * שרת HTTP זעיר שמאזין **רק על 127.0.0.1** ומוגש רק מול אסימון אקראי
 * של 32 תווים שנוצר לאותה צפייה ומת בסיומה. ExoPlayer מקבל כתובת
 * רגילה עם תמיכת Range, ולכן גרירה בסרגל עובדת כרגיל.
 *
 * ── מה זה עדיין לא ───────────────────────────────────────────────────────
 * זה לא Widevine. Widevine אמיתי (L1, עם מסלול וידאו מוגן בחומרה שגם
 * צילום מסך לא עובר בו) דורש שרת רישיונות ואריזת תוכן בצד השרת — ראה
 * docs/offline-drm.md. מה שיש כאן הוא החזק ביותר שאפשר לעשות כולו בצד
 * הלקוח, ובנוי כך שמסלול Widevine ייכנס לצדו בלי לשבור הורדות קיימות.
 */
class SecureDownloadModule(private val ctx: ReactApplicationContext) :
    ReactContextBaseJavaModule(ctx) {

    override fun getName() = "SecureDownload"

    companion object {
        private const val KEY_ALIAS = "zovex_dl_master_v1"
        private const val KEYSTORE = "AndroidKeyStore"

        // כותרת הקובץ: מזהה, גרסה, מפתח הנתונים העטוף, ו-IV של גוף הקובץ.
        private val MAGIC = byteArrayOf(0x5A, 0x56, 0x58, 0x45, 0x31) // "ZVXE1"
        private const val VERSION: Byte = 1
        private const val GCM_IV_LEN = 12
        private const val GCM_TAG_BITS = 128
        private const val CTR_IV_LEN = 16
        private const val BUF = 1 shl 16
    }

    // ── מפתח-העל, בחומרה ────────────────────────────────────────────────
    private fun masterKey(): SecretKey {
        val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (ks.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }

        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .apply {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    // המכשיר חייב להיות פתוח כדי לפרוש את המפתח. הורדה מנוגנת
                    // רק כשהמשתמש מול המסך ממילא, ולכן זה לא עולה בכלום.
                    setUnlockedDeviceRequired(true)
                    // StrongBox הוא שבב נפרד. לא בכל מכשיר יש, ולכן ננסה
                    // ונפיל חזרה ל-TEE אם הוא לא קיים (ראה ה-catch למטה).
                    setIsStrongBoxBacked(true)
                }
            }
            .build()
        return try {
            gen.init(spec)
            gen.generateKey()
        } catch (_: Throwable) {
            // אין StrongBox / המכשיר דחה את הדרישות המחמירות. נופלים ל-TEE,
            // שהוא עדיין מפתח שלא ניתן לייצוא.
            val fallback = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
            fallback.init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            fallback.generateKey()
        }
    }

    private fun wrap(dataKey: ByteArray): Pair<ByteArray, ByteArray> {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, masterKey())
        return Pair(c.iv.copyOf(), c.doFinal(dataKey))
    }

    private fun unwrap(gcmIv: ByteArray, wrapped: ByteArray): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, masterKey(), GCMParameterSpec(GCM_TAG_BITS, gcmIv))
        return c.doFinal(wrapped)
    }

    // ── כתיבה ───────────────────────────────────────────────────────────
    /**
     * מצפין [srcPath] אל [dstPath] ומוחק את המקור. הקובץ הגלוי לא שורד
     * את הקריאה הזאת — זו כל הנקודה.
     */
    @ReactMethod
    fun encryptFile(srcPath: String, dstPath: String, promise: Promise) {
        thread {
            try {
                val src = File(srcPath)
                if (!src.exists()) throw IllegalStateException("source missing: $srcPath")
                val dst = File(dstPath)
                dst.parentFile?.mkdirs()
                if (dst.exists()) dst.delete()

                val rnd = SecureRandom()
                val dataKey = ByteArray(32).also { rnd.nextBytes(it) }
                val ctrIv = ByteArray(CTR_IV_LEN).also { rnd.nextBytes(it) }
                val (gcmIv, wrapped) = wrap(dataKey)

                val cipher = Cipher.getInstance("AES/CTR/NoPadding")
                cipher.init(
                    Cipher.ENCRYPT_MODE,
                    SecretKeySpec(dataKey, "AES"),
                    IvParameterSpec(ctrIv),
                )

                src.inputStream().use { input ->
                    dst.outputStream().use { out ->
                        writeHeader(out, gcmIv, wrapped, ctrIv)
                        val buf = ByteArray(BUF)
                        while (true) {
                            val n = input.read(buf)
                            if (n <= 0) break
                            out.write(cipher.update(buf, 0, n) ?: ByteArray(0))
                        }
                        cipher.doFinal()?.let { if (it.isNotEmpty()) out.write(it) }
                        out.flush()
                    }
                }
                java.util.Arrays.fill(dataKey, 0)
                // המקור נמחק רק אחרי שהיעד נכתב במלואו: הפסקה באמצע משאירה
                // את ההורדה הגולמית, לא כלום.
                src.delete()
                promise.resolve(dst.length().toDouble())
            } catch (e: Throwable) {
                try { File(dstPath).delete() } catch (_: Throwable) {}
                promise.reject("encrypt_failed", e.message, e)
            }
        }
    }

    private fun writeHeader(out: OutputStream, gcmIv: ByteArray, wrapped: ByteArray, ctrIv: ByteArray) {
        out.write(MAGIC)
        out.write(byteArrayOf(VERSION))
        out.write(byteArrayOf((wrapped.size shr 8).toByte(), (wrapped.size and 0xFF).toByte()))
        out.write(gcmIv)
        out.write(wrapped)
        out.write(ctrIv)
    }

    private class Header(val dataKey: ByteArray, val ctrIv: ByteArray, val offset: Long)

    private fun readHeader(f: RandomAccessFile): Header {
        val magic = ByteArray(MAGIC.size)
        f.readFully(magic)
        if (!magic.contentEquals(MAGIC)) throw IllegalStateException("not a zovex encrypted file")
        val ver = f.readByte()
        if (ver != VERSION) throw IllegalStateException("unsupported version $ver")
        val len = ((f.readByte().toInt() and 0xFF) shl 8) or (f.readByte().toInt() and 0xFF)
        val gcmIv = ByteArray(GCM_IV_LEN).also { f.readFully(it) }
        val wrapped = ByteArray(len).also { f.readFully(it) }
        val ctrIv = ByteArray(CTR_IV_LEN).also { f.readFully(it) }
        return Header(unwrap(gcmIv, wrapped), ctrIv, f.filePointer)
    }

    // ── קריאה: אותו CTR, בהיסט שרירותי ──────────────────────────────────
    //
    // ב-CTR כל בלוק של 16 בייט מוצפן מול IV+index. כדי לקרוא מהיסט כלשהו
    // מספיק לקדם את המונה ל-index הנכון ולזרוק את השארית — ולכן גרירה
    // בסרגל עובדת בלי לפענח את כל מה שלפניה.
    private fun cipherAt(dataKey: ByteArray, ctrIv: ByteArray, plainOffset: Long): Pair<Cipher, Int> {
        val block = plainOffset / 16
        val skip = (plainOffset % 16).toInt()
        val iv = ctrIv.copyOf()
        var carry = block
        for (i in 15 downTo 0) {
            if (carry == 0L) break
            val sum = (iv[i].toInt() and 0xFF) + (carry and 0xFF).toInt()
            iv[i] = (sum and 0xFF).toByte()
            carry = (carry ushr 8) + (if (sum > 0xFF) 1 else 0)
        }
        val c = Cipher.getInstance("AES/CTR/NoPadding")
        c.init(Cipher.DECRYPT_MODE, SecretKeySpec(dataKey, "AES"), IvParameterSpec(iv))
        return Pair(c, skip)
    }

    // ── שרת לולאה מקומית ────────────────────────────────────────────────
    private val served = ConcurrentHashMap<String, String>()   // token → path
    @Volatile private var server: ServerSocket? = null
    @Volatile private var port = 0

    @ReactMethod
    fun serve(path: String, promise: Promise) {
        try {
            if (!File(path).exists()) throw IllegalStateException("file missing")
            startServer()
            val token = ByteArray(16).also { SecureRandom().nextBytes(it) }
                .joinToString("") { "%02x".format(it) }
            served[token] = path
            val r = Arguments.createMap()
            r.putString("url", "http://127.0.0.1:$port/$token")
            r.putString("token", token)
            promise.resolve(r)
        } catch (e: Throwable) {
            promise.reject("serve_failed", e.message, e)
        }
    }

    @ReactMethod
    fun stopServing(token: String) {
        served.remove(token)
    }

    @Synchronized
    private fun startServer() {
        if (server != null) return
        // 127.0.0.1 בלבד ופורט שהמערכת בוחרת. לא מאזינים על 0.0.0.0, ולכן
        // שום מכשיר אחר ברשת לא יכול אפילו לנסות.
        val s = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        server = s
        port = s.localPort
        thread(isDaemon = true) {
            while (!s.isClosed) {
                val sock = try { s.accept() } catch (_: Throwable) { break }
                thread(isDaemon = true) { handle(sock) }
            }
        }
    }

    private fun handle(sock: Socket) {
        try {
            sock.use { sk ->
                val input = sk.getInputStream()
                val req = readRequestHead(input) ?: return
                val line = req.firstOrNull() ?: return
                val parts = line.split(" ")
                if (parts.size < 2) return
                val method = parts[0]
                val token = parts[1].trimStart('/').substringBefore('?')
                val path = served[token]
                val out = sk.getOutputStream()
                if (path == null || !File(path).exists()) {
                    out.write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
                    out.flush()
                    return
                }

                RandomAccessFile(path, "r").use { f ->
                    val h = readHeader(f)
                    val total = f.length() - h.offset

                    var start = 0L
                    var end = total - 1
                    val range = req.firstOrNull { it.startsWith("Range:", true) }
                    if (range != null) {
                        val spec = range.substringAfter("=", "").trim()
                        val a = spec.substringBefore('-').trim()
                        val b = spec.substringAfter('-').trim()
                        if (a.isNotEmpty()) start = a.toLong()
                        if (b.isNotEmpty()) end = minOf(b.toLong(), total - 1)
                    }
                    if (start >= total || start > end) {
                        out.write(
                            ("HTTP/1.1 416 Range Not Satisfiable\r\n" +
                                "Content-Range: bytes */$total\r\nContent-Length: 0\r\n" +
                                "Connection: close\r\n\r\n").toByteArray(),
                        )
                        out.flush()
                        return
                    }

                    val len = end - start + 1
                    val head = StringBuilder()
                    head.append(if (range != null) "HTTP/1.1 206 Partial Content\r\n" else "HTTP/1.1 200 OK\r\n")
                    head.append("Content-Type: video/mp4\r\n")
                    head.append("Accept-Ranges: bytes\r\n")
                    head.append("Content-Length: $len\r\n")
                    if (range != null) head.append("Content-Range: bytes $start-$end/$total\r\n")
                    head.append("Cache-Control: no-store\r\n")
                    head.append("Connection: close\r\n\r\n")
                    out.write(head.toString().toByteArray())

                    if (method.equals("HEAD", true)) { out.flush(); return }

                    val (cipher, skip) = cipherAt(h.dataKey, h.ctrIv, start)
                    f.seek(h.offset + start - skip)
                    streamDecrypted(f, cipher, skip, len, out)
                    out.flush()
                }
            }
        } catch (_: Throwable) {
            // חיבור שנקטע באמצע (הצופה סגר, ExoPlayer פתח Range חדש) הוא
            // מצב רגיל לגמרי. אין מה לדווח ואין מה להפיל.
        }
    }

    private fun streamDecrypted(
        f: RandomAccessFile,
        cipher: Cipher,
        skip: Int,
        wanted: Long,
        out: OutputStream,
    ) {
        val raw = ByteArray(BUF)
        var left = wanted
        var toSkip = skip
        while (left > 0) {
            val n = f.read(raw)
            if (n <= 0) break
            val dec = cipher.update(raw, 0, n) ?: continue
            var off = 0
            var avail = dec.size
            if (toSkip > 0) {
                val s = minOf(toSkip, avail)
                off += s; avail -= s; toSkip -= s
            }
            if (avail <= 0) continue
            val take = minOf(avail.toLong(), left).toInt()
            out.write(dec, off, take)
            left -= take
        }
    }

    private fun readRequestHead(input: InputStream): List<String>? {
        val sb = StringBuilder()
        var last = 0
        while (sb.length < 8192) {
            val b = input.read()
            if (b < 0) break
            sb.append(b.toChar())
            if (b == '\n'.code && last == '\n'.code) break
            if (b != '\r'.code) last = b
        }
        val text = sb.toString()
        if (text.isBlank()) return null
        return text.split("\r\n", "\n").filter { it.isNotBlank() }
    }

    override fun invalidate() {
        super.invalidate()
        served.clear()
        try { server?.close() } catch (_: Throwable) {}
        server = null
    }

    /** לבדיקות ולממשק: האם המפתח אכן נשען על חומרה. */
    @ReactMethod
    fun keyInfo(promise: Promise) {
        try {
            val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
            masterKey()
            val key = (ks.getEntry(KEY_ALIAS, null) as KeyStore.SecretKeyEntry).secretKey
            val factory = javax.crypto.SecretKeyFactory.getInstance(key.algorithm, KEYSTORE)
            val info = factory.getKeySpec(key, android.security.keystore.KeyInfo::class.java)
                as android.security.keystore.KeyInfo
            val r = Arguments.createMap()
            r.putBoolean(
                "hardwareBacked",
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    info.securityLevel >= android.security.keystore.KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT
                } else {
                    @Suppress("DEPRECATION") info.isInsideSecureHardware
                },
            )
            promise.resolve(r)
        } catch (e: Throwable) {
            promise.reject("keyinfo_failed", e.message, e)
        }
    }
}
