/** Static check: every element id referenced by the page script exists in the markup. */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'ban-sticker.html'), 'utf8');

const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const refs = new Map();
for (const m of html.matchAll(/\$\('([^']+)'\)/g)) {
  refs.set(m[1], (refs.get(m[1]) || 0) + 1);
}
const missing = [...refs.keys()].filter((id) => !ids.has(id));
console.log('elements defined:', ids.size);
console.log('ids referenced by $():', refs.size);
console.log('missing:', missing.length ? missing.join(', ') : 'none');

/* every label/id pair used by the control binding list */
const bound = [...html.matchAll(/bind\('([^']+)'/g)].map((m) => m[1]);
const missingBound = bound.filter((id) => !ids.has(id));
console.log('controls bound:', bound.join(', '));
console.log('missing bound controls:', missingBound.length ? missingBound.join(', ') : 'none');

/* crude structural sanity */
const checks = [
  ['single file has no external requests', !/<(script|link|img)[^>]+(src|href)="(?!data:)/i.test(html)],
  ['stylesheet is inline', /<style>/.test(html)],
  ['no unreplaced placeholders', !/__[A-Z_]{4,}__/.test(html)],
  ['html closes properly', /<\/html>\s*$/.test(html)],
];
let bad = 0;
for (const [label, ok] of checks) {
  console.log((ok ? '  ok   ' : '  FAIL ') + label);
  if (!ok) bad++;
}
process.exit(missing.length || missingBound.length || bad ? 1 : 0);
