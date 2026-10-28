"""End-to-end GIF check: drive the REAL page in headless Edge the way a user does.

The page is loaded, a genuine animated GIF is pushed through the file input (the same
code path drag & drop uses), the download button is clicked and the exported blob is
read back out of the DOM and validated with Pillow.

Run:  python tools/gif_e2e.py [--keep] [--frames N] [--size N]
"""
import base64
import io
import json
import os
import re
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]

HARNESS = r"""
<script>
(function () {
  const B64 = "__GIF_B64__";
  // The trace and the result live in the DOM from the very first line, so a dump that
  // happens too early still says how far the page got instead of coming back empty.
  // The app's three inlined base64 assets are inside <script> elements; it has already
  // run, so dropping them keeps the dump small enough to read.
  document.querySelectorAll('script').forEach((s) => s.remove());
  const out = [];
  const logEl = document.createElement('pre');
  logEl.id = 'LOG';
  const dataEl = document.createElement('pre');
  dataEl.id = 'E2E';
  document.documentElement.appendChild(logEl);
  document.documentElement.appendChild(dataEl);
  const log = (m) => {
    out.push(m);
    document.title = 'step ' + out.length;
    logEl.textContent = JSON.stringify(out);
  };
  const status = () => (document.getElementById('status') || {}).textContent || '';

  const bytes = (b64) => {
    const bin = atob(b64), u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u;
  };
  // Waiting by polling burns the browser's virtual clock faster than the page can make
  // progress, so a slow decode looks like a hang.  Watch the status element instead.
  //
  // The heartbeat matters: while a frame is being decoded the page has nothing scheduled,
  // and the browser's virtual clock then leaps straight to the next pending timer - a long
  // timeout would fire immediately and the run would look stuck.  A short repeating timer
  // forces the clock to advance in small steps instead, so a long decode still gets to run.
  const hb = setInterval(() => {}, 50);
  const statusEl = () => document.getElementById('status');
  let settled = false;               // set once the run is over, to silence stray timeouts
  const watchStatus = (re, ms, what) => new Promise((resolve) => {
    const el = statusEl();
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      obs.disconnect();
      clearTimeout(timer);
      if (!ok && !settled) log('TIMEOUT waiting for ' + what);
      resolve(ok);
    };
    const check = () => { if (re.test(el.textContent || '')) finish(true); };
    const obs = new MutationObserver(check);
    obs.observe(el, { childList: true, characterData: true, subtree: true });
    const timer = setTimeout(() => finish(false), ms);
    check();
  });

  let blob = null, blobReady;
  const blobPromise = new Promise((res) => { blobReady = res; });
  HTMLAnchorElement.prototype.click = function () {
    if (this.download && /\.gif$/i.test(this.download)) {
      const url = this.href;
      fetch(url).then((r) => r.blob()).then((b) => { blob = b; log('captured ' + b.size + ' bytes'); blobReady(b); })
        .catch((e) => log('capture failed: ' + e));
      return;
    }
    log('unexpected download click: ' + this.download);
  };

  // Count how often the page tries to open the file picker, without opening one.
  let pickerOpens = 0;
  const realInputClick = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type === 'file') { pickerOpens++; return; }
    return realInputClick.apply(this, arguments);
  };

  // A cheap fingerprint of what the preview canvas is showing right now.
  const previewSig = () => {
    const c = document.getElementById('preview');
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let h = 0;
    for (let i = 0; i < d.length; i += 401) h = (h * 31 + d[i] + d[i + 1] * 7) | 0;
    return h;
  };

  // Drive a real pan through the preview: pointerdown, move, up, then the click a browser
  // would synthesise at the end of the gesture.
  function panBy(dx, dy) {
    const p = document.getElementById('preview');
    const r = p.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const ev = (type, cx, cy) => new PointerEvent(type, {
      bubbles: true, cancelable: true, clientX: cx, clientY: cy,
      pointerId: 1, pointerType: 'mouse', isPrimary: true, buttons: type === 'pointerup' ? 0 : 1,
    });
    p.dispatchEvent(ev('pointerdown', x, y));
    p.dispatchEvent(ev('pointermove', x + dx, y + dy));
    p.dispatchEvent(ev('pointerup', x + dx, y + dy));
    p.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x + dx, clientY: y + dy }));
  }

  (async function () {
    try {
      if (!await watchStatus(/\u51c6\u5907\u5c31\u7eea/, 60000, 'ready')) return;
      log('ready: ' + status());

      const dt = new DataTransfer();
      dt.items.add(new File([bytes(B64)], 'anim.gif', { type: 'image/gif' }));
      const input = document.getElementById('file');
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));

      const loaded = await watchStatus(/\u52a8\u56fe\u5df2\u5c31\u7eea|\u5355\u5e27|\u8bfb\u53d6\u5931\u8d25/, __LOADMS__, 'load');
      log('loaded: ' + status());
      log('mode: ' + document.getElementById('modePill').textContent);
      log('info: ' + document.getElementById('info').textContent);
      if (!loaded || /\u5355\u5e27|\u8bfb\u53d6\u5931\u8d25/.test(status())) return;

      const app = window.__banApp;

      /* 1. the preview must play the animation, not just show frame 0 */
      const seen = new Set([previewSig()]);
      for (let i = 0; i < 20 && seen.size < 3; i++) {
        await new Promise((r) => setTimeout(r, 80));
        seen.add(previewSig());
      }
      log('preview animation: running=' + app.animState().running +
          ' distinct preview frames=' + seen.size);

      /* 2. a pan must not leave the picture stuck at the old +-200 limit ... */
      app.params.dx = 0; app.params.dy = 0;
      const before = pickerOpens;
      panBy(600, 420);
      log('after pan: dx=' + Math.round(app.params.dx) + ' dy=' + Math.round(app.params.dy) +
          ' picker opens=' + (pickerOpens - before));

      /* 3. ... but a plain click on the picture is still how you pick another file */
      const before2 = pickerOpens;
      const pv = document.getElementById('preview');
      pv.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 2, clientX: 5, clientY: 5 }));
      pv.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 2, clientX: 5, clientY: 5 }));
      pv.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 5, clientY: 5 }));
      log('after plain click: picker opens=' + (pickerOpens - before2));

      // put the picture back before exporting, so the frames still line up with the sign
      app.params.dx = 0; app.params.dy = 0;
      document.getElementById('fit').click();

      for (const [id, v] of [['maxFrames', '__MAXFRAMES__'], ['colors', '128'], ['outSize', '__SIZE__']]) {
        const el = document.getElementById(id);
        el.value = v;
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      // the click handler is async and swallows its own errors into #status
      let peak = 0;
      const mem = setInterval(() => {
        if (performance.memory) peak = Math.max(peak, performance.memory.usedJSHeapSize);
      }, 200);
      const t0 = Date.now();
      const failed = watchStatus(/\u5bfc\u51fa\u5931\u8d25/, __EXPORTMS__, 'export error');
      document.getElementById('download').click();
      const outcome = await Promise.race([
        blobPromise.then(() => 'ok'),
        failed.then((matched) => (matched ? 'failed' : 'timeout')),
      ]);
      const ms = Date.now() - t0;
      clearInterval(mem);
      log('export ' + outcome + ' after ' + ms + ' ms, peak JS heap ' +
          (peak / 1048576).toFixed(0) + ' MB');
      log('final status: ' + status());
      if (outcome !== 'ok' || !blob) return;

      dataEl.textContent = await new Promise((res) => {
        const fr = new FileReader();
        fr.onload = () => res(String(fr.result).split(',')[1]);
        fr.readAsDataURL(blob);
      });
      log('done');
    } catch (e) {
      log('EXCEPTION ' + (e && e.stack ? e.stack : e));
    } finally {
      settled = true;
      try { window.__banApp.stopAnim(); } catch (e) { /* nothing to stop */ }
      clearInterval(hb);          // let the virtual clock drain so the dump can happen
    }
  })();
})();
</script>
"""


