package com.zovexapp

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.io.File

// ── התקנת עדכון מתוך האפליקציה ────────────────────────────────────────────────
// האפליקציה מותקנת מחוץ לחנות (sideload), ולכן מותר לה להתקין עדכון של עצמה:
// מורידים את ה-APK לתיקיית המטמון, ואז פותחים את מתקין המערכת על הקובץ. המשתמש
// רק מאשר "התקן" — בלי לצאת לדפדפן ובלי גיטהאב.
//
// שתי דרישות של אנדרואיד:
//  1) FileProvider — אסור להעביר file:// לאפליקציה אחרת (FileUriExposedException),
//     חייבים content:// עם הרשאת קריאה זמנית.
//  2) מאנדרואיד 8: הרשאת REQUEST_INSTALL_PACKAGES + אישור המשתמש פר-אפליקציה
//     ("התקנת אפליקציות לא ידועות"). canInstall()/openInstallSettings() מטפלים בזה.
class ApkInstallerModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

    override fun getName() = "ApkInstaller"

    /** האם מותר לנו כרגע להתקין חבילות (אנדרואיד 8+ דורש אישור מפורש). */
    @ReactMethod
    fun canInstall(promise: Promise) {
        try {
            val ok = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                reactContext.packageManager.canRequestPackageInstalls()
            } else true
            promise.resolve(ok)
        } catch (e: Exception) {
            promise.resolve(false)
        }
    }

    /** פותח את מסך ההגדרות שבו המשתמש מאשר לנו להתקין עדכונים. */
    @ReactMethod
    fun openInstallSettings(promise: Promise) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val i = Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:${reactContext.packageName}")
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                reactContext.startActivity(i)
            }
            promise.resolve(true)
        } catch (e: Exception) {
            promise.reject("SETTINGS_FAILED", e.message, e)
        }
    }

    /** מפעיל את מתקין המערכת על קובץ ה-APK שהורדנו. */
    @ReactMethod
    fun install(path: String, promise: Promise) {
        try {
            val file = File(path)
            if (!file.exists()) {
                promise.reject("NO_FILE", "קובץ העדכון לא נמצא")
                return
            }
            val uri: Uri =
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                    FileProvider.getUriForFile(
                        reactContext, "${reactContext.packageName}.fileprovider", file)
                } else {
                    Uri.fromFile(file)
                }
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            reactContext.startActivity(intent)
            promise.resolve(true)
        } catch (e: Exception) {
            promise.reject("INSTALL_FAILED", e.message, e)
        }
    }
}
