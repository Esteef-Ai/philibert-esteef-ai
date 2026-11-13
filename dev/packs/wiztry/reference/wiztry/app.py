"""WizTry GUI application - tkinter window with treemap, tree view and file-type list."""

import os
import threading
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import wiztry.actions as actions
import wiztry.theme as theme
from tkinter import ttk

from wiztry.scanner import Node, clean_root, scan, summary, ext_of
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
        self.status = tk.StringVar(value="Ready")

        theme.apply(self)
        self._build_toolbar()
        self._build_status_bar()
        self._build_panes()
        theme.dark_title_bar(self)

        self.menu = tk.Menu(self, tearoff=0, bg=theme.RAISE, fg=theme.TEXT,
                            activebackground=theme.SELECT, activeforeground=theme.SELECT_TEXT,
                            bd=0, relief="flat")
        self.menu.add_command(label="Show in Explorer", command=self.show_in_explorer)
        self.menu.add_command(label="Copy path", command=self.copy_path)
        self.menu.add_command(label="Delete (Recycle Bin)...", command=self.delete_selected)

        self._resize_id = None
        self._tooltip_label = None
        self.swatches = []

        self.show_hint("Pick a folder, then press Scan")

    def _build_toolbar(self):
        """Create the toolbar frame with path entry and buttons."""
        toolbar = ttk.Frame(self, style="Bar.TFrame", padding=(12, 8))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(toolbar, text="WIZTRY", style="Brand.TLabel").pack(side=tk.LEFT, padx=(0, 8))

        ttk.Entry(toolbar, textvariable=self.path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        ttk.Button(toolbar, text="Browse...", command=self.browse).pack(side=tk.LEFT, padx=(0, 8))

        self.scan_btn = ttk.Button(toolbar, text="Scan", command=self._on_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(toolbar, text="Top", command=self.zoom_top).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(toolbar, text="Export...", command=self.export).pack(side=tk.LEFT, padx=(0, 8))

    def _build_status_bar(self):
        """Create the status bar frame at the bottom of the window."""
        status_bar = ttk.Frame(self, style="Bar.TFrame", padding=(12, 4))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status, style="Bar.TLabel").pack(side=tk.LEFT)

    def _build_panes(self):
        """Create the vertical PanedWindow with tree, types and canvas."""
        self._pw = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self._pw.pack(fill=tk.BOTH, expand=True)

        self._hp = ttk.PanedWindow(self._pw, orient=tk.HORIZONTAL)
        self._pw.add(self._hp, weight=1)

        tree_frame = ttk.Frame(self._hp)
        self._hp.add(tree_frame, weight=3)

        ttk.Label(tree_frame, text="TREE VIEW", style="Title.TLabel").pack(side=tk.TOP, anchor="w", padx=8, pady=(8, 4))

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
        for c in ("#0", "pct", "modified"):
            self.tree.column(c, anchor="w")
        for c in ("size", "items", "files", "folders"):
            self.tree.column(c, anchor="e")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree_scroll.config(command=self.tree.yview)

        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.tree.bind("<Delete>", self._on_delete_key)

        types_frame = ttk.Frame(self._hp)
        self._hp.add(types_frame, weight=1)

        ttk.Label(types_frame, text="FILE TYPES", style="Title.TLabel").pack(side=tk.TOP, anchor="w", padx=8, pady=(8, 4))

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
        self.types.column("#0", anchor="w")
        for c in ("size", "pct", "files"):
            self.types.column(c, anchor="e")
        self.types.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        types_scroll.config(command=self.types.yview)

        canvas_frame = ttk.Frame(self._pw)
        self._pw.add(canvas_frame, weight=3)

        ttk.Label(canvas_frame, text="TREEMAP", style="Title.TLabel").pack(side=tk.TOP, anchor="w", padx=8, pady=(8, 4))

        self.canvas = tk.Canvas(canvas_frame, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<Leave>", self._on_canvas_leave)

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
        self.show_hint("Scanning...")
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
        self.by_ext = by_ext
        self.tree.delete(*self.tree.get_children())

        self.colors = color_map(by_ext)

        self._fill_tree(top)
        self._fill_types(by_ext)
        self.draw_treemap()

        total_files = top.files
        total_folders = top.folders
        total_size = top.size
        self.status.set(f"{total_files:,} files, {total_folders:,} folders, {human(total_size)} in {secs:.1f} s")

    def _add_row(self, parent_iid, node):
        """Insert one row for *node* under *parent_iid*. Returns the row id."""
        item = self.tree.insert(parent_iid, tk.END, text=node.name, open=False, values=self._row_values(node))
        self.nodes[item] = node
        self.items[id(node)] = item
        if node.is_dir and node.children:
            self.tree.insert(item, tk.END, text="")
        return item

    def _fill_row(self, iid):
        """Fill *iid* row's children from its Node. If already filled, return."""
        node = self.nodes.get(iid)
        if node is None or not node.is_dir:
            return
        kids = self.tree.get_children(iid)
        if kids and self.nodes.get(kids[0]) is not None:
            return
        self.tree.delete(*kids)
        for child in node.children:
            self._add_row(iid, child)

    def _fill_tree(self, top):
        """Empty the tree and build the cascade from *top* down."""
        self.tree.delete(*self.tree.get_children())
        self.nodes = {}
        self.items = {}
        root_iid = self._add_row("", top)
        self._fill_row(root_iid)
        self.tree.item(root_iid, open=True)

    def _row_values(self, node):
        """Return the tuple of column values for *node*."""
        parent_size = node.parent.size if node.parent else 1
        pct = (node.size / parent_size * 100) if parent_size else 0.0
        if node.parent is None:
            pct = 100.0
        items_count = node.files + node.folders
        modified = ""
        if node.mtime:
            import datetime
            dt = datetime.datetime.fromtimestamp(node.mtime)
            modified = dt.strftime("%Y-%m-%d %H:%M")
        return (bar(pct), human(node.size), str(items_count), str(node.files),
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

    def show_hint(self, text):
        """Show a centered hint text on the canvas."""
        self.canvas.delete("all")
        self.blocks = {}
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10:
            w = 1
        if h < 10:
            h = 1
        self.canvas.create_text(w / 2, h / 2, text=text,
                                fill=theme.DIM,
                                font=(theme.FONT_UI[0], 12),
                                tags="hint")

    def _on_canvas_configure(self, event):
        """Move the hint text to the center when the canvas is resized."""
        w = event.width
        h = event.height
        if w < 10:
            w = 1
        if h < 10:
            h = 1
        items = self.canvas.find_tagged("hint") if hasattr(self.canvas, 'find_tagged') else self.canvas.find_withtag("hint")
        for item in items:
            if item and self.canvas.type(item) == "text":
                self.canvas.coords(item, w / 2, h / 2)

    def _on_canvas_leave(self, event):
        """Destroy the tooltip when the pointer leaves the canvas."""
        if self._tooltip_label is not None:
            self._tooltip_label.destroy()
            self._tooltip_label = None

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
            self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill=theme.FOLDER_FILL, outline="")

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
            self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, outline=theme.FOLDER_LINE, fill="")

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
        if text == "":
            if self._tooltip_label is not None:
                self._tooltip_label.destroy()
                self._tooltip_label = None
            return
        if self._tooltip_label is None:
            self._tooltip_label = tk.Label(self.canvas, text=text, bg=theme.RAISE, fg=theme.TEXT,
                                             relief="solid", borderwidth=1,
                                             font=(theme.FONT_UI[0], 9), justify="left", padx=6, pady=3)
        self._tooltip_label.place(x=event.x + 16, y=event.y + 16)
        # Pull back inside canvas if it would stick out
        tw = self._tooltip_label.winfo_reqwidth()
        th = self._tooltip_label.winfo_reqheight()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if event.x + 16 + tw > cw:
            self._tooltip_label.place(x=event.x - tw - 16, y=event.y + 16)
        if event.y + 16 + th > ch:
            self._tooltip_label.place(x=event.x + 16, y=event.y - th - 16)

    def _on_canvas_click(self, event):
        """Select the node at the click position."""
        node = self.node_at(event.x, event.y)
        if node is not None and not node.is_dir:
            self.select_node(node)

    def select_node(self, node):
        """Open parent rows, select and show the row for *node*, return the item id."""
        if node is None:
            return None

        # Walk up from node collecting Nodes that have no row yet
        ancestors = []
        current = node
        has_row = None
        while current is not None:
            row = self.items.get(id(current))
            if row is not None:
                has_row = current
                break
            ancestors.append(current)
            current = current.parent

        if current is None:
            return None

        # Going back down, _fill_row each parent
        for anc in reversed(ancestors):
            parent = anc.parent
            if parent is not None:
                parent_row = self.items.get(id(parent))
                if parent_row is not None:
                    self._fill_row(parent_row)

        # Find the row for the node itself
        target_iid = self.items.get(id(node))
        if target_iid is None:
            return None

        # Open every ancestor row of node's row
        row = target_iid
        while row:
            self.tree.item(row, open=True)
            row = self.tree.parent(row)

        self.tree.selection_set(target_iid)
        self.tree.see(target_iid)
        self.tree.focus(target_iid)
        return target_iid

    def _on_tree_open(self, event):
        """Handle tree expansion: fill in children for a folder."""
        self._fill_row(self.tree.focus())

    def zoom_row(self, iid):
        """If *iid* is a folder row, zoom the treemap into its Node."""
        node = self.nodes.get(iid)
        if node is not None and node.is_dir:
            self.zoom(node)

    def _on_tree_double_click(self, event):
        """Handle double-click on a tree row: zoom into the folder."""
        iid = self.tree.identify_row(event.y)
        if iid:
            self.zoom_row(iid)

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

    def _on_tree_right_click(self, event):
        """Handle right-click on the tree: show context menu on the row under the pointer."""
        row = self.tree.identify_row(event.y)
        if row and row in self.nodes:
            self.tree.selection_set(row)
            self.tree.see(row)
            self.tree.focus(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _on_canvas_right_click(self, event):
        """Handle right-click on the treemap canvas: show context menu on the node at the pointer."""
        node = self.node_at(event.x, event.y)
        if node is not None:
            self.select_node(node)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _on_delete_key(self, event):
        """Handle Delete key press in the tree."""
        self.delete_selected()

    def selected_node(self):
        """Return the Node of the first selected tree row, or None."""
        sel = self.tree.selection()
        if not sel:
            return None
        row = sel[0]
        return self.nodes.get(row)

    def copy_path(self):
        """Copy the path of the selected node to the clipboard."""
        node = self.selected_node()
        if node is None:
            return
        self.clipboard_clear()
        self.clipboard_append(node.path)
        self.status.set(f"Copied: {node.path}")

    def show_in_explorer(self):
        """Show the selected node's folder in Explorer."""
        node = self.selected_node()
        if node is None:
            return
        actions.show_in_explorer(node.path)

    def delete_selected(self):
        """Move the selected item to the Recycle Bin. Returns True on success."""
        node = self.selected_node()
        if node is None or self.top is None:
            return False

        why = actions.can_delete(node.path, self.top.path)
        if why:
            self.status.set(f"Cannot delete: {why}")
            return False

        if not tkinter.messagebox.askyesno("WizTry", f"Move this to the Recycle Bin?\n\n{node.path}\n{human(node.size)}", parent=self):
            return False

        try:
            actions.trash(node.path, self.top.path)
        except (OSError, ValueError) as e:
            self.status.set(f"Could not delete: {e}")
            return False

        # (a) Compute what was removed
        if node.is_dir:
            gone = summary(node)["by_ext"]
        else:
            ext = ext_of(node.name)
            gone = {ext: {"size": node.size, "files": 1}}

        # (b) Remember parent and row id, then forget the node
        parent = node.parent
        row_id = self.items.get(id(node))

        actions.forget(node)

        # (c) Remove the row and every child row from self.nodes and self.items
        if row_id:
            stack = [row_id]
            deleted_rows = []
            node_ids_to_remove = []
            while stack:
                rid = stack.pop()
                if rid in self.nodes:
                    del self.nodes[rid]
                # Find and remove the node id that maps to this row
                for nid in list(self.items.keys()):
                    if self.items[nid] == rid:
                        node_ids_to_remove.append(nid)
                        break
                deleted_rows.append(rid)
                kids = self.tree.get_children(rid)
                for child_iid in kids:
                    stack.append(child_iid)
            for nid in node_ids_to_remove:
                del self.items[nid]
            for rid in deleted_rows:
                try:
                    self.tree.delete(rid)
                except tk.TclError:
                    pass

        # (d) Update parent rows up to top, and their child rows' % of Parent
        current = parent
        while current is not None:
            parent_row = self.items.get(id(current))
            if parent_row is not None and parent_row in self.nodes:
                self.tree.item(parent_row, values=self._row_values(current))
                # Also update child rows that are still in self.nodes
                for child_iid in self.tree.get_children(parent_row):
                    if child_iid in self.nodes:
                        child_node = self.nodes[child_iid]
                        self.tree.item(child_iid, values=self._row_values(child_node))
                        # If the child folder now has no children, delete leftover child rows
                        if child_node.is_dir and not child_node.children:
                            leftover = self.tree.get_children(child_iid)
                            for li in leftover:
                                if li in self.nodes:
                                    del self.nodes[li]
                                if li in self.items:
                                    del self.items[li]
                            self.tree.delete(*leftover)
            current = current.parent

        # (e) Subtract gone from self.by_ext, rebuild colors and File Types list
        for ext, info in gone.items():
            if ext in self.by_ext:
                self.by_ext[ext]["size"] -= info["size"]
                self.by_ext[ext]["files"] -= info["files"]
                if self.by_ext[ext]["files"] <= 0:
                    del self.by_ext[ext]
            else:
                if ext not in self.by_ext:
                    self.by_ext[ext] = {"size": 0, "files": 0}
                self.by_ext[ext]["size"] -= info["size"]
                self.by_ext[ext]["files"] -= info["files"]
                if self.by_ext[ext]["files"] <= 0:
                    del self.by_ext[ext]

        self.colors = color_map(self.by_ext)
        self._fill_types(self.by_ext)

        # (f) If self.view is the deleted node or inside it, reset to top
        if self.view is not None:
            check = self.view
            while check is not None:
                if check is node:
                    self.view = self.top
                    break
                check = check.parent

        # (g) Redraw treemap
        self.draw_treemap()

        # (h) Status message and return
        self.status.set(f"Moved to the Recycle Bin: {node.name} ({human(node.size)})")
        return True

    def export(self):
        """Export the current tree to a CSV file."""
        if self.top is None:
            return
        file = tkinter.filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not file:
            return
        rows = actions.export_csv(self.top, file)
        self.status.set(f"Exported {rows:,} rows to {file}")


def main():
    """Entry point: create and run the App."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
