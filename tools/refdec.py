"""Reference LZW decoder implementing the verified rule, validated against Pillow's own GIFs."""
import os
import sys

from PIL import Image


def payload_of(path):
    raw = open(path, "rb").read()
    p = 6
    packed = raw[p + 4]
    gct = 1 << ((packed & 7) + 1) if packed & 0x80 else 0
    p += 7 + gct * 3
    frames = []
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
        frames.append((w, h, mincode, bytes(pay)))
    return frames


def decode(pay, mincode, expected, log=None):
    clear, eoi = 1 << mincode, (1 << mincode) + 1
    cur = mincode + 1
    table = [[i] for i in range(clear)] + [None, None]
    bp = 0
    prev = None
    out = []
    while True:
        c = 0
        ok = True
        for i in range(cur):
            bi = bp >> 3
            if bi >= len(pay):
                ok = False
                break
            c |= ((pay[bi] >> (bp & 7)) & 1) << i
            bp += 1
        if not ok:
            break
        if c == clear:
            if log is not None:
                log.append("CLEAR@%d" % cur)
            table = [[i] for i in range(clear)] + [None, None]
            cur = mincode + 1
            prev = None
            continue
        if c == eoi:
            if log is not None:
                log.append("EOI@%d" % cur)
            break
        if c < len(table) and table[c]:
            entry = table[c]
        elif c == len(table) and prev:
            entry = prev + [prev[0]]
        else:
            return out, "INVALID %d table=%d cur=%d" % (c, len(table), cur)
        if log is not None:
            log.append("code %d @%d" % (c, cur))
        out += entry
        if prev:
            table.append(prev + [entry[0]])
            if len(table) == (1 << cur) and cur < 12:
                cur += 1
                if log is not None:
                    log.append("  widen->%d" % cur)
        prev = entry
        if expected and len(out) >= expected:
            break
    return out, None


HERE = os.path.dirname(os.path.abspath(__file__))
# handy GIFs to poke at; anything missing is simply skipped
for name, path in [("ours small.gif", os.path.join(HERE, "gifs", "small.gif")),
                   ("ours noise.gif", os.path.join(HERE, "gifs", "noise.gif")),
                   ("ours transparent.gif", os.path.join(HERE, "gifs", "transparent.gif")),
                   ("ours alpha256.gif", os.path.join(HERE, "gifs", "alpha256.gif"))]:
    if not os.path.exists(path):
        continue
    print("==", name)
    for (w, h, mincode, pay) in payload_of(path):
        out, err = decode(pay, mincode, w * h)
        truth = None
        try:
            im = Image.open(path)
            truth = list(im.getdata())[:len(out)]
        except Exception as exc:  # noqa: BLE001
            truth = None
        status = "decoded %d/%d px" % (len(out), w * h)
        if err:
            status += " ERROR " + err
        if truth is not None:
            status += " matches-pillow=%s" % (out == truth)
        print("   %dx%d mincode=%d -> %s" % (w, h, mincode, status))
        print("   first px:", out[:16])
        break
