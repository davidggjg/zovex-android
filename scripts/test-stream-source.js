#!/usr/bin/env node
/**
 * test-stream-source — איך נגזר סוג הזרם מהכתובת.
 *
 * הבאג שבגללו זה נכתב: ערוץ IPTV בכתובת ‎http://host/<user>/<pass>/<id>‎
 * (הצורה של Xtream Codes) לא התנגן בכלל. שלושת הנגנים הניחו שכל כתובת
 * שידור חי בלי סיומת היא HLS, שלחו ‎type:'m3u8'‎, ו-ExoPlayer בנה
 * HlsMediaSource שמצפה ל-‎#EXTM3U‎ — בעוד שהשרת מגיש MPEG-TS גולמי
 * שמתחיל ב-0x47. הפרסר נפל על הבית הראשון.
 *
 * מה שנבדק כאן הוא בדיוק מה שאי אפשר לבדוק בלי מכשיר ובלי השרת החי:
 * שהניחוש הראשון נכון, שיש תמיד דרך שנייה, ושלא נשברו הכתובות שכבר
 * עבדו. רץ על הקוד עצמו מ-src/utils/liveSource.js, לא על שכפול שלו.
 *
 *     node scripts/test-stream-source.js
 */
const babel = require('@babel/core');
const fs = require('fs');
const path = require('path');
const Module = require('module');

const file = path.resolve(__dirname, '../src/utils/liveSource.js');
const out = babel.transformSync(fs.readFileSync(file, 'utf8'), {
  configFile: false, babelrc: false, filename: file,
  presets: [[require.resolve('@babel/preset-env'),
             {targets: {node: 'current'}, modules: 'commonjs'}]],
}).code;
const m = new Module(file, null);
m.filename = file;
m.paths = Module._nodeModulePaths(path.dirname(file));
m._compile(out, file);
const {streamVariants, buildStreamSource, isXtreamStyle,
       variantLabel, LIVE_UA} = m.exports;

let pass = 0, fail = 0;
const t = (name, got, want) => {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log(`  ✗ ${name}\n      התקבל  ${a}\n      ציפינו ${b}`); }
};

console.log('\n1. הכתובת שדווחה (Xtream, בלי סיומת)');
const U = 'http://host.example/aliallham28/029753987589/472690';
t('מזוהה כ-Xtream', isXtreamStyle(U), true);
t('ארבע דרכים, בסדר הנכון', streamVariants(U), [
  {url: U},
  {url: U + '.m3u8', type: 'm3u8'},
  {url: U + '.ts'},
  {url: U, type: 'm3u8'},
]);
t('ניסיון 1: הכתובת החשופה, בלי type → TsExtractor',
  buildStreamSource(U, 0, {isLive: true}),
  {uri: U, headers: {'User-Agent': LIVE_UA}});
t('ניסיון 2: ‎.m3u8‎ — הצורה הסטנדרטית של Xtream ל-HLS',
  buildStreamSource(U, 1, {isLive: true}),
  {uri: U + '.m3u8', type: 'm3u8', headers: {'User-Agent': LIVE_UA}});
t('ניסיון 3: ‎.ts‎ — הצורה הסטנדרטית ל-MPEG-TS',
  buildStreamSource(U, 2, {isLive: true}),
  {uri: U + '.ts', headers: {'User-Agent': LIVE_UA}});
t('נגמרו הדרכים → null', buildStreamSource(U, 4, {isLive: true}), null);

console.log('\n2. הסיומת נדבקת לפני ה-query, לא אחריו');
const Q = 'http://h/user/pass/123?token=abc&exp=9';
t('‎.m3u8‎ לפני ה-?', streamVariants(Q)[1].url,
  'http://h/user/pass/123.m3u8?token=abc&exp=9');
t('‎.ts‎ לפני ה-?', streamVariants(Q)[2].url,
  'http://h/user/pass/123.ts?token=abc&exp=9');

console.log('\n3. כתובות שכבר עבדו — אסור לשבור');
t('.m3u8 → HLS ראשון, על אותה כתובת',
  streamVariants('http://h/live/x.m3u8')[0],
  {url: 'http://h/live/x.m3u8', type: 'm3u8'});
t('.mpd → DASH בלבד', streamVariants('http://h/x.mpd'),
  [{url: 'http://h/x.mpd', type: 'mpd'}]);
t('.mp4 → mp4 ראשון', streamVariants('http://h/v.mp4')[0],
  {url: 'http://h/v.mp4', type: 'mp4'});
t('.ts → progressive ראשון', streamVariants('http://h/a/b/c.ts')[0],
  {url: 'http://h/a/b/c.ts'});
t('בלי סיומת ולא Xtream → HLS ראשון, כמו קודם',
  streamVariants('http://h/live/channel5')[0],
  {url: 'http://h/live/channel5', type: 'm3u8'});

console.log('\n4. תמיד יש דרך שנייה (זה מה שמציל ניחוש שגוי)');
for (const u of ['http://h/live/x.m3u8', 'http://h/a/b/c.ts',
                 'http://h/live/channel5', U, 'http://h/v.mp4']) {
  t(`≥2 דרכים: ${u}`, streamVariants(u).length >= 2, true);
}

console.log('\n5. אף דרך לא חוזרת פעמיים');
for (const u of [U, Q, 'http://h/live/channel5']) {
  const keys = streamVariants(u).map(v => `${v.url}|${v.type || ''}`);
  t(`בלי כפילויות: ${u}`, keys.length, new Set(keys).size);
}

console.log('\n6. גבולות זיהוי Xtream');
t('שני מקטעים בלבד', isXtreamStyle('http://h/user/472690'), false);
t('מקטע אחרון לא מספרי', isXtreamStyle('http://h/a/b/channel'), false);
t('מקטע אחרון עם סיומת', isXtreamStyle('http://h/a/b/472690.ts'), false);
t('‎/movie/user/pass/id‎ נתפס גם', isXtreamStyle('http://h/movie/u/p/123'), true);

console.log('\n7. User-Agent');
t('שידור חי מקבל UA של VLC',
  buildStreamSource(U, 0, {isLive: true}).headers['User-Agent'], LIVE_UA);
t('תוכן רגיל — בלי headers',
  buildStreamSource('http://h/v.mp4', 0, {isLive: false}).headers, undefined);

console.log('\n8. תוויות לשורות השגיאה');
t('ניסיון 1', variantLabel(U, 0), 'ישיר');
t('ניסיון 2', variantLabel(U, 1), 'HLS+.m3u8');
t('ניסיון 3', variantLabel(U, 2), 'ישיר+.ts');
t('ניסיון 4', variantLabel(U, 3), 'HLS');

console.log('\n9. שלושת הנגנים באמת משתמשים בזה');
const root = path.resolve(__dirname, '..');
for (const f of ['src/components/LiveMedia3Player.js',
                 'src/components/NativePlayer.js',
                 'src/components/TvNativePlayer.js']) {
  const code = fs.readFileSync(path.join(root, f), 'utf8');
  t(`${path.basename(f)} מייבא buildStreamSource`,
    code.includes("from '../utils/liveSource'"), true);
  const hardcoded = code.split('\n').filter(
    l => !/^\s*(\/\/|\*)/.test(l) && /type:\s*'m3u8'/.test(l));
  t(`${path.basename(f)} בלי type:'m3u8' מקובע`, hardcoded, []);
}

console.log(`\n${fail === 0 ? '✓' : '✗'} ${pass} עברו, ${fail} נכשלו\n`);
process.exit(fail === 0 ? 0 : 1);
