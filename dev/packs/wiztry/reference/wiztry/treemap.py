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
    remaining = list(sizes)
    remaining_total = sum(remaining)

    while remaining and remaining_total > 0 and w > 0 and h > 0:
        # When all remaining items are equal, use a grid layout for better aspect ratios.
        if len(remaining) >= 4 and _all_equal(remaining):
            result.extend(_grid_layout(remaining, x, y, w, h))
            break

        # Try both split directions and pick the one with better worst AR
        row_h, rem_h = _next_row(list(remaining), remaining_total, h, w)
        row_v, rem_v = _next_row(list(remaining), remaining_total, w, h)

        worst_h = _worst_ar(row_h, sum(row_h), h, w, remaining_total) if row_h else float('inf')
        worst_v = _worst_ar(row_v, sum(row_v), w, h, remaining_total) if row_v else float('inf')

        if worst_v <= worst_h:
            row, remaining = row_v, rem_v
            row_sum = sum(row)
            if row_sum == 0:
                break
            row_height = row_sum / remaining_total * h
            cur_y = y
            for s in row:
                rh = s / row_sum * row_height
                result.append((x, cur_y, w, rh))
                cur_y += rh
            y += row_height
            h -= row_height
        else:
            row, remaining = row_h, rem_h
            row_sum = sum(row)
            if row_sum == 0:
                break
            row_width = row_sum / remaining_total * w
            cur_x = x
            for s in row:
                rw = s / row_sum * row_width
                result.append((cur_x, y, rw, h))
                cur_x += rw
            x += row_width
            w -= row_width

        remaining_total = sum(remaining)

    return result


def _all_equal(sizes):
    """Check if all sizes are approximately equal."""
    if not sizes:
        return True
    first = sizes[0]
    return all(abs(s - first) < 1e-9 * max(abs(first), 1) for s in sizes)


def _grid_layout(sizes, x, y, w, h):
    """Lay out equal-sized items in a grid pattern."""
    n = len(sizes)
    # Try all possible grid dimensions and pick the one with best worst AR
    best_rects = []
    best_worst_ar = float('inf')
    for rows in range(1, n + 1):
        cols = n / rows
        if abs(cols - round(cols)) > 1e-9:
            continue
        cols = int(round(cols))
        cell_w = w / cols
        cell_h = h / rows
        worst = max(max(cell_w / cell_h, cell_h / cell_w) for _ in range(n))
        if worst < best_worst_ar:
            best_worst_ar = worst
            best_rects = []
            for r in range(rows):
                for c in range(cols):
                    best_rects.append((x + c * cell_w, y + r * cell_h, cell_w, cell_h))
    return best_rects


def _next_row(sizes, remaining_total, fixed_dim, box_dim):
    """Pick the next row using the squarified algorithm.

    Add items while the worst aspect ratio does not get worse.
    fixed_dim: the dimension that stays constant for all items in this row.
    box_dim: the box dimension in the split direction.
    """
    row = []
    while sizes:
        s = sizes[0]
        test = row + [s]
        test_sum = sum(test)
        if row:
            worst_new = _worst_ar(test, test_sum, fixed_dim, box_dim, remaining_total)
            worst_old = _worst_ar(row, sum(row), fixed_dim, box_dim, remaining_total)
            if worst_new > worst_old:
                break
            # When worst AR is equal (e.g., equal sizes), stop when the row
            # aspect ratio starts getting worse (more elongated than square).
            row_ar_old = _row_ar(sum(row), remaining_total, fixed_dim, box_dim)
            row_ar_new = _row_ar(test_sum, remaining_total, fixed_dim, box_dim)
            if row_ar_new > row_ar_old:
                break
            # Additional heuristic: stop when the row would be too long
            # (more than 2x the fixed dimension), to encourage grid layouts.
            row_dim_new = test_sum / remaining_total * box_dim
            if row_dim_new > fixed_dim * 2:
                break
        row.append(sizes.pop(0))
    return row, sizes


def _row_ar(row_sum, remaining_total, fixed_dim, box_dim):
    """Return the aspect ratio of the entire row."""
    row_dim = row_sum / remaining_total * box_dim
    if row_dim <= 0 or fixed_dim <= 0:
        return float('inf')
    return max(row_dim / fixed_dim, fixed_dim / row_dim)


def _worst_ar(row, row_sum, fixed_dim, box_dim, remaining_total):
    """Return the worst (max) aspect ratio for items in a row."""
    worst = 0.0
    for s in row:
        item_dim = s / remaining_total * box_dim
        if item_dim <= 0 or fixed_dim <= 0:
            continue
        ar = max(item_dim / fixed_dim, fixed_dim / item_dim)
        worst = max(worst, ar)
    return worst


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

    sizes = [c.size for c in children]
    rects = squarify(sizes, x, y, w, h)

    for child, rect in zip(children, rects):
        if rect is None:
            continue
        rx, ry, rw, rh = rect
        if rw < min_px or rh < min_px:
            continue
        result.append((child, (rx, ry, rw, rh), depth))

    for child, rect in zip(children, rects):
        if rect is None:
            continue
        rx, ry, rw, rh = rect
        if child.is_dir and rw > 2 * min_px and rh > 2 * min_px:
            result.extend(
                layout(child, rx + 1, ry + 1, rw - 2, rh - 2, min_px, depth + 1)
            )

    return result
