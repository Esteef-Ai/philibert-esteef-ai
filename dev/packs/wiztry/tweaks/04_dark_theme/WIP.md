# Tweak 04_dark_theme: NOT FINISHED (stopped 2026-11-12, usage limit)

Do not apply this tweak yet: there is no tweak.json, and nothing here has been proven on a scratch copy.

## Done
- Style research (the owner's vault): Philibert Setup look = navy #0f172a, deep #0a1120, panel #111d36,
  raise #162544, line #1e3054, text #d7e3f4, dim #8ea3c4, faint #6f86a8, ONE accent cyan #00e5ff, pink #ff2e88
  as the rare second; Coma Toast / Daily Bread = near-black #121214 with the same cyan and pink (+ lime, yellow);
  house rules (NeuralDock - UI House Style): one surface, one accent used sparingly, three type roles, 8 px
  spacing, real app chrome, visible empty / loading / error / disabled states. The owner likes dark themes.
- tests/test_trash_sure.py (T14) and tests/test_theme.py (T15) are written, NOT yet run against a reference.
- Palette checked by calculation (contrast >= 3 on #0a1120, Lab distance >= 20 between any two):
  #38bdf8 #f472b6 #a3e635 #fbbf24 #a78bfa #34d399 #fb923c #3b82f6 #f87171 #2dd4bf
  #e879f9 #c2410c #94a3b8 #16a34a #fda4af #0e7490 #be185d #d4a373 #7c3aed #fef08a ; OTHER #4b5a78 ;
  SELECT #0d4f68 with white text; FOLDER_LINE stays #707070 (tests/test_app.py checks that literal).

## Planned tasks
- T14 (wiztry/actions.py): the Windows call moves into _recycle(path) -> result code; trash() raises OSError
  when the code is not 0 or the item is "still there" afterwards; fAnyOperationsAborted becomes wintypes.BOOL.
- T15 (wiztry/theme.py, wiztry/filetypes.py): the named colors, PALETTE/OTHER (filetypes imports them), fonts
  (Segoe UI, Segoe UI bold for the brand, Consolas; system fonts only), apply(root) with the clam theme and the
  styles test_theme.py lists (incl. Bar.*, Brand.TLabel, Title.TLabel), dark_title_bar(root) via
  DwmSetWindowAttribute(hwnd, 20, 1).
- T16 (wiztry/app.py): the window wears the theme. Toolbar as a DEEP bar with a "WIZTRY" brand label; the status
  line moves to a bar at the bottom; small pane titles "TREE VIEW" / "FILE TYPES"; number columns right-aligned;
  canvas, tooltip and right-click menu in theme colors; folder fill theme.FOLDER_FILL; an empty state on the
  canvas before the first scan ("Pick a folder, then press Scan") and "Scanning..." while it runs.
  Its test (tests/test_look.py) is NOT written: walk every widget and require a dark background, check the
  bars' positions, the brand label, the anchors, the canvas text states and the block fill colors.

## Still to do, in order
1. Write tests/test_look.py.
2. Write a reference solution for T14, T15, T16 on a scratch clone of C:\PCodeTest\wiztry11 and prove each
   task ALONE, in order, with every older test still passing (and the exe build at the end).
3. Write tweak.json (tasks, briefs, "tests"); add "tests_update" support to studio_pack.py tweak so the
   workspace gets the pack's tests/test_window_big.py (its freeze limit is 2.5 s in the pack, 1.5 s in the
   workspace).
4. Apply to wiztry11; the owner launches the build and looks at the exe: looks cannot be judged by tests.
