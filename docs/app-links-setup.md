# הגדרת Android App Links (קישור https שפותח ישירות את האפליקציה)

הקוד כבר מוכן משני הצדדים (`AndroidManifest.xml` ו-`App.js`). נשארו שני שלבים ידניים שרק אתה יכול לעשות (דורשים גישה לחשבון GitHub ולקובץ החתימה של האפליקציה):

## שלב 1: קבל את ה-SHA256 fingerprint של חתימת האפליקציה

זה מוכיח לגוגל שהאפליקציה שלך והדומיין שלך שייכים לאותו גורם. תריץ בטרמינל (במחשב שיש עליו את קובץ ה-keystore ששימש לחתום את ה-APK ב-release):

```
keytool -list -v -keystore <הנתיב-לקובץ-keystore-שלך> -alias <alias-של-המפתח>
```

תעתיק את הערך שמופיע ליד `SHA256:` (מחרוזת ארוכה עם נקודותיים בין כל שני תווים, כמו `AA:BB:CC:...`).

## שלב 2: צור ריפו חדש בשם המדויק `davidggjg.github.io`

זה חייב להיות **בדיוק** השם הזה (זה השם המיוחד ש-GitHub Pages מזהה בתור "דף הבית" של החשבון שלך, לא דף פרויקט). בתוך הריפו החדש, צור קובץ בנתיב:

```
.well-known/assetlinks.json
```

עם התוכן הבא (תחליף את `PASTE_YOUR_SHA256_HERE` בערך שקיבלת בשלב 1):

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "com.zovexapp",
      "sha256_cert_fingerprints": [
        "PASTE_YOUR_SHA256_HERE"
      ]
    }
  }
]
```

(`com.zovexapp` הוא ה-package name של האפליקציה - אימתתי את זה מול `android/app/build.gradle`.)

## שלב 3: אפשר GitHub Pages בריפו החדש

הגדרות → Pages → Source: הענף `main`, תיקייה `/ (root)`.

## איך לבדוק שזה עבד

אחרי כמה דקות, תבדוק:
```
https://davidggjg.github.io/.well-known/assetlinks.json
```
זה אמור להחזיר את קובץ ה-JSON שיצרת (לא 404).

בנוסף, Google מספקת כלי בדיקה רשמי:
```
https://developers.google.com/digital-asset-links/tools/generator
```

## מה קורה בינתיים (עד שהשלבים האלה מבוצעים)

שום דבר לא נשבר. קישורי `https://davidggjg.github.io/zovex/...` ימשיכו להיפתח בדפדפן כרגיל, בדיוק כמו היום. הקישור המיוחד `zovex://<slug>` **כבר עובד עכשיו**, בלי שום הגדרה נוספת - זה הכי מהיר לבדוק שהקוד באפליקציה עצמו תקין, לפני שמשקיעים בהגדרת ה-App Links המלאה.
