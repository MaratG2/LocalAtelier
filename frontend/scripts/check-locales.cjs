const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const ru = JSON.parse(fs.readFileSync(path.join(root, 'src/ru.json'), 'utf8'));
const brands = new Set(['Local Atelier','TRELLIS.2','VDN-H3','VDN-H3 · MiniMax H3','H3','1K','1.5K','2K']);
const missing = [];
for (const file of fs.readdirSync(path.join(root, 'src')).filter(f => f.endsWith('.tsx') && f !== 'i18n.tsx')) {
  const source = ts.createSourceFile(file, fs.readFileSync(path.join(root, 'src', file), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  function visit(node) {
    if (ts.isJsxText(node)) {
      const text = node.text.replace(/\s+/g, ' ').trim();
      if (/[a-zA-Z]/.test(text) && !brands.has(text)) missing.push(`${file}: unlocalized JSX text: ${text}`);
    }
    if (ts.isCallExpression(node) && node.expression.getText(source) === 't' && ts.isStringLiteral(node.arguments[0])) {
      const text = node.arguments[0].text;
      if (/[a-zA-Z]/.test(text) && !ru[text] && !brands.has(text)) missing.push(`${file}: missing Russian key: ${text}`);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
for (const [key, value] of Object.entries(ru)) {
  if (!value.trim()) missing.push(`Empty translation: ${key}`);
  const slots = text => (text.match(/\{\d+\}/g) || []).sort().join();
  if (slots(key) !== slots(value)) missing.push(`Interpolation mismatch: ${key}`);
}
// Exercise locale selection, interpolation and Russian plural forms without a DOM.
const storage = new Map();
const sandbox = {exports: {}, document: {documentElement:{}}, navigator:{language:'en-US'}, localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}, Intl,
  require: name => name === './ru.json' ? ru : name === 'react' ? {useSyncExternalStore:()=>{}} : {}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root, 'src/i18n.tsx'), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS, jsx:ts.JsxEmit.ReactJSX, esModuleInterop:true}}).outputText, sandbox);
const i18n = sandbox.exports;
i18n.setLanguage('ru');
for (const [actual, expected] of [[i18n.t('Images'),'Изображения'],[i18n.quantity(2,'seconds'),'2 секунды'],[i18n.quantity(5,'seconds'),'5 секунд'],[i18n.assetCount(21),'21 материал'],[i18n.t('Rendering · step 3 of 25'),'Генерация · шаг 3 из 25'],[i18n.projectName({id:'custom',name:'Images'}),'Images']]) {
  if (actual !== expected) missing.push(`Locale result: ${actual} !== ${expected}`);
}
i18n.setLanguage('en');
if (i18n.t('Images') !== 'Images') missing.push('English switch failed');
if (missing.length) {console.error(missing.join('\n'));process.exit(1);}
console.log(`Localization checked: ${Object.keys(ru).length} Russian entries, JSX coverage, interpolation and plural forms.`);
