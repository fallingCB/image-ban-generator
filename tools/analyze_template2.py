"""Refine: ring-only circle fit + sign board quad detection."""
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
img = Image.open(os.path.join(ROOT, "template-source.jpg")).convert("RGB")
a = np.asarray(img).astype(np.float32)
h, w, _ = a.shape
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
red = (r > 120) & (r - g > 55) & (r - b > 45)
ys, xs = np.nonzero(red)
x = xs.astype(np.float64); y = ys.astype(np.float64)

# start from bbox circle, iterate: fit only pixels inside an annulus
cx, cy, rad = 334.5, 259.5, 99.0
for it in range(6):
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    band = (d > rad - 14) & (d < rad + 14)
    xb, yb = x[band], y[band]
    A = np.column_stack([xb, yb, np.ones_like(xb)])
    bb = xb * xb + yb * yb
    sol, *_ = np.linalg.lstsq(A, bb, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    rad = np.sqrt(sol[2] + cx ** 2 + cy ** 2)
d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
band = (d > rad - 14) & (d < rad + 14)
print("ring-only fit: center=(%.2f, %.2f) r=%.2f  (band px=%d)" % (cx, cy, rad, band.sum()))
db = d[band]
print("ring band p2/p50/p98: %.2f %.2f %.2f" % tuple(np.percentile(db, [2, 50, 98])))

# slash direction: inside pixels
inside = d < rad - 12
xi, yi = x[inside], y[inside]
# fit a line via PCA
mx, my = xi.mean(), yi.mean()
cov = np.cov(np.vstack([xi - mx, yi - my]))
evals, evecs = np.linalg.eigh(cov)
v = evecs[:, evals.argmax()]
print("slash center (%.2f, %.2f) dir (%.3f, %.3f) angle=%.2f deg" % (mx, my, v[0], v[1], np.degrees(np.arctan2(v[1], v[0]))))
# perpendicular extent of the slash => stroke width
perp = evecs[:, evals.argmin()]
proj = (xi - mx) * perp[0] + (yi - my) * perp[1]
print("slash stroke width ~ %.2f px (p2..p98 = %.2f..%.2f)" % (
    np.percentile(proj, 98) - np.percentile(proj, 2), np.percentile(proj, 2), np.percentile(proj, 98)))
length = (xi - mx) * v[0] + (yi - my) * v[1]
print("slash length ~ %.2f px" % (length.max() - length.min()))

# ---- board: find the white quad by scanning the dark rounded-rect border ----
# dark outline pixels near the board
dark = (r < 110) & (g < 110) & (b < 110)
reg = np.zeros_like(dark); reg[110:340, 140:580] = True
dm = dark & reg
ys3, xs3 = np.nonzero(dm)
print("dark border bbox x %d..%d y %d..%d" % (xs3.min(), xs3.max(), ys3.min(), ys3.max()))
# top edge: for each column, first dark y
cols = np.unique(xs3)
print("first/last dark col:", cols.min(), cols.max())
top = {}
bot = {}
for c in cols:
    yy = ys3[xs3 == c]
    top[c] = yy.min(); bot[c] = yy.max()
cc = np.array(sorted(top))
print("top edge y at cols 200/300/400/500:", [top[c] for c in (200, 300, 400, 500) if c in top])
print("bottom edge y at cols 200/300/400/500:", [bot[c] for c in (200, 300, 400, 500) if c in bot])
# left/right extreme rows
rows = np.unique(ys3)
left, right = {}, {}
for rr in rows:
    xx = xs3[ys3 == rr]
    left[rr] = xx.min(); right[rr] = xx.max()
print("left edge x at rows 150/200/250/300:", [left[rr] for rr in (150, 200, 250, 300) if rr in left])
print("right edge x at rows 150/200/250/300:", [right[rr] for rr in (150, 200, 250, 300) if rr in right])
