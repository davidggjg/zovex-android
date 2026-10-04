# התקנה מאפס — שרת ייעודי

מדריך מלא להקמת הבוט על שרת חדש, כולל חשבון טלגרם חדש ומפתחות חדשים.
מכוון לשרת עם 6 ליבות שלא רץ עליו שום דבר אחר.

---

## שלב 0 — מה צריך להכין לפני שמתחילים

| מה | מאיפה | כמה זמן |
|---|---|---|
| שרת לינוקס עם גישת root | — | — |
| מספר טלפון עם טלגרם | החשבון שהבוט יעבוד עליו | — |
| `api_id` + `api_hash` | https://my.telegram.org | 2 דקות |
| מפתחות Groq | https://console.groq.com/keys | דקה למפתח |
| מפתחות Gemini | https://aistudio.google.com/apikey | דקה למפתח |

**המלצה:** לפחות 5 מפתחות מכל סוג. כל מפתח הוא חשבון נפרד עם מכסה משלו,
והמערכת מריצה קטע תמלול לכל מפתח Groq וחלון תרגום לכל מפתח Gemini
**במקביל**. יותר מפתחות = עבודה מהירה יותר, לא רק גיבוי.

---

## שלב 1 — תלויות מערכת

```bash
apt update
apt install -y ffmpeg python3-venv python3-pip git fonts-noto-core curl
apt install -y fonts-noto-hebrew || true
fc-cache -f
```

בדיקה שיש פונט עברי (חובה לצריבה):

```bash
fc-list | grep -i hebrew | head -3
```

אם ריק — הכתוביות הצרובות יצאו ריבועים. התקן:
```bash
apt install -y fonts-noto-cjk fonts-dejavu && fc-cache -f
```

---

## שלב 2 — הורדת הקוד

```bash
mkdir -p /opt/zovexsub
git clone -b ccr-7e9ba85e-p9u399 https://github.com/davidggjg/zovex-android /opt/zovexsub/repo
ln -s /opt/zovexsub/repo/bot /opt/zovexsub/bot
```

---

## שלב 3 — סביבת פייתון

```bash
python3 -m venv /opt/zovexsub/venv
/opt/zovexsub/venv/bin/pip install --upgrade pip
/opt/zovexsub/venv/bin/pip install -r /opt/zovexsub/bot/requirements.txt
```

**אימות — חובה.** שתי החבילות האלה קריטיות:

```bash
/opt/zovexsub/venv/bin/python -c "import cryptg, yt_dlp, telethon; print('✅ cryptg — העברות מהירות'); print('✅ yt-dlp', yt_dlp.version.__version__, '— הורדה מקישור'); print('✅ telethon', telethon.__version__)"
```

`cryptg` מאיץ את ההצפנה פי עשרות. בלעדיה ההורדה תהיה איטית בצורה קיצונית.

---

## שלב 4 — מפתחות ה-API

### Groq (תמלול)

1. נכנסים ל-https://console.groq.com/keys
2. `Create API Key` → מעתיקים (מתחיל ב-`gsk_`)
3. חוזרים על זה בכל חשבון שיש לכם

### Gemini (תרגום)

1. נכנסים ל-https://aistudio.google.com/apikey
2. `Create API key` → מעתיקים (מתחיל ב-`AQ.`)
3. חוזרים על זה בכל חשבון

**חשוב לדעת:** בתוכנית החינמית מודלי `pro` חסומים לגמרי (`limit: 0`).
המערכת מזהה את זה אוטומטית ויורדת ל-`flash`. אם תפעילו חיוב בחשבון
Google, `pro` ייפתח והאיכות תשתפר — בעיקר בהתאמת זכר/נקבה — בלי שינוי קוד.

### טלגרם

1. נכנסים ל-https://my.telegram.org עם **מספר הטלפון של החשבון שהבוט יעבוד עליו**
2. `API development tools`
3. ממלאים שם אפליקציה כלשהו
4. מעתיקים `App api_id` ו-`App api_hash`

