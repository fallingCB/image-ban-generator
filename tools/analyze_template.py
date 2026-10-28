"""Locate the red prohibition circle in the template image.

Prints the detected circle center/radii plus the sign board quad, so the
values can be hardcoded into the HTML generator as fallbacks.
"""
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
img = Image.open(os.path.join(ROOT, "template-source.jpg")).convert("RGB")
a = np.asarray(img).astype(np.float32)
h, w, _ = a.shape
print("size", w, h)

r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
# Strong red: red dominant, low green/blue
red = (r > 120) & (r - g > 55) & (r - b > 45)
print("red pixels", int(red.sum()))

ys, xs = np.nonzero(red)
print("bbox x", xs.min(), xs.max(), "y", ys.min(), ys.max())
print("centroid", xs.mean().round(2), ys.mean().round(2))

cx0 = (xs.min() + xs.max()) / 2.0
cy0 = (ys.min() + ys.max()) / 2.0
# Robust: use extremes along the centroid rows/cols to get the ring diameter
cy = int(round(ys.mean()))
row = np.nonzero(red[cy])[0]
print("row@centroidy:", row.min(), row.max(), "width", row.max() - row.min() + 1)
cx = int(round(xs.mean()))
col = np.nonzero(red[:, cx])[0]
print("col@centroidx:", col.min(), col.max(), "height", col.max() - col.min() + 1)

cx = (row.min() + row.max() + 1) / 2.0
cy = (col.min() + col.max() + 1) / 2.0
ro = ((row.max() - row.min() + 1) + (col.max() - col.min() + 1)) / 4.0
print("center", cx, cy, "outer radius", ro)

# ring thickness: walk along the horizontal through the center
line = red[cy.astype(int), :]
idx = np.nonzero(line)[0]
# find contiguous runs
runs = []
start = idx[0]
prev = idx[0]
for i in idx[1:]:
    if i != prev + 1:
        runs.append((start, prev))
        start = i
    prev = i
runs.append((start, prev))
print("horizontal runs (left/right ring):", runs)
if len(runs) >= 2:
    left_th = runs[0][1] - runs[0][0] + 1
    right_th = runs[-1][1] - runs[-1][0] + 1
    print("thickness L/R:", left_th, right_th)
    inner = runs[0][1] + 1
    inner_r = runs[-1][0] - 1
    print("inner gap x:", inner, inner_r, "inner radius", (inner_r - inner + 1) / 2)

# circle fit (algebraic, Kasa) on red ring pixels
x = xs.astype(np.float64)
y = ys.astype(np.float64)
A = np.column_stack([x, y, np.ones_like(x)])
bb = x * x + y * y
sol, *_ = np.linalg.lstsq(A, bb, rcond=None)
cx_f = sol[0] / 2
cy_f = sol[1] / 2
rad = np.sqrt(sol[2] + cx_f ** 2 + cy_f ** 2)
print("kasa fit center", round(cx_f, 2), round(cy_f, 2), "radius", round(rad, 2))

# ring residual spread
d = np.sqrt((x - cx_f) ** 2 + (y - cy_f) ** 2)
print("radius p1/p50/p99:", np.percentile(d, 1).round(2), np.percentile(d, 50).round(2), np.percentile(d, 99).round(2))

# The diagonal slash: red pixels well inside the ring
inside = d < rad - 8
print("inside red pixels (slash):", int(inside.sum()))

# ---- detect the white sign board (4 corners) ----
white = (r > 225) & (g > 225) & (b > 225)
# restrict to upper-left quadrant area
mask = np.zeros_like(white)
mask[100:400, 100:600] = True
wb = white & mask
ys2, xs2 = np.nonzero(wb)
print("board bbox x", xs2.min(), xs2.max(), "y", ys2.min(), ys2.max())
# corners: extreme sums/diffs
s = xs2 + ys2
d2 = xs2 - ys2
tl = (xs2[s.argmin()], ys2[s.argmin()])
br = (xs2[s.argmax()], ys2[s.argmax()])
tr = (xs2[d2.argmax()], ys2[d2.argmax()])
bl = (xs2[d2.argmin()], ys2[d2.argmin()])
print("corners TL TR BR BL:", tl, tr, br, bl)

# board height/width estimate via convex extremes
print("board width~", br[0] - tl[0], "height~", bl[1] - tr[1])
