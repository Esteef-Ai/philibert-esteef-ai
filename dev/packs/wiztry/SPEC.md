# WizTry - the spec

A portable Windows disk space analyzer, a simplified clone of WizTree (diskanalyzer.com).
Scanning is read-only: it never deletes, moves, renames or writes any file it scans. The one thing that changes the disk is Delete in the right-click menu: it asks first and moves the item to the Recycle Bin. No admin rights.

## Tech (fixed)
- Python 3.11 with tkinter/ttk; standard library only in the app itself.
- PyInstaller only for packaging: `build.bat` makes one file, `dist\WizTry.exe`, that runs with no Python installed.

## Speed is the main feature
The scan is as fast as plain Python goes without admin rights: `os.scandir` with an explicit stack (not
`os.walk`), and the size Windows already returns in the directory listing (`DirEntry.stat`).

## What it does
1. Toolbar: a folder path box, Browse, Scan, Top, and a status line ("Scanning... 12,345 files" while it
   runs, then "1,234,567 files, 1,234 folders, 45.6 GB in 3.2 s").
2. The scan runs in a background thread; only the main thread touches tkinter. Folders it cannot read are
   skipped and counted. Junctions and symlinks are neither followed nor counted.
3. Tree View (top left): folders and files, largest first. Columns: Name | % of Parent (a text bar and the
   number) | Size | Items | Files | Folders | Modified. Folders fill in when opened.
4. File Types (top right): color swatch | Extension | Size | % | Files, largest first. The biggest 20 types
   get their own colors; the rest share one gray.
5. Treemap (bottom): every file a rectangle sized by its bytes, squarified layout, nested in its folders,
   colored by extension with cushion shading. Hover shows path and size. Clicking a block selects the file
   in the tree. Double-clicking a folder in the tree shows just that folder; Top goes back. Redraws on resize.
6. Look: light Windows look like WizTree: white panes, thin gray borders, light blue selection, splitters.
7. Command line: `WizTry.exe --scan <folder> --json <file>` scans with no window and writes JSON: root,
   total_size, files, folders (not counting the root), skipped, seconds, by_ext ({".mp3": {"size", "files"}},
   lower-case with the dot, "(none)" for no extension) and top_level ([{"name", "size", "files", "folders"}]
   for each entry directly inside the root, largest first; a folder's numbers cover everything inside it).

## Done means
- Every test in `tests\` passes, including the exe built by `build.bat`.
- The report for the fixture folder equals `tests\expected.json`.
- The window opens, scans, and fills the tree, the file types list and the treemap.

## Tree and tools (added 2026-11-12)
- The folder tree always starts at the scanned folder. Every folder with something in it can be opened, level by level. Clicking a block in the treemap opens every folder on the way to that file, selects it and scrolls to it. Double-clicking a folder row zooms the treemap into it.
- Right-click on a tree row or a treemap block: Show in Explorer, Copy path, Delete (Recycle Bin)... The Delete key does the same as Delete. Delete asks first, refuses the scanned folder itself, drives and anything outside the scanned folder, and afterwards the tree, the file types and the treemap show the new sizes without a new scan.
- Export... in the toolbar writes the tree as a CSV file: Path, Type, Size, Files, Folders, Modified.

## Look (added 2026-11-12)
- Dark, in the house colors: navy surfaces (#0f172a window, #0a1120 bars and treemap background, #111d36 lists), one accent (cyan #00e5ff) used sparingly, pink #ff2e88 kept for rare marks. Every color has a name in `wiztry/theme.py`; no color is written anywhere else.
- A toolbar across the top with the name WIZTRY, the path box and the buttons; a status bar across the bottom; a small title above each pane (TREE VIEW, FILE TYPES, TREEMAP); number columns right-aligned.
- Before a scan the treemap says what to do; while scanning it says Scanning...; hovering a block shows its path and size.
- File types use a palette of 20 colors that can be told apart on the dark background; folders are a dark fill with a gray outline.
