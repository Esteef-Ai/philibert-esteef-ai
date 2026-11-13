"""T14: trash() only says "deleted" when the item is really gone, and reads Windows' answer from the right place."""
import ctypes
import faulthandler
import shutil
import tempfile
from pathlib import Path

faulthandler.dump_traceback_later(60, exit=True)
from _t import check, finish  # noqa: E402

try:
    from wiztry import actions
except Exception as e:                                  # noqa: BLE001
    check("wiztry.actions imports", False, e)
    finish()

box = Path(tempfile.mkdtemp(prefix="pc_test_"))
root = box / "scanned"
root.mkdir()
(root / "a.txt").write_bytes(b"a" * 10)
(root / "b.txt").write_bytes(b"b" * 10)
R = str(root)

# 1. the structure Windows fills in: fAnyOperationsAborted is a 4-byte BOOL at offset 36 on 64-bit Windows.
#    (Declared as a 1-byte bool it sat at offset 34 and never saw the answer.)
S = getattr(actions, "SHFILEOPSTRUCTW", None)
check("actions.SHFILEOPSTRUCTW is a ctypes.Structure", isinstance(S, type) and issubclass(S, ctypes.Structure), S)
if isinstance(S, type) and issubclass(S, ctypes.Structure):
    f = S.fAnyOperationsAborted
    check("fAnyOperationsAborted is 4 bytes wide (a BOOL)", f.size == 4, f.size)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        check("it sits at offset 36 and the structure is 56 bytes", f.offset == 36 and ctypes.sizeof(S) == 56, (f.offset, ctypes.sizeof(S)))
    check("fFlags is 2 bytes wide", S.fFlags.size == 2, S.fFlags.size)

# 2. the one call to Windows is in _recycle(path) -> the result code; trash() checks what happened afterwards
check("actions._recycle exists", callable(getattr(actions, "_recycle", None)))
real = getattr(actions, "_recycle", None)
called = []


def says_ok_but_does_nothing(path):
    called.append(path)
    return 0


def says_failed(path):
    called.append(path)
    return 120


def outcome(path):
    try:
        actions.trash(path, R)
    except OSError as e:
        return "OSError: " + str(e)
    except Exception as e:                              # noqa: BLE001
        return repr(e)
    return "no error"


actions._recycle = says_ok_but_does_nothing
got = outcome(str(root / "a.txt"))
check("trash() goes through _recycle with the full path", called == [str(root / "a.txt")], called)
check("Windows says done but the file is still there: OSError, not success", got.startswith("OSError") and (root / "a.txt").exists(), got)
check("and the message says it is still there", "still there" in got, got)

called.clear()
actions._recycle = says_failed
got = outcome(str(root / "a.txt"))
check("a result code other than 0 is an OSError that names the code", got.startswith("OSError") and "120" in got, got)

called.clear()
got = outcome(str(box / "nope.txt"))
check("what may not be deleted never reaches _recycle", not called and got != "no error", (called, got))

# 3. the real thing still works
if real is not None:
    actions._recycle = real
    got = outcome(str(root / "a.txt"))
    check("a real delete still goes to the Recycle Bin without an error", got == "no error" and not (root / "a.txt").exists(), got)
    check("and leaves the other file", (root / "b.txt").exists())

shutil.rmtree(box, ignore_errors=True)
finish()
