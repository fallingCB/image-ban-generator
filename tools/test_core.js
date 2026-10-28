/**
 * Node-side checks for the pure logic embedded in src/app.template.html:
 *   - median-cut palette quality
 *   - GIF89a encoder output parsed by a strict reader implementing the verified rules
 *     (the first code after CLEAR uses minCodeSize+1; the width grows once the decoder's
 *     table reaches 2^width).  Deep pixel-level validation lives in verify3.py, which
 *     cross-checks against Pillow.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'src', 'app.template.html'), 'utf8');
const start = html.indexOf('/* ==== CORE:BEGIN ====')
const end = html.indexOf('/* ==== CORE:END ==== */');
if (start < 0 || end < 0) throw new Error('CORE markers not found');
const core = html.slice(start, end);

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(core + '\n;this.medianCutPalette=medianCutPalette;this.encodeGIF=encodeGIF;', sandbox);
const { medianCutPalette, encodeGIF } = sandbox;

let failures = 0;
const check = (label, cond, extra = '') => {
  console.log((cond ? '  ok   ' : '  FAIL ') + label + (extra ? '  ' + extra : ''));
  if (!cond) failures++;
};

/* ---------- strict GIF reader ---------- */
function readGif(bytes) {
  let p = 0;
  const u8 = () => bytes[p++];
  const u16 = () => { const v = bytes[p] | (bytes[p + 1] << 8); p += 2; return v; };
  const prefix = String.fromCharCode(...bytes.slice(0, 6));
  if (prefix !== 'GIF89a') throw new Error('bad signature ' + prefix);
  p = 6;
  const width = u16(), height = u16();
  const packed = u8();
  const gctSize = (packed & 0x80) ? (1 << ((packed & 7) + 1)) : 0;
  u8(); u8();
  const gct = [];
  for (let i = 0; i < gctSize; i++) gct.push([u8(), u8(), u8()]);
  const frames = [];
  let pending = { delay: 0, transparent: false, tIndex: 0 };
  for (;;) {
    const marker = u8();
    if (marker === 0x3b) break;
    if (marker === 0x21) {
      const label = u8();
      if (label === 0xf9) {
        const size = u8();
        if (size !== 4) throw new Error('bad GCE size ' + size);
        const flags = u8();
        pending = {
          disposal: (flags >> 2) & 7,
          transparent: !!(flags & 1),
          delay: u16(),
          tIndex: u8(),
        };
        if (u8() !== 0) throw new Error('GCE not terminated');
      } else {
        let n = u8();
        while (n) { p += n; n = u8(); }
      }
      continue;
    }
    if (marker !== 0x2c) throw new Error('unexpected marker 0x' + marker.toString(16));
    const left = u16(), top = u16(), w = u16(), h = u16();
    const ipacked = u8();
    if (ipacked & 0x80) throw new Error('unexpected local colour table');
    const minCode = u8();
    const data = [];
    for (;;) { const n = u8(); if (!n) break; for (let i = 0; i < n; i++) data.push(u8()); }
    frames.push({ left, top, w, h, minCode, payload: data, ...pending });
  }
  return { width, height, gct, frames };
}

function decodeFrame(frame) {
  const { minCode, payload, w, h } = frame;
  const clear = 1 << minCode, eoi = clear + 1;
  let cur = minCode + 1;
  let table = [];
  for (let i = 0; i < clear; i++) table.push([i]);
  table.push(null, null);
  let bp = 0, prev = null;
  const out = [];
  while (out.length < w * h) {
    let c = 0;
    for (let i = 0; i < cur; i++) {
      const bi = bp >> 3;
      if (bi >= payload.length) throw new Error('truncated stream');
      c |= ((payload[bi] >> (bp & 7)) & 1) << i;
      bp++;
    }
    if (c === clear) {
      table = [];
      for (let i = 0; i < clear; i++) table.push([i]);
      table.push(null, null);
      cur = minCode + 1;
      prev = null;
      continue;
    }
    if (c === eoi) throw new Error('early EOI at ' + out.length + '/' + (w * h));
    let entry;
    if (c < table.length && table[c]) entry = table[c];
    else if (c === table.length && prev) entry = prev.concat([prev[0]]);
    else throw new Error('invalid code ' + c + ' (table ' + table.length + ', width ' + cur + ')');
    out.push(...entry);
    if (prev) {
      table.push(prev.concat([entry[0]]));
      if (table.length === (1 << cur) && cur < 12) cur++;
    }
    prev = entry;
    if (out.length > w * h) throw new Error('decoded too many pixels');
  }
  return out;
}

