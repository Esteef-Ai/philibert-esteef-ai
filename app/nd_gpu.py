"""Which GPU is this, and what does the rest of ND need to know about it?

ND's agent core does not care what silicon is underneath -- nd_reskin,
nd_design_review, the tool loop and the UI all speak HTTP to Ollama and to
ComfyUI and contain no vendor code at all. Six places in the launcher DID care,
and every one of them asked an NVIDIA-shaped question:

    nvidia-smi --query-gpu=memory.total   -> empty on anything else
    torch.cuda.is_available()             -> False without a CUDA/HIP build
    --index-url .../whl/cu128             -> the wrong wheel for AMD/Intel
    run_nvidia_gpu.bat                    -> the wrong ComfyUI launcher
    device="cuda"                         -> a hard failure

The first one is the dangerous one, and it is a live bug on NVIDIA too.
gpu_vram_bytes() returning 0 does not raise. It makes _rank_key() compute
budget = 0, which makes fits = 0 for EVERY model, which silently switches off
the does-it-fit-in-VRAM routing that decides which specialist runs. No error,
no log line -- just quietly worse model choices. A probe that cannot answer
must say so loudly, not return a number that means "no".

So: probe once, cache, and record WHICH probe answered.

This module deliberately has no imports beyond the standard library. It is
consulted while deciding whether to install PyTorch, so it cannot depend on
PyTorch being installed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

_IS_WINDOWS = os.name == "nt"

# Vendors ND knows how to configure. "none" means no usable accelerator was
# found, which is different from "unknown" -- unknown means a GPU is present
# but no probe could size it, and callers should degrade loudly rather than
# assume zero.
NVIDIA, AMD, INTEL, NONE, UNKNOWN = "nvidia", "amd", "intel", "none", "unknown"

_cache = None


def _run(cmd, timeout=15):
    """Run a probe. Returns (ok, stdout). Never raises, never blocks forever."""
    try:
        exe = cmd[0]
        if not shutil.which(exe):
            return False, ""
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=(0x08000000 if _IS_WINDOWS else 0))
        return p.returncode == 0, (p.stdout or "")
    except Exception:
        return False, ""


def _probe_nvidia():
    ok, out = _run(["nvidia-smi", "--query-gpu=memory.total,name",
                    "--format=csv,noheader,nounits"])
    if not ok or not out.strip():
        return None
    line = out.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    try:
        mb = int(float(parts[0]))
    except (ValueError, IndexError):
        return None
    name = parts[1] if len(parts) > 1 else "NVIDIA GPU"
    return {"vendor": NVIDIA, "name": name, "vram_bytes": mb * 1024 * 1024,
            "source": "nvidia-smi"}


def _probe_amd():
    """amd-smi is the current tool; rocm-smi is the one most guides still show.
    Try both, and accept either JSON shape -- the key names have changed twice.
    """
    ok, out = _run(["amd-smi", "static", "-g", "0", "--json"])
    if ok and out.strip():
        got = _amd_from_json(out)
        if got:
            return dict(got, source="amd-smi")
    ok, out = _run(["rocm-smi", "--showmeminfo", "vram", "--json"])
    if ok and out.strip():
        got = _amd_from_json(out)
        if got:
            return dict(got, source="rocm-smi")
    return None


def _amd_from_json(text):
    try:
        data = json.loads(text)
    except Exception:
        return None
    # Walk the whole document for the first plausible "total VRAM in bytes".
    # rocm-smi says "VRAM Total Memory (B)"; amd-smi nests it under vram.size
    # and reports MB. Rather than hardcode a path that changes every release,
    # find any key that mentions vram/total and sanity-check the magnitude.
    best = 0
    for key, val in _walk(data):
        k = key.lower()
        if "vram" not in k and "total" not in k:
            continue
        try:
            n = int(float(str(val).strip()))
        except (TypeError, ValueError):
            continue
        if 1 <= n < 1024 * 1024:          # looks like MB
            n *= 1024 * 1024
        if 2 * 1024**3 <= n <= 512 * 1024**3:
            best = max(best, n)
    if not best:
        return None
    return {"vendor": AMD, "name": _first_str(data, "AMD GPU"), "vram_bytes": best}


def _walk(obj, prefix=""):
    """Yield (key, scalar) for every leaf in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, prefix)
    else:
        yield prefix, obj


