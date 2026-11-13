"""Actions module: delete to Recycle Bin, show in Explorer, export CSV, forget nodes."""

import csv
import ctypes
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from wiztry.scanner import Node

try:
    from ctypes import wintypes
except ImportError:
    wintypes = None  # type: ignore[misc, assignment]

# SHFileOperationW flags
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400

# SHFileOperationW function codes
FO_DELETE = 3


# ---------------------------------------------------------------------------
# can_delete
# ---------------------------------------------------------------------------

def can_delete(path: str, root: str) -> str:
    """Return "" when path may be deleted, otherwise the reason string."""
    if not path or path.strip() == "":
        return "no path"

    p = os.path.normcase(os.path.abspath(path)).rstrip("\\")
    r = os.path.normcase(os.path.abspath(root)).rstrip("\\")

    # Check if p is a drive letter like "c:"
    if len(p) == 2 and p[1] == ":":
        return "a drive"

    if p == r:
        return "the scanned folder itself"

    if not p.startswith(r + "\\"):
        return "outside the scanned folder"

    if not os.path.lexists(path):
        return "not found"

    return ""


# ---------------------------------------------------------------------------
# trash
# ---------------------------------------------------------------------------

class SHFILEOPSTRUCTW(ctypes.Structure):
    """Structure for SHFileOperationW."""
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def _recycle(path: str) -> int:
    """Call SHFileOperationW to recycle a file/folder. Returns the result code."""
    op = SHFILEOPSTRUCTW()
    op.hwnd = 0
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0\0"
    op.pTo = "\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = 0
    op.lpszProgressTitle = None

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result == 0 and op.fAnyOperationsAborted:
        return 1223
    return result


def trash(path: str, root: str) -> None:
    """Move path to the Recycle Bin via SHFileOperationW."""
    why = can_delete(path, root)
    if why:
        raise ValueError(why)

    full = os.path.abspath(path)
    code = _recycle(full)

    if code != 0:
        raise OSError(f"Windows could not move it to the Recycle Bin (code {code})")

    if os.path.lexists(full):
        raise OSError("Windows reported success but the item is still there")


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------

def forget(node: Node) -> None:
    """Remove node from its parent's children and subtract its counts up the tree."""
    if node.parent is None:
        return

    # Remove from parent's children
    parent = node.parent
    if node in parent.children:
        parent.children.remove(node)

    # Subtract from parent upward
    current = parent
    while current is not None:
        current.size -= node.size
        current.files -= node.files
        # node.folders counts sub-folders within node; we also need to account
        # for node itself being a folder
        if node.is_dir:
            current.folders -= (node.folders + 1)
        else:
            current.folders -= node.folders
        # Move to grandparent (node is the original node, not current)
        orig = node
        node = current
        current = current.parent
        node = orig


# ---------------------------------------------------------------------------
# explorer
# ---------------------------------------------------------------------------

def explorer_args(path: str) -> list:
    """Return the command-line arguments for showing a file/folder in Explorer."""
    return ["explorer.exe", "/select,", path]


def show_in_explorer(path: str) -> None:
    """Open Windows Explorer at the given path."""
    subprocess.Popen(explorer_args(path))


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------

def export_csv(top: Node, file: str) -> int:
    """Write a CSV export of the tree. Returns the number of rows written (excluding header)."""
    rows_written = 0
    stack = [top]

    with open(file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Path", "Type", "Size", "Files", "Folders", "Modified"])

        while stack:
            node = stack.pop()

            node_type = "Folder" if node.is_dir else "File"
            mtime_str = ""
            if node.mtime != 0:
                dt = datetime.fromtimestamp(node.mtime, tz=timezone.utc)
                mtime_str = dt.strftime("%Y-%m-%d %H:%M")

            writer.writerow([
                node.path,
                node_type,
                str(node.size),
                str(node.files),
                str(node.folders),
                mtime_str,
            ])
            rows_written += 1

            # Push children in reverse order so largest-first comes out first
            for child in reversed(node.children):
                stack.append(child)

    return rows_written
