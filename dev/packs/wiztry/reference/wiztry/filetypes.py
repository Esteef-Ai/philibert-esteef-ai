"""File-type helpers: human-readable sizes, per-extension rows and colors."""

PALETTE: list[str] = [
    "#E63946", "#F1FAEE", "#A8DADC", "#457B9D", "#1D3557",
    "#F4A261", "#2A9D8F", "#264653", "#E76F51", "#606C38",
    "#283618", "#DDA15E", "#BC6C25", "#6D6875", "#B5838D",
    "#6D597A", "#2B624A", "#B07D65", "#588157", "#3A5A61",
]
OTHER: str = "#a0a0a0"


def human(n: int) -> str:
    """Return a human-readable size string like '1.5 KB' or '5000.0 TB'."""
    if n < 1024:
        return f"{n} bytes"
    for unit in ("KB", "MB", "GB", "TB"):
        n = n / 1024
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def ext_rows(by_ext: dict) -> list[dict]:
    """Return sorted list of {ext, size, files, pct, color} rows from by_ext."""
    total = sum(v["size"] for v in by_ext.values())
    rows = sorted(by_ext.items(), key=lambda kv: (-kv[1]["size"], kv[0]))
    result: list[dict] = []
    for i, (ext, info) in enumerate(rows):
        pct = (info["size"] / total * 100) if total else 0.0
        color = PALETTE[i] if i < 20 else OTHER
        result.append({
            "ext": ext,
            "size": info["size"],
            "files": info["files"],
            "pct": pct,
            "color": color,
        })
    return result


def color_map(by_ext: dict) -> dict:
    """Return {ext: color} mapping as assigned by ext_rows."""
    rows = ext_rows(by_ext)
    return {r["ext"]: r["color"] for r in rows}
