"""Render the approved icon SVGs to PNG (Edge headless) and pack Windows .ico files.
python make_icons.py  ->  round3/final/{philibert,retrovault}-{16..256}.png + .ico"""
import subprocess, tempfile, os
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
FINAL = HERE / "final"; FINAL.mkdir(exist_ok=True)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SIZES = [16, 24, 32, 48, 64, 128, 256]

def render(svg: Path, px: int, out: Path):
    # transparent page, the SVG drawn at exactly px x px (big renders are downscaled for sharp small sizes)
    big = max(px, 256) * 2
    html = Path(tempfile.gettempdir()) / f"icon_{svg.stem}.html"
    html.write_text(f"<html><body style='margin:0;background:transparent'><img src='{svg.as_uri()}' "
                    f"width='{big}' height='{big}' style='display:block'></body></html>", encoding="utf-8")
    shot = Path(tempfile.gettempdir()) / f"icon_{svg.stem}_{big}.png"
    if not shot.exists():
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000",
                        f"--user-data-dir={tempfile.gettempdir()}\\edgeIcons", f"--window-size={big},{big}",
                        f"--screenshot={shot}", html.as_uri()], capture_output=True, timeout=60)
    im = Image.open(shot).convert("RGBA").resize((px, px), Image.LANCZOS)
    im.save(out)
    return im

for name in ("philibert-icon", "retrovault-icon"):
    svg = HERE / f"{name}.svg"
    short = name.replace("-icon", "")
    ims = [render(svg, s, FINAL / f"{short}-{s}.png") for s in SIZES]
    ims[-1].save(FINAL / f"{short}.ico", sizes=[(s, s) for s in SIZES], append_images=ims[:-1])
    print(short, "->", FINAL / f"{short}.ico", os.path.getsize(FINAL / f"{short}.ico"), "bytes")
