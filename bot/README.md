# בוט כתוביות עברית (Zovex Sub)

userbot בטלגרם שמקבל סרטון בכל שפה ומחזיר **קובץ SRT בעברית ברמת אולפן**,
ואופציונלית גם וידאו עם כתוביות צרובות (עד 10 דקות, צריבה קלה ומהירה).

## איך זה עובד

| שלב | כלי | מה קורה |
|---|---|---|
| 1 | ffmpeg | חילוץ אודיו FLAC 16kHz מונו, וחיתוך לחלקים אם צריך |
| 2 | Groq `whisper-large-v3` | תמלול עם חותמות זמן ברמת סגמנט ומילה + סינון "המצאות" על שקט |
| 3 | Gemini + חיפוש Google | מעבר חקר: נושא, דוברים ומגדריהם, אל מי פונים, שמות, מונחים, אימות ציטוטים |
| 4 | Gemini | תרגום/עריכה בחלונות, עם מסמך החקר כקונטקסט — התאמה 1:1 לשורות המקור |
| 5 | Gemini | בקרת איכות על כל הכתוביות יחד: זכר/נקבה, עקביות מונחים, מספרים |
| 6 | — | בניית SRT: תזמונים ללא חפיפות, מהירות קריאה, פיצול שורות עברי |
| 7 | ffmpeg | צריבה אופציונלית: `preset veryfast`, CRF 28, thread אחד, עד 720p |

**למה הזכר/נקבה יוצא נכון:** ההחלטה מי הדובר ואל מי הוא פונה מתקבלת **פעם
אחת על כל הסרטון** במעבר החקר, ואחר כך כל שורה מתורגמת לפי ההחלטה הזו —
במקום שהמודל ינחש מחדש בכל שורה. מעבר הבקרה בסוף סורק את כל הכתוביות
יחד ומתקן התאמות מגדר שנשברו באמצע.

## התקנה על שרת לינוקס

```bash
# 1. תלויות מערכת (ffmpeg + פונט עברי לצריבה)
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip fonts-noto-core fonts-noto-hebrew
fc-cache -f

# 2. הקוד
sudo mkdir -p /opt/zovexsub && sudo chown "$USER" /opt/zovexsub
git clone -b ccr-7e9ba85e-p9u399 https://github.com/davidggjg/zovex-android /opt/zovexsub/repo
ln -s /opt/zovexsub/repo/bot /opt/zovexsub/bot

# 3. סביבה וירטואלית
python3 -m venv /opt/zovexsub/venv
/opt/zovexsub/venv/bin/pip install -r /opt/zovexsub/bot/requirements.txt

# 4. הגדרות — כאן נכנסים המפתחות (לא בגיט!)
cp /opt/zovexsub/bot/.env.example /opt/zovexsub/bot/.env
nano /opt/zovexsub/bot/.env
chmod 600 /opt/zovexsub/bot/.env

# 5. התחברות ראשונה לחשבון (מספר טלפון + קוד). מריצים פעם אחת באופן ידני:
cd /opt/zovexsub/bot && /opt/zovexsub/venv/bin/python -m zovexsub.bot
```

`TG_API_ID` ו-`TG_API_HASH` נלקחים מ-https://my.telegram.org ← API development tools.

### הרצה כשירות

```bash
sudo cp /opt/zovexsub/bot/zovexsub.service /etc/systemd/system/zovexsub.service
sudo sed -i "s/User=%i/User=$USER/" /etc/systemd/system/zovexsub.service
sudo systemctl daemon-reload
sudo systemctl enable --now zovexsub
sudo journalctl -u zovexsub -f
```

## שימוש

בכל צ'אט, שולחים סרטון עם כיתוב:

| כיתוב | תוצאה |
|---|---|
| `.srt` | קובץ SRT בעברית |
| `.srt צריבה` | SRT + וידאו עם כתוביות צרובות (עד 10 דקות) |
| `.srt עזרה` | הוראות |

אפשר גם להשיב `.srt` להודעה שכבר מכילה סרטון.

### בדיקה בלי טלגרם

```bash
cd /opt/zovexsub/bot
/opt/zovexsub/venv/bin/python cli.py /path/to/video.mp4 --burn
```

## שליטה בעומס השרת

הכול ב-`.env`:

| משתנה | ברירת מחדל | מה זה עושה |
|---|---|---|
| `BURN_MAX_MINUTES` | 10 | מעל זה נשלח SRT בלבד, בלי צריבה |
| `BURN_PRESET` / `BURN_CRF` | veryfast / 28 | כמה הצריבה "חלשה ומהירה" |
| `BURN_MAX_HEIGHT` | 720 | הקטנת רזולוציה לפני צריבה |
| `FFMPEG_THREADS` | 1 | מספר ליבות ל-ffmpeg |
| `NICE` | 15 | עדיפות CPU נמוכה (+ `ionice -c 3`) |
| `MAX_INPUT_MINUTES` | 180 | אורך מקסימלי לתמלול |

בנוסף: **עבודה אחת בכל רגע** (תור פנימי), ו-`systemd` מגביל זיכרון ל-3GB
ועדיפות IO ל-idle.

## מפתחות API

`GROQ_API_KEYS` ו-`GEMINI_API_KEYS` מקבלים **כמה מפתחות מופרדים בפסיק**.
המערכת מסובבת ביניהם (round-robin), ומפתח שחוזר עם 429 נכנס לקירור
אוטומטי ולא נבחר עד שהוא משתחרר. אפשר להוסיף או להסיר מפתחות בכל שלב —
רק `.env` ואתחול השירות.

⚠️ מפתחות נשמרים **רק** ב-`.env`, שנמצא ב-`.gitignore`. מפתח שנחשף — החליפו אותו.
