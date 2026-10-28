"""Build template.png + overlay.png from the source meme, plus tools/geometry.json.

In the finished sticker the user's picture is clipped to a circle, so inside that circle
the picture hides *everything* the source meme had there - including the red ring.  That
makes the overlay the only thing drawing the ring, and it means the ring has to be
measured exactly: any part of the picture that reaches past the painted red would show up
as a halo of the picture outside the prohibition sign (the bug this file now guards
against by construction).

Pipeline
  1. a red mask that also rejects the mascot's yellow/orange and skin tones,
  2. circle centre fit + the ring's inner/outer edge measured per angle (keeps the
     hand-drawn wobble),
  3. overlay.png
       - r >= ring_in(angle): the source's own pixels (board, ring's soft outer edge),
       - the ring band [ring_in, ring_out] repainted in the sign's red, aged with
         multi-scale ink-density noise, chips and grime, its outer edge nibbled by the
         same noise so it stops reading as a vector circle laid over the photograph,
       - a clean slash inside, cut off at the ring's inner edge, carrying the same ink,
     so the picture shows through the ring's inner hole and nothing past it,
  4. slashmask.png: just the slash, so the page can drop it for "only keep the ring",
  5. template.png: the same source with everything inside ring_in(angle) painted white
     (the yellow mascot erased, the wobble preserved).
"""
import io
import json
import math
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "template-source.jpg")
OUT = os.path.join(ROOT, "assets")
os.makedirs(OUT, exist_ok=True)

NB = 48                      # angular buckets for the ring profile
FEATHER = 1.0                # px of antialiasing on every edge we synthesise
RED_FALLBACK = (190, 32, 45)


def smooth_circular(values):
    n = len(values)
    return [(values[(i - 1) % n] + 2 * values[i] + values[(i + 1) % n]) / 4 for i in range(n)]


img = Image.open(SRC).convert("RGB")
W, H = img.size
a = np.asarray(img).astype(np.float32)
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]

# ---- red mask ------------------------------------------------------------------------
# The mascot is orange/yellow and skin is pink, and both satisfy "r > g > b".  What makes
# real red different is that its blue is close to its green, while yellow/skin have a lot
# less blue than green.  That single test keeps the mask clean without any blob hunting.
red = (r > 100) & (r - g > 35) & (b >= g - 15)
print("red mask: %d px" % int(red.sum()))

ys, xs = np.nonzero(red)
picked = np.hypot(xs - 333.67, ys - 259.78) > 70      # ignore the slash while fitting
x = xs[picked].astype(np.float64)
y = ys[picked].astype(np.float64)

# ---- circle centre: iterative algebraic fit on the ring band -------------------------
cx, cy, rad = 334.5, 259.5, 99.0
for _ in range(12):
    d = np.hypot(x - cx, y - cy)
    m = d > rad - 20
    A = np.column_stack([x[m], y[m], np.ones(int(m.sum()))])
    sol, *_ = np.linalg.lstsq(A, x[m] ** 2 + y[m] ** 2, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    rad = math.sqrt(sol[2] + cx * cx + cy * cy)
print("centre=(%.2f, %.2f) radius~%.2f" % (cx, cy, rad))

# ---- slash: direction, offset and width ----------------------------------------------
# Inside the ring the remaining red pixels are the slash (the warm smear the mascot's face
# picks up is deliberately not in the mask).  A prohibition slash always runs from upper
# left to lower right, so the angle is searched in that neighbourhood only.
sel = np.hypot(x - cx, y - cy) < (rad - 12)
xi, yi = x[sel], y[sel]
mean = np.array([xi.mean(), yi.mean()])
best = None
for deg in np.arange(35.0, 56.01, 0.25):
    th = math.radians(deg)
    dv = np.array([math.cos(th), math.sin(th)])
    pv = np.array([-dv[1], dv[0]])
    pr = np.vstack([xi - mean[0], yi - mean[1]]).T @ pv
    for wid in np.arange(8.0, 24.5, 0.5):
        m = np.abs(pr) <= wid / 2
        if m.sum() < 60:
            break
        tr = np.vstack([xi[m] - mean[0], yi[m] - mean[1]]).T @ dv
        span = float(np.percentile(tr, 99) - np.percentile(tr, 1))
        score = span - 0.4 * wid
        if best is None or score > best[0]:
            best = (score, deg, wid, span)
_, deg, _, span = best
th = math.radians(deg)
adir = np.array([math.cos(th), math.sin(th)])
aperp = np.array([-adir[1], adir[0]])
pr = (xi - cx) * aperp[0] + (yi - cy) * aperp[1]
slash_off = float(np.median(pr))                 # line offset from the sign's centre
near = np.abs(pr - slash_off) < 14.0
# the pixel core plus the ~1px of JPEG blending on each side is what the eye reads as the
# stroke, and it lands on the same weight as the ring (which is how the meme is drawn)
slash_w = float(np.percentile(pr[near], 97) - np.percentile(pr[near], 3)) + 2.0
print("slash: angle=%.1f deg dir=(%.4f, %.4f) width=%.2f offset=%.2f" %
      (deg, adir[0], adir[1], slash_w, slash_off))

# ---- ring band per angle -------------------------------------------------------------
yy, xx = np.mgrid[0:H, 0:W]
dist = np.hypot(xx - cx, yy - cy)
ang = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 360.0) % 360.0
# drop the slash (and its ends, which blend into the ring) before measuring the band
slash_perp = np.abs((xx - cx) * aperp[0] + (yy - cy) * aperp[1] - slash_off)
ring_only = red & (slash_perp > slash_w / 2 + 4)

