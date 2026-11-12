"""T01: the fast read-only scanner that walks a folder tree with scandir."""
import os
import stat
import time
from dataclasses import dataclass, field

REPARSE_POINT = 0x400


@dataclass(eq=False)
class Node:
    """One file or folder in the scan tree."""

    name: str
    path: str
    is_dir: bool
    size: int = 0
    files: int = 0
    folders: int = 0
    mtime: float = 0.0
    children: list = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)


def ext_of(name: str) -> str:
    """Lower-case extension of a file name, with its dot, or '(none)'."""
    ext = os.path.splitext(name)[1]
    return ext.lower() if ext else "(none)"


def scan(root: str, progress=None, cancel=None) -> tuple[Node, int]:
    """Scan root (read-only) into a Node tree; returns (top, skipped)."""
    root = os.path.abspath(root)
    top = Node(os.path.basename(root) or root, root, True)
    stack = [top]
    skipped = 0
    count = 0
    while stack:
        if cancel is not None and cancel():
            break
        node = stack.pop()
        try:
            entries = list(os.scandir(node.path))
        except OSError:
            skipped += 1
            continue
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if st.st_file_attributes & REPARSE_POINT:
                continue
            child = Node(e.name, e.path, stat.S_ISDIR(st.st_mode),
                         size=st.st_size if not stat.S_ISDIR(st.st_mode) else 0,
                         files=0 if stat.S_ISDIR(st.st_mode) else 1,
                         mtime=st.st_mtime, parent=node)
            node.children.append(child)
            if child.is_dir:
                stack.append(child)
            else:
                count += 1
                if progress is not None and count % 2000 == 0:
                    progress(count)
    # add sizes up, deepest folders first
    def add_up(node):
        for c in node.children:
            if c.is_dir:
                add_up(c)
        node.size = sum(c.size for c in node.children)
        node.files = sum(c.files for c in node.children)
        node.folders = sum(1 for c in node.children if c.is_dir) + sum(c.folders for c in node.children)

    add_up(top)

    def sort_all(node):
        node.children.sort(key=lambda c: (-c.size, c.name.lower()))
        for c in node.children:
            if c.is_dir:
                sort_all(c)

    sort_all(top)
    return top, skipped


def summary(top: Node, skipped: int = 0, seconds: float = 0.0) -> dict:
    """Summarize a scan: root, totals, by_ext and top_level."""
    by_ext: dict[str, dict] = {}

    def walk(node):
        for c in node.children:
            if c.is_dir:
                walk(c)
            else:
                d = by_ext.setdefault(ext_of(c.name), {"size": 0, "files": 0})
                d["size"] += c.size
                d["files"] += 1

    walk(top)
    return {
        "root": top.path,
        "total_size": top.size,
        "files": top.files,
        "folders": top.folders,
        "skipped": skipped,
        "seconds": round(seconds, 3),
        "by_ext": {k: by_ext[k] for k in sorted(by_ext)},
        "top_level": [{"name": c.name, "size": c.size, "files": c.files, "folders": c.folders} for c in top.children],
    }


def timed_scan(root: str, progress=None, cancel=None) -> tuple[Node, int, float]:
    """scan() plus the time it took in seconds."""
    t0 = time.perf_counter()
    top, skipped = scan(root, progress, cancel)
    return top, skipped, time.perf_counter() - t0