def _first_str(data, default):
    for key, val in _walk(data):
        if isinstance(val, str) and re.search(r"radeon|instinct|arc|geforce", val, re.I):
            return val.strip()
    return default


def _probe_intel():
    ok, out = _run(["xpu-smi", "discovery", "-j"])
    if ok and out.strip():
        try:
            data = json.loads(out)
        except Exception:
            data = None
        if data:
            for key, val in _walk(data):
                if "memory" in key.lower() and "physical" in key.lower():
                    try:
                        n = int(float(str(val)))
                    except (TypeError, ValueError):
                        continue
                    if 1 <= n < 1024 * 1024:
                        n *= 1024 * 1024
                    if n >= 2 * 1024**3:
                        return {"vendor": INTEL, "name": _first_str(data, "Intel GPU"),
                                "vram_bytes": n, "source": "xpu-smi"}
    return None


_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _probe_windows_registry():
    """Vendor-neutral Windows fallback.

    Every display driver writes HardwareInformation.qwMemorySize under its
    display-class key. This is the only probe here that works with no vendor
    tooling installed at all, which is exactly the situation on a fresh AMD or
    Intel box before ROCm / oneAPI is set up. (Win32_VideoController.AdapterRAM
    is NOT usable for this -- it is a uint32 and saturates at 4 GB.)
    """
    if not _IS_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:
        return None
    best = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as root:
            for i in range(16):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not re.fullmatch(r"\d{4}", sub):
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        size = int(winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0])
                        desc = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                except (OSError, ValueError, TypeError):
                    continue
                if size < 2 * 1024**3:
                    continue
                if best is None or size > best["vram_bytes"]:
                    best = {"vendor": _vendor_from_name(desc), "name": desc,
                            "vram_bytes": size, "source": "windows-registry"}
    except OSError:
        return None
    return best


def _vendor_from_name(name):
    n = (name or "").lower()
    if re.search(r"nvidia|geforce|rtx|gtx|quadro|tesla", n):
        return NVIDIA
    if re.search(r"amd|radeon|instinct|firepro", n):
        return AMD
    if re.search(r"intel|arc|iris|uhd graphics", n):
        return INTEL
    return UNKNOWN


def _probe_torch(python_exe=None):
    """Last resort, and the slowest: ask PyTorch itself.

    A ROCm build of torch reports through torch.cuda (HIP is mapped onto the
    cuda namespace), so torch.cuda.is_available() being True does NOT mean the
    card is NVIDIA -- torch.version.hip is what distinguishes them. Intel uses
    the separate torch.xpu namespace.
    """
    exe = python_exe or sys.executable
    code = (
        "import json,torch;"
        "d={'hip':bool(getattr(torch.version,'hip',None)),'cuda':False,'xpu':False,"
        "'name':'','bytes':0};"
        "d['cuda']=torch.cuda.is_available();"
        "d['xpu']=bool(getattr(torch,'xpu',None) and torch.xpu.is_available());"
        "p=(torch.cuda.get_device_properties(0) if d['cuda'] else"
        " (torch.xpu.get_device_properties(0) if d['xpu'] else None));"
        "d['name']=getattr(p,'name','') if p else '';"
        "d['bytes']=int(getattr(p,'total_memory',0)) if p else 0;"
        "print(json.dumps(d))"
    )
    ok, out = _run([exe, "-c", code], timeout=90)
    if not ok or not out.strip():
        return None
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return None
    if not d.get("bytes"):
        return None
    vendor = INTEL if d.get("xpu") else (AMD if d.get("hip") else NVIDIA)
    return {"vendor": vendor, "name": d.get("name") or f"{vendor} GPU",
            "vram_bytes": int(d["bytes"]), "source": "torch"}


