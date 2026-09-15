// מילוני התרגום. המפתח הוא באנגלית ותיאורי, כדי שקריאה בקוד תסביר את עצמה.
//
// מתורגמים כאן רק מסכי המשתמש. מסכי הניהול (AdminDashboard, SavedUpload,
// AdminScreen) נשארים בעברית במכוון — רק המפעיל נכנס אליהם, ותרגום שלהם
// היה מכפיל את העבודה בלי שאף משתמש יראה אותה.

const he = {
  // ניווט וכללי
  'common.all': 'הכל',
  'common.live': 'שידורים חיים',
  'common.history': 'היסטוריה',
  'common.favorites': 'מועדפים',
  'common.downloads': 'הורדות',
  'common.search': 'חיפוש',
  'common.cancel': 'ביטול',
  'common.close': 'סגור',
  'common.retry': 'נסה שוב',
  'common.back': 'חזרה',
  'common.settings': 'הגדרות',
  'common.loading': 'טוען…',
  'common.noResults': 'לא נמצאו תוצאות',

  // מסך הבית
  'home.continueWatching': '▶ המשך צפייה',
  'home.support': 'תמיכה',
  'home.myFavorites': '❤ המועדפים שלי',
  'home.watch': '▶ צפה',
  'home.historyEmpty': 'ההיסטוריה שלך תופיע כאן',
  'home.favoritesEmpty': 'פריטים שתסמן בלב יופיעו כאן',

  // דף הפריט
  'detail.play': '▶ הפעל',
  'detail.download': '⬇ הורדה',
  'detail.addFavorite': 'הוסף למועדפים',
  'detail.removeFavorite': 'הסר מהמועדפים',

  // נגן
  'player.resumeTitle': 'להמשיך מאיפה שעצרת?',
  'player.resumeYes': 'המשך מכאן',
  'player.resumeNo': 'התחל מההתחלה',
  'player.speed': 'מהירות הפעלה',
  'player.speedNormal': 'רגיל',
  'player.nextEpisode': 'המשך לפרק הבא ▶',
  'player.nextLabel': 'הפרק הבא',
  'player.error': 'שגיאת ניגון',

  // הורדות
  'dl.downloading': 'מוריד {pct}%',
  'dl.remaining': 'נותרו {time}',
  'dl.notFound': 'קובץ ההורדה לא נמצא — ייתכן שההורדה לא הסתיימה. הורד שוב.',
  'dl.noDirectLink': 'אין קישור וידאו ישיר להורדה',
  'dl.failed': 'ההורדה נכשלה ({code})',

  // הגדרות
  'settings.title': 'הגדרות',
  'settings.language': 'שפה',
  'settings.languageHint': 'שינוי שפה מחליף את הטקסט מיד. כיוון הכתיבה יתעדכן לאחר הפעלה מחדש.',
  'settings.restartNeeded': 'כדי להשלים את המעבר, סגור את האפליקציה ופתח אותה מחדש.',
  'settings.about': 'אודות',
  'settings.version': 'גרסה {v}',

  // רשת

  // תמיכה
  'support.kind.support': 'תמיכה 💬',
  'support.kind.review': 'חוות דעת ⭐',
  'support.kind.tip': 'טיפ 💡',
  'support.gate': 'תמיכה, חוות דעת וטיפ פתוחים רק למחוברים',
  'support.empty': 'כתבו לנו כל דבר — בעיה, חוות דעת או רעיון לשיפור',
  'support.placeholder': 'כתבו הודעה...',
  'support.send': 'שלח',
  'support.button': 'תמיכה',

  // עדכון גרסה
  'update.install': 'התקן',
  'update.required': 'עדכון נדרש',
  'update.available': 'גרסה חדשה זמינה',
  'update.forcedBody': 'הגרסה שלכם אינה נתמכת יותר. יש לעדכן כדי להמשיך להשתמש באפליקציה.',
  'update.optionalBody': 'שדרגנו את האפליקציה! מומלץ לעדכן לגרסה האחרונה.',
  'update.installing': 'מתקין…',
  'update.badFile': 'הקובץ שהתקבל אינו תקין',
  'update.failed': 'העדכון האוטומטי נכשל. פותח את הדף להורדה ידנית.',

  // ערוצים חיים
  'live.notYet': 'עדיין לא הגיע',
  'live.title': 'שידור חי',
  'live.reminderSet': '🔔 יזכיר',
  'live.remindMe': 'הזכר לי',
  'genre.kids': '👶 ילדים',
  'genre.sport': '⚽ ספורט',
  'genre.news': '📰 חדשות ואקטואליה',
  'genre.doc': '🌍 דוקו וטבע',
  'genre.movies': '🎬 סרטים',
  'genre.series': '📺 סדרות ודרמה',
  'genre.lifestyle': '✨ לייף סטייל ובידור',
  'genre.other': '📡 עוד ערוצים',

  'net.offline': 'אין חיבור לשרת',
  'net.offlineHint': 'ייתכן שהרשת שאתה מחובר אליה חוסמת את השירות. נסה רשת אחרת או נתונים סלולריים.',
};

