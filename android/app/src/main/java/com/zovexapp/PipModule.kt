package com.zovexapp

import android.app.Activity
import android.app.PictureInPictureParams
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
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val params = PictureInPictureParams.Builder()
                .setAspectRatio(Rational(16, 9))
                .setAutoEnterEnabled(playing)
                .build()
            activity.runOnUiThread { activity.setPictureInPictureParams(params) }
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
            } catch (_: IllegalStateException) {
                // Not fullscreen (split-screen/freeform/PiP) — ignore.
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
