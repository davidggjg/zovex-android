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
        val realTv = uiMode.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
        if (!realTv) {
            // מצב בדיקת הטלוויזיה: טלוויזיה היא לרוחב, ובדיקה במסך אנכי
            // לא מראה את מה שבאמת צריך לבדוק — הפריסה, מספר העמודות
            // וכיוון תנועת ה-focus כולם נגזרים מהיחס. לכן שם לרוחב,
            // ובכל שאר המקרים נשאר אנכי כרגיל.
            requestedOrientation = if (DevTvModule.isEnabled(this)) {
                ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            } else {
                ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            }
        }
        // Most robust fix: listen for insets being (re)applied at all —
        // this fires on rotation, fold/unfold, split-screen, keyboard
        // showing, or the system re-showing bars for any reason — and
        // instantly re-hides them if we're supposed to be in fullscreen.
        // This covers cases onWindowFocusChanged/onConfigurationChanged
        // miss, which is what was still leaving the bar visible on some
        // large-screen / tablet transitions.
        window.decorView.setOnApplyWindowInsetsListener { view, insets ->
            applyChrome()
            view.onApplyWindowInsets(insets)
        }
        applyChrome()
    }

    /**
     * סרגלי המערכת.
     *
     * סרגל הניווט של אנדרואיד מוסתר **תמיד**, בכל טלפון, ולא רק בזמן
     * סרט. הוא אינו משמש את האפליקציה בשום מסך — יש לה ניווט תחתון משלה
     * ו"אחורה" עובד בתנועה — והוא רק אוכל שורה מהמסך. שורת הסטטוס
     * (שעה, סוללה, קליטה) נשארת: היא כן נותנת מידע, והמשתמש מצפה לראות
     * אותה.
     *
     * ‎BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE‎ ולא הסתרה קשיחה: החלקה מהקצה
     * מחזירה את הסרגל לרגע, ולכן מי שרוצה את כפתורי הניווט עדיין מגיע
     * אליהם. בלי זה היינו נועלים מכשירים עם ניווט בשלושה כפתורים.
     *
     * בזמן מסך מלא בנגן ממשיכים למסלול הקיים, שמסתיר גם את שורת הסטטוס.
     */
    private fun applyChrome() {
        if (PipModule.isFullscreen) {
            PipModule.applyImmersiveMode(this, true)
            return
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val ctrl = window.insetsController ?: return
                ctrl.hide(android.view.WindowInsets.Type.navigationBars())
                ctrl.systemBarsBehavior =
                    android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            } else {
                @Suppress("DEPRECATION")
                window.decorView.systemUiVisibility =
                    (android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        or android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        or android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        or android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION)
            }
        } catch (_: Exception) {
            // תקלה ספציפית ליצרן לא תפיל את האפליקציה בגלל סרגל.
        }
    }

    override fun onResume() {
        super.onResume()
        applyChrome()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        // רק כשהחלון שלנו בחזית: החלת מצב סרגלים על חלון שאיבד focus
        // נלחמת במקלדת ובחלונות מערכת.
        if (hasFocus) applyChrome()
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
        applyChrome()
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
        // כל שאר מעברי הלייאאוט למעלה (onResume/onWindowFocusChanged/
        // onConfigurationChanged) מחילים מחדש את מצב המסך-המלא הסוחף אם
        // isFullscreen. זה היה היחיד שלא - וזה בדיוק הקריאה שמגיעה כשחוזרים
        // מ-PiP (חלון צף) למסך מלא. בלעדיו הסרגלים של המערכת יכולים להישאר
        // גלויים ולשנות את גודל האזור הזמין, מה שיכול לטלטל את הפריסה בדיוק
        // ברגע שהצופה מצפה לחזור ישר לנגן.
        if (!isInPictureInPictureMode) applyChrome()
    }
}
