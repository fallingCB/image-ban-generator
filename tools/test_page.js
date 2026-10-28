/**
 * Runs the page's real script in Node and exercises the pure placement math plus the
 * geometry constants baked into the page.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const geo = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools', 'geometry.json'), 'utf8'));
// build_page.py substitutes the same JSON; do it here too so the source can be run directly
const html = fs.readFileSync(path.join(ROOT, 'src', 'app.template.html'), 'utf8')
  .replace('__GEO_JSON__', JSON.stringify(geo));
const built = fs.readFileSync(path.join(ROOT, 'ban-sticker.html'), 'utf8');
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (scripts.length !== 2) throw new Error('expected 2 inline scripts, got ' + scripts.length);
// The page has two inline scripts; a browser puts both in global scope, so concatenate.
const appScript = scripts[0] + '\n' + scripts[1];

function makeElement(tag) {
  const el = {
    tagName: tag, style: {}, dataset: {}, children: [], files: [], innerHTML: '', textContent: '',
    classList: { add() {}, remove() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {}, setAttribute() {}, removeAttribute() {},
    appendChild(c) { el.children.push(c); return c; }, remove() {}, click() {},
    setPointerCapture() {}, getContext: () => null,
  };
  el.firstElementChild = { style: {} };
  return el;
}

class StubCanvas {
  constructor() { this.width = 300; this.height = 150; }
  getContext() { return null; }
  toDataURL() { return 'data:image/png;base64,'; }
}

const document = {
  getElementById: () => makeElement('div'),
  createElement: (tag) => (tag === 'canvas' ? new StubCanvas() : makeElement(tag)),
  addEventListener() {}, body: makeElement('body'),
};
const window = { addEventListener() {} };

function FakeImage() {
  this.width = 1; this.height = 1; this.naturalWidth = 1; this.naturalHeight = 1;
  Object.defineProperty(this, 'src', {
    set(v) { this._src = v; if (this.onload) setTimeout(() => this.onload(), 0); },
    get() { return this._src; },
  });
}

const sandbox = {
  document, window, Image: FakeImage,
  ImageData: class { constructor(data, w, h) { this.data = data; this.width = w; this.height = h; } },
  requestAnimationFrame: (fn) => setTimeout(fn, 0), setTimeout, clearTimeout, console,
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  Blob: class {}, Uint8Array, Uint8ClampedArray, Int16Array, Math, JSON, Promise, Object, Array,
  Number, String, parseFloat, parseInt, isNaN, Error, Map, Set, Date,
};
sandbox.globalThis = sandbox;
const context = vm.createContext(sandbox);
vm.runInContext(appScript, context, { filename: 'ban-app.js' });

const app = sandbox.window.__banApp;
if (!app) throw new Error('window.__banApp missing: the page script did not initialise');

let failures = 0;
const check = (label, cond, extra = '') => {
  console.log((cond ? '  ok   ' : '  FAIL ') + label + (extra ? '  ' + extra : ''));
  if (!cond) failures++;
};

console.log('geometry baked into the page');
check('matches the measured geometry exactly', JSON.stringify(app.GEO) === JSON.stringify(geo),
  `(${app.GEO.cx}, ${app.GEO.cy}) ring ${app.GEO.ring_in}..${app.GEO.ring_out}`);
check('base canvas matches the artwork', app.BASE === geo.w && app.H_BASE === geo.h,
  `${app.BASE}x${app.H_BASE}`);
check('the picture is clipped inside the overlay it hides behind',
  app.GEO.clip_r > app.GEO.ring_out_max && app.GEO.clip_r < app.GEO.disc_r,
  `clip ${app.GEO.clip_r} < disc ${app.GEO.disc_r}`);
check('the auto-fit target stays under the ring\'s painted band',
  app.GEO.cover_r > app.GEO.ring_in_min && app.GEO.cover_r <= app.GEO.ring_in_max + 3,
  `cover ${app.GEO.cover_r} vs ring inner ${app.GEO.ring_in_min}..${app.GEO.ring_in_max}`);
check('assets were inlined as data URIs', /data:image\/png;base64,[A-Za-z0-9+/]{500,}/.test(built));
check('the slash mask is inlined too', (built.match(/data:image\/png;base64,/g) || []).length >= 3,
  `${(built.match(/data:image\/png;base64,/g) || []).length} png assets`);
check('thumbnail inlined too', /data:image\/jpeg;base64,/.test(built));
check('no placeholders left in the built page', !/__[A-Z_]{4,}__/.test(built));

console.log('placement math');
const place = app.computePlacement;
{
  // default fit: a large square photo scaled down so it exactly covers the ring
  const size = app.BASE;
  const fit = place(size, 800, 800, { scale: 1, dx: 0, dy: 0, rot: 0 });
  check('clip radius encloses the ring band', fit.clipRadius > app.GEO.ring_out * fit.k &&
    fit.clipRadius < app.GEO.disc_r * fit.k,
    `clip ${fit.clipRadius.toFixed(1)} vs ring ${(app.GEO.ring_out * fit.k).toFixed(1)}`);
  check('rotation is converted to radians',
    Math.abs(place(816, 10, 10, { scale: 1, dx: 0, dy: 0, rot: 180 }).rot - Math.PI) < 1e-9);
  check('image scale cannot go negative',
    place(816, 10, 10, { scale: -5, dx: 0, dy: 0, rot: 0 }).dw > 0);

  // offsets move the picture in output pixels, scaled by the output size
  const a = place(816, 400, 400, { scale: 1, dx: 20, dy: -30, rot: 0 });
  const b = place(408, 400, 400, { scale: 1, dx: 20, dy: -30, rot: 0 });
  check('offset scales with the output size',
    Math.abs((a.x - b.x * 2) + (a.dw - b.dw * 2) / 2) < 1e-6 && Math.abs(a.dw - b.dw * 2) < 1e-6,
    `centre ${(a.x + a.dw / 2).toFixed(1)} at 816 vs ${(b.x + b.dw / 2).toFixed(1)} at 408`);

  // the auto-fit has to make *every* aspect ratio cover the circle, which is where the
  // original build went wrong: a portrait was scaled by its long side and left a gap.
  app.src.kind = 'static';
  for (const [w, h] of [[400, 400], [300, 500], [500, 300], [1000, 200], [200, 1000], [64, 64]]) {
    app.src.w = w; app.src.h = h;
    app.params.scale = app.fitScale();
    const p = place(816, w, h, app.params);
    const gap = Math.min(p.dw, p.dh) - 2 * app.GEO.cover_r;
    check(`auto-fit covers the circle for ${w}x${h}`, p.coversCircle && gap >= -0.5,
      `drawn ${p.dw.toFixed(1)}x${p.dh.toFixed(1)}, needs ${(2 * app.GEO.cover_r).toFixed(1)}`);
  }
}

console.log('gif helpers exposed to the exporter');
check('encodeGIF exposed', typeof app.encodeGIF === 'function');
check('medianCutPalette exposed', typeof app.medianCutPalette === 'function');

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall page checks passed');
process.exit(failures ? 1 : 0);