angles = np.arange(NB) * 360.0 / NB
edge_in, edge_out = [np.nan] * NB, [np.nan] * NB
for i in range(NB):
    s = ring_only & (ang >= i * 360.0 / NB) & (ang < (i + 1) * 360.0 / NB) & (dist > 70) & (dist < 125)
    dd = dist[s]
    if dd.size < 25:
        continue
    edge_in[i] = float(np.percentile(dd, 3))
    edge_out[i] = float(np.percentile(dd, 97))
# buckets where the slash crosses the ring keep too few pixels: interpolate from the
# buckets that do have a measurement, then smooth around the circle
good = [i for i in range(NB) if not np.isnan(edge_in[i])]
if len(good) < NB // 2:
    raise SystemExit("could not measure the ring: only %d/%d buckets had pixels" % (len(good), NB))
wrapped = good + [g + NB for g in good]
for i in range(NB):
    if np.isnan(edge_in[i]):
        k = np.searchsorted(wrapped, i)
        lo, hi = wrapped[k - 1], wrapped[k]
        t = (i - lo) / (hi - lo)
        edge_in[i] = edge_in[lo % NB] * (1 - t) + edge_in[hi % NB] * t
        edge_out[i] = edge_out[lo % NB] * (1 - t) + edge_out[hi % NB] * t
prof_in = smooth_circular(edge_in)
prof_out = smooth_circular(edge_out)
ring_in, ring_out = float(np.median(prof_in)), float(np.median(prof_out))
ring_in_min, ring_in_max = float(min(prof_in)), float(max(prof_in))
ring_out_min, ring_out_max = float(min(prof_out)), float(max(prof_out))
print("ring in %.1f..%.1f (med %.1f)  out %.1f..%.1f (med %.1f)" %
      (ring_in_min, ring_in_max, ring_in, ring_out_min, ring_out_max, ring_out))

# ---- colour of the repainted sign ----------------------------------------------------
# The source is a re-encoded JPEG and its stroke reads as a dull brick red; the sign is
# repainted in the red the tool has always used so the finished sticker looks like a
# prohibition sign rather than a washed-out copy.
RED = RED_FALLBACK
band = red & (np.abs(dist - (ring_in + ring_out) / 2) < 4)
print("ring core colour in the source %s (%d px), repainting with %s" %
      (tuple(int(np.median(a[:, :, c][band])) for c in range(3)), int(band.sum()), RED))

# ---- per-pixel interpolated ring edges ----------------------------------------------
grid = np.concatenate([angles, [360.0]])
rin_px = np.interp(ang, grid, prof_in + [prof_in[0]])
rout_px = np.interp(ang, grid, prof_out + [prof_out[0]])

clip = lambda v: np.clip(v, 0.0, 1.0)


