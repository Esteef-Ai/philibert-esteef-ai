"""A QR code, made here with no libraries (Philibert's own Python has none): byte mode, error
correction level M, versions 1-6 (up to 106 bytes - a web address on the home network fits easily),
the mask with the lowest penalty. Checked module for module against the `qrcode` package.

  matrix(text) -> [[bool]]   (True = dark)
  svg(text, px=8) -> an <svg> with a 4-module quiet zone
"""

# (data codewords per block, number of blocks, EC codewords per block) for level M
_M = {1: (16, 1, 10), 2: (28, 1, 16), 3: (44, 1, 26), 4: (32, 2, 18), 5: (43, 2, 24), 6: (27, 4, 16)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7}

# GF(256) with the QR polynomial 0x11D
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n):
    g = [1]
    for i in range(n):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _mul(c, _EXP[i])
        g = ng
    return g                                   # highest power first, g[0] == 1


def _rs_ec(data, n):
    g = _rs_generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(g)):
                rem[i + j] ^= _mul(g[j], c)
    return rem[len(data):]


def _codewords(data):
    for v in range(1, 7):
        dcw, blocks, ecn = _M[v]
        cap = dcw * blocks
        if len(data) + 2 <= cap:                # 4 mode + 8 length bits + data (+ terminator) fits
            break
    else:
        raise ValueError("too long for a small QR code (106 bytes at most)")
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(7, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0
    while len(cw) < cap:
        cw.append((0xEC, 0x11)[pad % 2])
        pad += 1
    blks = [cw[i * dcw:(i + 1) * dcw] for i in range(blocks)]
    ecs = [_rs_ec(b, ecn) for b in blks]
    out = [b[i] for i in range(dcw) for b in blks] + [e[i] for i in range(ecn) for e in ecs]
    return v, out


def _penalty(m):
    n = len(m)
    p = 0
    for rows in (m, [list(c) for c in zip(*m)]):
        for row in rows:
            run, prev = 0, None
            for c in row:
                if c == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run, prev = 1, c
            if run >= 5:
                p += run - 2
            s = "".join("1" if c else "0" for c in row)
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                p += 3
    dark = sum(map(sum, m))
    p += 10 * (abs(dark * 20 - n * n * 10) // (n * n))
    return p


_MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
          lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
          lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
          lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def matrix(text, mask=None):
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    v, cws = _codewords(data)
    n = 17 + 4 * v
    m = [[False] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def setf(x, y, dark):
        m[y][x] = dark
        fn[y][x] = True

    for i in range(n):                                       # timing
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):          # finders + separators
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < n and 0 <= y < n:
                    d = max(abs(dx), abs(dy))
                    setf(x, y, d != 2 and d != 4)
    al = _ALIGN[v]
    for i, ay in enumerate(al):                               # alignment
        for j, ax in enumerate(al):
            if (i == 0 and j == 0) or (i == 0 and j == len(al) - 1) or (i == len(al) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(mk):
        d = (0 << 3) | mk                                     # level M = 00
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        bits = ((d << 10) | r) ^ 0x5412
        b = [(bits >> i) & 1 == 1 for i in range(15)]
        for i in range(6):
            setf(8, i, b[i])
        setf(8, 7, b[6])
        setf(8, 8, b[7])
        setf(7, 8, b[8])
        for i in range(9, 15):
            setf(14 - i, 8, b[i])
        for i in range(8):
            setf(n - 1 - i, 8, b[i])
        for i in range(8, 15):
            setf(8, n - 15 + i, b[i])
        setf(8, n - 8, True)                                  # the dark module

    format_bits(0)                                            # reserve the places
    bits = [((c >> (7 - k)) & 1) == 1 for c in cws for k in range(8)] + [False] * _REMAINDER[v]
    i = 0
    right = n - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(n):
            for j in range(2):
                x = right - j
                up = ((right + 1) & 2) == 0
                y = n - 1 - vert if up else vert
                if not fn[y][x] and i < len(bits):
                    m[y][x] = bits[i]
                    i += 1
        right -= 2

    def masked(mk):
        out = [row[:] for row in m]
        f = _MASKS[mk]
        for y in range(n):
            for x in range(n):
                if not fn[y][x] and f(x, y):
                    out[y][x] = not out[y][x]
        return out

    best = None
    for mk in ([mask] if mask is not None else range(8)):
        format_bits(mk)
        cand = masked(mk)
        score = _penalty(cand)
        if best is None or score < best[0]:
            best = (score, cand)
    return best[1]


def svg(text, px=8, dark="#000", light="#fff"):
    m = matrix(text)
    n = len(m) + 8
    rects = "".join(f'<rect x="{x + 4}" y="{y + 4}" width="1" height="1"/>'
                    for y, row in enumerate(m) for x, c in enumerate(row) if c)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * px}" height="{n * px}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="{light}"/>'
            f'<g fill="{dark}">{rects}</g></svg>')
