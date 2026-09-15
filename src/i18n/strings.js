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

  'net.offline': 'No connection to the server',
  'net.offlineHint': 'The network you are on may be blocking the service. Try a different network or mobile data.',
};

export default {he, en};