def value_noise(shape, cells, seed):
    """Smooth pseudo-random field in [0,1): a coarse grid, smoothstep-upsampled."""
    h, w = shape
    g = np.random.default_rng(seed).random((cells + 1, cells + 1)).astype(np.float32)
    ys = np.linspace(0.0, cells, h, endpoint=False)
    xs = np.linspace(0.0, cells, w, endpoint=False)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    a00 = g[np.ix_(y0, x0)]
    a01 = g[np.ix_(y0, x0 + 1)]
    a10 = g[np.ix_(y0 + 1, x0)]
    a11 = g[np.ix_(y0 + 1, x0 + 1)]
    top = a00 * (1 - fx) + a01 * fx
    bot = a10 * (1 - fx) + a11 * fx
    return top * (1 - fy) + bot * fy


# ---- aged ink -------------------------------------------------------------------------
# A perfectly even red reads as a vector overlay pasted onto the photograph.  Real screen
# print on a board is never even: it thins where it was wiped, darkens where it pooled,
# gets knocked off in chips and carries a faint grain.  All of that lives in the *colour*
# only - the overlay's alpha, which is what actually keeps the picture inside the ring, is
# left exactly as measured, so none of this can move the leak boundary.
#
# The amplitudes are set so the ring's tonal spread is in the same league as the source
# photo's own (a flat repaint measures ~0 where the source measures ~27), because a stroke
# far smoother than its surroundings is what gives the game away.
blotch = value_noise((H, W), 8, 1301)             # broad thinning / pooling
patch = value_noise((H, W), 24, 1305)             # unevenness along the stroke
speck = value_noise((H, W), 55, 1302)             # patchiness
tooth = value_noise((H, W), 190, 1303)            # fine tooth
grain = np.random.default_rng(1306).normal(0.0, 1.0, (H, W)).astype(np.float32)
BOARD = np.array([201, 194, 183], np.float32)     # what the print sits on
GRIME = np.array([78, 52, 46], np.float32)        # soot caught in the low spots

density = np.clip(1.0
                  + 0.30 * (blotch - 0.5) * 2.0
                  + 0.17 * (patch - 0.5) * 2.0
                  + 0.11 * (speck - 0.5) * 2.0
                  + 0.07 * (tooth - 0.5) * 2.0
                  + 0.07 * grain, 0.60, 1.28)
ink = np.array(RED, np.float32)[None, None, :] * density[:, :, None]

# a soft faded wash over the thin parts of the print ...
wash = clip((0.52 - blotch) * 3.2) * (0.45 + 0.55 * patch) * 0.30
# ... plus rarer spots where the ink is actually gone and the board shows
spots = clip((0.34 - speck) * 5.0) * clip(0.35 + (0.58 - blotch) * 2.0) * 0.85
wear = np.maximum(wash, spots)
ink = ink * (1 - wear[:, :, None]) + BOARD * wear[:, :, None]

# grime settles in the broad low areas
grime = clip((blotch - 0.66) * 2.8) * (0.55 + 0.45 * grain * 0.5) * 0.34
ink = ink * (1 - grime[:, :, None]) + GRIME * grime[:, :, None]

# ---- overlay -------------------------------------------------------------------------
# The board, the sign's black frame and the ring's soft outer edge all come straight from
# the source; only the ring band and the slash are repainted.
disc_r = ring_out_max + 6.0
dist_slash = np.abs((xx - cx) * aperp[0] + (yy - cy) * aperp[1] - slash_off)
outside_a = clip((dist - rin_px) / FEATHER) * clip((disc_r - dist) / FEATHER)
# Both edges of the stroke are nibbled by the same noise so it stops reading as a compass
# circle laid over the photo.  Eroding or extending the *red* is safe: what keeps the
# picture in is outside_a, and all that changes here is which colour sits on top.
edge_out = (value_noise((H, W), 70, 1304) - 0.5) * 4.2
edge_in = (value_noise((H, W), 46, 1307) - 0.5) * 1.8
ring_a = clip(0.5 + np.minimum(dist - (rin_px + edge_in), rout_px + edge_out - dist) / FEATHER)
slash_a = clip(slash_w / 2 + 0.5 - dist_slash) * clip((ring_in_max + 2.0 - dist) / FEATHER)
red_a = np.maximum(ring_a, slash_a)

ov_rgb = a * (1.0 - red_a[:, :, None]) + ink * red_a[:, :, None]
ov_a = np.maximum(outside_a, slash_a) * 255.0
ov = np.dstack([ov_rgb, ov_a]).astype(np.uint8)

