#!/usr/bin/env node
/**
 * test-dev-tv — מצב בדיקת הטלוויזיה על הטלפון.
 *
 * שתי סכנות שקטות כאן, ושתיהן נבדקות:
 *
 *   1. שהקוד הסודי ידלוף כטקסט גלוי לתוך האפליקציה. ‎strings‎ על ה-bundle
 *      מוצא אותו בשנייה, ואז הוא כתובת ולא סוד. נשמר רק ה-hash.
 *   2. שמצב הבדיקה יידלק אצל משתמש רגיל. הוא תלוי בדגל נייטיב שברירת
 *      המחדל שלו false, והשלט מצויר רק כשהוא דלוק.
 *
 *     node scripts/test-dev-tv.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const babel = require('@babel/core');
const Module = require('module');

const root = path.resolve(__dirname, '..');
let pass = 0, fail = 0;
const t = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '\n      ' + extra : '')); }
};

function loadEsm(rel) {
  const f = path.join(root, rel);
  const out = babel.transformSync(fs.readFileSync(f, 'utf8'), {
    configFile: false, babelrc: false, filename: f,
    presets: [[require.resolve('@babel/preset-env'),
               {targets: {node: 'current'}, modules: 'commonjs'}]],
  }).code;
  const m = new Module(f, null);
  m.filename = f; m.paths = Module._nodeModulePaths(path.dirname(f));
  m._compile(out, f);
  return m.exports;
}

console.log('\n1. SHA-256 שלנו נכון');
const {sha256hex} = loadEsm('src/utils/sha256.js');
for (const probe of ['', 'a', 'abc', 'ZOVEX', 'x'.repeat(200)]) {
  const want = crypto.createHash('sha256').update(probe).digest('hex');
  t(`תואם ל-node עבור קלט באורך ${probe.length}`, sha256hex(probe) === want);
}

console.log('\n2. הקוד הסודי אינו בקוד המקור כטקסט');
const home = fs.readFileSync(path.join(root, 'src/screens/HomeScreen.js'), 'utf8');
const m = home.match(/DEV_TV_HASH = '([0-9a-f]{64})'/);
t('קיים hash בן 64 תווים', !!m, m ? '' : 'לא נמצא DEV_TV_HASH');
// סורקים את כל ה-src: אסור ששום קובץ יכיל מחרוזת שה-hash שלה הוא זה.
// הבדיקה היא על כל "מילה" ארוכה בקוד, כלומר גם על קוד שהודבק בטעות
// במקום אחר לגמרי.
if (m) {
  const hash = m[1];
  let leaked = null;
  const walk = d => {
    for (const e of fs.readdirSync(d, {withFileTypes: true})) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { walk(p); continue; }
      if (!/\.(js|jsx|ts|tsx|kt|java|json|md)$/.test(e.name)) continue;
      const txt = fs.readFileSync(p, 'utf8');
      for (const tok of txt.match(/[^\s'"`,;(){}\[\]]{20,}/g) || []) {
        if (crypto.createHash('sha256').update(tok).digest('hex') === hash) {
          leaked = `${path.relative(root, p)}`;
          return;
        }
      }
    }
  };
  walk(path.join(root, 'src'));
  walk(path.join(root, 'android/app/src/main/java'));
  t('הסוד עצמו לא מופיע בשום קובץ מקור', leaked === null,
    leaked ? `נמצא ב-${leaked}` : '');
}

console.log('\n3. ברירת המחדל כבויה, ורק דגל נייטיב מדליק');
const isTv = fs.readFileSync(path.join(root, 'src/theme/isTv.js'), 'utf8');
t('IS_TV כולל גם את הדגל', /Platform\.isTV \|\| DEV_TV/.test(isTv));
t('IS_REAL_TV נשאר חומרה בלבד', /IS_REAL_TV = Platform\.isTV/.test(isTv));
t('IS_TV_EMULATED רק כשלא טלוויזיה אמיתית',
  /IS_TV_EMULATED = !Platform\.isTV && DEV_TV/.test(isTv));
const kt = fs.readFileSync(
  path.join(root, 'android/app/src/main/java/com/zovexapp/DevTvModule.kt'), 'utf8');
t('ברירת המחדל בנייטיב היא false', /getBoolean\(KEY, false\)/.test(kt));
t('נחשף כ-constant (נקרא סינכרונית בטעינה)', /getConstants/.test(kt));

console.log('\n4. השלט מצויר רק במצב הבדיקה');
t('HomeScreen מגדיר אותו מאחורי IS_TV_EMULATED',
  /\{IS_TV_EMULATED && <TvRemote \/>\}/.test(home));
const remote = fs.readFileSync(path.join(root, 'src/components/TvRemote.js'), 'utf8');
t('שולח KeyEvent אמיתי ולא מדמה', /DevTv\?\.sendKey/.test(remote));
for (const [name, code] of [['UP',19],['DOWN',20],['LEFT',21],['RIGHT',22],['CENTER',23]]) {
  t(`קוד מקש ${name}=${code} נכון`, new RegExp(`${name}: ${code}\\b`).test(remote));
}

console.log('\n5. כל מי שקורא את הדגל קורא מאותו מקום');
let stray = [];
const scan = d => {
  for (const e of fs.readdirSync(d, {withFileTypes: true})) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) { scan(p); continue; }
    if (!/\.js$/.test(e.name)) continue;
    if (p.endsWith('theme/isTv.js')) continue;
    const txt = fs.readFileSync(p, 'utf8');
    txt.split('\n').forEach((l, i) => {
      if (/Platform\.isTV/.test(l) && !/^\s*(\/\/|\*)/.test(l)) {
        stray.push(`${path.relative(root, p)}:${i + 1}`);
      }
    });
  }
};
scan(path.join(root, 'src'));
// שלושה שימושים לגיטימיים נשארו, וכולם שאלות על *חומרה* ולא על פריסה.
const ALLOWED = ['src/screens/HomeScreen.js', 'src/components/CrashBoundary.js'];
const bad = stray.filter(x => !ALLOWED.includes(x.split(':')[0]));
t('אין קריאה ישירה ל-Platform.isTV מחוץ למותר', bad.length === 0, bad.join(', '));

console.log(`\n${fail === 0 ? '✓' : '✗'} ${pass} עברו, ${fail} נכשלו\n`);
process.exit(fail === 0 ? 0 : 1);
