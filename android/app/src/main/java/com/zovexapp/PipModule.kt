package com.zovexapp

import android.app.PictureInPictureParams
import android.os.Build
import android.util.Rational
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class PipModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

    override fun getName() = "PipModule"

    companion object {
        @Volatile var videoActive = false
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
    fun setFullscreen(enter: Boolean) {
        val activity = currentActivity ?: return
        activity.runOnUiThread {
            val window = activity.window
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val ctrl = window.insetsController ?: return@runOnUiThread
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
        }
    }
}
