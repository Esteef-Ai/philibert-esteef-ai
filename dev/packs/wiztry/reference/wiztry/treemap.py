"""T02: pure squarified treemap layout and recursive node layout."""
from wiztry.scanner import Node


def squarify(sizes: list[int | float], x: int | float, y: int | float,
             w: int | float, h: int | float) -> list[tuple[float, float, float, float] | None]:
    """Squarify sizes into (x, y, w, h) rectangles inside the box (x, y, w, h)."""
    if not sizes:
        return []
    if w <= 0 or h <= 0:
        return [None for _ in sizes]

    total = sum(sizes)
    if total <= 0:
        return [None for _ in sizes]

    # Compute target areas for non-zero sizes
    areas: list[float] = []
    for s in sizes:
        if s > 0:
            areas.append(s / total * w * h)

    if not areas:
        return [None for _ in sizes]

    def _worst(row: list[float], pw: float, ph: float) -> float:
        """Worst aspect ratio among rectangles in a row."""
        s = sum(row)
        if s <= 0 or pw <= 0 or ph <= 0:
            return float('inf')
        if pw >= ph:
            # horizontal: row spreads along width
            row_h = s / pw
            if row_h <= 0:
                return float('inf')
            # widths = area_i / row_h
            max_ar = 0.0
            for a in row:
                row_w = a / row_h
                ar = max(row_w / row_h, row_h / row_w)
                if ar > max_ar:
                    max_ar = ar
            return max_ar
        else:
            # vertical: row spreads along height
            row_w = s / ph
            if row_w <= 0:
                return float('inf')
            max_ar = 0.0
            for a in row:
                row_h = a / row_w
                ar = max(row_w / row_h, row_h / row_w)
                if ar > max_ar:
                    max_ar = ar
            return max_ar

    def _squarify(areas_list: list[float], px: float, py: float, pw: float, ph: float) -> list[tuple[float, float, float, float]]:
        """Core squarified algorithm."""
        if not areas_list or pw <= 0 or ph <= 0:
            return []

        result: list[tuple[float, float, float, float]] = []
        current: list[float] = []

        for i, area in enumerate(areas_list):
            current.append(area)
            # Check if removing the last item would improve worst aspect
            if len(current) > 1:
                prev = current[:-1]
                w_prev = _worst(prev, pw, ph)
                w_cur = _worst(current, pw, ph)
                if w_cur > w_prev:
                    # Lay out prev as a row
                    result.extend(_lay_row(prev, px, py, pw, ph))
                    # Recurse with remaining (from index i onward)
                    remaining = areas_list[i:]
                    if pw >= ph:
                        row_h = sum(prev) / pw
                        result.extend(_squarify(remaining, px, py + row_h, pw, ph - row_h))
                    else:
                        row_w = sum(prev) / ph
                        result.extend(_squarify(remaining, px + row_w, py, pw - row_w, ph))
                    return result
            # else: keep accumulating

        # All remaining items fit in one row
        result.extend(_lay_row(current, px, py, pw, ph))
        return result

    def _lay_row(row: list[float], px: float, py: float, pw: float, ph: float) -> list[tuple[float, float, float, float]]:
        """Lay out a single row of rectangles."""
        result: list[tuple[float, float, float, float]] = []
        row_total = sum(row)
        if pw >= ph:
            # horizontal: spread along width
            row_h = row_total / pw if pw > 0 else 0
            if row_h <= 0:
                return result
            cur_x = px
            for area in row:
                row_w = area / row_h
                result.append((cur_x, py, row_w, row_h))
                cur_x += row_w
        else:
            # vertical: spread along height
            row_w = row_total / ph if ph > 0 else 0
            if row_w <= 0:
                return result
            cur_y = py
            for area in row:
                row_h = area / row_w
                result.append((px, cur_y, row_w, row_h))
                cur_y += row_h
        return result

    laid = _squarify(areas, x, y, w, h)

    # Merge with None entries for zero sizes
    out: list[tuple[float, float, float, float] | None] = []
    lay_idx = 0
    for s in sizes:
        if s <= 0:
            out.append(None)
        else:
            out.append(laid[lay_idx])
            lay_idx += 1

    return out


def layout(node: Node, x: int | float, y: int | float, w: int | float, h: int | float,
           min_px: int = 3, depth: int = 0) -> list[tuple[Node, tuple[float, float, float, float], int]]:
    """Lay out children of a node recursively, returning (node, rect, depth) triples."""
    result: list[tuple[Node, tuple[float, float, float, float], int]] = []

    # Lay out children
    valid_children = [c for c in node.children if c.size > 0]

    if valid_children:
        sizes = [c.size for c in valid_children]
        rects = squarify(sizes, x, y, w, h)

        for child, rect in zip(valid_children, rects):
            if rect is not None and rect[2] >= min_px and rect[3] >= min_px:
                result.append((child, rect, depth))
            # If this child is a folder, recurse into it
            if child.is_dir and rect is not None:
                if rect[2] > 2 * min_px and rect[3] > 2 * min_px:
                    inner_x = rect[0] + 1
                    inner_y = rect[1] + 1
                    inner_w = rect[2] - 2
                    inner_h = rect[3] - 2
                    result.extend(layout(child, inner_x, inner_y, inner_w, inner_h, min_px, depth + 1))
                elif rect[2] >= min_px and rect[3] >= min_px:
                    result.extend(layout(child, rect[0], rect[1], rect[2], rect[3], min_px, depth + 1))

    return result
