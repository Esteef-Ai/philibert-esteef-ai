"""A hidden Windows desktop — for driving native apps without touching the
user's screen.

This is the last rung of the automation ladder and the most limited one; read
this before reaching for it.

WHAT IT IS. Windows can hold more than one "desktop" object on a window
station. Create a second one, launch a program onto it, and that program's
windows live there — not on the desktop the user is looking at. We never switch
the input/display to it (that would flip the user's screen), so:

  * CAPTURE is reliable. PrintWindow asks a window to paint itself into an
    off-screen device context; it works regardless of which desktop is showing,
    so we can see what is on the hidden desktop without revealing it.

  * INPUT is best-effort. SendInput goes to whatever desktop currently has the
    input focus — the user's — so we cannot use it without hijacking the screen.
    Instead we PostMessage clicks and keystrokes straight to the target window.
    Standard Win32 controls honour these; many modern apps (anything drawing its
    own UI on a GPU surface, most games, some Electron apps) ignore synthetic
    messages and will not respond. When that happens, the honest move is to fall
    back to the real screen with gui_action, or to tell the user.

So: use the MANAGED BROWSER for anything on the web (it is far more capable),
and use this only for a native app that has no web version and no command line,
when the user does not want their screen touched.
"""
import base64
import ctypes
import io
import time
from ctypes import wintypes

try:
    import win32gui
    import win32ui
    import win32process
    import win32con
    _WIN = True
except Exception:
    _WIN = False

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Desktop access rights (winuser.h).
_GENERIC_ALL = 0x10000000
_DESKTOP_CREATEWINDOW = 0x0002
_DESKTOP_ENUMERATE = 0x0040
_DESKTOP_ALL = 0x01FF
_PW_RENDERFULLCONTENT = 0x00000002
_WM_LBUTTONDOWN, _WM_LBUTTONUP = 0x0201, 0x0202
_WM_CHAR, _WM_KEYDOWN, _WM_KEYUP = 0x0102, 0x0100, 0x0101

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _lparam_xy(x, y):
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


