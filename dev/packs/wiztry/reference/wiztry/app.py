"""WizTry GUI application - tkinter window with treemap, tree view and file-type list."""

import os
import threading
import tkinter as tk
import tkinter.filedialog
from tkinter import ttk

from wiztry.scanner import Node, clean_root, scan
from wiztry.filetypes import OTHER, PALETTE, color_map, ext_rows, human
from wiztry.treemap import layout


def bar(pct):
    """Return a 10-cell progress bar string for a percentage value."""
    full = int(round(pct / 10))
    full = max(0, min(10, full))
    light = 10 - full
    return "\u2588" * full + "\u2591" * light + " " + f"{pct:5.1f}%"


def shade(color, k):
    """Darken (k < 1) or lighten (k > 1) a hex color string."""
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    if k < 1:
        r = int(r * k)
        g = int(g * k)
        b = int(b * k)
    else:
        r = int(r + (255 - r) * (k - 1))
        g = int(g + (255 - g) * (k - 1))
        b = int(b + (255 - b) * (k - 1))
    r = min(255, max(0, r))
    g = min(255, max(0, g))
    b = min(255, max(0, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _timed_scan(root, progress=None, cancel=None):
    """Scan root and return (top, skipped, elapsed_seconds)."""
    import time
    start = time.perf_counter()
    top, skipped = scan(root, progress, cancel)
    elapsed = time.perf_counter() - start
    return top, skipped, elapsed


class App(tk.Tk):
    """Main WizTry application window."""

    def __init__(self, start_path=""):
        super().__init__()
        self.title("WizTry")
        self.geometry("1200x800")

        self.busy = False
        self.top = None
        self.view = None
        self.nodes = {}
        self.blocks = {}
        self.colors = {}
        self.scan_result = None
        self.scan_secs = 0.0

        default_path = os.environ.get("SystemDrive", "C:") + "\\"
        self.path_var = tk.StringVar(value=default_path if not start_path else start_path)
        self.status = tk.StringVar()

        self._build_toolbar()
        self._build_panes()

        self._resize_id = None

    def _build_toolbar(self):
        """Create the toolbar frame with path entry and buttons."""
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)

        ttk.Entry(toolbar, textvariable=self.path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        ttk.Button(toolbar, text="Browse...", command=self.browse).pack(side=tk.LEFT, padx=(0, 4))

        self.scan_btn = ttk.Button(toolbar, text="Scan", command=self._on_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(toolbar, text="Top", command=self.zoom_top).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Label(toolbar, textvariable=self.status).pack(side=tk.LEFT, padx=(4, 0))

    def _build_panes(self):
        """Create the vertical PanedWindow with tree, types and canvas."""
        self._pw = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self._pw.pack(fill=tk.BOTH, expand=True)

        self._hp = ttk.PanedWindow(self._pw, orient=tk.HORIZONTAL)
        self._pw.add(self._hp, weight=1)

        tree_frame = ttk.Frame(self._hp)
        self._hp.add(tree_frame, weight=3)

        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("pct", "size", "items", "files", "folders", "modified"),
            yscrollcommand=tree_scroll.set,
            selectmode="extended",
        )
        self.tree.heading("#0", text="Name")
        for col, txt in zip(self.tree["columns"], ("% of Parent", "Size", "Items", "Files", "Folders", "Modified")):
            self.tree.heading(col, text=txt)
        self.tree.column("#0", width=180)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree_scroll.config(command=self.tree.yview)

        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)

        types_frame = ttk.Frame(self._hp)
        self._hp.add(types_frame, weight=1)

        types_scroll = ttk.Scrollbar(types_frame)
        types_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.types = ttk.Treeview(
            types_frame,
            columns=("size", "pct", "files"),
            yscrollcommand=types_scroll.set,
        )
        self.types.heading("#0", text="Extension")
        self.types.heading("size", text="Size")
        self.types.heading("pct", text="%")
        self.types.heading("files", text="Files")
        self.types.column("#0", width=100)
        self.types.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        types_scroll.config(command=self.types.yview)

        canvas_frame = ttk.Frame(self._pw)
        self._pw.add(canvas_frame, weight=3)

        self.canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        self._tooltip_label = None

        self.bind("<Configure>", self._on_resize)

    def browse(self):
        """Open a folder selection dialog and start scanning the chosen folder."""
        path = tk.filedialog.askdirectory(parent=self)
        if path == "":
            return
        cleaned = clean_root(path)
        self.path_var.set(cleaned)
        self.start_scan(cleaned)

    def _on_scan(self):
        """Queue a scan of the path in the entry."""
        path = clean_root(self.path_var.get())
        if not path:
            self.status.set("Type a folder or press Browse... first")
            return
        if not os.path.isdir(path):
            self.status.set(f"Folder not found: {path}")
            return
        self.path_var.set(path)
        self.start_scan(path)

    def start_scan(self, path):
        """Start scanning *path* in a background thread."""
        if self.busy:
            return
        self.busy = True
        self.scan_btn.config(state="disabled")
        self.status.set("Scanning...")
        self.canvas.delete("all")
        self.blocks = {}
        self.tree.delete(*self.tree.get_children())
        self.scan_result = None
        self.scan_secs = 0.0
        self.scan_count = 0

        def progress(n):
            self.scan_count = n

        def _worker():
            top, skipped, secs = _timed_scan(path, progress)
            from wiztry.scanner import summary
            by_ext = summary(top)["by_ext"]
            self.scan_result = (top, skipped, secs, by_ext)

        threading.Thread(target=_worker, daemon=True).start()
        self._poll_scan()

    def _poll_scan(self):
        """Poll for scan completion and update the UI."""
        if self.scan_result is None:
            if self.scan_count > 0:
                self.status.set(f"Scanning... {self.scan_count:,} files")
            self.after(10, self._poll_scan)
            return

        top, skipped, secs, by_ext = self.scan_result
        self.scan_result = None
        self.busy = False
        self.scan_btn.config(state="normal")
        self.scan_secs = secs

        self.show_result(top, skipped, secs, by_ext)

    def show_result(self, top, skipped, secs, by_ext):
        """Display scan results on the main thread from a tree built in memory."""
        self.top = top
        self.view = top
        self.nodes = {}
        self.tree.delete(*self.tree.get_children())

        self.colors = color_map(by_ext)

        self._fill_tree(top)
        self._fill_types(by_ext)
        self.draw_treemap()

        total_files = top.files
        total_folders = top.folders
        total_size = top.size
        self.status.set(f"{total_files:,} files, {total_folders:,} folders, {human(total_size)} in {secs:.1f} s")

    def _fill_tree(self, parent):
        """Fill tree rows for all children of *parent* node."""
        if parent is None:
            return

        # Show top-level root row
        if parent is self.top and not self.tree.get_children():
            item = self.tree.insert("", tk.END, text=parent.name, open=True, values=self._row_values(parent))
            self.nodes[item] = parent
            for child in parent.children:
                self._insert_tree_item(item, child)
        else:
            for child in parent.children:
                item = self.tree.insert(parent, tk.END, text=child.name, open=False, values=self._row_values(child))
                self.nodes[item] = child

    def _insert_tree_item(self, parent, node):
        """Insert a single tree item for *node* under *parent*."""
        item = self.tree.insert(parent, tk.END, text=node.name, open=False, values=self._row_values(node))
        self.nodes[item] = node

    def _row_values(self, node):
        """Return the tuple of column values for *node*."""
        total = self.top.size if self.top else 1
        pct = (node.size / total * 100) if total else 0.0
        items_count = node.files + node.folders
        modified = ""
        if node.mtime:
            import datetime
            dt = datetime.datetime.fromtimestamp(node.mtime)
            modified = dt.strftime("%Y-%m-%d %H:%M")
        return (f"{pct:.1f}%", human(node.size), str(items_count), str(node.files),
                str(node.folders) if node.is_dir else "", modified)

    def _fill_types(self, by_ext):
        """Fill the file-types tree with rows sorted by size descending."""
        self.types.delete(*self.types.get_children())
        self.swatches = []
        rows = ext_rows(by_ext)
        self.colors = color_map(by_ext)
        for row in rows:
            ext = row["ext"]
            size = row["size"]
            pct = row["pct"]
            files = row["files"]
            color = row["color"]

            # Create a 12x12 color swatch image
            img = tk.PhotoImage(width=12, height=12)
            img.put(color, (0, 0, 12, 12))
            self.swatches.append(img)

            item = self.types.insert("", tk.END, text=f" {ext}", values=(human(size), f"{pct:.1f}%", str(files)))
            self.types.set(item, "size", human(size))
            self.types.set(item, "pct", f"{pct:.1f}")
            self.types.set(item, "files", str(files))
            self.types.item(item, image=img)
            self.types.image = img

    def draw_treemap(self):
        """Clear the canvas and draw the squarified treemap for self.view."""
        self.canvas.delete("all")
        self.blocks = {}

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            cw, ch = 800, 300

        if self.view is None:
            return

        MAX_BLOCKS = 8000
        blocks = layout(self.view, 0, 0, cw, ch)

        # Cap file blocks at MAX_BLOCKS by keeping the largest area ones
        if len(blocks) > MAX_BLOCKS:
            folder_blocks = [b for b in blocks if b[0].is_dir]
            file_blocks = [b for b in blocks if not b[0].is_dir]
            # Keep MAX_BLOCKS largest file blocks by area
            file_blocks.sort(key=lambda b: b[1][2] * b[1][3], reverse=True)
            file_blocks = file_blocks[:MAX_BLOCKS]
            blocks = folder_blocks + file_blocks

        # Separate folders and files
        folder_items = [(d, child, rect) for child, rect, d in blocks if child.is_dir]
        file_items = [(d, child, rect) for child, rect, d in blocks if not child.is_dir]

        # Draw folder gray fills first (so small files leave gray, not white)
        for depth, child, (rx, ry, rw, rh) in folder_items:
            self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill="#c8c8c8", outline="")

        # Draw files on top
        for depth, child, (rx, ry, rw, rh) in file_items:
            ext = os.path.splitext(child.name)[1].lower()
            base_color = self.colors.get(ext, OTHER)
            outline = shade(base_color, 0.6)
            rect_item = self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill=base_color, outline=outline)
            self.blocks[rect_item] = child

            # Cushion lines (after the fill, on top)
            if rw > 4 and rh > 4:
                light = shade(base_color, 1.45)
                dark = shade(base_color, 0.75)
                self.canvas.create_line(rx, ry, rx + rw, ry, fill=light)
                self.canvas.create_line(rx, ry, rx, ry + rh, fill=light)
                self.canvas.create_line(rx, ry + rh, rx + rw, ry + rh, fill=dark)
                self.canvas.create_line(rx + rw, ry, rx + rw, ry + rh, fill=dark)

        # Draw folder outlines on top of everything
        for depth, child, (rx, ry, rw, rh) in folder_items:
            self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, outline="#707070", fill="")

    def node_at(self, x, y):
        """Return the Node of the file block at point (x, y), or None."""
        items = self.canvas.find_overlapping(x, y, x, y)
        for item in items:
            if item in self.blocks:
                return self.blocks[item]
        return None

    def tooltip_text_at(self, x, y):
        """Return tooltip text for point (x, y) or empty string."""
        node = self.node_at(x, y)
        if node is None:
            return ""
        return f"{node.path}\n{human(node.size)}"

    def _on_motion(self, event):
        """Show tooltip on mouse motion over the canvas."""
        text = self.tooltip_text_at(event.x, event.y)
        if self._tooltip_label is None or text == "":
            if self._tooltip_label is not None:
                self._tooltip_label.destroy()
                self._tooltip_label = None
            return
        if text:
            if self._tooltip_label is None:
                self._tooltip_label = tk.Label(self, text=text, bg="yellow", relief="solid", borderwidth=1,
                                                 font=("TkDefaultFont", 8))
            self._tooltip_label.place(x=event.x + 15, y=event.y + 15)

    def _on_canvas_click(self, event):
        """Select the node at the click position."""
        node = self.node_at(event.x, event.y)
        if node is not None and not node.is_dir:
            self.select_node(node)

    def select_node(self, node):
        """Open parent rows, select and show the row for *node*, return the item id."""
        # Walk up to find the item ids and build the path
        path_items = []
        current = node
        while current is not None and current.parent is not None:
            parent = current.parent
            # Find the tree item for parent
            parent_iid = None
            for iid, n in self.nodes.items():
                if n is parent:
                    parent_iid = iid
                    break
            if parent_iid is None:
                # Parent not in tree - insert it
                parent_iid = self.tree.insert("", tk.END, text=parent.name, open=False, values=self._row_values(parent))
                self.nodes[parent_iid] = parent
            path_items.append((parent_iid, current))
            current = parent

        # Open parent rows (fill placeholders)
        for parent_iid, child_node in reversed(path_items):
            if not self.tree.item(parent_iid, "open"):
                self._open_placeholder(parent_iid)

        # Find the item for the node itself
        target_iid = None
        for iid, n in self.nodes.items():
            if n is node:
                target_iid = iid
                break

        if target_iid is None:
            # Node not in tree - insert it under its parent
            parent_iid = None
            for iid, n in self.nodes.items():
                if n is node.parent:
                    parent_iid = iid
                    break
            if parent_iid is None:
                return None
            target_iid = self.tree.insert(parent_iid, tk.END, text=node.name, open=False, values=self._row_values(node))
            self.nodes[target_iid] = node

        self.tree.selection_set(target_iid)
        self.tree.see(target_iid)
        self.tree.focus(target_iid)
        return target_iid

    def _open_placeholder(self, item):
        """Open a placeholder folder row by inserting its children."""
        node = self.nodes.get(item)
        if node is None or not node.is_dir:
            return
        if node.children:
            self.tree.item(item, open=True)
            for child in node.children:
                found = False
                for kid in self.tree.get_children(item):
                    if self.nodes.get(kid) is child:
                        found = True
                        break
                if not found:
                    kid = self.tree.insert(item, tk.END, text=child.name, open=False,
                                           values=self._row_values(child))
                    self.nodes[kid] = child
            self.tree.item(item, open=True)

    def zoom(self, node):
        """Zoom the treemap to show *node*'s children."""
        self.view = node
        self.canvas.delete("all")
        self.blocks = {}
        self.draw_treemap()

    def zoom_top(self):
        """Zoom back to the root view."""
        if self.top is not None:
            self.view = self.top
            self.canvas.delete("all")
            self.blocks = {}
            self.draw_treemap()

    def _on_tree_open(self, event):
        """Handle tree expansion: fill in children for a folder."""
        item = self.tree.focus()
        node = self.nodes.get(item)
        if node is None or not node.is_dir:
            return
        if self.tree.item(item, "open"):
            return
        # Insert children
        for child in node.children:
            kid = self.tree.insert(item, tk.END, text=child.name, open=False, values=self._row_values(child))
            self.nodes[kid] = child
        self.tree.item(item, open=True)

    def _on_tree_select(self, event):
        """Handle tree selection - only for folders."""
        pass

    def _on_tree_click(self, event):
        """Handle single click on tree row - only select, don't change view."""
        pass

    def _on_tree_release(self, event):
        """Handle release on tree row - keep view on a folder."""
        pass

    def _on_resize(self, event):
        """Debounced window resize handler."""
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(150, self._do_resize)

    def _do_resize(self):
        """Actually redraw on resize."""
        self._resize_id = None
        if self.view is not None:
            self.draw_treemap()


def main():
    """Entry point: create and run the App."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
