"""Inline the generated assets into the single-file app (src/app.template.html -> ban-sticker.html)."""
import base64
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
TPL = os.path.join(ROOT, "src", "app.template.html")
OUT = os.path.join(ROOT, "ban-sticker.html")
SITE = os.path.join(ROOT, "index.html")
GEO = os.path.join(ROOT, "tools", "geometry.json")


def data_uri(name, mime):
    with open(os.path.join(ASSETS, name), "rb") as fh:
        return "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode("ascii"))


def geometry_json():
    """The page never hard-codes sign geometry: it is baked in from the same measurement
    that produced the assets, so the two can never drift apart again."""
    with open(GEO, encoding="utf-8") as fh:
        geo = json.load(fh)
    geo["w"] = int(geo["w"])
    geo["h"] = int(geo["h"])
    return json.dumps(geo, separators=(",", ":"))


html = open(TPL, encoding="utf-8").read()
repl = {
    "__GEO_JSON__": geometry_json(),
    "__TEMPLATE_DATA_URI__": data_uri("template.png", "image/png"),
    "__OVERLAY_DATA_URI__": data_uri("overlay.png", "image/png"),
    "__SLASHMASK_DATA_URI__": data_uri("slashmask.png", "image/png"),
    "__THUMB_DATA_URI__": data_uri("thumb.jpg", "image/jpeg"),
}
for key, val in repl.items():
    if key not in html:
        raise SystemExit("placeholder %s missing in template" % key)
    html = html.replace(key, val)
if "__" in re.sub(r"data:[^\"')]+", "", html):
    leftover = set(re.findall(r"__[A-Z_]+__", html))
    if leftover:
        raise SystemExit("unreplaced placeholders: %s" % leftover)
# ban-sticker.html is the file you double-click locally; index.html is the very same bytes,
# because GitHub Pages serves index.html at the site root.  Git stores identical content once,
# so keeping both costs nothing and neither can drift from the other.
for target in (OUT, SITE):
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
print("wrote %s (%.1f KB) and %s" %
      (OUT, os.path.getsize(OUT) / 1024, os.path.basename(SITE)))
