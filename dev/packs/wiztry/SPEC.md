# WizTry - the spec

A portable Windows disk space analyzer, a simplified clone of WizTree (diskanalyzer.com).
It is read-only: it never deletes, moves, renames or writes any file it scans. No admin rights.

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
