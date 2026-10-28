/** Encode several edge-case GIFs with the page's encoder so Pillow can validate them. */
const fs = require('fs'); const path = require('path'); const vm = require('vm');
const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'src/app.template.html'), 'utf8');
const core = html.slice(html.indexOf('/* ==== CORE:BEGIN ===='), html.indexOf('/* ==== CORE:END ==== */'));
const sb = {}; vm.createContext(sb);
vm.runInContext(core + ';this.encodeGIF=encodeGIF;this.medianCutPalette=medianCutPalette;', sb);
const { encodeGIF, medianCutPalette } = sb;

const OUT = path.join(ROOT, 'tools', 'gifs');
fs.mkdirSync(OUT, { recursive: true });
const meta = {};

function save(name, gif, frames, palette) {
  fs.writeFileSync(path.join(OUT, name + '.gif'), gif);
  meta[name] = {
    frames: frames.map((f) => ({ indices: Array.from(f.indices), delayMs: f.delayMs, transparent: !!f.transparent })),
    palette: palette.map((c) => Array.from(c)),
    width: gif.width, height: gif.height,
  };
  console.log('%s: %d bytes, %d frames', name, gif.length, frames.length);
}

/* 1. tiny pattern, 2 frames, 4 colours */
{
  const palette = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]];
  const w = 17, h = 9;
  const mk = (seed) => {
    const idx = new Uint8Array(w * h);
    for (let i = 0; i < idx.length; i++) idx[i] = (i * seed) % 4;
    return { indices: idx, delayMs: 80, transparent: false };
  };
  const f = [mk(1), mk(3)];
  const gif = encodeGIF({ width: w, height: h, frames: f, palette });
  gif.width = w; gif.height = h;
  save('small', gif, f, palette);
}

/* 2. worst-case noise 128x128, 256 colours (forces dictionary overflow) */
{
  const palette = [];
  for (let i = 0; i < 256; i++) palette.push([i, (i * 7) % 256, (i * 13) % 256]);
  const w = 128, h = 128;
  const idx = new Uint8Array(w * h);
  let seed = 12345;
  for (let i = 0; i < idx.length; i++) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    idx[i] = seed % 256;
  }
  const f = [{ indices: idx, delayMs: 40, transparent: false }];
  const gif = encodeGIF({ width: w, height: h, frames: f, palette });
  gif.width = w; gif.height = h;
  save('noise', gif, f, palette);
}

/* 3. 5 colours (non power of two) with dots */
{
  const palette = [[10, 20, 30], [200, 100, 50], [0, 200, 0], [255, 255, 0], [0, 0, 0]];
  const w = 33, h = 21;
  const idx = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) idx[y * w + x] = (x * y) % 5;
  const f = [{ indices: idx, delayMs: 130, transparent: false }];
  const gif = encodeGIF({ width: w, height: h, frames: f, palette });
  gif.width = w; gif.height = h;
  save('five', gif, f, palette);
}

/* 4. transparency + multiple frames of differing content */
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
  const gif = encodeGIF({ width: w, height: h, frames, palette });
  gif.width = w; gif.height = h;
  save('transparent', gif, frames, palette);
}

/* 5. median-cut round trip on a photo-ish gradient */
{
  const w = 160, h = 120, N = w * h;
  const samples = new Uint8Array(N * 3);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 3;
    samples[i] = Math.round(255 * x / (w - 1));
    samples[i + 1] = Math.round(255 * y / (h - 1));
    samples[i + 2] = Math.round(120 + 100 * Math.sin(x / 9) * Math.cos(y / 7));
  }
  const palette = medianCutPalette(samples, 128);
  const idx = new Uint8Array(N);
  for (let i = 0; i < N; i++) {
    const r = samples[i * 3], g = samples[i * 3 + 1], b = samples[i * 3 + 2];
    let bi = 0, bd = Infinity;
    for (let k = 0; k < palette.length; k++) {
      const c = palette[k];
      const d = (r - c[0]) ** 2 + (g - c[1]) ** 2 + (b - c[2]) ** 2;
      if (d < bd) { bd = d; bi = k; }
    }
    idx[i] = bi;
  }
  const frames = [{ indices: idx, delayMs: 100, transparent: false }];
  const gif = encodeGIF({ width: w, height: h, frames, palette });
  gif.width = w; gif.height = h;
  save('gradient', gif, frames, palette);
}

/* 6. a full 256-colour palette plus transparency: forces a 512-entry colour table */
{
  const palette = [];
  for (let i = 0; i < 256; i++) palette.push([(i * 5) % 256, i, (i * 3) % 256]);
  const w = h = 24;
  const frames = [];
  for (let t = 0; t < 2; t++) {
    const idx = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      idx[y * w + x] = ((x + y + t) % 6 === 0) ? 255 : ((x * 11 + y * 7 + t) % 256);
    }
    frames.push({ indices: idx, delayMs: 50, transparent: true });
  }
  const gif = encodeGIF({ width: w, height: h, frames, palette });
  gif.width = w; gif.height = h;
  save('alpha256', gif, frames, palette);
}
fs.writeFileSync(path.join(OUT, 'meta.json'), JSON.stringify(meta));
console.log('wrote', Object.keys(meta).length, 'gifs + meta.json');
