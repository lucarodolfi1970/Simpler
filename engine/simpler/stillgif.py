"""(1.78.4, Luca: Rumex Crispus with solid leaf cards in the real-time view) GIF pictures as still images.

Some plant exports keep a cut-out mask as a GIF. Blender opens a GIF as a movie: Cycles shows it, but the picture
was not copied next to the model in the library (only still images were), and the real-time view could not get it
(the reduced copies are made for still images only): the leaves came out as solid cards. Here a GIF is read (its
first picture, pure Python: no library needed in Blender) and written as a PNG.
"""
import os
import struct
import zlib


def _lzw(data, min_size, count):
    """Indices of the pixels of a GIF picture (LZW, variable code size)."""
    clear, end = 1 << min_size, (1 << min_size) + 1
    size = min_size + 1
    table = [bytes([i]) for i in range(clear)] + [b"", b""]
    out = bytearray()
    prev = None
    bits = nbits = 0
    for byte in data:
        bits |= byte << nbits
        nbits += 8
        while nbits >= size:
            code = bits & ((1 << size) - 1)
            bits >>= size
            nbits -= size
            if code == clear:
                size = min_size + 1
                table = table[:end + 1]
                prev = None
                continue
            if code == end:
                return bytes(out[:count])
            if prev is None:
                entry = table[code]
            elif code < len(table):
                entry = table[code]
                table.append(prev + entry[:1])
            else:
                entry = prev + prev[:1]
                table.append(entry)
            out += entry
            prev = entry
            if len(table) == (1 << size) and size < 12:
                size += 1
            if len(out) >= count:
                return bytes(out[:count])
    return bytes(out[:count])


def read(path):
    """(width, height, RGBA bytes, top row first) of the first picture of a GIF; None when it is not one."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w, h, flags = struct.unpack("<HHB", d[6:11])
    pos = 13
    gct = None
    if flags & 0x80:
        n = 3 * (2 << (flags & 7))
        gct = d[pos:pos + n]
        pos += n
    transp = None
    canvas = bytearray(w * h * 4)
    while pos < len(d):
        b = d[pos]
        pos += 1
        if b == 0x3B:                                   # (end of the file)
            break
        if b == 0x21:                                   # extension: the graphic control gives the transparent colour
            label = d[pos]
            pos += 1
            if label == 0xF9 and d[pos] >= 4 and d[pos + 1] & 1:
                transp = d[pos + 4]
            while d[pos]:
                pos += d[pos] + 1
            pos += 1
            continue
        if b != 0x2C:
            return None
        x0, y0, iw, ih, iflags = struct.unpack("<HHHHB", d[pos:pos + 9])
        pos += 9
        table = gct
        if iflags & 0x80:
            n = 3 * (2 << (iflags & 7))
            table = d[pos:pos + n]
            pos += n
        if table is None:
            return None
        min_size = d[pos]
        pos += 1
        data = bytearray()
        while d[pos]:
            data += d[pos + 1:pos + 1 + d[pos]]
            pos += d[pos] + 1
        pos += 1
        idx = _lzw(bytes(data), min_size, iw * ih)
        rows = list(range(ih))
        if iflags & 0x40:                               # interlaced: rows come in four passes
            rows = list(range(0, ih, 8)) + list(range(4, ih, 8)) + list(range(2, ih, 4)) + list(range(1, ih, 2))
        for r, y in enumerate(rows):
            line = idx[r * iw:(r + 1) * iw]
            yy = y0 + y
            if yy >= h:
                continue
            for x, c in enumerate(line):
                xx = x0 + x
                if xx >= w or c == transp or 3 * c + 2 >= len(table):
                    continue
                o = (yy * w + xx) * 4
                canvas[o:o + 4] = bytes((table[3 * c], table[3 * c + 1], table[3 * c + 2], 255))
        return w, h, bytes(canvas)                      # (the first picture: a still)
    return None


def write_png(path, w, h, rgba):
    """RGBA bytes (top row first) to a PNG file."""
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def to_png(gif_path, png_path):
    """The GIF as a PNG next to the given path; True when written."""
    try:
        got = read(gif_path)
    except Exception:
        got = None
    if not got:
        return False
    write_png(png_path, *got)
    return True
