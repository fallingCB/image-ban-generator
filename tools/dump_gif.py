"""Dump the exact structure of a GIF produced by our encoder."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "gifs", "small.gif")
d = open(path, "rb").read()
print("total", len(d))
print("hex  ", d.hex(" "))
p = 0
print("header    ", d[0:6])
p = 6
w = d[p] | (d[p + 1] << 8); h = d[p + 2] | (d[p + 3] << 8)
packed = d[p + 4]
gct = 1 << ((packed & 7) + 1) if packed & 0x80 else 0
print("screen    %dx%d packed=0x%02x gct=%d bg=%d aspect=%d" % (w, h, packed, gct, d[p + 5], d[p + 6]))
p += 7
print("gct       %d bytes: %s" % (gct * 3, d[p:p + gct * 3].hex(" ")))
p += gct * 3
while p < len(d):
    m = d[p]
    if m == 0x3B:
        print("trailer   at %d" % p)
        break
    if m == 0x21:
        label = d[p + 1]
        print("ext 0x21 label=0x%02x" % label)
        p += 2
        while d[p]:                       # an extension can carry several sub-blocks
            n = d[p]
            print("  subblock len=%d data=%s" % (n, d[p + 1:p + 1 + n].hex(" ")))
            p += 1 + n
        print("  terminator at %d" % p)
        p += 1
        continue
    if m == 0x2C:
        fw = d[p + 5] | (d[p + 6] << 8)
        fh = d[p + 7] | (d[p + 8] << 8)
        ip = d[p + 9]
        mincode = d[p + 10]
        print("image     at %d %dx%d packed=0x%02x mincode=%d" % (p, fw, fh, ip, mincode))
        p += 11
        total = 0
        while d[p]:
            n = d[p]
            print("  subblock len=%d data=%s" % (n, d[p + 1:p + 1 + n].hex(" ")))
            total += n
            p += 1 + n
        print("  terminator at %d, payload total=%d bytes" % (p, total))
        p += 1
        continue
    print("UNKNOWN marker 0x%02x at %d" % (m, p))
    break