def make_source_gif(path, frames=12, size=300, simple=True):
    """Solid alternating colours by default - a frame that silently repeats its predecessor is
    then obvious and the change stays inside the picture.  --heavy switches to a noisy moving
    pattern, which is what the encoder actually meets in the wild."""
    imgs = []
    if simple:
        for t in range(frames):
            imgs.append(Image.new("RGB", (size, size), (0, 200, 0) if t % 2 == 0 else (255, 220, 0)))
    else:
        import numpy as np
        rng = np.random.default_rng(7)
        noise = rng.integers(0, 70, (size, size, 3))
        yy, xx = np.mgrid[0:size, 0:size]
        for t in range(frames):
            a = 2 * np.pi * t / frames
            cx = size / 2 + np.cos(a) * size * 0.25
            cy = size / 2 + np.sin(a) * size * 0.25
            r = np.clip(255 - 255 * np.hypot(xx - cx, yy - cy) / (size * 0.6), 0, 255)
            g = (xx * 255 // size)
            b = (yy * 255 // size)
            arr = np.clip(np.stack([r, g, b], -1) * (0.75 + 0.25 * np.cos(a + xx / 23.0))[..., None]
                          + noise, 0, 255).astype("uint8")
            imgs.append(Image.fromarray(arr, "RGB"))
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=80, loop=0)


def main():
    keep = "--keep" in sys.argv
    frames = int(sys.argv[sys.argv.index("--frames") + 1]) if "--frames" in sys.argv else 12
    size = int(sys.argv[sys.argv.index("--size") + 1]) if "--size" in sys.argv else 816
    maxframes = int(sys.argv[sys.argv.index("--maxframes") + 1]) if "--maxframes" in sys.argv else 150

    browser = next((p for p in BROWSERS if os.path.exists(p)), None)
    if not browser:
        print("no Edge/Chrome found - GIF end-to-end test SKIPPED")
        return 0

    heavy = "--heavy" in sys.argv
    work = os.path.join(ROOT, "tools", "_gife2e")
    os.makedirs(work, exist_ok=True)
    srcgif = os.path.join(work, "source.gif")
    make_source_gif(srcgif, frames, simple=not heavy)
    b64 = base64.b64encode(open(srcgif, "rb").read()).decode()

    html = open(os.path.join(ROOT, "ban-sticker.html"), encoding="utf-8").read()
    # The harness waits on the page's own progress; these are only safety nets.  They scale
    # with the frame count because decoding and re-rendering both do.
    load_ms = 300000 + frames * 15000
    export_ms = 300000 + frames * 30000
    harness = (HARNESS.replace("__GIF_B64__", b64)
                      .replace("__MAXFRAMES__", str(maxframes))
                      .replace("__SIZE__", str(size))
                      .replace("__LOADMS__", str(load_ms))
                      .replace("__EXPORTMS__", str(export_ms)))
    html = html.replace("</body>", harness + "</body>")
    page = os.path.join(work, "harness.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(html)

    budget = load_ms + export_ms + 300000
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--allow-file-access-from-files", "--virtual-time-budget=%d" % budget,
           "--dump-dom", "file:///" + page.replace("\\", "/")]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800)
    dom = proc.stdout or ""

    log = []
    trace = re.search(r'<pre id="LOG">(.*?)</pre>', dom, re.S)
    if trace:
        try:
            log = json.loads(trace.group(1))
        except Exception:
            log = ["<unparsable trace>"]
    data = re.search(r'<pre id="E2E">([A-Za-z0-9+/=]+)</pre>', dom, re.S)
    print("--- page trace ---")
    for line in log:
        print("  " + line)
    if not log:
        title = re.search(r"<title>(.*?)</title>", dom, re.S)
        print("  (no trace; dump was %d bytes, title %r)" %
              (len(dom), title.group(1) if title else None))
        print((proc.stderr or "")[-1500:])

    if not data:
        print("\nGIF end-to-end FAILED: the page never produced a .gif blob")
        return 1
    raw = base64.b64decode(data.group(1))
    out = os.path.join(work, "exported.gif")
    open(out, "wb").write(raw)
    print("\nexported %d bytes -> %s" % (len(raw), out))

    failures = 0

    def check(label, ok, extra=""):
        nonlocal failures
        print(("  ok   " if ok else "  FAIL ") + label + (("  " + extra) if extra else ""))
        if not ok:
            failures += 1

    src_n = Image.open(srcgif).n_frames
    geo = json.load(open(os.path.join(ROOT, "tools", "geometry.json"), encoding="utf-8"))
    import numpy as np

    def logmatch(pattern):
        for line in log:
            m = re.search(pattern, line)
            if m:
                return m
        return None

    # the three behaviours that are not about the exported file
    anim = logmatch(r"distinct preview frames=(\d+)")
    check("the preview plays the animation", bool(anim) and int(anim.group(1)) >= 2,
          "distinct preview frames=%s (needs >= 2)" % (anim.group(1) if anim else "?"))
    pan = logmatch(r"after pan: dx=(-?\d+) dy=(-?\d+) picker opens=(\d+)")
    check("panning is not clamped to the old +-200 box",
          bool(pan) and max(abs(int(pan.group(1))), abs(int(pan.group(2)))) > 200,
          "dx=%s dy=%s" % (pan.group(1), pan.group(2)) if pan else "no pan recorded")
    check("finishing a pan does not open the file picker",
          bool(pan) and pan.group(3) == "0", "picker opens=%s" % (pan.group(3) if pan else "?"))
    click = logmatch(r"after plain click: picker opens=(\d+)")
    check("a plain click still opens the file picker",
          bool(click) and click.group(1) == "1", "picker opens=%s" % (click.group(1) if click else "?"))

    try:
        im = Image.open(out)
        n = im.n_frames
        # the page decimates with step = ceil(total / maxFrames) and keeps every step-th frame
        step = (src_n + maxframes - 1) // maxframes if src_n > maxframes else 1
        want = (src_n + step - 1) // step
        check("output is a valid GIF", True,
              "%d frames, %dx%d, %s" % (n, im.width, im.height, im.format))
        check("frame count matches the source", n == want,
              "got %d, want %d (source %d, step %d)" % (n, want, src_n, step))
        check("the exported GIF asks to loop forever", im.info.get("loop") == 0,
              "NETSCAPE2.0 loop=%r (0 means endless)" % (im.info.get("loop"),))

        k = im.width / float(geo["w"])
        yy, xx = np.mgrid[0:im.height, 0:im.width]
        inside = np.hypot(xx - geo["cx"] * k, yy - geo["cy"] * k) < geo["cover_r"] * k
        # only the picture area can change; the sign itself must stay put between frames
        import numpy as np
        frames = []
        for i in range(n):
            im.seek(i)
            frames.append(np.asarray(im.convert("RGB"), "int16"))
        first = frames[0]
        drift = [float(np.abs(f - first)[inside].mean()) for f in frames[1:]]
        neighbours = [float(np.abs(b - a)[inside].mean()) for a, b in zip(frames, frames[1:])]
        sign_diffs = [float(np.abs(f - first)[~inside].mean()) for f in frames[1:]]
        check("frames actually animate inside the sign", not drift or max(drift) > 10.0,
              "max drift from frame 0 = %.1f (neighbour delta %.1f..%.1f)" %
              (max(drift) if drift else 0.0,
               min(neighbours) if neighbours else 0.0, max(neighbours) if neighbours else 0.0))
        check("the sign is identical in every frame", not sign_diffs or max(sign_diffs) < 6.0,
              "max outside delta=%.2f" % (max(sign_diffs),) if sign_diffs else "")

        arr = first
        red = (arr[:, :, 0] > 120) & (arr[:, :, 0] - arr[:, :, 1] > 60) & (arr[:, :, 0] - arr[:, :, 2] > 45)
        check("the ban sign survived the GIF export", int(red.sum()) > 500, "%d red px" % int(red.sum()))
    except Exception as e:
        check("output GIF decodes with Pillow", False, repr(e))

    print("\n%s" % ("GIF end-to-end FAILED" if failures else "GIF end-to-end passed"))
    if not keep:
        for f in ("harness.html",):
            p = os.path.join(work, f)
            if os.path.exists(p):
                os.remove(p)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
