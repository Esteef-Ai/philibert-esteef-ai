"""Squarified treemap layout algorithms for WizTry."""

from wiztry.scanner import Node


def squarify(sizes, x, y, w, h):
    """Squarify a list of sizes into rectangles filling (x, y, w, h).

    Returns a list of (x, y, w, h) tuples in the same order as sizes,
    or None for zero sizes and empty/no-room cases.
    """
    if w <= 0 or h <= 0:
        return [None] * len(sizes) if sizes else []

    total = sum(sizes)
    if total == 0:
        return [None] * len(sizes) if sizes else []

    # Separate zero sizes (they get None) from the rest
    active_indices = [i for i, s in enumerate(sizes) if s > 0]
    if not active_indices:
        return [None] * len(sizes)

    active_sizes = [sizes[i] for i in active_indices]

    rects = _squarify_impl(active_sizes, x, y, w, h)

    result = [None] * len(sizes)
    for idx, rect in zip(active_indices, rects):
        result[idx] = rect

    return result


def _squarify_impl(sizes, x, y, w, h):
    """Internal squarified layout for non-zero sizes."""
    result = []
    total = sum(sizes)
    if total <= 0:
        return []
    scale = w * h / total
    n = len(sizes)
    i = 0
    remaining_total = total

    while i < n and remaining_total > 0 and w > 0 and h > 0:
        side = min(w, h)
        # row_sum is the area (in pixels) of the row
        row_sum = sizes[i] * scale
        lo = row_sum
        hi = row_sum
        worst = max(side * side * hi / row_sum ** 2, row_sum ** 2 / (side * side * lo))
        row = [i]
        j = i + 1
        while j < n:
            new_sum = row_sum + sizes[j] * scale
            new_lo = min(lo, sizes[j] * scale)
            new_hi = max(hi, sizes[j] * scale)
            new_worst = max(side * side * new_hi / new_sum ** 2, new_sum ** 2 / (side * side * new_lo))
            if new_worst > worst:
                break
            row.append(j)
            row_sum = new_sum
            lo = new_lo
            hi = new_hi
            worst = new_worst
            j += 1

        thick = row_sum / side
        if w >= h:
            cur = y
            for k in row:
                area = sizes[k] * scale
                result.append((x, cur, thick, area / thick))
                cur += area / thick
            x += thick
            w -= thick
        else:
            cur = x
            for k in row:
                area = sizes[k] * scale
                result.append((cur, y, area / thick, thick))
                cur += area / thick
            y += thick
            h -= thick

        remaining_total -= row_sum / scale
        i = j

    return result


MAX_CHILDREN = 4000


def layout(node, x, y, w, h, min_px=3, depth=0):
    """Lay out a node's children as rectangles inside (x, y, w, h).

    Returns a list of (child, (x, y, w, h), depth) for every child of node
    with size > 0 whose block is at least min_px in both directions.
    """
    result = []
    children = [c for c in node.children if c.size > 0]
    if not children:
        return result

    total_size = sum(c.size for c in children)
    if total_size == 0:
        return result

    if w < min_px or h < min_px:
        return result

    # Filter children that can be seen (need at least min_px x min_px area)
    need = min_px * min_px * total_size / (w * h)
    kept = [c for c in children if c.size >= need]

    # Cap at MAX_CHILDREN
    if len(kept) > MAX_CHILDREN:
        kept = sorted(kept, key=lambda c: -c.size)[:MAX_CHILDREN]

    if not kept:
        return result

    # Compute rest: total_size minus the sum of kept sizes
    kept_total = sum(c.size for c in kept)
    rest = total_size - kept_total

    # Build list of (child, size) sorted largest first
    kept_sorted = sorted(kept, key=lambda c: -c.size)
    sizes = [c.size for c in kept_sorted]

    # Insert rest as one extra entry at the right position
    if rest > 0:
        # Find insertion point: before first size smaller than rest
        ins = 0
        for s in sizes:
            if s < rest:
                break
            ins += 1
        sizes.insert(ins, rest)

    rects = squarify(sizes, x, y, w, h)

    # Determine which rect index corresponds to rest (if inserted)
    rest_rect_idx = None
    if rest > 0:
        rest_rect_idx = ins

    for idx, child in enumerate(kept_sorted):
        rect = rects[idx]
        if rect is None:
            continue
        rx, ry, rw, rh = rect
        if rw < min_px or rh < min_px:
            continue
        result.append((child, (rx, ry, rw, rh), depth))

    for child, rect in zip(kept_sorted, rects):
        if rect is None:
            continue
        rx, ry, rw, rh = rect
        if child.is_dir and rw > 2 * min_px and rh > 2 * min_px:
            result.extend(
                layout(child, rx + 1, ry + 1, rw - 2, rh - 2, min_px, depth + 1)
            )

    return result
