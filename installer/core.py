"""Philibert Setup - the logic behind the installer window (no UI here).

Survey the computer, list the places Philibert can go, judge a drive's format
against the computers it must work on, rate each model for this hardware, and
measure how fast the chosen drive is. Pure functions where possible so the
tests can drive them without a window.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
_NO_WINDOW = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW for helper tools


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


# -- the computer -------------------------------------------------------------
def _win_gpus():
    """Every display adapter with its real memory. WMI's AdapterRAM stops at 4 GB,
    so the size comes from the driver's registry entry (64-bit), any vendor."""
    gpus = []
    try:
        import winreg
        base = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(k, sub) as g:
                        name = winreg.QueryValueEx(g, "DriverDesc")[0]
                        try:
                            mem = int(winreg.QueryValueEx(g, "HardwareInformation.qwMemorySize")[0])
                        except OSError:
                            raw = winreg.QueryValueEx(g, "HardwareInformation.MemorySize")[0]
                            mem = int.from_bytes(raw, "little") if isinstance(raw, bytes) else int(raw)
                        gpus.append({"name": name, "vram_gb": round(mem / 2**30, 1)})
                except OSError:
                    continue
    except Exception:
        pass
    # nvidia-smi is the authority for NVIDIA cards when it is there
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[1].isdigit():
            gb = round(int(parts[1]) / 1024, 1)
            for g in gpus:
                if g["name"].strip().lower() == parts[0].lower():
                    g["vram_gb"] = gb
                    break
            else:
                gpus.append({"name": parts[0], "vram_gb": gb})
    return gpus


def gpu_role(g):
    """What a graphics card is good for here: 'cuda' (NVIDIA), 'rocm' (a dedicated
    AMD card), or '' (integrated / other - the models run on the processor)."""
    n = g["name"].lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "quadro" in n:
        return "cuda"
    if ("radeon" in n or "amd" in n) and "radeon(tm) graphics" not in n and g.get("vram_gb", 0) >= 6:
        return "rocm"
    return ""


def survey():
    """This computer: OS, chip, memory, graphics, and how much memory the models
    can run in at full speed ('fast_gb')."""
    info = {"os": "windows" if IS_WIN else ("mac" if IS_MAC else sys.platform),
            "arch": platform.machine().lower(), "cpu": "", "ram_gb": 0.0, "gpus": [],
            "fast_gb": 0.0, "fast_kind": "processor"}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    if IS_WIN:
        info["cpu"] = _run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Processor).Name"]).strip() or platform.processor()
        info["gpus"] = _win_gpus()
        best = max((g for g in info["gpus"] if gpu_role(g)), key=lambda g: g["vram_gb"], default=None)
        if best:
            info["fast_gb"] = best["vram_gb"]
            info["fast_kind"] = best["name"]
    elif IS_MAC:
        info["cpu"] = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        mem = _run(["sysctl", "-n", "hw.memsize"]).strip()
        if mem.isdigit():
            info["ram_gb"] = round(int(mem) / 2**30, 1)
        if info["arch"] == "arm64":
            # Apple Silicon: the GPU shares memory; macOS lets it use about 70%
            info["fast_gb"] = round(info["ram_gb"] * 0.70, 1)
            info["fast_kind"] = "Apple Silicon (shared memory)"
            info["gpus"] = [{"name": info["cpu"] or "Apple Silicon", "vram_gb": info["fast_gb"]}]
    return info


# -- models: red / yellow / green ----------------------------------------------
def model_need_gb(m):
    """Memory a model needs at Philibert's 32K context (flash attention, q8 cache):
    its file plus a little. Calibrated on an RTX 5070 Ti 16 GB, 2026-10-21: the
    13.7 GB 27B loaded as 14 GB fully on the GPU; the 15.7 GB build as 17 GB with
    16% on the processor; the 25.9 GB build as 27 GB."""
    size = float(m.get("size_gb") or 0)
    return round(size * 1.02 + 0.6, 1)


def rate(m, info):
    """green: fits on the GPU; yellow: runs with part on the processor (slower);
    red: will not run usefully on this computer."""
    need = model_need_gb(m)
    fast = float(info.get("fast_gb") or 0)
    spare = max(0.0, float(info.get("ram_gb") or 0) - 3.5)          # leave the system ~3.5 GB
    if fast and need <= fast:
        return "green", "Runs fully on the graphics card - fast."
    if need <= fast + spare:
        if fast and fast >= need * 0.75:
            return "yellow", "Fits with a little on the processor - works, somewhat slower."
        if fast:
            return "yellow", "Fits with much of it on the processor - works, but slowly."
        return "yellow", "No usable graphics card: runs on the processor - works, slow."
    return "red", "Needs more memory than this computer has - it will not run usefully."


def catalog(path=None):
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "models.json"
    return json.loads(p.read_text(encoding="utf-8"))["models"]


def rated_catalog(info, path=None):
    out = []
    for m in catalog(path):
        colour, why = rate(m, info)
        out.append({**m, "need_gb": model_need_gb(m), "rating": colour, "why": why,
                    "locked": bool(m.get("required"))})
    return out


# -- where it goes -------------------------------------------------------------
FORMAT_RULES = {
    # format: (works on windows, works on mac, note)
    "exfat": (True, True, "Works on both Windows and Mac."),
    "ntfs": (True, False, "Windows only: a Mac can read NTFS but cannot save to it."),
    "apfs": (False, True, "Mac only: Windows cannot read APFS."),
    "hfs": (False, True, "Mac only: Windows cannot read Mac OS Extended."),
    "fat32": (False, False, "FAT32 cannot hold files over 4 GB, and every AI model is bigger."),
    "refs": (False, False, "ReFS is not supported."),
}


