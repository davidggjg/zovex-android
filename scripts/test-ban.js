#!/usr/bin/env node
/**
 * test-ban — בדיקות לחסימת הגישה לפי מייל.
 *
 * מקביל ל-‎zovex/scripts/test-ban.mjs‎ שבאתר: מרים שרת מדומה שמחזיר את
 * שתי התשובות, ומריץ מולו את ‎checkAccess‎ האמיתי מ-‎src/api/access.js‎
 * (לא העתק שלו — הקובץ עצמו, מתורגם ל-CJS בזמן ריצה).
 *
 * למה זה שווה בדיקה אוטומטית ולא רק ידנית: שלושת הכללים כאן הם בדיוק
 * אלה שאפשר לשבור בלי לשים לב, ושני כיווני השבירה גרועים —
 * "נחסם ממשיך לצפות" מצד אחד, ו"משתמש תקין נעול בגלל שנייה של רשת"
 * מצד שני. בדיקה ידנית מול הפרודקשן לא מכסה את השני בכלל.
 *
 *     node scripts/test-ban.js
 */
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');

const ROOT = path.resolve(__dirname, '..');

// ‎access.js‎ מייבא AsyncStorage, שאינו קיים מחוץ ל-React Native. מחליפים
// אותו בזיכרון בלבד — החלק שנבדק כאן (checkAccess) לא נוגע בו ממילא.
const FAKE_STORAGE = {
  __store: {},
  getItem: k => Promise.resolve(FAKE_STORAGE.__store[k] ?? null),
  setItem: (k, v) => { FAKE_STORAGE.__store[k] = v; return Promise.resolve(); },
  removeItem: k => { delete FAKE_STORAGE.__store[k]; return Promise.resolve(); },
};
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (req, ...rest) {
  if (req === '@react-native-async-storage/async-storage') return '__fake_async_storage__';
  return origResolve.call(this, req, ...rest);
};
require.cache.__fake_async_storage__ = {
  id: '__fake_async_storage__',
  filename: '__fake_async_storage__',
  loaded: true,
  exports: {default: FAKE_STORAGE, ...FAKE_STORAGE},
};

// מתרגמים את המקור האמיתי ל-CJS ומריצים אותו, כדי שהבדיקה תרוץ על הקוד
// שבאמת נשלח ולא על שכפול שלו שיתיישן.
function loadEsm(relPath, sourceOverride) {
  const babel = require('@babel/core');
  const file = path.join(ROOT, relPath);
  let code = sourceOverride ?? fs.readFileSync(file, 'utf8');
  const out = babel.transformSync(code, {
    configFile: false, babelrc: false, filename: file,
    presets: [[require.resolve('@babel/preset-env'), {targets: {node: 'current'}, modules: 'commonjs'}]],
  }).code;
  const m = new Module(file, null);
  m.filename = file;
  m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(out, file);
  return m.exports;
}

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '  → ' + extra : '')); }
}

