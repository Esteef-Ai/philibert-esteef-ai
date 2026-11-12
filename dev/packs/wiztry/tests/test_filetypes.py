"""T03: sizes read like WizTree's, and each file type has its own color."""
from _t import EXPECTED, check, finish

try:
    from wiztry.filetypes import OTHER, PALETTE, color_map, ext_rows, human
except Exception as e:                                  # noqa: BLE001
    check("wiztry.filetypes imports", False, e)
    finish()

for n, want in ((0, "0 bytes"), (512, "512 bytes"), (1536, "1.5 KB"), (10 * 1024 ** 2, "10.0 MB"),
                (int(2.5 * 1024 ** 3), "2.5 GB"), (3 * 1024 ** 4, "3.0 TB"), (5000 * 1024 ** 4, "5000.0 TB")):
    check(f"human({n})", human(n) == want, human(n))
check("20 colors, all different", len(PALETTE) == 20 and len(set(PALETTE)) == 20 and OTHER not in PALETTE)
rows = ext_rows(EXPECTED["by_ext"])
check("one row per extension", len(rows) == len(EXPECTED["by_ext"]), len(rows))
check("largest first", [r["size"] for r in rows] == sorted((r["size"] for r in rows), reverse=True))
check("first is .cr2", rows[0]["ext"] == ".cr2" and rows[0]["files"] == 3, rows[0])
check("shares add up to 100", abs(sum(r["pct"] for r in rows) - 100) < 0.01)
check("each row has ext, size, files, pct and color", all(set(r) == {"ext", "size", "files", "pct", "color"} for r in rows))
many = {f".e{i:02}": {"size": 1000 - i, "files": 1} for i in range(25)}
mr = ext_rows(many)
check("the top 20 get the palette in order", [r["color"] for r in mr[:20]] == PALETTE)
check("the rest are gray", all(r["color"] == OTHER for r in mr[20:]))
check("ties are broken by name", [r["ext"] for r in ext_rows({".b": {"size": 5, "files": 1}, ".a": {"size": 5, "files": 1}})] == [".a", ".b"])
check("color_map matches the rows", color_map(many) == {r["ext"]: r["color"] for r in mr})
check("no files gives no rows", ext_rows({}) == [])
finish()
