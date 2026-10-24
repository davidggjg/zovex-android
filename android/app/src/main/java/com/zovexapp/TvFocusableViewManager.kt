package com.zovexapp

import android.content.Context
import android.os.SystemClock
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
/** כמה זמן אחרי שחלון קיבל focus עדיין נחשב "נפתח עכשיו". מספיק כדי
 *  לכסות את ה-Dialog של Modal, וקצר מכדי לפגוע בניווט רגיל. */
private const val INITIAL_FOCUS_GRACE_MS = 1000L

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

    /** האם בכלל להודיע ל-JS על תזוזת focus.
     *
     *  זה הפרט שקבע את תחושת השלט. כל תזוזת חץ היא *שתי* תזוזות focus —
     *  אחת מאבדת ואחת מקבלת — וכל אחת שלחה אירוע ל-JS, שם setState רינדר
     *  מחדש את הכרטיס, ומשם חזרה עדכון תצוגה לצד הנייטיב. ארבע חציות גשר
     *  ושני רינדורים של React על כל לחיצה בודדת, בזמן שהרשימה ממילא
     *  מרנדרת אצווה חדשה — ולכן הלחיצות הצטברו והשלט "לא הגיב".
     *
     *  הסימון עצמו מצויר כאן ממילא, בלי JS. לכן ברירת המחדל היא לא לדווח,
     *  ומי שבאמת צריך לדעת (דיאלוג עם עמעום, למשל) מבקש זאת במפורש.
     */
    var reportFocus = false

    /** עמעום כשאין focus — בקבוצת בחירה של שני כפתורים. נעשה כאן ולא ב-JS
     *  מאותה סיבה: שקיפות היא תכונת תצוגה, ואין שום סיבה לסבב React בשבילה. */
    var dimUnfocused = false
        set(v) {
            field = v
            alpha = if (!v || isFocused) 1f else 0.55f
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
        // הרמה קלה של הפריט הממוקד מעל שכניו. זה מה ש-cardFocused עשה ב-JS
        // דרך elevation; ה-shadow* שלצידו הוא iOS בלבד ולא צויר כאן מעולם.
        // translationZ ולא elevation, כדי לא לדרוס ערך שמגיע מהסגנון.
        translationZ = if (gainFocus) dp(9f) else 0f
        if (dimUnfocused) alpha = if (gainFocus) 1f else 0.55f
        if (reportFocus) emit("topFocusChange", gainFocus)
    }

    /** החצים לא יוצאים מקבוצת האחים שבתוך אותו מיכל.
     *
     *  zIndex ו-elevation קובעים מה *נראה* מעל מה, ולא לאן focus זז:
     *  חיפוש ה-focus של אנדרואיד הוא גאומטרי על כל החלון, והוא שמח לנחות
     *  על פקד שמוסתר לגמרי מאחורי שכבה. בבורר העונות זה אומר שחץ למטה
     *  מוציא את הסמן מהבורר אל רשימת הפרקים שמאחוריו — הסימון נעלם, ומה
     *  שהמשתמש רואה הוא בורר שלא מגיב.
     *
     *  לכן בשכבה מודאלית צריך גם לחסום יציאה, לא רק לבקש focus. הבדיקה
     *  היא מול *ההורה* שלנו, שהוא תיבת הבורר, ולכן היא מתארת בדיוק את
     *  קבוצת הפריטים שמותר לנוע ביניהם — בלי להעביר מזהים בין רכיבים.
     */
    var trapFocus = false

    override fun focusSearch(direction: Int): View? {
        val found = super.focusSearch(direction)
        if (!trapFocus) return found
        val box = parent as? ViewGroup ?: return found
        // [fix_trap_null] "אין יעד" אינו "לברוח", ואסור לחסום אותו.
        //
        // כאן הוחזר ‎this‎ גם כש-‎found‎ היה null, וזה שבר את בורר העונות:
        // כשהסמן על הפריט האחרון שנראה, חיפוש הפוקוס מחזיר null כי הפריט
        // הבא נמצא מחוץ לאזור הנראה של ה-ScrollView. null הוא בדיוק האות
        // ש-ScrollView מחכה לו — הוא גולל בעצמו ואז מחפש שוב. בהחזרת
        // ‎this‎ ביטלנו את המנגנון הזה, והרשימה נתקעה פריט אחד לפני הסוף.
        //
        // דווח שלוש פעמים: 4 → 5 → 6, וכל "תיקון" שהרחיב את התצוגה רק
        // הזיז את הקיר בפריט אחד. זו הייתה הסיבה כל הזמן.
        //
        // המלכודת נועדה למנוע בריחה לפקדים שמוסתרים מאחורי השכבה, כלומר
        // למקרה שבו *נמצא* יעד והוא מחוץ לקבוצה. רק הוא נחסם.
        if (found == null) return null
        var p: android.view.ViewParent? = found.parent
        while (p != null) {
            if (p === box) return found
            p = p.parent
        }
        // נמצא יעד מחוץ לקבוצה — זו הבריחה. נשארים במקום.
        return this
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

    // ── בקשת focus שמחכה עד שהיא באמת יכולה להצליח ──────────────────────
    //
    // קודם היה כאן post { requestFocus() } — ניסיון **אחד**. זה עובד במסך
    // רגיל ולא עובד ב-Modal, ותפריט הפרופיל בטלוויזיה נשאר בלי focus:
    // ה-D-pad המשיך לנווט במסך שמאחור, ולמשתמש זה נראה כאילו השלט מת.
    // אומת על הגרסה האחרונה, אחרי שהתיקון הקודם כבר היה בפנים.
    //
    // אומת במקור של react-native 0.73.6, ReactModalHostView:
    //
    //     mDialog.getWindow().setFlags(FLAG_NOT_FOCUSABLE, FLAG_NOT_FOCUSABLE);
    //     ...
    //     mDialog.getWindow().clearFlags(FLAG_NOT_FOCUSABLE);
    //
    // כלומר RN פותח את חלון ה-Modal **כחלון שאינו יכול לקבל focus**,
    // ומסיר את הדגל רק אחרי שהחלון כבר מוצג. ברגע שבו ה-prop מגיע אף
    // תצוגה בחלון הזה לא יכולה לקבל focus, ולכן post יחיד תמיד נכשל —
    // וגם בדיקה מקדימה על hasWindowFocus() רק דוחה את כל הניסיונות.
    //
    // onWindowFocusChanged הוא בדיוק הרגע שבו הדגל מוסר, ולכן הוא
    // הטריגר האמין; הניסיונות החוזרים הם רשת ביטחון סביבו.
    //
    // הניסיונות נעצרים ברגע שיש focus, ותקרה של 30 (כ-1.5 שניות) מונעת
    // לולאה אם משהו אחר מונע אותו לגמרי.
    private var focusTries = 0
    private var focusWanted = false
    /** האם הבקשה הנוכחית מורשית לקחת focus ממחזיק קיים. ראה
     *  requestFocusTakeover. */
    private var takeover = false

    /** מתי החלון הזה קיבל focus לאחרונה.
     *
     *  צריך להבדיל בין שני מצבים שנראים זהים מבפנים: "המשתמש עומד על
     *  משהו" לעומת "אנדרואיד בחר בעצמו את ה-view הראשון ברגע שהחלון
     *  נפתח". בשני המקרים יש מחזיק focus, אבל רק הראשון הוא בחירה של
     *  אדם — ועל השני אסור לוותר, אחרת בקשת ה-focus ההתחלתית ב-Modal
     *  מפסידה תמיד למי שאנחנו לא בחרנו. ראה את ההסבר ב-someoneElseHasIt. */
    private var windowFocusedAt = 0L

    /** האם הבקשה ההתחלתית כבר מולאה **עבור התצוגה הזאת**.
     *
     *  ‎hasFocus‎ פירושו "התחל כאן", ולא "החזר אליי focus בכל הזדמנות".
     *  בלי הדגל הזה כל הרכבה מחדש של הכרטיס הראשון — וזה קורה כל הזמן,
     *  כי ‎FlatList‎ ממחזר תאים כשגוללים — הריצה שוב את הבקשה **וגנבה את
     *  ה-focus** מהמקום שבו המשתמש עמד.
     *
     *  זה בדיוק מה שדווח מהשטח: "לוחץ, לא מגיב, ואז קופץ את שתי הלחיצות
     *  — אבל אז צריך שוב לנווט למקום הנכון". החלק האחרון אינו איטיות
     *  אלא focus שנלקח.
     */
    private var initialFocusDone = false

    fun requestFocusWhenReady() {
        if (initialFocusDone) return
        initialFocusDone = true
        focusWanted = true
        focusTries = 0
        tryFocusSoon()
    }

    /** שכבה שנפתחה *בתוך* חלון שכבר פתוח — ולכן מותר לה לקחת focus.
     *
     *  ‎requestFocusWhenReady‎ מוותר כשמישהו אחר מחזיק focus, וההגנה הזאת
     *  נכונה: בלעדיה כל כרטיס שנבנה מחדש היה גונב את הסמן. היא מוותרת רק
     *  בחלון שנפתח עכשיו (‎INITIAL_FOCUS_GRACE_MS‎), כי שם המחזיק הוא
     *  בחירה אוטומטית של ‎ViewRootImpl‎ ולא של אדם.
     *
     *  בורר העונות אינו חלון. הוא נפתח כשכבה בתוך חלון הפרטים שפתוח
     *  מזמן, וה-focus יושב על כפתור "עונה X ▾" שמאחוריו — מחזיק *אמיתי*,
     *  מלפני יותר משנייה. לכן הבקשה ויתרה תמיד, הבורר הופיע בלי סימון,
     *  והחצים הזיזו focus לפקדים שמוסתרים מאחורי השכבה. זה מה שדווח
     *  כ"אי אפשר לעבור בין עונות".
     *
     *  הבקשה הזאת אומרת במפורש "קח", ולכן היא פרופ נפרד מ-‎hasFocus‎
     *  ואין בה את התנאי הזה. מי שמבקש אותה הוא שכבה שהמשתמש פתח בעצמו
     *  באותו רגע, ולכן לקיחת ה-focus היא בדיוק מה שהוא ציפה לו.
     */
    fun requestFocusTakeover() {
        if (initialFocusDone) return
        initialFocusDone = true
        focusWanted = true
        focusTries = 0
        takeover = true
        tryFocusSoon()
    }

    /** ליציאה ממצב הקלדה: שם הבקשה היא כן "תחזיר אליי", ולכן היא מפורשת. */
    fun requestFocusBack() {
        focusWanted = true
        focusTries = 0
        tryFocusSoon()
    }

    private fun tryFocusSoon() {
        post {
            if (!focusWanted || isFocused) return@post
            // פשוט לנסות, ולבדוק אם הצליח.
            //
            // כאן הייתה בדיקה מקדימה — width/height/hasWindowFocus — ובמקום
            // להגן היא חסמה: ב-Dialog של Modal אחד התנאים לא מתקיים בזמן,
            // כל 20 הניסיונות נדחו בלי שאף אחד מהם באמת ניסה, והתפריט נשאר
            // בלי focus. התנאי הזה החמיר את המצב במקום לתקן אותו.
            //
            // requestFocus כבר מחזיר false בעצמו כשאי אפשר, ולכן ערך החזרה
            // שלו הוא הבדיקה הנכונה היחידה — ומנסים שוב עד שהוא מצליח.
            // ── "התחל כאן" אינו "קח ממי שמחזיק" ────────────────────────
            //
            // הבקשה הזאת באה מ-‎hasTVPreferredFocus‎, שפירושו focus
            // **התחלתי**. אם משהו אחר בחלון כבר ממוקד — המשתמש נמצא שם.
            //
            // מה שקרה בלעדיה: בכל הקלדה בחיפוש רשימת התוצאות מתחלפת,
            // הכרטיס הראשון הוא **תצוגה חדשה** עם הבקשה הזאת, והוא לקח
            // את ה-focus מתיבת הטקסט. אנדרואיד סוגר את המקלדת ברגע
            // שהתיבה מאבדת focus — ולכן נכנסה אות אחת בדיוק, וזה מה
            // שדווח מהשטח. אותו דבר קרה בניווט: כל אצווה חדשה החזירה את
            // הסמן לכרטיס הראשון, ו"היה צריך שוב לנווט למקום הנכון".
            // ── אבל "מישהו אחר" יכול להיות גם הבחירה של אנדרואיד ──────
            //
            // כשחלון נפתח, ‎ViewRootImpl‎ נותן focus ל-view הראשון שמסוגל
            // לקבל אותו. ב-Modal זה קרה לפני שהבקשה שלנו רצה, ולכן
            // הבדיקה שלמטה מצאה "מחזיק" — ויתרה לצמיתות
            // (‎focusWanted = false‎), ו-‎initialFocusDone‎ כבר מנע ניסיון
            // נוסף. התוצאה: בחלון הפרטים בטלוויזיה לא היה סימון על
            // ההפעלה ולא הייתה דרך להגיע לבורר העונות.
            //
            // הזמן הוא ההבדל. משתמש שעומד על משהו עשה את זה מתישהו;
            // הבחירה האוטומטית קורית באותו רגע שהחלון מקבל focus. לכן
            // בחלון שרק עכשיו נפתח הבקשה ההתחלתית מנצחת, ובמסך שכבר
            // פתוח מזמן ההגנה נשארת בדיוק כפי שהייתה — וזה מה שמונע
            // מכרטיס שנבנה מחדש לגנוב focus מתיבת החיפוש.
            val windowJustOpened =
                SystemClock.uptimeMillis() - windowFocusedAt < INITIAL_FOCUS_GRACE_MS
            val someoneElseHasIt = !takeover && !windowJustOpened &&
                (rootView?.findFocus() != null) && findFocus() == null
            if (someoneElseHasIt) {
                focusWanted = false
                return@post
            }
            if (isAttachedToWindow && requestFocus()) {
                focusWanted = false
                takeover = false
                return@post
            }
            if (focusTries++ < 30) postDelayed({ tryFocusSoon() }, 50)
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        // חיבור לחלון הוא בדיוק הרגע שבו בקשה שנכשלה קודם יכולה להצליח.
        if (focusWanted && !isFocused) tryFocusSoon()
    }

    override fun onWindowFocusChanged(hasWindowFocus: Boolean) {
        super.onWindowFocusChanged(hasWindowFocus)
        if (hasWindowFocus) windowFocusedAt = SystemClock.uptimeMillis()
        if (hasWindowFocus && focusWanted && !isFocused) tryFocusSoon()
    }
}

class TvFocusableViewManager : ViewGroupManager<TvFocusableView>() {

    override fun getName() = "TvFocusable"

    override fun createViewInstance(ctx: ThemedReactContext) = TvFocusableView(ctx)

    /** האם לשלוח ל-JS אירוע על כל תזוזת focus. ברירת המחדל היא לא — ראה
     *  reportFocus ב-TvFocusableView: זה היה המחיר של כל לחיצת חץ. */
    @ReactProp(name = "reportFocus")
    fun setReportFocus(view: TvFocusableView, v: Boolean) {
        view.reportFocus = v
    }

    /** עמעום כשאין focus, בצד הנייטיב. */
    @ReactProp(name = "dimUnfocused")
    fun setDimUnfocused(view: TvFocusableView, v: Boolean) {
        view.dimUnfocused = v
    }

    /** שדה חיפוש: לחיצה מרכזית מעבירה focus לתיבת הטקסט ופותחת מקלדת. */
    @ReactProp(name = "focusChildOnSelect")
    fun setFocusChildOnSelect(view: TvFocusableView, v: Boolean) {
        view.focusChildOnSelect = v
    }

    /** פותח/סוגר את חסימת ה-focus לילדים. ה-JS מרים את זה רגע לפני שהוא
     *  קורא ל-focus() על תיבת הטקסט — כך המקלדת נפתחת דרך המנגנון של RN,
     *  שאמין יותר מ-showSoftInput ידני, ואז החסימה חוזרת. */
    @ReactProp(name = "allowChildFocus")
    fun setAllowChildFocus(view: TvFocusableView, allow: Boolean) {
        if (allow) {
            view.descendantFocusability = android.view.ViewGroup.FOCUS_AFTER_DESCENDANTS
            return
        }
        // [tv_keyboard] חסימה כשילד ממוקד — לאן ה-focus הולך.
        //
        // setDescendantFocusability(FOCUS_BLOCK_DESCENDANTS) מנקה את
        // ה-focus מילד שממוקב באותו רגע, ומשם אנדרואיד מחפש יעד חדש
        // גאומטרית — כלומר ה-focus עלול לנחות במקום שרירותי במסך, או
        // לא לנחות בכלום. בתיבת החיפוש זה נראה כמו שלט שהפסיק להגיב.
        //
        // לכן מבקשים אותו בחזרה אל העטיפה עצמה, שהיא focusable ממילא
        // (ראה init). כך היציאה ממצב הקלדה מחזירה את המרובע בדיוק למקום
        // שממנו המשתמש נכנס, וה-D-pad ממשיך משם.
        val had = view.findFocus() != null
        view.descendantFocusability = android.view.ViewGroup.FOCUS_BLOCK_DESCENDANTS
        if (had && !view.isFocused) {
            view.requestFocusBack()
        }
    }

    /** מבקש את ה-focus ההתחלתי — כך שלשלט יש מאיפה להתחיל כשהמסך נטען.
     *  ראה requestFocusWhenReady: ב-Modal הבקשה מגיעה לפני שהחלון קיים,
     *  ולכן היא חוזרת עד שהיא מצליחה במקום לנסות פעם אחת. */
    @ReactProp(name = "hasFocus")
    fun setHasFocus(view: TvFocusableView, hasFocus: Boolean) {
        if (hasFocus) view.requestFocusWhenReady()
    }

    /** שכבה שנפתחה בתוך חלון פתוח ולכן מותר לה לקחת focus מהמחזיק —
     *  ראה requestFocusTakeover. נפרד מ-hasFocus בכוונה. */
    @ReactProp(name = "focusNow")
    fun setFocusNow(view: TvFocusableView, v: Boolean) {
        if (v) view.requestFocusTakeover()
    }

    /** חוסם יציאה של החצים מקבוצת האחים — ראה trapFocus. */
    @ReactProp(name = "trapFocus")
    fun setTrapFocus(view: TvFocusableView, v: Boolean) {
        view.trapFocus = v
    }

    override fun getExportedCustomDirectEventTypeConstants(): MutableMap<String, Any> =
        mutableMapOf(
            "topFocusChange" to mapOf("registrationName" to "onFocusChange"),
            "topSelect" to mapOf("registrationName" to "onSelect"),
        )
}
