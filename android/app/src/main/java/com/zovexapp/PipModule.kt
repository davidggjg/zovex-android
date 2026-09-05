package com.zovexapp

import android.app.Activity
import android.app.PictureInPictureParams
import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.util.Rational
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import androidx.core.view.WindowCompat
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class PipModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

    override fun getName() = "PipModule"

    companion object {
        @Volatile var videoActive = false
        @Volatile var isFullscreen = false

        // האם המכשיר בכלל תומך ב-Picture-in-Picture. טלפונים חלשים / רומים כשרים
        // (Qin F21/F22 Pro וכו') לרוב לא מכריזים על FEATURE_PICTURE_IN_PICTURE,
        // וקריאה ל-enterPictureInPictureMode/setPictureInPictureParams עליהם זורקת
        // IllegalStateException ומקריסה את האפליקציה (למשל כשסוגרים בזמן שסרט רץ).
        // בטלוויזיות: חלק מהמכשירים כן מכריזים על FEATURE_PICTURE_IN_PICTURE,
        // אבל חלון צף על מסך טלוויזיה הוא חסר משמעות — אין שם "לצאת לבית תוך
        // כדי צפייה", ובפועל זה רק מקטין את הסרט לפינה בלי שהצופה ביקש. לכן
        // מוציאים טלוויזיות מפורשות, ומשאירים את PiP לטלפונים בלבד.
        private fun isTv(activity: Activity): Boolean = try {
            val ui = activity.getSystemService(Context.UI_MODE_SERVICE) as UiModeManager
            ui.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION ||
                activity.packageManager.hasSystemFeature(
                    android.content.pm.PackageManager.FEATURE_LEANBACK)
        } catch (_: Throwable) {
            false
        }

        fun supportsPip(activity: Activity): Boolean =
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !isTv(activity) &&
            activity.packageManager.hasSystemFeature(
                android.content.pm.PackageManager.FEATURE_PICTURE_IN_PICTURE)

        // Shared immersive-mode logic. Exposed so MainActivity can re-apply
        // the exact same state whenever the window gets re-laid out
        // (rotation, fold/unfold, split-screen, large-screen size-class
        // changes) — those events don't always trigger onWindowFocusChanged,
        // which is what used to leave the navigation bar visible again.
        fun applyImmersiveMode(activity: Activity, enter: Boolean) {
            try {
                val window = activity.window
                // Let content draw behind the bars instead of being resized
                // around them — needed for hide() to stick reliably across
                // OEM skins and large-screen taskbars.
                WindowCompat.setDecorFitsSystemWindows(window, !enter)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    val ctrl = window.insetsController ?: return
                    if (enter) {
                        ctrl.hide(WindowInsets.Type.navigationBars() or WindowInsets.Type.statusBars())
                        ctrl.systemBarsBehavior =
                            WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                    } else {
                        ctrl.show(WindowInsets.Type.navigationBars() or WindowInsets.Type.statusBars())
                    }
                } else {
                    @Suppress("DEPRECATION")
                    window.decorView.systemUiVisibility = if (enter) {
                        (View.SYSTEM_UI_FLAG_FULLSCREEN
                            or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN)
                    } else {
                        View.SYSTEM_UI_FLAG_VISIBLE
                    }
                }
            } catch (_: Exception) {
                // Defensive: never let an OEM-specific quirk here crash the app.
            }
        }
    }

    @ReactMethod
    fun setVideoPlaying(playing: Boolean) {
        videoActive = playing
        val activity = currentActivity ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && supportsPip(activity)) {
            val params = PictureInPictureParams.Builder()
                .setAspectRatio(Rational(16, 9))
                .setAutoEnterEnabled(playing)
                .build()
            activity.runOnUiThread {
                try { activity.setPictureInPictureParams(params) } catch (_: Exception) {}
            }
        }
    }

    @ReactMethod
    fun setLandscape(enable: Boolean) {
        val activity = currentActivity ?: return
        activity.runOnUiThread {
            // Android throws IllegalStateException ("Only fullscreen
            // activities can request orientation") if the activity isn't
            // running truly fullscreen — e.g. in split-screen or freeform
            // multi-window mode, which is common on tablets/large screens.
            // That crash was taking the whole app down, which is why both
            // rotation AND the nav-bar hide appeared broken together on
            // large screens. We can't force-rotate in that case (the OS
            // won't allow one app to dictate orientation while sharing the
            // screen with another), so just skip it instead of crashing.
            val inMultiWindow = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                activity.isInMultiWindowMode
            } else false
            if (inMultiWindow) return@runOnUiThread
            try {
                activity.requestedOrientation = if (enable) {
                    android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                } else {
                    android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                }
            } catch (_: Throwable) {
                // Not fullscreen (split-screen/freeform/PiP), or a ROM that
                // refuses orientation changes outright. Catching only
                // IllegalStateException was not enough: anything else thrown
                // here runs on the UI thread and takes the whole app down.
                // setLandscape(false) is called while leaving the player,
                // which is exactly when the crash on exit was reported.
            }
        }
    }

    @ReactMethod
    fun setFullscreen(enter: Boolean) {
        isFullscreen = enter
        val activity = currentActivity ?: return
        activity.runOnUiThread { applyImmersiveMode(activity, enter) }
    }
}