function roundTrip(name, w, h, frames, palette, expectedTableBits) {
  const gif = encodeGIF({ width: w, height: h, frames, palette });
  const dec = readGif(gif);
  check(name + ': dimensions', dec.width === w && dec.height === h, `${dec.width}x${dec.height}`);
  check(name + ': frame count', dec.frames.length === frames.length);
  const tableEntries = dec.gct.length;
  check(name + ': colour table is a valid power of two',
    tableEntries >= 2 && (tableEntries & (tableEntries - 1)) === 0 && tableEntries <= 256,
    String(tableEntries));
  if (expectedTableBits) {
    // A transparent frame can push the palette up to a full 256-entry table.
    check(name + ': colour table covers palette and transparent slot',
      tableEntries >= (1 << expectedTableBits), `${tableEntries} entries`);
  }
  dec.frames.forEach((f, i) => {
    const got = decodeFrame(f);
    const want = frames[i].indices;
    check(name + `: frame ${i} indices exact`,
      got.length === want.length && got.every((v, j) => v === want[j]),
      `${got.length} px`);
    const wantDelay = Math.max(1, Math.round(frames[i].delayMs / 10));
    check(name + `: frame ${i} delay`, f.delay === wantDelay, `${f.delay} vs ${wantDelay}`);
    if (frames[i].transparent) {
      check(name + `: frame ${i} transparency flag`, f.transparent === true,
        'index ' + f.tIndex);
      check(name + `: frame ${i} transparent index inside table`,
        f.tIndex < tableEntries, `${f.tIndex} < ${tableEntries}`);
    }
  });
}

/* ---------- 1. two frames of a repeating pattern ---------- */
console.log('test: two-frame pattern');
{
  const palette = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]];
  const w = 17, h = 9;
  const mk = (seed) => {
    const idx = new Uint8Array(w * h);
    for (let i = 0; i < idx.length; i++) idx[i] = (i * seed) % 4;
    return { indices: idx, delayMs: 80, transparent: false };
  };
  roundTrip('pattern', w, h, [mk(1), mk(3)], palette);
}

/* ---------- 2. dictionary growth: forces every code-width bump ---------- */
console.log('test: dictionary growth (width bumps 9->12)');
{
  const palette = [];
  for (let i = 0; i < 256; i++) palette.push([i, (i * 7) % 256, (i * 13) % 256]);
  const w = 400, h = 100;
  const idx = new Uint8Array(w * h);
  let seed = 99;
  for (let i = 0; i < idx.length; i++) {
    seed = (seed * 48271) % 2147483647;          // stays exact in doubles
    idx[i] = seed % 256;
  }
  roundTrip('dictionary', w, h, [{ indices: idx, delayMs: 40, transparent: false }], palette, 8);
}

/* ---------- 3. transparency with a spare slot ---------- */
console.log('test: transparency');
{
  const palette = [[0, 0, 0], [255, 255, 255], [255, 0, 0]];
  const w = 30, h = 30;
  const frames = [];
  for (let t = 0; t < 3; t++) {
    const idx = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const inside = Math.hypot(x - 15, y - 15) < 8 + t;
      idx[y * w + x] = inside ? (t === 1 ? 2 : 1) : 255;
    }
    frames.push({ indices: idx, delayMs: 60 + t * 20, transparent: true });
  }
  roundTrip('alpha', w, h, frames, palette, 2);
}

/* ---------- 4. median-cut palette quality ---------- */
console.log('test: median-cut palette');
{
  const N = 40000;
  const samples = new Uint8Array(N * 3);
  let seed = 7;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  for (let i = 0; i < N; i++) {
    const t = rnd();
    let r, g, b;
    if (t < 0.33) { r = 200 + rnd() * 40; g = 30 + rnd() * 30; b = 40 + rnd() * 30; }
    else if (t < 0.66) { r = 20 + rnd() * 30; g = 140 + rnd() * 40; b = 200 + rnd() * 40; }
    else { r = rnd() * 255; g = rnd() * 255; b = rnd() * 255; }
    samples[i * 3] = r | 0; samples[i * 3 + 1] = g | 0; samples[i * 3 + 2] = b | 0;
  }
  const t0 = Date.now();
  const pal = medianCutPalette(samples, 200);
  const ms = Date.now() - t0;
  check('palette size <= requested', pal.length > 0 && pal.length <= 200, `${pal.length} colours in ${ms} ms`);
  check('palette entries are valid RGB',
    pal.every((c) => c.length === 3 && c.every((v) => Number.isInteger(v) && v >= 0 && v <= 255)));
  let se = 0;
  for (let i = 0; i < N; i++) {
    const r = samples[i * 3], g = samples[i * 3 + 1], b = samples[i * 3 + 2];
    let bd = Infinity;
    for (const c of pal) {
      const d = (r - c[0]) ** 2 + (g - c[1]) ** 2 + (b - c[2]) ** 2;
      if (d < bd) bd = d;
    }
    se += bd;
  }
  const rmse = Math.sqrt(se / N);
  check('quantisation RMSE is reasonable (< 18)', rmse < 18, 'rmse=' + rmse.toFixed(2));
  check('deterministic across calls',
    JSON.stringify(medianCutPalette(samples.slice(), 200)) === JSON.stringify(pal));
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed');
process.exit(failures ? 1 : 0);
