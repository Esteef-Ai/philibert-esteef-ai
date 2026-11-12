"""T05: tkinter + ttk window for WizTry."""
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from wiztry.scanner import timed_scan, summary
from wiztry.treemap import layout
from wiztry.filetypes import color_map, ext_rows, human


def bar(pct: float) -> str:
    """Render pct as 10 block cells (full block, light block) plus the percentage."""
    full = round(pct / 10)
    full = max(0, min(10, full))
    light = 10 - full
    return "\u2588" * full + "\u2591" * light + f" {pct:5.1f}%"


def shade(color: str, k: float) -> str:
    """Darken (k < 1) or lighten (k > 1) a hex color."""
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    if k < 1:
        r = int(r * k)
        g = int(g * k)
        b = int(b * k)
    else:
        r = min(255, int(r + (255 - r) * (k - 1)))
        g = min(255, int(g + (255 - g) * (k - 1)))
        b = min(255, int(b + (255 - b) * (k - 1)))
    return f"#{r:02x}{g:02x}{b:02x}"


class App(tk.Tk):
    """The WizTry main window."""

    def __init__(self, start_path: str = "") -> None:
        """Create the App window, optionally starting at start_path."""
        super().__init__()
        self.title("WizTry")
        self.geometry("1200x800")

        # Try vista theme, fallback to clam
        try:
            style = ttk.Style()
            style.theme_use("vista")
        except tk.TclError:
            style = ttk.Style()
            style.theme_use("clam")

        self.path_var = tk.StringVar(value=start_path)
        self.status = tk.StringVar(value="")
        self.busy = False
        self._scan_result = None  # (top, skipped, seconds)

        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=4, pady=4)

        path_entry = ttk.Entry(toolbar, textvariable=self.path_var)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        browse_btn = ttk.Button(toolbar, text="Browse...", command=self._browse)
        browse_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.scan_btn = ttk.Button(toolbar, text="Scan", command=self._on_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 4))

        top_btn = ttk.Button(toolbar, text="Top", command=self.zoom_top)
        top_btn.pack(side=tk.LEFT, padx=(0, 4))

        status_label = ttk.Label(toolbar, textvariable=self.status)
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Vertical Panedwindow
        v_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        v_paned.pack(fill=tk.BOTH, expand=True)

        # Horizontal paned for tree + types - must be inside a Frame
        h_frame = ttk.Frame(v_paned)
        v_paned.add(h_frame, weight=1)
        h_paned = ttk.PanedWindow(h_frame, orient=tk.HORIZONTAL)
        h_paned.pack(fill=tk.BOTH, expand=True)

        # Tree view
        tree_col = ttk.Frame(h_paned)
        tree_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_col, columns=("pct", "size", "items", "files", "folders", "modified"),
                                 show="tree headings")
        self.tree.heading("#0", text="Name")
        self.tree["columns"] = ("pct", "size", "items", "files", "folders", "modified")
        self.tree.heading("pct", text="% of Parent")
        self.tree.heading("size", text="Size")
        self.tree.heading("items", text="Items")
        self.tree.heading("files", text="Files")
        self.tree.heading("folders", text="Folders")
        self.tree.heading("modified", text="Modified")
        self.tree.column("pct", width=100, minwidth=60)
        self.tree.column("size", width=80, minwidth=50)
        self.tree.column("items", width=60, minwidth=40)
        self.tree.column("files", width=60, minwidth=40)
        self.tree.column("folders", width=60, minwidth=40)
        self.tree.column("modified", width=140, minwidth=80)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Double-1>", self._on_tree_double)
        self.tree.bind("<Button-1>", self._on_tree_click)

        # Types view
        types_frame = ttk.Frame(h_paned)
        types_col = ttk.Frame(types_frame)
        types_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.types = ttk.Treeview(types_col, columns=("size", "pct", "files"), show="tree headings")
        self.types.heading("#0", text="Extension")
        self.types.heading("size", text="Size")
        self.types.heading("pct", text="%")
        self.types.heading("files", text="Files")
        self.types.column("size", width=80, minwidth=50)
        self.types.column("pct", width=60, minwidth=40)
        self.types.column("files", width=60, minwidth=40)
        self.types.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Canvas for treemap
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        v_paned.add(self.canvas, weight=2)

        self.blocks: dict = {}
        self.top = None
        self.view = None
        self.colors: dict = {}
        self.tooltip_label = None
        self._resize_id = None
        self._nodes: dict = {}

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # Debounced resize handler
        self.canvas.bind("<Configure>", self._on_resize)

    def _browse(self) -> None:
        """Open a folder selection dialog."""
        path = filedialog.askdirectory(initialdir=self.path_var.get())
        if path:
            self.path_var.set(path)

    def start_scan(self, path: str) -> None:
        """Start a background scan of path."""
        if self.busy:
            return
        self.busy = True
        self.scan_btn.config(state="disabled")
        self._scan_result = None

        def _worker():
            top, skipped, seconds = timed_scan(path)
            self._scan_result = (top, skipped, seconds)

        threading.Thread(target=_worker, daemon=True).start()
        self._poll_scan()

    def _poll_scan(self) -> None:
        """Check if background scan has completed, update UI."""
        if self._scan_result is not None:
            top, skipped, seconds = self._scan_result
            self.busy = False
            self.scan_btn.config(state="normal")
            self._fill_tree(top)
            self._fill_types(top)
            self.draw_treemap(top)
            total_files = top.files
            total_folders = top.folders
            total_size = top.size
            self.status.set(f"{total_files:,} files, {total_folders:,} folders, {human(total_size)} in {seconds:.1f} s")
            return
        if self.busy:
            self.status.set("Scanning...")
        self.after(50, self._poll_scan)

    def _fill_tree(self, top) -> None:
        """Fill the tree view with the scan results."""
        self.top = top
        self.view = top
        self._nodes = {}
        # Insert the scanned folder as the single root item
        root_iid = self.tree.insert("", "end", text=top.name, open=True,
                                     values=("100.0%", human(top.size), str(top.folders + top.files + 1),
                                             str(top.files), str(top.folders), ""))
        self._nodes[root_iid] = top
        # Populate its children
        self._populate_children(root_iid, top)

    def _populate_children(self, parent: str, node) -> None:
        """Populate children of parent node in the tree."""
        for child in node.children:
            pct = f"{child.size / node.size * 100:.1f}%" if node.size > 0 else "0.0%"
            iid = self.tree.insert(parent, "end", text=child.name, open=False,
                                   values=(pct, human(child.size), str(child.folders + child.files + 1),
                                           str(child.files), str(child.folders), ""))
            if child.is_dir and child.folders > 0:
                self.tree.insert(iid, "end", text="")
            self._nodes[iid] = child

    def _fill_types(self, top) -> None:
        """Fill the types tree view."""
        self.types.delete(*self.types.get_children(""))
        s = summary(top, 0, 0)
        self.colors = color_map(s["by_ext"])
        rows = ext_rows(s["by_ext"])
        self._swatches = {}
        for row in rows:
            ext = row["ext"]
            color = row["color"]
            img = tk.PhotoImage(width=12, height=12)
            img.put(color, (0, 0, 11, 11))
            self.types.insert("", "end", text=ext, values=(human(row["size"]), f"{row['pct']:.1f}%", row["files"]),
                              image=img)
            self._swatches[id(img)] = img

    def draw_treemap(self, top) -> None:
        """Draw the treemap on the canvas."""
        self.canvas.delete("all")
        self.blocks = {}

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w < 10 or canvas_h < 10:
            canvas_w, canvas_h = 800, 300

        self.view = top
        min_px = 3
        total_files = top.files
        if total_files > 20000:
            min_px = max(min_px, total_files // 20000 + 1)

        # layout() returns children of the node (not the node itself)
        laid = layout(top, 0, 0, canvas_w, canvas_h, min_px=min_px)

        # Cap at 20,000 files
        file_count = sum(1 for n, _, _ in laid if not n.is_dir)
        if file_count > 20000:
            kept = []
            fc = 0
            for n, r, d in laid:
                if not n.is_dir:
                    if fc >= 20000:
                        continue
                    fc += 1
                kept.append((n, r, d))
            laid = kept

        # Build a quick lookup: node -> rect
        node_rect = {}
        for n, r, d in laid:
            if r is not None:
                node_rect[n] = r

        def draw_node(node, rect):
            """Draw a single node (folder gray or file block)."""
            if rect is None:
                return
            rx, ry, rw, rh = rect
            if node.is_dir:
                # Draw folder gray fill
                self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill="#c8c8c8", outline="")
            else:
                ext = os.path.splitext(node.name)[1].lower()
                base_color = self.colors.get(ext, "#a0a0a0")
                outlined = shade(base_color, 0.6)
                item = self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill=base_color, outline=outlined)
                self.blocks[item] = node
                # Draw cushion lines on top of the fill
                if rw > 4 and rh > 4:
                    light_color = shade(base_color, 1.45)
                    dark_color = shade(base_color, 0.75)
                    self.canvas.create_line(rx, ry, rx + rw, ry, fill=light_color, width=1)
                    self.canvas.create_line(rx, ry, rx, ry + rh, fill=light_color, width=1)
                    self.canvas.create_line(rx + rw - 1, ry, rx + rw - 1, ry + rh, fill=dark_color, width=1)
                    self.canvas.create_line(rx, ry + rh - 1, rx + rw, ry + rh - 1, fill=dark_color, width=1)

        def draw_children(node, rect):
            """Draw a folder's gray fill, then its file children, then recurse into folder children."""
            if rect is None:
                return
            # Draw folder gray first
            rx, ry, rw, rh = rect
            self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill="#c8c8c8", outline="")
            # Draw file children (on top of gray)
            for child in node.children:
                if child.size <= 0:
                    continue
                child_rect = node_rect.get(child)
                if child_rect is None:
                    continue
                if not child.is_dir:
                    draw_node(child, child_rect)
            # Recurse into folder children
            for child in node.children:
                if child.is_dir and child.size > 0:
                    child_rect = node_rect.get(child)
                    if child_rect is not None:
                        draw_children(child, child_rect)

        # Draw the top-level children (layout returns children of top, not top itself)
        for child in top.children:
            if child.size <= 0:
                continue
            child_rect = node_rect.get(child)
            if child_rect is None:
                continue
            if child.is_dir:
                draw_children(child, child_rect)
            else:
                draw_node(child, child_rect)

        # Draw folder outlines last (on top of everything)
        for n, r, d in laid:
            if n.is_dir and r is not None:
                rx, ry, rw, rh = r
                self.canvas.create_rectangle(rx, ry, rx + rw, ry + rh, fill="", outline="#707070")

    def _on_scan(self) -> None:
        """Handle scan button click."""
        path = self.path_var.get().strip()
        if path:
            self.start_scan(path)

    def _on_tree_open(self, event) -> None:
        """Handle tree node expansion (lazy load children)."""
        item = self.tree.focus()
        if not item:
            return
        node = self._nodes.get(item)
        if not node or not node.is_dir:
            return
        children = self.tree.get_children(item)
        if children and not children[0].strip():
            self.tree.delete(*children)
            for child in node.children:
                if child.is_dir and child.folders > 0:
                    child_iid = self.tree.insert(item, "end", text=child.name, open=False)
                    self.tree.insert(child_iid, "end", text="")
                else:
                    child_iid = self.tree.insert(item, "end", text=child.name, open=False)
                self._nodes[child_iid] = child

    def _on_tree_double(self, event) -> None:
        """Handle double-click on tree node."""
        item = self.tree.focus()
        if not item:
            return
        node = self._nodes.get(item)
        if node and node.is_dir:
            self.zoom(node)

    def _on_tree_click(self, event) -> None:
        """Handle single click on tree node."""
        pass

    def _on_mouse_move(self, event) -> None:
        """Show tooltip on mouse move over canvas."""
        node = self.node_at(event.x, event.y)
        if node:
            tip = f"{node.path}\n{human(node.size)}"
        else:
            tip = ""

        if self.tooltip_label is None:
            self.tooltip_label = tk.Label(self.canvas, text=tip, bg="yellow", fg="black",
                                          font=("TkDefaultFont", 8), relief="solid", borderwidth=1)
            self.tooltip_label.place_forget()

        if tip:
            x = event.x + 15
            y = event.y - 25
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if x + 200 > cw:
                x = event.x - 200
            if y < 0:
                y = event.y + 15
            self.tooltip_label.config(text=tip)
            self.tooltip_label.place(x=x, y=y)
        else:
            self.tooltip_label.place_forget()

    def _on_canvas_click(self, event) -> None:
        """Handle canvas click - select node in tree."""
        node = self.node_at(event.x, event.y)
        if node:
            self.select_node(node)

    def _on_resize(self, event) -> None:
        """Handle window resize with debounce."""
        if self._resize_id:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(150, lambda: self._do_resize(event))

    def _do_resize(self, event) -> None:
        """Actually perform the resize redraw."""
        if self.view:
            self.draw_treemap(self.view)
        self._resize_id = None

    def node_at(self, x: int, y: int):
        """Find the file Node under point (x, y), or None."""
        for item, node in self.blocks.items():
            coords = self.canvas.coords(item)
            if coords:
                rx0, ry0, rx1, ry1 = coords
                if rx0 <= x <= rx1 and ry0 <= y <= ry1:
                    return node
        return None

    def tooltip_text_at(self, x: int, y: int) -> str:
        """Return tooltip text for point (x, y), or empty string."""
        node = self.node_at(x, y)
        if node:
            return f"{node.path}\n{human(node.size)}"
        return ""

    def select_node(self, node) -> str:
        """Select node in the tree, return the item id."""
        # Walk up from node to root, collecting the path
        path_nodes = []
        cur = node
        while cur is not None:
            path_nodes.append(cur)
            cur = cur.parent if hasattr(cur, 'parent') else None
        path_nodes.reverse()

        # Walk down from root, expanding/inserting as needed
        root_iid = self.tree.get_children("")
        if not root_iid:
            return ""
        parent_iid = root_iid[0]

        # The root of the tree is app.top
        # We need to find each node in the tree structure
        for i in range(1, len(path_nodes)):  # skip root (app.top)
            target = path_nodes[i]
            # Look for the target among parent's children
            found_iid = None

            # First check already-populated children
            for child_iid in self.tree.get_children(parent_iid):
                nd = self._nodes.get(child_iid)
                if nd and nd.path == target.path:
                    found_iid = child_iid
                    break

            if not found_iid and parent_iid in self._nodes:
                parent_node = self._nodes[parent_iid]
                # Populate children from the scan tree
                for child in parent_node.children:
                    if child.path == target.path:
                        pct = f"{child.size / parent_node.size * 100:.1f}%" if parent_node.size > 0 else "0.0%"
                        found_iid = self.tree.insert(parent_iid, "end", text=child.name, open=False,
                                                     values=(pct, human(child.size), str(child.folders + child.files + 1),
                                                             str(child.files), str(child.folders), ""))
                        self._nodes[found_iid] = child
                        if child.is_dir and child.folders > 0:
                            self.tree.insert(found_iid, "end", text="")
                        break
                    # Check if child might contain target
                    if child.is_dir and target.path.startswith(child.path):
                        pct = f"{child.size / parent_node.size * 100:.1f}%" if parent_node.size > 0 else "0.0%"
                        found_iid = self.tree.insert(parent_iid, "end", text=child.name, open=False,
                                                     values=(pct, human(child.size), str(child.folders + child.files + 1),
                                                             str(child.files), str(child.folders), ""))
                        self._nodes[found_iid] = child
                        if child.is_dir and child.folders > 0:
                            self.tree.insert(found_iid, "end", text="")
                        break

            if not found_iid:
                return ""

            # Expand parent and set children
            children = self.tree.get_children(parent_iid)
            if children:
                self.tree.set_children(parent_iid, *children)
            self.tree.see(parent_iid)
            parent_iid = found_iid

        # Select the final item
        self.tree.selection_set(parent_iid)
        self.tree.see(parent_iid)
        return parent_iid

    def zoom(self, node) -> None:
        """Zoom into a folder node."""
        self.view = node
        self.draw_treemap(node)

    def zoom_top(self) -> None:
        """Zoom back to the root."""
        self.view = self.top
        self.draw_treemap(self.top)

    @property
    def nodes(self) -> dict:
        """Return the node dictionary."""
        return self._nodes

    @nodes.setter
    def nodes(self, val: dict) -> None:
        self._nodes = val


def main() -> None:
    """Entry point for the GUI application."""
    app = App()
    app.mainloop()
