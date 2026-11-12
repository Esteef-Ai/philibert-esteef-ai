"""T09: the treemap layout stays fast on folders with hundreds of thousands of files (it once took minutes)."""
import time

from _t import check, finish

try:
    from wiztry.scanner import Node
    from wiztry.treemap import layout
except Exception as e:                                  # noqa: BLE001
    check("wiztry.treemap imports", False, e)
    finish()

W, H = 1100, 440


def folder(name, sizes, parent=None):
    """A folder Node holding one file per size, largest first, totals filled in."""
    d = Node(name, "X:\\" + name, True)
    d.parent = parent
    d.children = [Node(f"f{i}", f"X:\\{name}\\f{i}", False, size=s, files=1, parent=d)
                  for i, s in enumerate(sorted(sizes, reverse=True))]
    d.size, d.files = sum(sizes), len(sizes)
    return d


def timed(node, w=W, h=H):
    t = time.perf_counter()
    out = layout(node, 0, 0, w, h)
    return out, time.perf_counter() - t


def inside(r, w=W, h=H):
    return r[0] >= -0.01 and r[1] >= -0.01 and r[0] + r[2] <= w + 0.01 and r[1] + r[3] <= h + 0.01


# 1. 300,000 small files in one folder: none is big enough to draw, and finding that out must be quick
n = 300_000
tiny = folder("tiny", [3 * n - i for i in range(n)])
out, secs = timed(tiny)
check("300,000 small files in one folder: laid out in under 1 second", secs < 1.0, f"{secs:.2f} s")
check("300,000 small files: no block is drawn smaller than 3 px", all(r[2] >= 3 and r[3] >= 3 for _c, r, _d in out),
      [r for _c, r, _d in out if r[2] < 3 or r[3] < 3][:3])

# 2. ten big files among 300,000 small ones: the big ones still show, at their true share of the area
mixed = folder("mixed", [1_000_000_000] * 10 + [1_000] * n)
out, secs = timed(mixed)
big = [(c, r) for c, r, _d in out if c.size == 1_000_000_000]
check("10 big files among 300,000 small: laid out in under 1 second", secs < 1.0, f"{secs:.2f} s")
check("10 big files among 300,000 small: all 10 big files are drawn", len(big) == 10, len(big))
share = 1_000_000_000 / mixed.size * W * H
worst = max([abs(r[2] * r[3] - share) / share for _c, r in big] or [1.0])
check("each big file's block has its true share of the area (within 5%)", worst <= 0.05, f"worst error {worst:.1%}")
check("every block is inside the box", all(inside(r) for _c, r, _d in out), [r for _c, r, _d in out if not inside(r)][:3])

# 3. the cut must not inflate what is kept: three files and a long tail of small ones
tail = folder("tail", [5_000, 3_000, 1_000] + [1] * 5_000)
out, secs = timed(tail, 600, 400)
by_size = {c.size: r for c, r, _d in out if c.size >= 1_000}
errs = [abs(r[2] * r[3] - s / tail.size * 600 * 400) / (s / tail.size * 600 * 400) for s, r in by_size.items()]
check("three files and 5,000 tiny ones: the three are drawn", len(by_size) == 3, sorted(by_size))
check("three files and 5,000 tiny ones: their areas keep their true share (within 5%)", bool(errs) and max(errs) <= 0.05,
      [f"{e:.1%}" for e in errs])

# 4. 20,000 equal files, each big enough to see
equal = folder("equal", [1_000] * 20_000)
out, secs = timed(equal)
check("20,000 equal files: laid out in under 1.5 seconds", secs < 1.5, f"{secs:.2f} s")
check("20,000 equal files: at least 2,000 blocks are drawn", len(out) >= 2_000, len(out))
check("20,000 equal files: every block is inside the box and at least 3 px", all(inside(r) and r[2] >= 3 and r[3] >= 3 for _c, r, _d in out),
      [r for _c, r, _d in out if not (inside(r) and r[2] >= 3 and r[3] >= 3)][:3])

# 5. a drive-like tree: 3,000 folders of 100 files each
top = Node("drive", "X:\\", True)
for k in range(3_000):
    d = folder(f"d{k}", [(k + 1) * 10 + j for j in range(100)], parent=top)
    top.children.append(d)
top.children.sort(key=lambda c: -c.size)
top.size, top.files, top.folders = sum(c.size for c in top.children), 300_000, 3_000
out, secs = timed(top)
check("3,000 folders of 100 files: laid out in under 1.5 seconds", secs < 1.5, f"{secs:.2f} s")
check("3,000 folders of 100 files: folders are drawn", sum(1 for c, _r, _d in out if c.is_dir) >= 500, sum(1 for c, _r, _d in out if c.is_dir))
check("3,000 folders of 100 files: every block is inside the box", all(inside(r) for _c, r, _d in out),
      [r for _c, r, _d in out if not inside(r)][:3])
finish()