// שרת מדומה. requests סופר כדי לאמת שאורח לא גורם לבקשה בכלל.
let mode = 'open';
let requests = [];
const server = http.createServer((req, res) => {
  requests.push(req.url);
  const email = new URL(req.url, 'http://x').searchParams.get('email');
  res.setHeader('Content-Type', 'application/json');
  if (mode === 'error500') { res.statusCode = 500; return res.end('{}'); }
  if (mode === 'garbage') { res.statusCode = 200; return res.end('<html>nope</html>'); }
  if (mode === 'truthy_string') {
    res.statusCode = 200;
    return res.end(JSON.stringify({blocked: 'true', message: 'should not block'}));
  }
  if (mode === 'blocked' && email === 'banned@test.com') {
    res.statusCode = 200;
    return res.end(JSON.stringify({blocked: true, message: 'נחסמת בגלל שיתוף חשבון'}));
  }
  if (mode === 'blocked_nomsg' && email === 'banned@test.com') {
    res.statusCode = 200;
    return res.end(JSON.stringify({blocked: true}));
  }
  res.statusCode = 200;
  res.end(JSON.stringify({blocked: false}));
});

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;

  // מפנים את הקובץ האמיתי לשרת המדומה; כל השאר הוא הקוד כמו שהוא.
  const src = fs.readFileSync(path.join(ROOT, 'src/api/access.js'), 'utf8');
  const realBase = "const BACKEND_URL = 'https://zovex.duckdns.org';";
  if (!src.includes(realBase)) {
    console.error('✗ לא נמצאה שורת BACKEND_URL ב-src/api/access.js — הבדיקה לא רצה על הקוד הנכון.');
    process.exit(1);
  }
  const {checkAccess} = loadEsm('src/api/access.js',
    src.replace(realBase, `const BACKEND_URL = '${base}';`));

  console.log('\n1. משתמש חסום → חסום, עם ההודעה מהשרת');
  mode = 'blocked';
  let r = await checkAccess('banned@test.com');
  check('blocked === true', r.blocked === true, JSON.stringify(r));
  check('ההודעה מהשרת הועברה', r.message === 'נחסמת בגלל שיתוף חשבון', r.message);

  console.log('\n2. משתמש תקין → אין חסימה');
  r = await checkAccess('fine@test.com');
  check('blocked === false', r.blocked === false, JSON.stringify(r));

  console.log('\n3. אורח → אין חסימה, ובלי בקשה לשרת בכלל');
  requests = [];
  for (const guest of [null, undefined, '', '   ']) {
    r = await checkAccess(guest);
    check(`blocked === false עבור ${JSON.stringify(guest)}`, r.blocked === false);
  }
  check('לא נשלחה שום בקשה', requests.length === 0, `נשלחו ${requests.length}`);

  console.log('\n4. השרת לא זמין / תשובה לא תקינה → אין חסימה');
  mode = 'error500';
  r = await checkAccess('banned@test.com');
  check('HTTP 500 אינו חוסם', r.blocked === false, JSON.stringify(r));
  mode = 'garbage';
  r = await checkAccess('banned@test.com');
  check('JSON פגום אינו חוסם', r.blocked === false, JSON.stringify(r));
  mode = 'truthy_string';
  r = await checkAccess('banned@test.com');
  check('blocked:"true" (מחרוזת) אינו חוסם', r.blocked === false, JSON.stringify(r));
  await new Promise(res => server.close(res));
  r = await checkAccess('banned@test.com');
  check('שרת כבוי אינו חוסם', r.blocked === false, JSON.stringify(r));

  console.log('\n5. נרמול המייל — זהה לשרת (strip + lower)');
  const srv2 = http.createServer((req, rs) => {
    requests.push(new URL(req.url, 'http://x').searchParams.get('email'));
    rs.setHeader('Content-Type', 'application/json');
    rs.end(JSON.stringify({blocked: false}));
  });
  await new Promise(r2 => srv2.listen(0, '127.0.0.1', r2));
  const {checkAccess: ca2} = loadEsm('src/api/access.js',
    src.replace(realBase, `const BACKEND_URL = 'http://127.0.0.1:${srv2.address().port}';`));
  requests = [];
  await ca2('  BanNed@Test.COM  ');
  check('נשלח מנורמל', requests[0] === 'banned@test.com', String(requests[0]));
  await new Promise(res => srv2.close(res));

  console.log('\n6. הודעה ריקה → נופל לברירת המחדל במסך');
  const blockedSrc = fs.readFileSync(path.join(ROOT, 'src/components/BlockedScreen.js'), 'utf8');
  check('קיימת ברירת מחדל "הגישה שלך נחסמה"',
    blockedSrc.includes("'הגישה שלך נחסמה'"));

  console.log('\n7. אין אף אלמנט שניתן ללחוץ עליו במסך החסימה');
  // מפשיטים הערות לפני הסריקה: ההערה בראש הקובץ *מסבירה* למה אין שם
  // TvFocusable, וסריקה נאיבית הייתה נופלת בדיוק על ההסבר הזה.
  const blockedCode = blockedSrc
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter(l => !/^\s*\/\//.test(l)).join('\n');
  for (const bad of ['TouchableOpacity', 'TouchableHighlight', 'TouchableWithoutFeedback',
                     'Pressable', 'Button', 'TvFocusable', 'onPress', 'Linking']) {
    check(`אין ${bad}`, !blockedCode.includes(bad));
  }
  check('pointerEvents="none" על השורש', blockedCode.includes('pointerEvents="none"'));

  console.log('\n8. המפתח באחסון זהה לזה של HomeScreen');
  const home = fs.readFileSync(path.join(ROOT, 'src/screens/HomeScreen.js'), 'utf8');
  const homeKey = (home.match(/const USER_KEY = '([^']+)'/) || [])[1];
  const accKey = (src.match(/const USER_KEY = '([^']+)'/) || [])[1];
  check(`USER_KEY תואם (${accKey})`, !!accKey && accKey === homeKey,
    `access=${accKey} home=${homeKey}`);

  console.log(`\n${fail === 0 ? '✓' : '✗'} ${pass} עברו, ${fail} נכשלו\n`);
  process.exit(fail === 0 ? 1 && 0 || 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
