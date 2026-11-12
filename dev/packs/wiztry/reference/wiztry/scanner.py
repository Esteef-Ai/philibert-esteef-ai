"""Scanner module for WizTry disk space analyzer."""

import os
import stat
import time
from dataclasses import dataclass, field

REPARSE_POINT = 0x400


def clean_root(path: str) -> str:
    """Normalize a path string: strip quotes/spaces, resolve drive roots, convert slashes."""
    s = path.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    s = s.strip()
    if not s:
        return ""
    s = s.replace("/", "\\")
    if len(s) == 2 and s[1] == ":":
        return s[0].upper() + ":" + os.sep
    return os.path.abspath(s)


@dataclass(eq=False)
class Node:
    """A file or folder node in the scanned directory tree."""
    name: str
    path: str
    is_dir: bool
    size: int = 0
    files: int = 0
    folders: int = 0
    mtime: float = 0.0
    children: list = field(default_factory=list)
    parent: 'Node | None' = None


def ext_of(name: str) -> str:
    """Return the lower-case extension with dot, or '(none)' if absent."""
    base = os.path.basename(name)
    root, ext = os.path.splitext(base)
    if ext:
        return ext.lower()
    return "(none)"


def scan(root, progress=None, cancel=None):
    """Walk root with os.scandir, return (top Node, skipped count)."""
    root = clean_root(root)
    top = Node(name=os.path.basename(root), path=root, is_dir=True)

    # Stack of (dir_path, parent_node, children_list_ref)
    stack = [(root, top, top.children)]
    file_count = 0
    skipped = 0

    while stack:
        if cancel and cancel():
            break

        dir_path, parent, children = stack.pop()

        try:
            entries = list(os.scandir(dir_path))
        except OSError:
            skipped += 1
            continue

        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue

            # Skip reparse points (junctions, symlinks)
            if st.st_file_attributes is not None and (st.st_file_attributes & REPARSE_POINT):
                continue

            name = e.name
            full_path = e.path

            is_dir = stat.S_ISDIR(st.st_mode)
            node = Node(
                name=name,
                path=full_path,
                is_dir=is_dir,
                mtime=st.st_mtime,
                parent=parent,
            )

            if is_dir:
                node.folders = 0
                node.files = 0
                node.size = 0
                children.append(node)
                stack.append((full_path, node, node.children))
            else:
                node.size = st.st_size
                node.files = 1
                node.folders = 0
                children.append(node)
                file_count += 1
                if progress and file_count % 2000 == 0:
                    progress(file_count)

    # Propagate sizes and counts upward from leaves to root
    # Collect all nodes by depth (deepest first)
    all_nodes = []
    for child in top.children:
        _collect(child, all_nodes)
        all_nodes.append(child)

    # all_nodes is in post-order (children after their descendants), so process in order
    for node in all_nodes:
        total_size = node.size
        total_files = node.files
        total_folders = node.folders
        for child in node.children:
            total_size += child.size
            total_files += child.files
            total_folders += child.folders
        node.size = total_size
        node.files = total_files
        node.folders = total_folders + len([c for c in node.children if c.is_dir])

    # Now propagate into top
    for child in top.children:
        top.size += child.size
        top.files += child.files
        top.folders += child.folders
    top.folders += len([c for c in top.children if c.is_dir])

    # Sort each node's children by (-size, lower-case name)
    _sort_children(top)

    return top, skipped


def _collect(node, out):
    """Recursively collect all descendants of node."""
    for child in node.children:
        _collect(child, out)
        out.append(child)


def _sort_children(node):
    """Sort node's children by (-size, lower-case name)."""
    node.children.sort(key=lambda c: (-c.size, c.name.lower()))
    for child in node.children:
        _sort_children(child)


def summary(top, skipped=0, seconds=0.0):
    """Return a dict summary of the scan results."""
    by_ext = {}
    for child in top.children:
        _accumulate_ext(child, by_ext)

    # Sort by_ext by extension key
    sorted_by_ext = dict(sorted(by_ext.items()))

    top_level = []
    for child in top.children:
        top_level.append({
            "name": child.name,
            "size": child.size,
            "files": child.files,
            "folders": child.folders,
        })

    return {
        "root": top.path,
        "total_size": top.size,
        "files": top.files,
        "folders": top.folders,
        "skipped": skipped,
        "seconds": round(seconds, 3),
        "by_ext": sorted_by_ext,
        "top_level": top_level,
    }


def _accumulate_ext(node, by_ext):
    """Accumulate file sizes and counts by extension."""
    if not node.is_dir:
        ext = ext_of(node.name)
        if ext not in by_ext:
            by_ext[ext] = {"size": 0, "files": 0}
        by_ext[ext]["size"] += node.size
        by_ext[ext]["files"] += node.files
    else:
        for child in node.children:
            _accumulate_ext(child, by_ext)


def timed_scan(root, progress=None, cancel=None):
    """Scan root and return (top Node, skipped, elapsed_seconds)."""
    start = time.perf_counter()
    top, skipped = scan(root, progress, cancel)
    elapsed = time.perf_counter() - start
    return top, skipped, elapsed