const en = {
  'common.all': 'All',
  'common.live': 'Live TV',
  'common.history': 'History',
  'common.favorites': 'Favorites',
  'common.downloads': 'Downloads',
  'common.search': 'Search',
  'common.cancel': 'Cancel',
  'common.close': 'Close',
  'common.retry': 'Try again',
  'common.back': 'Back',
  'common.settings': 'Settings',
  'common.loading': 'Loading…',
  'common.noResults': 'No results found',

  'home.continueWatching': '▶ Continue watching',
  'home.support': 'Support',
  'home.myFavorites': '❤ My favorites',
  'home.watch': '▶ Watch',
  'home.historyEmpty': 'Your watch history will appear here',
  'home.favoritesEmpty': 'Items you mark with a heart will appear here',

  'detail.play': '▶ Play',
  'detail.download': '⬇ Download',
  'detail.addFavorite': 'Add to favorites',
  'detail.removeFavorite': 'Remove from favorites',

  'player.resumeTitle': 'Resume where you left off?',
  'player.resumeYes': 'Resume',
  'player.resumeNo': 'Start from the beginning',
  'player.speed': 'Playback speed',
  'player.speedNormal': 'Normal',
  'player.nextEpisode': 'Next episode ▶',
  'player.nextLabel': 'Next episode',
  'player.error': 'Playback error',

  'dl.downloading': 'Downloading {pct}%',
  'dl.remaining': '{time} left',
  'dl.notFound': 'Downloaded file not found — the download may not have finished. Please download again.',
  'dl.noDirectLink': 'No direct video link available for download',
  'dl.failed': 'Download failed ({code})',

  'settings.title': 'Settings',
  'settings.language': 'Language',
  'settings.languageHint': 'Changing the language switches the text immediately. Writing direction updates after a restart.',
  'settings.restartNeeded': 'To finish switching, close the app and open it again.',
  'settings.about': 'About',
  'settings.version': 'Version {v}',


  'support.kind.support': 'Support 💬',
  'support.kind.review': 'Review ⭐',
  'support.kind.tip': 'Tip 💡',
  'support.gate': 'Support, reviews and tips are available to signed-in users only',
  'support.empty': 'Write to us about anything — a problem, feedback or an idea',
  'support.placeholder': 'Write a message...',
  'support.send': 'Send',
  'support.button': 'Support',

  'update.install': 'Install',
  'update.required': 'Update required',
  'update.available': 'A new version is available',
  'update.forcedBody': 'Your version is no longer supported. Please update to keep using the app.',
  'update.optionalBody': 'We have improved the app. Updating to the latest version is recommended.',
  'update.installing': 'Installing…',
  'update.badFile': 'The downloaded file is not valid',
  'update.failed': 'The automatic update failed. Opening the download page.',

  'live.notYet': 'Not started yet',
  'live.title': 'Live',
  'live.reminderSet': '🔔 Reminder set',
  'live.remindMe': 'Remind me',
  'genre.kids': '👶 Kids',
  'genre.sport': '⚽ Sports',
  'genre.news': '📰 News',
  'genre.doc': '🌍 Documentary & Nature',
  'genre.movies': '🎬 Movies',
  'genre.series': '📺 Series & Drama',
  'genre.lifestyle': '✨ Lifestyle & Entertainment',
  'genre.other': '📡 More channels',

  'net.offline': 'No connection to the server',
  'net.offlineHint': 'The network you are on may be blocking the service. Try a different network or mobile data.',
};

export default {he, en};
