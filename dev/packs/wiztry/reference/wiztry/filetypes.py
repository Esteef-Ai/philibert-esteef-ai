"""T03: human-readable sizes and per-extension colors for the type list."""
from __future__ import annotations

PALETTE = [
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
    "#a65628", "#f781bf", "#999999", "#66c2a5", "#fc8d62",
    "#8da0cb", "#e78ac3", "#66a61e", "#e6ab02", "#a6761d",
    "#009bbb", "#4d4d4d", "#1b9e77", "#d95f02", "#7570b3",
]
OTHER = "#a0a0a0"

_UNITS = [
    (1024 ** 4, "TB"),
    (1024 ** 3, "GB"),
    (1024 ** 2, "MB"),
    (1024, "KB"),
]


def human(n: int) -> str:
    """Size in bytes as a short string, e.g. "1.5 KB" or "5000.0 TB"."""
    if n < 1024:
        return f"{n} bytes"
    for div, name in _UNITS:
        if n >= div:
            return f"{n / div:.1f} {name}"
    return f"{n} bytes"


def _rows(by_ext: dict) -> list[dict]:
    total = sum(d["size"] for d in by_ext.values())
    ordered = sorted(by_ext.items(), key=lambda kv: (-kv[1]["size"], kv[0]))
    rows = []
    for i, (ext, d) in enumerate(ordered):
        pct = (d["size"] / total * 100) if total else 0.0
        rows.append({
            "ext": ext,
            "size": d["size"],
            "files": d["files"],
            "pct": pct,
            "color": PALETTE[i] if i < len(PALETTE) else OTHER,
        })
    return rows


def ext_rows(by_ext: dict) -> list[dict]:
    """Rows for the type list: one dict per extension, largest first, with a color."""
    if not by_ext:
        return []
    return _rows(by_ext)


def color_map(by_ext: dict) -> dict:
    """{ext: color} exactly as ext_rows assigns them."""
    return {r["ext"]: r["color"] for r in ext_rows(by_ext)}