def format_verdict(fs, pcs):
    """Can a drive formatted `fs` serve the computers in `pcs` ('windows', 'mac')?
    Returns {ok, message}."""
    key = (fs or "").lower().replace("fat ", "fat").replace("msdos", "fat32").replace("vfat", "fat32")
    if key == "fat":
        key = "fat32"
    if key.startswith("hfs"):
        key = "hfs"
    rule = FORMAT_RULES.get(key)
    if not rule:
        return {"ok": False, "message": f"This drive's format ({fs or 'unknown'}) is not supported. "
                                        "Reformat it as exFAT, or pick another drive."}
    win, mac, note = rule
    want_win, want_mac = "windows" in pcs, "mac" in pcs
    if (want_win and not win) or (want_mac and not mac):
        fix = ("Back up the drive and reformat it as exFAT (Disk Management on Windows, Disk Utility "
               "on a Mac), or choose " + ("Mac only." if mac and not win else "Windows only." if win and not mac
                                        else "another drive."))
        return {"ok": False, "message": f"{note} {fix}"}
    return {"ok": True, "message": note}


def _win_bus_types():
    """Drive letter -> bus ('USB', 'NVMe', 'SATA', ...). USB hard drives call
    themselves fixed disks, so 'external' is judged by the bus."""
    out = _run(["powershell", "-NoProfile", "-Command",
                "Get-Partition | Where-Object DriveLetter | ForEach-Object { "
                "$_.DriveLetter + '=' + (Get-Disk -Number $_.DiskNumber).BusType }"], timeout=30)
    buses = {}
    for line in out.splitlines():
        if "=" in line:
            letter, bus = line.strip().split("=", 1)
            buses[letter.upper() + ":\\"] = bus
    return buses


def places():
    """Drives Philibert can go on: every mounted drive with space, external first.
    The computer's own disk is allowed too (an internal install stays with it)."""
    out = []
    buses = _win_bus_types() if IS_WIN else {}
    try:
        import psutil
        parts = psutil.disk_partitions(all=False)
    except Exception:
        parts = []
    sysdrive = (os.environ.get("SystemDrive", "C:") + "\\").upper() if IS_WIN else "/"
    for p in parts:
        mount = p.mountpoint
        if IS_MAC and not (mount == "/" or mount.startswith("/Volumes/")):
            continue
        if "cdrom" in (p.opts or "") or not p.fstype:
            continue
        try:
            u = shutil.disk_usage(mount)
        except OSError:
            continue
        label = ""
        if IS_WIN:
            label = _run(["cmd", "/c", "vol", mount.rstrip("\\")]).splitlines()
            label = next((l.split(" is ", 1)[1] for l in label if " is " in l and "Volume in drive" in l), "")
        else:
            label = Path(mount).name if mount != "/" else "Macintosh HD"
        out.append({"path": mount, "label": label.strip(), "fs": p.fstype,
                    "free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1),
                    "bus": buses.get(mount.upper(), ""),
                    "external": ("removable" in (p.opts or "") or mount.startswith("/Volumes/")
                                 or buses.get(mount.upper(), "") in ("USB", "SD", "MMC", "1394")),
                    "system": mount.upper() == sysdrive})
    out.sort(key=lambda d: (d["system"], not d["external"], d["path"]))
    return out


def _read_uncached(path):
    """Read a file past the system's cache, so the number is the drive's, not RAM's."""
    if IS_WIN:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.VirtualAlloc.restype = ctypes.c_void_p
        GENERIC_READ, OPEN_EXISTING, NO_BUFFERING, SEQUENTIAL = 0x80000000, 3, 0x20000000, 0x08000000
        h = k32.CreateFileW(str(path), GENERIC_READ, 1, None, OPEN_EXISTING, NO_BUFFERING | SEQUENTIAL, None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), "cannot open for the speed test")
        size = 4 * 1024 * 1024
        buf = k32.VirtualAlloc(None, size, 0x3000, 0x04)      # page-aligned, as NO_BUFFERING needs
        got = wintypes.DWORD()
        try:
            while k32.ReadFile(h, ctypes.c_void_p(buf), size, ctypes.byref(got), None) and got.value:
                pass
        finally:
            k32.VirtualFree(ctypes.c_void_p(buf), 0, 0x8000)
            k32.CloseHandle(h)
        return
    with open(path, "rb", buffering=0) as r:
        if IS_MAC:
            import fcntl
            fcntl.fcntl(r.fileno(), 48, 1)                       # F_NOCACHE
        while r.read(4 * 1024 * 1024):
            pass


def speed_test(folder, mb=64):
    """Write and read back a temporary file on the drive: MB/s each way."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / ".philibert-speedtest.tmp"
    block = os.urandom(1024 * 1024)
    try:
        t0 = time.perf_counter()
        with open(f, "wb", buffering=0) as w:
            for _ in range(mb):
                w.write(block)
            os.fsync(w.fileno())
        wt = time.perf_counter() - t0
        t0 = time.perf_counter()
        _read_uncached(f)
        rt = time.perf_counter() - t0
        return {"write_mbs": round(mb / max(wt, 1e-3), 1), "read_mbs": round(mb / max(rt, 1e-3), 1)}
    finally:
        try:
            f.unlink()
        except OSError:
            pass


def load_minutes(size_gb, read_mbs):
    """How long a model of `size_gb` takes to load cold from a drive reading `read_mbs`."""
    if not read_mbs:
        return None
    return round(size_gb * 1024 / read_mbs / 60, 1)
