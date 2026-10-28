"""End-to-end check of the real page: render through paint() in headless Edge and look for
the failure this tool is most likely to have - a picture that shows up outside the red ring.

The harness page is the built app plus a script that feeds paint() synthetic pictures whose
colours appear nowhere in the artwork (green body, magenta border).  Whatever leaks out of
the sign is then trivially findable in the screenshot.

Run:  python tools/browser_test.py [--keep]
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]

HARNESS = r"""
<script>
(function () {
  const app = window.__banApp;
  const cases = __CASES__;
  const W = app.BASE, H = app.H_BASE;

  function picture(w, h) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const x = c.getContext('2d');
    x.fillStyle = '#00c000';                       // nothing in the artwork is this green
    x.fillRect(0, 0, w, h);
    x.strokeStyle = '#ff00ff';                     // nor this magenta
    x.lineWidth = Math.max(4, Math.round(Math.min(w, h) * 0.05));
    x.strokeRect(x.lineWidth / 2, x.lineWidth / 2, w - x.lineWidth, h - x.lineWidth);
    return x.getImageData(0, 0, w, h);
  }

  async function run() {
    document.querySelectorAll('body > *').forEach((el) => { el.style.display = 'none'; });
    document.body.style.margin = '0';
    document.body.style.background = '#ffffff';
    app.src.kind = 'static';
    app.params.shadow = true; app.params.stroke = 1; app.params.rot = 0;
    for (const cs of cases) {
      app.src.w = cs.w; app.src.h = cs.h;
      app.params.dx = 0; app.params.dy = 0; app.params.slash = cs.slash;
      app.params.scale = app.fitScale();
      const c = await app.renderFull(cs.size, picture(cs.w, cs.h));
      c.style.display = 'block';
      document.body.appendChild(c);
    }
    document.title = 'done ' + cases.length;
  }

  const t0 = Date.now();
  (function wait() {
    const st = document.getElementById('status');
    if (st && st.textContent.indexOf('\u51c6\u5907\u5c31\u7eea') >= 0) { run(); return; }
    if (Date.now() - t0 > 20000) { document.title = 'timeout'; return; }
    setTimeout(wait, 100);
  })();
})();
</script>
"""

# w, h, keep the slash?, output size
CASES = [(400, 400, True, 816), (300, 500, True, 816), (500, 300, True, 816),
         (1000, 200, True, 816), (400, 400, False, 816),
         (400, 400, True, 408), (300, 400, True, 1632)]


def find_browser():
    for path in EDGE:
        if os.path.exists(path):
            return path
    return None


def main():
    keep = "--keep" in sys.argv
    browser = find_browser()
    if not browser:
        print("no Edge/Chrome found - browser test SKIPPED")
        return 0

    geo = json.load(open(os.path.join(ROOT, "tools", "geometry.json"), encoding="utf-8"))
    html = open(os.path.join(ROOT, "ban-sticker.html"), encoding="utf-8").read()
    html = html.replace("</body>", HARNESS.replace(
        "__CASES__", json.dumps([dict(w=w, h=h, slash=s, size=z) for w, h, s, z in CASES])) + "</body>")
    panels = [(w, h, s, z, round(z * geo["h"] / geo["w"])) for w, h, s, z in CASES]
    shot_h = sum(p[4] for p in panels)
    work = os.path.join(ROOT, "tools", "_browsertest")
    os.makedirs(work, exist_ok=True)
    page = os.path.join(work, "harness.html")
    shot = os.path.join(work, "shot.png")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(html)

    cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", "--allow-file-access-from-files",
           "--virtual-time-budget=25000",
           "--window-size=%d,%d" % (max(p[3] for p in panels), shot_h),
           "--screenshot=" + shot, "file:///" + page.replace("\\", "/")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not os.path.exists(shot):
        print("browser produced no screenshot (exit %s)" % proc.returncode)
        print((proc.stderr or "")[-2000:])
        return 1

    img = np.asarray(Image.open(shot).convert("RGB")).astype(np.int16)
    if img.shape[0] < shot_h:
        print("screenshot is %dx%d, expected at least %d rows - the page did not render all "
              "panels" % (img.shape[1], img.shape[0], shot_h))
        return 1

    failures = 0

    def check(label, ok, extra=""):
        nonlocal failures
        print(("  ok   " if ok else "  FAIL ") + label + (("  " + extra) if extra else ""))
        if not ok:
            failures += 1

    y0 = 0
    for (w, h, want_slash, size, ph) in panels:
        k = size / float(geo["w"])
        p = img[y0:y0 + ph, 0:size]
        y0 += ph
        cx, cy = geo["cx"] * k, geo["cy"] * k
        outer, inner = geo["ring_out_max"] * k, geo["ring_in_min"] * k
        yy, xx = np.mgrid[0:ph, 0:size]
        dist = np.hypot(xx - cx, yy - cy)

        r, g, b = p[:, :, 0], p[:, :, 1], p[:, :, 2]
        green = (g > 110) & (g - r > 60) & (g - b > 60)
        magenta = (r > 140) & (b > 140) & (g < 120)
        outside = dist > outer + 1.5 * k
        leak = int((green | magenta)[outside].sum())
        leaks_at = dist[green | magenta]
        far = float(leaks_at.max()) if leaks_at.size else 0.0
        tag = "%4dx%-4d @%-4d" % (w, h, size) + ("" if want_slash else " no-slash")
        check("%s nothing of the picture outside the ring" % tag, leak <= 40 * k * k,
              "leaked px=%d (worst r=%.1f, ring ends at %.1f)" % (leak, far, outer))

        greyish = (np.abs(r - g) < 45) & (np.abs(g - b) < 45) & (r > 130)
        hole = dist < inner - 2 * k
        white = int((greyish & hole).sum())
        check("%s picture fills the ring (no white gap)" % tag,
              white <= 0.004 * int(hole.sum()), "grey px=%d of %d" % (white, int(hole.sum())))

        # the ring is hand-drawn: its radius wobbles by a few px, so look for red somewhere
        # inside the band in every direction rather than at one exact radius
        ring = (r > 120) & (r - g > 60) & (r - b > 45)
        band = (dist > inner - 6 * k) & (dist < outer + 2 * k)
        ang = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 360.0) % 360.0
        buckets = [int((ring & band & (ang >= j * 15) & (ang < (j + 1) * 15)).sum())
                   for j in range(24)]
        check("%s ring goes all the way round" % tag, min(buckets) >= 12 * k * k,
              "thinnest sector has %d red px" % min(buckets))

        # "keep the slash" off must remove the slash and touch nothing else
        inner_red = int((ring & (dist < inner - 6 * k)).sum())
        check("%s slash %s" % (tag, "present" if want_slash else "removed"),
              inner_red > 500 * k * k if want_slash else inner_red == 0,
              "%d red px inside the ring" % inner_red)

    print("\n%s" % ("browser test FAILED" if failures else
                    "browser test passed (%d panels: aspect ratios, slash off, preview + full "
                    "size)" % len(panels)))
    print("screenshot: %s" % shot)
    if not keep:
        os.remove(page)                 # 540 KB of inlined assets, easy to regenerate
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
