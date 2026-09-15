import {AppRegistry} from 'react-native';
import {enableScreens} from 'react-native-screens';
import App from './src/App';
import {lockLayoutDirection} from './src/i18n';
import {name as appName} from './app.json';

enableScreens();
// לפני הציור הראשון: מנוע הפריסה נעול על שמאל-לימין. ראה ההסבר המלא
// ב-src/i18n/index.js — החלפת שפה לא אמורה להפוך את הפריסה, והיפוך כזה
// הוא מה ששבר את הנגן (ה-✕ מתחת לסמל השידור, ±10 מתחלפים, פס התקדמות הפוך).
lockLayoutDirection();
AppRegistry.registerComponent(appName, () => App);