def detect(refresh=False, python_exe=None, log=None):
    """Identify the accelerator once and cache it.

    Probe order is cheapest-and-most-specific first. The registry probe sits
    ABOVE torch on purpose: it is instant, needs nothing installed, and answers
    on all three vendors, whereas the torch probe costs an interpreter start
    and is the thing we are often trying to decide whether to install.

    Always returns a dict. 'confident' is False when no probe could size the
    card -- callers must branch on that rather than on vram_bytes == 0.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache
    found = None
    for probe in (_probe_nvidia, _probe_amd, _probe_intel, _probe_windows_registry):
        try:
            found = probe()
        except Exception:
            found = None
        if found:
            break
    if not found:
        try:
            found = _probe_torch(python_exe)
        except Exception:
            found = None
    if not found:
        found = {"vendor": NONE, "name": "no GPU detected", "vram_bytes": 0,
                 "source": "none"}
    found["confident"] = bool(found.get("vram_bytes"))
    found["vram_gb"] = round(found["vram_bytes"] / 1024**3, 1)
    found.update(_derive(found["vendor"]))
    _cache = found
    if log:
        log(describe(found), "info" if found["confident"] else "warn")
    return found


# What each vendor needs, in one table instead of scattered through the
# launcher. torch_device is "cuda" for AMD as well: a ROCm build of PyTorch
# exposes HIP devices through the cuda namespace, so device="cuda" is correct
# there and only Intel needs a different string.
_DERIVED = {
    NVIDIA: {
        "torch_device": "cuda",
        "torch_index_url": "https://download.pytorch.org/whl/cu128",
        "comfy_launchers": ["run_nvidia_gpu.bat"],
        "whisper_backend": "faster-whisper",
        "smi": "nvidia-smi",
    },
    AMD: {
        "torch_device": "cuda",
        "torch_index_url": "https://download.pytorch.org/whl/rocm6.2",
        "comfy_launchers": ["run_amd_gpu.bat", "run_rocm_gpu.bat", "run_cpu.bat"],
        # faster-whisper is CTranslate2, which has no ROCm backend. whisper.cpp
        # over Vulkan needs no vendor SDK at all, which matches how Ollama is
        # best run on AMD anyway.
        "whisper_backend": "whisper.cpp-vulkan",
        "smi": "rocm-smi",
    },
    INTEL: {
        "torch_device": "xpu",
        "torch_index_url": "https://download.pytorch.org/whl/xpu",
        "comfy_launchers": ["run_intel_gpu.bat", "run_cpu.bat"],
        "whisper_backend": "whisper.cpp-vulkan",
        "smi": "xpu-smi",
    },
}

_CPU_DERIVED = {
    "torch_device": "cpu",
    "torch_index_url": "https://download.pytorch.org/whl/cpu",
    "comfy_launchers": ["run_cpu.bat"],
    "whisper_backend": "faster-whisper",   # CPU int8; works everywhere
    "smi": "",
}


def _derive(vendor):
    return dict(_DERIVED.get(vendor, _CPU_DERIVED))


# ── Accessors the launcher calls ─────────────────────────────────────────────

def vram_bytes(default=0):
    """Total VRAM. Returns `default` when nothing could size the card.

    Callers that route on capacity should pass a default they can reason about,
    or check confident() first. Returning a bare 0 is what made the old
    nvidia-smi-only version fail silently.
    """
    g = detect()
    return g["vram_bytes"] if g["confident"] else default


def confident():
    return bool(detect()["confident"])


def vendor():
    return detect()["vendor"]


def torch_device():
    return detect()["torch_device"]


def torch_index_url():
    return detect()["torch_index_url"]


def comfy_launchers():
    return list(detect()["comfy_launchers"])


def whisper_backend():
    return detect()["whisper_backend"]


def describe(g=None):
    g = g or detect()
    if not g["confident"]:
        return (f"GPU: {g['name']} — VRAM UNKNOWN (no probe answered; tried "
                f"nvidia-smi, amd-smi/rocm-smi, xpu-smi, registry, torch). "
                f"Model fit-routing will fall back to size heuristics.")
    return (f"GPU: {g['name']} — {g['vram_gb']} GB, vendor={g['vendor']}, "
            f"via {g['source']}; torch device={g['torch_device']}, "
            f"whisper={g['whisper_backend']}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Report the accelerator ND will use.")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--all-probes", action="store_true",
                    help="run every probe and show which ones answered")
    a = ap.parse_args()

    if a.all_probes:
        for fn in (_probe_nvidia, _probe_amd, _probe_intel,
                   _probe_windows_registry, _probe_torch):
            name = fn.__name__.replace("_probe_", "")
            try:
                got = fn()
            except Exception as e:
                print(f"  {name:<18} EXCEPTION {e}")
                continue
            if got:
                gb = round(got["vram_bytes"] / 1024**3, 1)
                print(f"  {name:<18} {got['vendor']:<8} {gb} GB  ({got['name']})")
            else:
                print(f"  {name:<18} —")
        print()

    g = detect()
    print(json.dumps(g, indent=2) if a.json else describe(g))
    sys.exit(0 if g["confident"] else 1)
