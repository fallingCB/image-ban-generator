"""Final encoder verification:
   1. decode every frame's LZW stream with the verified rule and compare raw palette
      indices against exactly what the encoder was given (format correctness);
   2. load with Pillow and compare pixel colours for opaque frames.
"""
import json
import os
import sys

from PIL import Image, ImageSequence

GIFS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "gifs")
meta = json.load(open(os.path.join(GIFS, "meta.json")))


def frames_of(path):
    raw = open(path, "rb").read()
    p = 6
    packed = raw[p + 4]
    gct = 1 << ((packed & 7) + 1)
    p += 7 + gct * 3
    out = []
    while p < len(raw):
        m = raw[p]
        if m == 0x3B:
            break
        if m == 0x21:
            p += 2
            while raw[p]:                 # walk the sub-blocks (an extension can have several)
                p += 1 + raw[p]
            p += 1
            continue
        if m != 0x2C:
            break
        w = raw[p + 5] | (raw[p + 6] << 8)
        h = raw[p + 7] | (raw[p + 8] << 8)
        mincode = raw[p + 10]
        p += 11
        pay = bytearray()
        while raw[p]:
            n = raw[p]
            pay += raw[p + 1:p + 1 + n]
            p += 1 + n
        p += 1
        out.append((w, h, mincode, bytes(pay)))
    return out


def decode(pay, mincode, expected):
    clear, eoi = 1 << mincode, (1 << mincode) + 1
    cur = mincode + 1
    table = [[i] for i in range(clear)] + [None, None]
    bp = 0
    prev = None
    res = []
    while len(res) < expected:
        c = 0
        for i in range(cur):
            bi = bp >> 3
            if bi >= len(pay):
                return res, "truncated at %d" % len(res)
            c |= ((pay[bi] >> (bp & 7)) & 1) << i
            bp += 1
        if c == clear:
            table = [[i] for i in range(clear)] + [None, None]
            cur = mincode + 1
            prev = None
            continue
        if c == eoi:
            return res, "early EOI at %d" % len(res)
        if c < len(table) and table[c]:
            entry = table[c]
        elif c == len(table) and prev:
            entry = prev + [prev[0]]
        else:
            return res, "invalid code %d (table %d, width %d)" % (c, len(table), cur)
        res += entry
        if prev:
            table.append(prev + [entry[0]])
            if len(table) == (1 << cur) and cur < 12:
                cur += 1
        prev = entry
    return res, None


failures = 0
for name, m in meta.items():
    path = os.path.join(GIFS, name + ".gif")
    print("== %s (%d bytes)" % (name, os.path.getsize(path)))
    got = frames_of(path)
    if len(got) != len(m["frames"]):
        print("   FAIL frame count %d vs %d" % (len(got), len(m["frames"])))
        failures += 1
        continue
    for i, ((w, h, mincode, pay), exp) in enumerate(zip(got, m["frames"])):
        idx, err = decode(pay, mincode, w * h)
        same = idx == exp["indices"]
        print("   frame %d: %dx%d mincode=%d -> indices %s%s" %
              (i, w, h, mincode, "exact" if same else "MISMATCH",
               "" if not err else " (" + err + ")"))
        if not same:
            failures += 1
        want_ms = max(1, round(exp["delayMs"] / 10)) * 10
        # read the delay straight out of the GCE for this frame
    # Pillow pixel check for opaque frames
    im = Image.open(path)
    frames = [f.copy() for f in ImageSequence.Iterator(im)]
    for i, (fr, exp) in enumerate(zip(frames, m["frames"])):
        if exp["transparent"]:
            continue
        rgba = fr.convert("RGBA")
        px = rgba.load()
        bad = 0
        for y in range(fr.size[1]):
            for x in range(fr.size[0]):
                c = m["palette"][exp["indices"][y * fr.size[0] + x]]
                if px[x, y][:3] != tuple(c):
                    bad += 1
        print("   pillow frame %d colour mismatches: %d" % (i, bad))
        if bad:
            failures += 1
    d = im.info.get("duration")
    print("   pillow duration: %s" % d)
    # the NETSCAPE2.0 block has to ask for an endless loop, or a viewer may play once
    loop = im.info.get("loop")
    print("   pillow loop: %r" % (loop,))
    if loop != 0:
        print("   FAIL the GIF must loop forever (loop=%r)" % (loop,))
        failures += 1

print("\n%s" % ("ALL GOOD" if failures == 0 else "%d FAILURES" % failures))
sys.exit(1 if failures else 0)
