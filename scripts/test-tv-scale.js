#!/usr/bin/env node
/**
 * test-tv-scale — המקדם שמתקן את הפרופורציות בטלוויזיה.
 *
 * הבאג: גוגל מגדירה את בסיס העיצוב לטלוויזיה כ-960×540 dp, אבל חלק
 * מקופסאות ה-Android TV מדווחות צפיפות 1.0, כלומר 1920dp. באפליקציה יש
 * 80 מידות קבועות ב-dp רק ב-HomeScreen; על מסך כזה כולן מתכווצות ליחס
 * חצי, בעוד שמידות שנגזרות מהמסך (הבאנר) נשארות נכונות. מכאן "הבאנר ענק
 * והטקסט זעיר, שום דבר לא פרופורציונלי".
 *
 * מה שנבדק: שבטלפון ובטלוויזיה תקינה לא משתנה **כלום** (זה החלק
 * המסוכן — רגרסיה כאן נוגעת בכל מסך), ושעל קופסה של 1920dp המידות
 * הנכונות מוכפלות והלא-נכונות לא.
 *
 *     node scripts/test-tv-scale.js
 */
// ופעם כקופסת TV שמדווחת 1920dp.
const babel=require('@babel/core'),fs=require('fs'),path=require('path'),Module=require('module');
function load(isTV,w,h){
  const f=require('path').resolve(__dirname,'../src/theme/tvScale.js');
  let code=fs.readFileSync(f,'utf8');
  const out=babel.transformSync(code,{configFile:false,babelrc:false,filename:f,
    presets:[[require.resolve('@babel/preset-env'),{targets:{node:'current'},modules:'commonjs'}]]}).code;
  const fake={Platform:{isTV},Dimensions:{get:()=>({width:w,height:h})}};
  const orig=Module._load;
  Module._load=function(r,...a){ if(r==='react-native') return fake; return orig.call(this,r,...a); };
  const m=new Module(f,null); m.filename=f; m.paths=Module._nodeModulePaths(path.dirname(f));
  try{ m._compile(out,f); } finally { Module._load=orig; }
  return m.exports;
}
let pass=0,fail=0;
const t=(n,g,w)=>{const a=JSON.stringify(g),b=JSON.stringify(w);
  if(a===b){pass++;console.log('  ok  '+n)}else{fail++;console.log('  FAIL '+n+'\n       got '+a+'\n       want '+b)}};

const SHEET={
  title:{fontSize:14,lineHeight:20,paddingHorizontal:16,borderRadius:12,color:'#fff',fontWeight:'800'},
  pill:{borderRadius:999,padding:8},
  box:{width:300,height:120,flex:1,opacity:0.5,aspectRatio:1.5},
  pct:{width:'50%',maxHeight:756},
};

console.log('\nטלפון (לא TV) — חייב להיות זהה לחלוטין, אפס עלות');
let ph=load(false,400,800);
t('TV_SCALE=1', ph.TV_SCALE, 1);
t('מחזיר את אותו אובייקט', ph.tvStyles(SHEET)===SHEET, true);
t('overscan=0', [ph.OVERSCAN_X,ph.OVERSCAN_Y], [0,0]);

console.log('\nטלוויזיה תקינה 960dp — גם כאן כלום לא משתנה');
let ok=load(true,960,540);
t('TV_SCALE=1', ok.TV_SCALE, 1);
t('אותו אובייקט', ok.tvStyles(SHEET)===SHEET, true);

console.log('\nקופסה שמדווחת 1920dp — כאן מתקנים');
let tv=load(true,1920,1080);
t('TV_SCALE=2', tv.TV_SCALE, 2);
const s=tv.tvStyles(SHEET);
t('fontSize הוכפל', s.title.fontSize, 28);
t('lineHeight הוכפל', s.title.lineHeight, 40);
t('paddingHorizontal הוכפל', s.title.paddingHorizontal, 32);
t('borderRadius הוכפל', s.title.borderRadius, 24);
t('צבע לא נגע', s.title.color, '#fff');
t('fontWeight לא נגע', s.title.fontWeight, '800');
t('גלולה (999) לא הוכפלה', s.pill.borderRadius, 999);
t('padding בגלולה כן', s.pill.padding, 16);
t('width לא הוכפל (עלול להיגזר מהמסך)', s.box.width, 300);
t('height לא הוכפל', s.box.height, 120);
t('flex/opacity/aspectRatio לא נגעו', [s.box.flex,s.box.opacity,s.box.aspectRatio], [1,0.5,1.5]);
t('אחוזים לא נגעו', s.pct.width, '50%');
t('maxHeight שנגזר ממסך לא הוכפל', s.pct.maxHeight, 756);
t('overscan לפי גוגל, מוכפל', [tv.OVERSCAN_X,tv.OVERSCAN_Y], [96,54]);
t('ts() מכפיל', tv.ts(10), 20);
t('לא משנה את המקור', SHEET.title.fontSize, 14);

console.log('\nמכשיר חריג');
t('מתחת ל-960 לא מקטין', load(true,540,360).TV_SCALE, 1);
t('4K שמדווח 3840 נחסם ב-2.5', load(true,3840,2160).TV_SCALE, 2.5);

console.log(`\n${fail?'✗':'✓'} ${pass} עברו, ${fail} נכשלו\n`);
process.exit(fail?1:0);
