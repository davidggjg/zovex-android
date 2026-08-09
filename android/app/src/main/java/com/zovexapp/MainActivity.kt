package com.zovexapp

import android.app.PictureInPictureParams
import android.content.Context
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import android.util.Rational
import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

class MainActivity : ReactActivity() {
    override fun getMainComponentName(): String = "ZovexApp"

    override fun createReactActivityDelegate(): ReactActivityDelegate =
        DefaultReactActivityDelegate(this, mainComponentName, fabricEnabled)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // בטלפון: נעל portrait (ה-UI מעוצב אנכית). בטלוויזיה: אפשר landscape,
        // אחרת התצוגה מופיעה מסובבת. מזהים טלוויזיה לפי UiMode.
        val uiMode = getSystemService(Context.UI_MODE_SERVICE) as android.app.UiModeManager
        if (uiMode.currentModeType != Configuration.UI_MODE_TYPE_TELEVISION) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
        // Most robust fix: listen for insets being (re)applied at all —
        // this fires on rotation, fold/unfold, split-screen, keyboard
        // showing, or the system re-showing bars for any reason — and
        // instantly re-hides them if we're supposed to be in fullscreen.
        // This covers cases onWindowFocusChanged/onConfigurationChanged
        // miss, which is what was still leaving the bar visible on some
        // large-screen / tablet transitions.
        window.decorView.setOnApplyWindowInsetsListener { view, insets ->
            if (PipModule.isFullscreen) {
                PipModule.applyImmersiveMode(this, true)
            }
            view.onApplyWindowInsets(insets)
        }
    }

    override fun onResume() {
        super.onResume()
        if (PipModule.isFullscreen) {
            PipModule.applyImmersiveMode(this, true)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus || !PipModule.isFullscreen) return
        PipModule.applyImmersiveMode(this, true)
    }

    // The manifest declares configChanges for orientation/screenLayout/
    // screenSize/smallestScreenSize so the Activity is NOT recreated when
    // those change (rotation, fold/unfold, entering split-screen on a
    // large screen or tablet). Because of that, onWindowFocusChanged alone
    // isn't reliably called on every one of those transitions, and the
    // navigation bar could reappear and stay visible. Re-apply the
    // immersive state here too so fullscreen sticks on large screens.
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (PipModule.isFullscreen) {
            PipModule.applyImmersiveMode(this, true)
        }
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (!PipModule.videoActive) return
        // חשוב: בודקים שהמכשיר תומך ב-PiP (FEATURE_PICTURE_IN_PICTURE) לפני הקריאה.
        // בטלפונים בלי תמיכת PiP (Qin F21/F22 Pro ורומים כשרים) enterPictureInPictureMode
        // זורק IllegalStateException ומקריס את האפליקציה כשסוגרים בזמן שסרט רץ.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            Build.VERSION.SDK_INT < Build.VERSION_CODES.S &&
            PipModule.supportsPip(this)) {
            // Android 8–11: manually enter PiP when user presses home, only if video is playing
            try {
                val params = PictureInPictureParams.Builder()
                    .setAspectRatio(Rational(16, 9))
                    .build()
                enterPictureInPictureMode(params)
            } catch (_: Exception) {
                // מכשיר לא תומך / מצב לא-פולסקרין — מדלגים במקום להקריס.
            }
        }
    }

    override fun onPictureInPictureModeChanged(
        isInPictureInPictureMode: Boolean,
        newConfig: Configuration
    ) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
    }
}
