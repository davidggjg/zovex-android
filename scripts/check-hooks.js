#!/usr/bin/env node
/**
 * check-hooks — הוק אחרי ‎return‎ מוקדם הוא מסך שחור.
 *
 * הבאג שבגללו זה נכתב: ‎gridItems‎ היה חישוב רגיל אחרי ‎if (loading)
 * return‎, וזה חוקי לגמרי. הפיכתו ל-‎useMemo‎ שינתה את זה — ההוק רץ רק
 * כשהטעינה נגמרה, כלומר מספר ההוקים שונה בין רינדור לרינדור, ו-React
 * זרק "Rendered more hooks than during the previous render".
 *
 * בבנייה זה עבר בלי אזהרה אחת: metro מקמפל, לא מריץ. האפליקציה הותקנה,
 * נתקעה על מסך שחור לפני שהפתיח בכלל רץ, והדרך היחידה לגלות הייתה
 * להתקין אותה על טלוויזיה.
 *
 * לכן הבדיקה רצה **לפני** הבנייה: היא סורקת כל רכיב, מוצאת את היציאה
 * המוקדמת הראשונה, ונכשלת על כל קריאת הוק אחריה.
 *
 *     node scripts/check-hooks.js src
 */
// סורק כל רכיב ובודק: האם יש קריאת הוק **אחרי** return מוקדם.
// זה בדיוק הבאג שהפיל את האפליקציה למסך שחור — useMemo שהוצב אחרי
// `if (loading) return`, כלומר מספר ההוקים משתנה בין רינדור לרינדור.
const parser = require('@babel/parser');
const fs = require('fs');
const path = require('path');

const HOOK = /^use[A-Z]/;
let problems = [];
let parseFailed = false;

function walkFn(node, file, lines) {
  // גוף הפונקציה ברמה העליונה בלבד — הוקים בתוך callback אינם הוקים
  const body = node.body && node.body.type === 'BlockStatement' ? node.body.body : [];
  let returnedAt = null;
  for (const st of body) {
    if (st.type === 'IfStatement' && hasReturn(st)) {
      if (returnedAt === null) returnedAt = st.loc.start.line;
      continue;
    }
    if (st.type === 'ReturnStatement' && returnedAt === null) {
      // ה-return האחרון של הרכיב — לא מעניין
      continue;
    }
    if (returnedAt !== null) {
      const hooks = findHooks(st);
      for (const h of hooks)
        problems.push(`${file}:${h.line}  ${h.name} אחרי return מוקדם בשורה ${returnedAt}`);
    }
  }
}

function hasReturn(node) {
  let found = false;
  (function scan(n) {
    if (!n || typeof n !== 'object' || found) return;
    if (n.type === 'ReturnStatement') { found = true; return; }
    if (n.type === 'FunctionDeclaration' || n.type === 'FunctionExpression'
        || n.type === 'ArrowFunctionExpression') return;   // לא של התנאי
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach(scan);
      else if (v && typeof v.type === 'string') scan(v);
    }
  })(node);
  return found;
}

function findHooks(node) {
  const out = [];
  (function scan(n, depth) {
    if (!n || typeof n !== 'object') return;
    if (depth > 0 && (n.type === 'FunctionDeclaration' || n.type === 'FunctionExpression'
        || n.type === 'ArrowFunctionExpression')) return;
    if (n.type === 'CallExpression' && n.callee && n.callee.type === 'Identifier'
        && HOOK.test(n.callee.name))
      out.push({name: n.callee.name, line: n.loc.start.line});
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach(x => scan(x, depth + 1));
      else if (v && typeof v.type === 'string') scan(v, depth + 1);
    }
  })(node, 0);
  return out;
}

function files(dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap(e => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return files(p);
    return /\.(js|jsx)$/.test(e.name) ? [p] : [];
  });
}

const root = process.argv[2];
for (const f of files(root)) {
  const src = fs.readFileSync(f, 'utf8');
  let ast;
  try {
    ast = parser.parse(src, {sourceType: 'module', plugins: ['jsx', 'flow',
      'classProperties', 'optionalChaining', 'nullishCoalescingOperator']});
  } catch (e) {
    console.log(`  ✗ ${f}: ${e.message}`);
    parseFailed = true;
    continue;
  }
  (function scan(n) {
    if (!n || typeof n !== 'object') return;
    if ((n.type === 'FunctionDeclaration' || n.type === 'FunctionExpression'
         || n.type === 'ArrowFunctionExpression'))
      walkFn(n, path.relative(root, f), src.split('\n'));
    for (const k of Object.keys(n)) {
      const v = n[k];
      if (Array.isArray(v)) v.forEach(scan);
      else if (v && typeof v.type === 'string') scan(v);
    }
  })(ast);
}

if (parseFailed) {
  console.log('✗ קבצים שלא נפרסו — הבדיקה לא רצה עליהם, וזה כישלון בפני עצמו.');
  process.exit(1);
}

if (problems.length) {
  console.log('✗ הוקים אחרי return מוקדם:');
  problems.forEach(p => console.log('   ' + p));
  process.exit(1);
}
console.log('✓ אין הוק אחרי return מוקדם באף רכיב');