class HiddenDesktop:
    def __init__(self, name="NeuralDockWork", log=None):
        self.name = name
        self._log = log or (lambda *a, **k: None)
        self._hdesk = None
        self._pids = []

    def available(self):
        if not _WIN:
            return "pywin32 (win32gui/win32ui) is not installed in this environment"
        return ""

    def _ensure(self):
        if self._hdesk:
            return ""
        _user32.CreateDesktopW.restype = wintypes.HANDLE
        _user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           ctypes.c_void_p, wintypes.DWORD,
                                           wintypes.DWORD, ctypes.c_void_p]
        h = _user32.CreateDesktopW(self.name, None, None, 0, _GENERIC_ALL, None)
        if not h:
            return f"could not create the hidden desktop (error {ctypes.get_last_error()})"
        self._hdesk = h
        self._log(f"Hidden desktop '{self.name}' ready", "info")
        return ""

    def launch(self, command):
        err = self._ensure()
        if err:
            return "[hidden] " + err
        try:
            si = win32process.STARTUPINFO()
            si.lpDesktop = self.name           # THIS is what puts it on the hidden desktop
            # CREATE_NEW_CONSOLE keeps any console off the user's desktop too.
            flags = win32con.CREATE_NEW_PROCESS_GROUP
            hProc, hThread, pid, tid = win32process.CreateProcess(
                None, command, None, None, False, flags, None, None, si)
            self._pids.append(pid)
            time.sleep(1.0)
            return (f"[hidden] Launched on the hidden desktop (pid {pid}). "
                    "Use hidden_desktop action='windows' to see its windows, then 'see' to look.")
        except Exception as e:
            return f"[hidden] Could not launch there: {e}"

    def windows(self):
        err = self._ensure()
        if err:
            return "[hidden] " + err
        found = []

        def _cb(hwnd, _):
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                found.append((hwnd, title))
            return True

        try:
            _user32.EnumDesktopWindows(self._hdesk, _WNDENUMPROC(_cb), 0)
        except Exception as e:
            return f"[hidden] Could not enumerate windows: {e}"
        if not found:
            return ("[hidden] No titled windows on the hidden desktop yet. The app may still "
                    "be starting, or it draws no standard window. Give it a moment and retry.")
        lines = ["[hidden] Windows on the hidden desktop (hwnd · title):"]
        for hwnd, title in found[:20]:
            lines.append(f"  {hwnd}  {title[:70]}")
        lines.append("  Pass an hwnd to 'see' to capture it, or to 'click'/'type' to act on it.")
        return "\n".join(lines)

    def _pick_window(self):
        best = [0, 0]   # hwnd, area

        def _cb(hwnd, _):
            if not _user32.IsWindowVisible(hwnd):
                return True
            r = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
            if area > best[1]:
                best[0], best[1] = hwnd, area
            return True

        _user32.EnumDesktopWindows(self._hdesk, _WNDENUMPROC(_cb), 0)
        return best[0]

    def capture(self, hwnd=None, max_width=1280):
        err = self._ensure()
        if err:
            return {"error": err}
        try:
            hwnd = int(hwnd) if hwnd else self._pick_window()
            if not hwnd:
                return {"error": "no window to capture on the hidden desktop yet"}
            r = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if w < 2 or h < 2:
                return {"error": "the target window has no visible area"}
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            # PW_RENDERFULLCONTENT captures DWM/GPU-composited content too, which
            # plain PrintWindow misses and which is most of why "it came back
            # black" used to happen.
            ok = _user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), _PW_RENDERFULLCONTENT)
            info = bmp.GetInfo()
            bits = bmp.GetBitmapBits(True)
            try:
                from PIL import Image
                img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                                       bits, "raw", "BGRX", 0, 1)
                if img.width > max_width:
                    nh = int(img.height * (max_width / img.width))
                    img = img.resize((max_width, nh))
                buf = io.BytesIO(); img.save(buf, "PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            finally:
                win32gui.DeleteObject(bmp.GetHandle())
                save_dc.DeleteDC(); mfc_dc.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            if not ok:
                return {"error": "PrintWindow reported failure; the capture may be blank"}
            return {"image_b64": b64, "width": info["bmWidth"], "height": info["bmHeight"], "hwnd": hwnd}
        except Exception as e:
            return {"error": str(e)}

    def click(self, hwnd, x, y):
        err = self._ensure()
        if err:
            return "[hidden] " + err
        try:
            hwnd = int(hwnd) if hwnd else self._pick_window()
            lp = _lparam_xy(x, y)
            _user32.PostMessageW(hwnd, _WM_LBUTTONDOWN, 1, lp)
            _user32.PostMessageW(hwnd, _WM_LBUTTONUP, 0, lp)
            time.sleep(0.3)
            return (f"[hidden] Posted a click at ({x},{y}) to window {hwnd}. "
                    "Capture again to confirm — synthetic clicks do not land in every app. "
                    "If nothing changed, this app may need the real screen (gui_action).")
        except Exception as e:
            return f"[hidden] Could not click: {e}"

    def type(self, hwnd, text):
        err = self._ensure()
        if err:
            return "[hidden] " + err
        try:
            hwnd = int(hwnd) if hwnd else self._pick_window()
            for ch in str(text):
                _user32.PostMessageW(hwnd, _WM_CHAR, ord(ch), 0)
                time.sleep(0.008)
            return (f"[hidden] Posted {len(str(text))} char(s) to window {hwnd}. "
                    "Capture again to confirm it landed.")
        except Exception as e:
            return f"[hidden] Could not type: {e}"

    def stop(self):
        for pid in self._pids:
            try:
                h = _kernel32.OpenProcess(0x0001, False, pid)   # PROCESS_TERMINATE
                if h:
                    _kernel32.TerminateProcess(h, 0)
                    _kernel32.CloseHandle(h)
            except Exception:
                pass
        self._pids = []
        return "[hidden] Stopped the apps launched on the hidden desktop."