---

## שלב 5 — קובץ ההגדרות

```bash
cp /opt/zovexsub/bot/.env.dedicated.example /opt/zovexsub/bot/.env
nano /opt/zovexsub/bot/.env
```

ממלאים את ארבעת השדות הריקים:

```
TG_API_ID=12345678
TG_API_HASH=abc123...
GROQ_API_KEYS=gsk_1,gsk_2,gsk_3,gsk_4,gsk_5
GEMINI_API_KEYS=AQ.1,AQ.2,AQ.3,AQ.4,AQ.5
```

מפתחות מופרדים **בפסיק בלי רווחים**. שמירה: `Ctrl+O` → `Enter` → `Ctrl+X`.

```bash
chmod 600 /opt/zovexsub/bot/.env
```

בדיקה שהכל נקרא:

```bash
cd /opt/zovexsub/bot && /opt/zovexsub/venv/bin/python -c "
from zovexsub import config
print('Groq:', len(config.GROQ_API_KEYS), '| Gemini:', len(config.GEMINI_API_KEYS))
print('ליבות לצריבה:', config.BURN_THREADS)
print('בעיות:', config.validate() or 'אין')"
```

---

## שלב 6 — התחברות ראשונה לחשבון

**פעם אחת בלבד, ידנית:**

```bash
cd /opt/zovexsub/bot && /opt/zovexsub/venv/bin/python -m zovexsub.bot
```

הוא יבקש:

| שאלה | מה עונים |
|---|---|
| `Please enter your phone` | המספר עם קידומת: `+972501234567` |
| `Please enter the code` | הקוד שמגיע **בתוך טלגרם**, לא ב-SMS |
| `Please enter your password` | סיסמת האימות הדו-שלבי, אם מוגדרת |

כשמופיע `מחובר כ-... · 0 מורשים · N מפתחות Groq` — **`Ctrl+C`**.

נוצר קובץ `zovexsub.session` — זו ההתחברות השמורה. **אל תמחק אותו** ואל
תעתיק אותו לשרת אחר (טלגרם ינתק את שניהם).

---

## שלב 7 — הפעלה כשירות

```bash
cp /opt/zovexsub/bot/zovexsub-dedicated.service /etc/systemd/system/zovexsub.service
systemctl daemon-reload
systemctl enable --now zovexsub
systemctl status zovexsub --no-pager
```

אמור להציג `active (running)`.

**מעקב אחרי הלוג:**
```bash
tail -f /var/log/zovexsub.log
```
(יציאה: `Ctrl+C` — עוצר רק את הצפייה, לא את הבוט.)

---

## שלב 8 — בדיקה

בטלגרם, ב**הודעות השמורות** של החשבון:

1. שולחים סרטון קצר
2. **מגיבים** להודעת הסרטון עם `.srt`
3. אמור להופיע: `📥 מוריד` → `🎧 מחלץ אודיו` → `✍️ מתמלל` → `🇮🇱 מתרגם` → קובץ SRT
4. אחריו הצעת צריבה → עונים `כן` בתגובה

---

# מדריך שימוש

## פקודות למשתמשים

| פקודה | מה היא עושה |
|---|---|
| `.srt` בתגובה לסרטון | מפיק קובץ כתוביות בעברית |
| `.srt https://...` | מוריד את הווידאו מהקישור ומתמלל אותו |
| `.srt צריבה` בתגובה לסרטון | מבקש קובץ כתוביות קיים וצורב אותו |
| `כן` בתגובה להצעת הצריבה | מתחיל לצרוב |
| `.srt עזרה` | ההוראות |

**סרטון לבד לא מפעיל כלום.** חייבים להגיב לו עם הפקודה, והפקודה חייבת
להיות המילה הראשונה בהודעה ולהתחיל בנקודה.