# How uneven did the ink end up?  A flat repaint measures ~0 here while the source photo's
# own stroke measures ~27, and a stroke far smoother than its surroundings is what makes the
# sign look pasted on.  "worn" is the share of the stroke where the board shows through.
lum = ov_rgb[:, :, :3][band].mean(1)
worn = 100.0 * (ov_rgb[:, :, 1][band] > 90).mean()
print("aged ink: luminance std %.1f (was %.1f for a flat repaint, source stroke %.1f), "
      "p1..p99 %.0f..%.0f, worn %.1f%%" %
      (lum.std(), 0.0, np.asarray(a[:, :, :3][band]).mean(1).std(),
       np.percentile(lum, 1), np.percentile(lum, 99), worn))
Image.fromarray(ov).save(os.path.join(OUT, "overlay.png"), optimize=True)

# ---- slash-only mask -----------------------------------------------------------------
# The page can switch the slash off ("keep only the ring").  This little mask holds exactly
# the pixels the slash contributes, so the page can erase them from the overlay without
# touching the ring where the two meet.
slash_only = clip(slash_a * (1.0 - ring_a))
sy, sx = np.nonzero(slash_only > 0.004)
if sx.size:
    mx0, my0 = int(sx.min()) - 1, int(sy.min()) - 1
    mx1, my1 = int(sx.max()) + 2, int(sy.max()) + 2
    Image.fromarray((slash_only[my0:my1, mx0:mx1] * 255).astype(np.uint8), "L").save(
        os.path.join(OUT, "slashmask.png"), optimize=True)
else:
    mx0 = my0 = 0
    mx1, my1 = 1, 1
    Image.fromarray(np.zeros((1, 1), np.uint8), "L").save(os.path.join(OUT, "slashmask.png"))
print("slash mask %dx%d at (%d, %d)" % (mx1 - mx0, my1 - my0, mx0, my0))

# ---- base template: the sign's interior painted white -------------------------------
inner = clip((dist - (rin_px - 1.2)) / FEATHER)          # 0 inside the sign, 1 outside
base = a * inner[:, :, None] + 255.0 * (1.0 - inner[:, :, None])
tpl = Image.fromarray(base.astype(np.uint8))
tpl.save(os.path.join(OUT, "template.png"), optimize=True)

thumb = tpl.resize((408, 356), Image.LANCZOS)
buf = io.BytesIO()
thumb.save(buf, "JPEG", quality=72, optimize=True)
open(os.path.join(OUT, "thumb.jpg"), "wb").write(buf.getvalue())

geo = dict(
    w=W, h=H,
    cx=round(cx, 2), cy=round(cy, 2),
    ring_in=round(ring_in, 2), ring_out=round(ring_out, 2),
    ring_in_min=round(ring_in_min, 2), ring_in_max=round(ring_in_max, 2),
    ring_out_min=round(ring_out_min, 2), ring_out_max=round(ring_out_max, 2),
    # the picture is clipped here and must cover cover_r, so it can neither leave a white
    # gap inside the ring nor a halo of itself outside it
    clip_r=round(ring_out_max + 4.0, 2),
    cover_r=round(ring_in_max + 2.0, 2),
    disc_r=round(disc_r, 2),
    slash=dict(cx=round(cx + aperp[0] * slash_off, 2), cy=round(cy + aperp[1] * slash_off, 2),
               dx=round(float(adir[0]), 4), dy=round(float(adir[1]), 4),
               w=round(slash_w, 2), offset=round(slash_off, 2),
               end_r=round(ring_in_max + 2.0, 2)),
    slash_mask=dict(x=mx0, y=my0, w=mx1 - mx0, h=my1 - my0),
    red=list(RED),
)
# written with LF so a rebuild never shows up as a line-ending-only diff
with open(os.path.join(ROOT, "tools", "geometry.json"), "w", encoding="utf-8", newline="\n") as fh:
    json.dump(geo, fh, indent=1)
    fh.write("\n")
print("GEO", geo)
print("sizes: template %d, overlay %d, thumb %d" %
      (os.path.getsize(os.path.join(OUT, "template.png")),
       os.path.getsize(os.path.join(OUT, "overlay.png")), len(buf.getvalue())))
