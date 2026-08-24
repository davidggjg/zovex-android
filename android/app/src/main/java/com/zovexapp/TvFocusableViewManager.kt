package com.zovexapp

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.ReactContext
import com.facebook.react.uimanager.ThemedReactContext
import com.facebook.react.uimanager.ViewGroupManager
import com.facebook.react.uimanager.annotations.ReactProp
import com.facebook.react.uimanager.events.RCTEventEmitter
import com.facebook.react.views.view.ReactViewGroup

/**
 * מיכל שאפשר לנווט אליו עם שלט (D-pad) ושמדווח ל-JS מתי הוא מקבל/מאבד focus.
 *
 * למה בכלל צריך את זה: React Native הליבה (להבדיל מהפורק react-native-tvos)
 * *לא* תומך ב-onFocus/onBlur/hasTVPreferredFocus על Touchable/Pressable —
 * הפרופס האלה פשוט נבלעים בשקט. אנדרואיד כן מזיז focus בין רכיבים focusable
 * לבד, אבל בלי אירוע ל-JS אי אפשר לצייר שום סימון, ולכן למשתמש זה נראה כאילו
 * השלט מת. המעבר לפורק היה משנה את ה-Maven namespace של אנדרואיד ומסכן את
 * הקישור הנייטיב הידני שלנו, ולכן מוסיפים כאן רכיב עצמאי וקטן במקום.
 */
class TvFocusableView(context: Context) : ReactViewGroup(context) {

    private fun dp(v: Float) = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics)

    /** המרובע שמסמן את הפריט הממוקד — נצבע *מעל* התוכן (foreground) ולכן אינו
     *  משנה גודל או מיקום של שום דבר, ולא מזיז את השורה כמו מסגרת רגילה. */
    private val focusRect = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = dp(8f)
        setColor(Color.TRANSPARENT)
        setStroke(dp(3f).toInt(), Color.WHITE)
    }

    init {
        isFocusable = true
        isFocusableInTouchMode = true
        // הילדים (TouchableOpacity וכו') לא אמורים לחטוף focus בעצמם — אחרת
        // ה-D-pad "נתקע" בתוך הכרטיס במקום לעבור לכרטיס הבא.
        descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
    }

    private fun emit(name: String, focused: Boolean) {
        val ctx = context as? ReactContext ?: return
        val payload = Arguments.createMap().apply { putBoolean("focused", focused) }
        ctx.getJSModule(RCTEventEmitter::class.java).receiveEvent(id, name, payload)
    }

    override fun onFocusChanged(gainFocus: Boolean, direction: Int, prev: android.graphics.Rect?) {
        super.onFocusChanged(gainFocus, direction, prev)
        // מציירים/מסירים את המרובע מיד, בלי לחכות לסבב JS — כך הסימון עוקב
        // אחרי החץ בלי השהיה, כמו בכל ממשק טלוויזיה.
        foreground = if (gainFocus) focusRect else null
        emit("topFocusChange", gainFocus)
    }

    /** true לשדה החיפוש: לחיצה על המקש המרכזי מעבירה את ה-focus לתיבת הטקסט
     *  שבפנים, וכך נפתחת המקלדת של הטלוויזיה ואפשר להקליד. */
    var focusChildOnSelect = false

    private fun firstEditText(v: View = this): EditText? {
        if (v is EditText) return v
        if (v is ViewGroup) {
            for (i in 0 until v.childCount) firstEditText(v.getChildAt(i))?.let { return it }
        }
        return null
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        // אישור בשלט: המקש המרכזי, Enter, או כפתור A בג'ויסטיק.
        if (keyCode == KeyEvent.KEYCODE_DPAD_CENTER ||
            keyCode == KeyEvent.KEYCODE_ENTER ||
            keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER ||
            keyCode == KeyEvent.KEYCODE_BUTTON_A
        ) {
            if (focusChildOnSelect) {
                val edit = firstEditText()
                if (edit != null) {
                    // פותחים זמנית את החסימה כדי שתיבת הטקסט תוכל לקבל focus,
                    // ומבקשים את המקלדת. החסימה מוחזרת ברגע שהיא משחררת focus,
                    // כדי שה-D-pad ימשיך לדלג בין הפקדים ולא ייתקע בתוך התיבה.
                    descendantFocusability = ViewGroup.FOCUS_AFTER_DESCENDANTS
                    edit.isFocusableInTouchMode = true
                    edit.requestFocus()
                    (context.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager)
                        ?.showSoftInput(edit, InputMethodManager.SHOW_IMPLICIT)
                    edit.setOnFocusChangeListener { _, hasFocus ->
                        if (!hasFocus) {
                            descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
                        }
                    }
                    return true
                }
            }
            emit("topSelect", true)
            return true
        }
        return super.onKeyUp(keyCode, event)
    }
}

class TvFocusableViewManager : ViewGroupManager<TvFocusableView>() {

    override fun getName() = "TvFocusable"

    override fun createViewInstance(ctx: ThemedReactContext) = TvFocusableView(ctx)

    /** שדה חיפוש: לחיצה מרכזית מעבירה focus לתיבת הטקסט ופותחת מקלדת. */
    @ReactProp(name = "focusChildOnSelect")
    fun setFocusChildOnSelect(view: TvFocusableView, v: Boolean) {
        view.focusChildOnSelect = v
    }

    /** מבקש את ה-focus ההתחלתי — כך שלשלט יש מאיפה להתחיל כשהמסך נטען. */
    @ReactProp(name = "hasFocus")
    fun setHasFocus(view: TvFocusableView, hasFocus: Boolean) {
        if (hasFocus) {
            view.post { view.requestFocus() }
        }
    }

    override fun getExportedCustomDirectEventTypeConstants(): MutableMap<String, Any> =
        mutableMapOf(
            "topFocusChange" to mapOf("registrationName" to "onFocusChange"),
            "topSelect" to mapOf("registrationName" to "onSelect"),
        )
}
