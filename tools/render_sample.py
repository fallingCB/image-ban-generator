"""Render a sample sticker exactly the way the web app composites it.

Layer order (same as paint() in src/app.template.html):
  1. template.png   - the banner with the mascot erased
  2. the picture, clipped to clip_r (the overlay hides everything past it)
  3. overlay.png    - ring + slash + the board just outside the ring

Geometry comes from tools/geometry.json, so the samples can never disagree with the page.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = json.load(open(os.path.join(ROOT, "tools", "geometry.json"), encoding="utf-8"))
CX, CY = GEO["cx"], GEO["cy"]
W, H = int(GEO["w"]), int(GEO["h"])
CLIP_R, COVER_R = GEO["clip_r"], GEO["cover_r"]


def make_demo_photo(w=600, h=800):
    """A stand-in for the user's picture: a portrait "selfie" on a plain background."""
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :, 0] = (52 + xx * 40 / (w - 1)).astype(np.uint8)          # blue studio backdrop
    img[:, :, 1] = (120 + yy * 60 / (h - 1)).astype(np.uint8)
    img[:, :, 2] = (196 - yy * 40 / (h - 1)).astype(np.uint8)
    photo = Image.fromarray(img)
    d = ImageDraw.Draw(photo)
    d.ellipse([w * 0.18, h * 0.30, w * 0.82, h * 0.86], fill=(150, 110, 88))    # shoulders
    d.ellipse([w * 0.30, h * 0.13, w * 0.70, h * 0.52], fill=(246, 214, 186))   # face
    d.chord([w * 0.28, h * 0.08, w * 0.72, h * 0.40], 180, 360, fill=(58, 48, 46))  # hair
    for sx in (0.40, 0.57):
        d.ellipse([w * sx, h * 0.28, w * (sx + 0.06), h * 0.32], fill=(38, 38, 44))
    d.line([w * 0.46, h * 0.38, w * 0.61, h * 0.38], fill=(70, 70, 78), width=4)  # glasses
    d.arc([w * 0.42, h * 0.36, w * 0.58, h * 0.46], 20, 160, fill=(160, 96, 92), width=4)
    return photo


def fit_scale(w, h):
    return min(5.0, 2 * COVER_R / max(1, min(w, h)))


def render(photo, scale, dx=0, dy=0, rot=0.0, out_size=None, path=None):
    out_size = out_size or W
    base = Image.open(os.path.join(ROOT, "assets", "template.png")).convert("RGBA")
    overlay = Image.open(os.path.join(ROOT, "assets", "overlay.png")).convert("RGBA")
    k = out_size / W
    oh = round(out_size * H / W)
    base = base.resize((out_size, oh), Image.LANCZOS)
    overlay = overlay.resize((out_size, oh), Image.LANCZOS)

    dw = photo.width * scale * k
    dh = photo.height * scale * k
    pic = photo.convert("RGBA").resize((max(1, round(dw)), max(1, round(dh))), Image.LANCZOS)
    if rot:
        pic = pic.rotate(rot, resample=Image.BICUBIC, expand=True)

    layer = Image.new("RGBA", (out_size, oh), (0, 0, 0, 0))
    layer.paste(pic, (round((CX + dx) * k - pic.width / 2), round((CY + dy) * k - pic.height / 2)), pic)

    mask = Image.new("L", (out_size, oh), 0)
    r = CLIP_R * k
    ImageDraw.Draw(mask).ellipse([CX * k - r, CY * k - r, CX * k + r, CY * k + r], fill=255)

    out = Image.composite(layer, base, mask)
    out.alpha_composite(overlay)
    out = out.convert("RGB")
    if path:
        out.save(path)
    return out


if __name__ == "__main__":
    photo = make_demo_photo()
    out = render(photo, scale=fit_scale(*photo.size), path=os.path.join(ROOT, "sample-output.png"))
    print("wrote sample-output.png", out.size, "fit=%.4f" % fit_scale(*photo.size))
    small = render(photo, scale=0.9, dx=40, dy=-25, rot=12, out_size=408,
                   path=os.path.join(ROOT, "sample-output-small.png"))
    print("wrote sample-output-small.png", small.size)