## פקודות ניהול — רק מהחשבון עצמו

| פקודה | מה היא עושה |
|---|---|
| `.srt id` בתגובה להודעה | מראה שם, ID, והאם הוא מאושר |
| `.srt הוסף` בתגובה להודעה | מאשר את מי ששלח אותה |
| `.srt הוסף 123456789` | מאשר לפי ID |
| `.srt הסר 123456789` | מבטל אישור |
| `.srt רשימה` | כל המאושרים |
| `.srt ניהול` | כל פקודות הניהול |
| `.srt בדיקה` בתגובה לסרטון | דוח אבחון תזמונים |

**הדרך הנוחה להוסיף מישהו:** מעבירים (Forward) הודעה שלו להודעות
השמורות ומגיבים לה `.srt הוסף`.

הרשימה נשמרת ב-`allowlist.json` ליד הקוד. לא צריך לערוך `.env` ולא
להפעיל מחדש.

---

# תחזוקה

## עדכון הקוד

```bash
cd /opt/zovexsub/repo && git pull && /opt/zovexsub/venv/bin/pip install -r /opt/zovexsub/bot/requirements.txt && systemctl restart zovexsub
```

**אל תריץ באמצע עבודה** — ה-restart יהרוג אותה.

## הוספת מפתחות

```bash
nano /opt/zovexsub/bot/.env     # מוסיפים בסוף השורה, מופרד בפסיק
systemctl restart zovexsub
```

## החלפת חשבון הטלגרם

```bash
systemctl stop zovexsub
rm /opt/zovexsub/bot/zovexsub.session
nano /opt/zovexsub/bot/.env      # מעדכנים TG_API_ID ו-TG_API_HASH
cd /opt/zovexsub/bot && /opt/zovexsub/venv/bin/python -m zovexsub.bot   # התחברות חדשה
# Ctrl+C אחרי שמופיע "מחובר"
systemctl start zovexsub
```

## בדיקת תקינות הקוד

```bash
/opt/zovexsub/venv/bin/python -m pyflakes /opt/zovexsub/bot/zovexsub/*.py
```
פלט ריק = תקין.

---

# כוונון ביצועים

הקובץ `.env.dedicated.example` כבר מכוון לשרת ייעודי עם 6 ליבות. הנה מה
שאפשר לשנות ולמה.

## מהירות מול גודל הקובץ

| `BURN_PROFILE` | קודק | מהירות | גודל |
|---|---|---|---|
| `quick` | H.264 ultrafast | הכי מהיר | גדול |
| `balanced` | H.265 veryfast | בינוני | חצי |
| `small` | H.265 medium | איטי | הקטן ביותר |
| `auto` ← ברירת המחדל | לפי גודל המקור | | |

ב-`auto`, קובץ קטן מ-`QUICK_UNDER_MB` מקבל קידוד מהיר. אם הפלט הצפוי
חורג ממגבלת ההעלאה, המערכת יורדת לפרופיל דחוס אוטומטית.

**רוצים מהיר תמיד:**
```
BURN_PROFILE=quick
```

**רוצים קבצים קטנים תמיד:**
```
BURN_PROFILE=small
```

## ליבות

| משתנה | ערך לשרת ייעודי | הסבר |
|---|---|---|
| `BURN_THREADS` | `6` | כל הליבות. `auto` מתאים לשרת משותף |
| `RESERVE_CORES` | `0` | אין למי לשמור מקום |
| `NICE` | `0` | בלי הנמכת עדיפות |
| `FFMPEG_THREADS` | `2` | חילוץ אודיו, זול ממילא |

**על שרת משותף** (שרץ עליו גם אתר/סטרימינג) החזירו:
```
BURN_THREADS=auto
RESERVE_CORES=1.5
NICE=15
```

## מגבלות

