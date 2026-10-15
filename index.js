import {AppRegistry, Text, TextInput, Dimensions} from 'react-native';
import {enableScreens} from 'react-native-screens';
import App from './src/App';
import {lockLayoutDirection} from './src/i18n';
import {name as appName} from './app.json';

enableScreens();

// ── גודל גופן מהמערכת ───────────────────────────────────────────────────────
// בטלפונים קטנים או עם "גודל גופן" מוגדל בהגדרות, כל טקסט באפליקציה גדל
// כפול (כותרות כרטיסים נשברות לאות-אות, הסרגל התחתון מתנפח). מגבילים את
// ההגדלה: עד 15% מעל הרגיל, ובמסך צר (פחות מ-360dp) בכלל בלי הגדלה.
// כך עדיין יש התחשבות בהעדפת המשתמש, אבל הפריסה לא נשברת.
// בטלוויזיה fontScale הוא 1, ולכן אין שום שינוי שם.
const FONT_CAP = Dimensions.get('window').width < 360 ? 1.0 : 1.15;
Text.defaultProps = {...(Text.defaultProps || {}), maxFontSizeMultiplier: FONT_CAP};
TextInput.defaultProps = {...(TextInput.defaultProps || {}), maxFontSizeMultiplier: FONT_CAP};
// לפני הציור הראשון: מנוע הפריסה נעול על שמאל-לימין. ראה ההסבר המלא
// ב-src/i18n/index.js — החלפת שפה לא אמורה להפוך את הפריסה, והיפוך כזה
// הוא מה ששבר את הנגן (ה-✕ מתחת לסמל השידור, ±10 מתחלפים, פס התקדמות הפוך).
lockLayoutDirection();
AppRegistry.registerComponent(appName, () => App);
