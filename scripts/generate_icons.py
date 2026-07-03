"""Generate the PWA app icons with zero dependencies (stdlib zlib only).

Run: python scripts/generate_icons.py

Design: warm orange tile (dashboard accent) with a white heart-pulse mark.
Maskable variant is full-bleed (no rounded corners) so platform masks crop
cleanly within the safe zone.
"""
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "icons")
ACCENT = (224, 122, 79)   # #e07a4f
WHITE = (255, 255, 255)


def chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


def encode_png(size, rgba):
    sig = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    stride = size * 4
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def in_rounded_rect(x, y, size, radius):
    dx = max(radius - x, x - (size - radius), 0)
    dy = max(radius - y, y - (size - radius), 0)
    return (dx * dx + dy * dy) ** 0.5 <= radius


def in_heart(px, py, cx, cy, scale):
    # Classic heart implicit curve, sampled in a local coordinate space.
    x = (px - cx) / scale
    y = -(py - cy) / scale + 0.35
    return (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0


def draw_icon(size, maskable):
    rgba = bytearray(size * size * 4)
    radius = size * 0.18
    cx, cy = size / 2, size / 2
    scale = size * 0.30

    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            px, py = x + 0.5, y + 0.5
            visible = maskable or in_rounded_rect(px, py, size, radius)
            if not visible:
                continue
            color = WHITE if in_heart(px, py, cx, cy, scale) else ACCENT
            rgba[i:i + 4] = bytes(color) + bytes([255])
    return encode_png(size, bytes(rgba))


def main():
    os.makedirs(OUT, exist_ok=True)
    specs = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ]
    for name, size, maskable in specs:
        path = os.path.join(OUT, name)
        with open(path, "wb") as f:
            f.write(draw_icon(size, maskable))
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