| משתנה | ברירת מחדל | מה זה |
|---|---|---|
| `BURN_MAX_MINUTES` | 150 | מעל זה נשלח SRT בלי צריבה |
| `MAX_INPUT_MINUTES` | 180 | אורך מקסימלי לתמלול |
| `BURN_TIMEOUT` | auto | תקרת זמן, פי 4 מאורך הווידאו |
| `BURN_MAX_HEIGHT` | 1080 | תקרה בלבד; 4K יורד, 480p נשאר |

## מקביליות

| משתנה | ברירת מחדל | מה זה |
|---|---|---|
| `STT_PARALLEL` | 0 | קטעי תמלול במקביל. 0 = לפי מספר מפתחות Groq |
| `TRANSLATE_PARALLEL` | 0 | חלונות תרגום במקביל. 0 = לפי מפתחות Gemini |
| `PARALLEL_CEILING` | 16 | תקרה עליונה |
| `TG_CONNECTIONS` | 4 | בקשות במקביל מול טלגרם |

אם רואים הרבה `מכסה` או `429` בלוג — יורדים:
```
STT_PARALLEL=3
TRANSLATE_PARALLEL=3
```

---

# פתרון תקלות

| תסמין | סיבה ובדיקה |
|---|---|
| הבוט לא מגיב בכלל | `systemctl status zovexsub`; `tail -50 /var/log/zovexsub.log` |
| הבוט לא מגיב לפקודה | הפקודה חייבת להיות המילה הראשונה ולהתחיל בנקודה. ולוודא שהמשתמש מאושר |
| הורדה איטית מאוד (מתחת ל-1MB/s) | `/opt/zovexsub/venv/bin/python -c "import cryptg"` — אם נכשל, התקן |
| `HTTP 502` מ-Groq | עומס זמני אצלם. המערכת מנסה 10 פעמים, עוברת למודל גיבוי, ואז ל-Gemini |
| `limit: 0` על Gemini | מודלי pro חסומים בתוכנית חינמית. המערכת יורדת ל-flash לבד |
| כתוביות ריבועים בצריבה | אין פונט עברי: `apt install fonts-noto-core && fc-cache -f` |
| `אין מספיק מקום בדיסק` | `df -h`; המערכת דורשת פי 2.5 מגודל המקור ועוד 3GB |
| צריבה נעצרת על תקרת זמן | העלה `BURN_TIMEOUT_FACTOR` |
| סנכרון כתוביות לא מדויק | `.srt בדיקה` בתגובה לסרטון — מפיק דוח תזמונים מלא |

**לוג ממוקד בעבודה עצמה:**
```bash
tail -f /var/log/zovexsub.log | grep -E "מתמלל|מתרגם|תוקן|צורב|מעלה|❌|502"
```

---

# מה המערכת עושה מאחורי הקלעים

| שלב | כלי | תפקיד |
|---|---|---|
| 1 | ffmpeg | חילוץ אודיו FLAC 16kHz, חיתוך לקטעים לפי מספר המפתחות |
| 2 | Groq whisper-large-v3 | תמלול מקבילי עם חותמות זמן ברמת מילה |
| 3 | קוד | תיקון מילים שנמתחו, סינון המצאות, זיהוי דיבור |
| 4 | Groq | הקשבה חוזרת לכתוביות שהתזמון שלהן חשוד |
| 5 | Gemini + חיפוש | מסמך חקר: דוברים, מגדרים, שמות, מונחים |
| 6 | Gemini | תרגום מקבילי בחלונות, 1:1 לשורות המקור |
| 7 | Gemini | מעבר התאמת מגדר פנייה, ואחריו בקרת איכות |
| 8 | קוד | ניקוי ניקוד ואותיות זרות, בניית SRT |
| 9 | ffmpeg | צריבה אופציונלית עם קרדיט פתיחה |

התמלול והתרגום רצים **אצל הספקים**, לא על השרת. הדבר היחיד שצורך מעבד
משמעותי הוא הצריבה.
