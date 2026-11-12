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
const {streamVariants, buildStreamSource, isXtreamStyle, LIVE_UA} = m.exports;

let pass = 0, fail = 0;
const t = (name, got, want) => {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log(`  ✗ ${name}\n      התקבל  ${a}\n      ציפינו ${b}`); }
};

console.log('\n1. הכתובת שדווחה (Xtream, בלי סיומת)');
const U = 'http://host.example/aliallham28/029753987589/472690';
t('מזוהה כ-Xtream', isXtreamStyle(U), true);
t('progressive ראשון ואז HLS', streamVariants(U), [{}, {type: 'm3u8'}]);
t('הניסיון הראשון בלי type → TsExtractor',
  buildStreamSource(U, 0, {isLive: true}),
  {uri: U, headers: {'User-Agent': LIVE_UA}});
t('הניסיון השני הוא HLS', buildStreamSource(U, 1, {isLive: true}).type, 'm3u8');
t('נגמרו הדרכים → null', buildStreamSource(U, 2, {isLive: true}), null);

console.log('\n2. כתובות שכבר עבדו — אסור לשבור');
t('.m3u8 → HLS ראשון', streamVariants('http://h/live/x.m3u8')[0], {type: 'm3u8'});
t('.m3u8 עם query', streamVariants('http://h/x.m3u8?token=1')[0], {type: 'm3u8'});
t('.mpd → DASH', streamVariants('http://h/x.mpd'), [{type: 'mpd'}]);
t('.mp4 → mp4', streamVariants('http://h/v.mp4')[0], {type: 'mp4'});
t('.ts → progressive ראשון', streamVariants('http://h/a/b/c.ts')[0], {});
t('בלי סיומת ולא Xtream → HLS ראשון, כמו קודם',
  streamVariants('http://h/live/channel5')[0], {type: 'm3u8'});

console.log('\n3. תמיד יש דרך שנייה (זה מה שמציל ניחוש שגוי)');
for (const u of ['http://h/live/x.m3u8', 'http://h/a/b/c.ts',
                 'http://h/live/channel5', U, 'http://h/v.mp4']) {
  t(`≥2 דרכים: ${u}`, streamVariants(u).length >= 2, true);
}

console.log('\n4. גבולות זיהוי Xtream');
t('שני מקטעים בלבד', isXtreamStyle('http://h/user/472690'), false);
t('מקטע אחרון לא מספרי', isXtreamStyle('http://h/a/b/channel'), false);
t('מקטע אחרון עם סיומת', isXtreamStyle('http://h/a/b/472690.ts'), false);
t('‎/movie/user/pass/id‎ נתפס גם', isXtreamStyle('http://h/movie/u/p/123'), true);

console.log('\n5. User-Agent');
t('שידור חי מקבל UA של VLC',
  buildStreamSource(U, 0, {isLive: true}).headers['User-Agent'], LIVE_UA);
t('תוכן רגיל — בלי headers',
  buildStreamSource('http://h/v.mp4', 0, {isLive: false}).headers, undefined);

console.log('\n6. שלושת הנגנים באמת משתמשים בזה');
const root = path.resolve(__dirname, '..');
for (const f of ['src/components/LiveMedia3Player.js',
                 'src/components/NativePlayer.js',
                 'src/components/TvNativePlayer.js']) {
  const code = fs.readFileSync(path.join(root, f), 'utf8');
  t(`${path.basename(f)} מייבא buildStreamSource`,
    code.includes("from '../utils/liveSource'"), true);
  // ‎type: 'm3u8'‎ מקובע חזרה בנגן הוא בדיוק הנסיגה שאנחנו מונעים.
  const hardcoded = code.split('\n').filter(
    l => !/^\s*(\/\/|\*)/.test(l) && /type:\s*'m3u8'/.test(l));
  t(`${path.basename(f)} בלי type:'m3u8' מקובע`, hardcoded, []);
}

console.log(`\n${fail === 0 ? '✓' : '✗'} ${pass} עברו, ${fail} נכשלו\n`);
process.exit(fail === 0 ? 0 : 1);
