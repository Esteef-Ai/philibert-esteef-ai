"""T02: the squarified treemap fills its box, overlaps nothing and keeps blocks close to square."""
from _t import FIXTURE, check, finish

try:
    from wiztry.scanner import scan
    from wiztry.treemap import layout, squarify
except Exception as e:                                  # noqa: BLE001
    check("wiztry.treemap imports", False, e)
    finish()


def overlap(a, b):
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 0.01
            and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > 0.01)


def _depth(n, top):
    d = 0
    while n.parent is not top:
        n, d = n.parent, d + 1
    return d


def inside(r, box):
    return r[0] >= box[0] - 0.01 and r[1] >= box[1] - 0.01 and r[0] + r[2] <= box[0] + box[2] + 0.01 \
        and r[1] + r[3] <= box[1] + box[3] + 0.01


sizes = [600, 600, 400, 300, 200, 100, 100, 50, 0]
box = (10, 20, 600, 400)
rs = squarify(sizes, *box)
check("one entry per size", len(rs) == len(sizes), len(rs))
check("a zero size gets no block (None)", rs[-1] is None, rs[-1])
real = [r for r in rs if r]
check("every block is inside the box", all(inside(r, box) for r in real), real)
check("no two blocks overlap", not any(overlap(a, b) for i, a in enumerate(real) for b in real[i + 1:]))
total = sum(sizes)
check("area is proportional to size",
      all(abs(r[2] * r[3] - s / total * 600 * 400) < 1 for r, s in zip(rs, sizes) if r), [round(r[2] * r[3]) for r in real])
check("together they fill the box", abs(sum(r[2] * r[3] for r in real) - 600 * 400) < 1)
worst = max(max(r[2] / r[3], r[3] / r[2]) for r in real)
check("blocks stay near square (worst aspect at most 6)", worst <= 6, f"worst aspect {worst:.1f}")
slices = squarify([1] * 12, 0, 0, 600, 400)
check("equal sizes are not cut into thin slices (squarified, not slice-and-dice)",
      max(max(r[2] / r[3], r[3] / r[2]) for r in slices) <= 2.5, slices[:2])
check("nothing to lay out gives no blocks", squarify([], 0, 0, 10, 10) == [] and squarify([0, 0], 0, 0, 10, 10) == [None, None])
check("a box with no room gives no blocks", squarify([5, 5], 0, 0, 0, 10) == [None, None])
rep = squarify([5, 5, 5, 1], 0, 0, 100, 100)
check("repeated sizes: areas in proportion and the box exactly filled",
      all(r and abs(r[2] * r[3] - v / 16 * 10000) < 1 for r, v in zip(rep, [5, 5, 5, 1]))
      and abs(sum(r[2] * r[3] for r in rep if r) - 10000) < 1, rep)
check("repeated sizes: no overlap, all inside", not any(overlap(a, b) for i, a in enumerate(rep) for b in rep[i + 1:])
      and all(inside(r, (0, 0, 100, 100)) for r in rep), rep)

top, _ = scan(FIXTURE)
B = (0, 0, 800, 300)
blocks = layout(top, *B)
check("layout returns (node, rect, depth) triples", blocks and all(len(b) == 3 and len(b[1]) == 4 for b in blocks), blocks[:1])
check("layout covers files deep in folders", any(b[0].name == "part5.o" for b in blocks),
      sorted({b[0].name for b in blocks})[:12])
check("every node gets at most one block", len({id(b[0]) for b in blocks}) == len(blocks),
      f"{len(blocks)} blocks for {len({id(b[0]) for b in blocks})} nodes")
check("a block's depth is its nesting level", all(b[2] == _depth(b[0], top) for b in blocks),
      [(b[0].name, b[2], _depth(b[0], top)) for b in blocks if b[2] != _depth(b[0], top)][:6])
check("every block is inside the canvas", all(inside(b[1], B) for b in blocks))
by_node = {id(b[0]): b for b in blocks}
check("a block sits inside its folder's block",
      all(inside(b[1], by_node[id(b[0].parent)][1]) for b in blocks if id(b[0].parent) in by_node))
level0 = [b[1] for b in blocks if b[2] == 0]
check("top-level blocks do not overlap", not any(overlap(a, c) for i, a in enumerate(level0) for c in level0[i + 1:]))
check("blocks smaller than min_px are left out", all(b[1][2] >= 3 and b[1][3] >= 3 for b in blocks))
check("empty things are left out", not any(b[0].size == 0 for b in blocks))
finish()
