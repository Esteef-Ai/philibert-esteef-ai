"""The picture engine (ComfyUI) watched and stopped from Philibert (dev/patching.py IMAGEGEN_ENGINE hooks it into
nd_imagegen: _call, _run_prompt, start and handle).

- ComfyUI's reasons: when it turns a picture down (HTTP 400), the person sees why ("Leave out: value not in list:
  ckpt_name 'x.safetensors'"), not "HTTP Error 400: Bad Request". A model the engine had not seen yet (added while
  it ran; on an exFAT drive ComfyUI's file list does not notice) restarts the engine once and tries again.
- One picture at a time: a second request while one is drawing (a double click, Refine while MAKE IT runs, the
  phone and the desktop at once) is told so, instead of queueing behind it unseen.
- STOP: the picture being drawn is interrupted, anything waiting in ComfyUI's queue (the ComfyUI editor's too) is
  cleared, and the request that waits for it returns "Stopped.". UNLOAD gives the graphics card back and leaves the
  engine running; TURN OFF ends the engine (also one an earlier Philibert left running, found by its port and its
  Python - nothing else is ever stopped).

    handle(op, body, root) -> dict       ops: engine, halt, unload, engine_stop
"""
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_lock = threading.Lock()                  # held while a picture is drawn (submit .. result)
_now = {"what": "", "since": 0.0, "prompt_id": "", "run": 0}
_halt = {"run": -1}                       # the run STOP was pressed for
_root = {"path": None}


def _ig():
    import nd_imagegen
    return nd_imagegen


def seen_root(root):
    _root["path"] = root


# --- ComfyUI's own answers ------------------------------------------------------------------
def reason(code, raw):
    """ComfyUI's error body -> one readable line (it says which node and which value)."""
    try:
        d = json.loads(raw)
    except ValueError:
        return f"ComfyUI answered {code}: {raw[:200].decode('utf-8', 'replace') if isinstance(raw, bytes) else raw[:200]}"
    e = d.get("error") if isinstance(d, dict) else None
    head = (e.get("message") if isinstance(e, dict) else str(e or "")) or f"it answered {code}"
    bits = []
    for node in (d.get("node_errors") or {}).values() if isinstance(d, dict) else []:
        for x in node.get("errors") or []:
            bits.append(f"{node.get('class_type', '?')}: {x.get('message', '')}" + (f" ({x['details']})" if x.get("details") else ""))
    if not bits and isinstance(e, dict) and e.get("details"):
        bits.append(str(e["details"]))
    return "ComfyUI turned the picture down: " + head + (" - " + "; ".join(bits) if bits else "")


class Refused(RuntimeError):
    def __init__(self, msg, kinds):
        super().__init__(msg)
        self.kinds = kinds


def call(path, payload=None, timeout=30):
    req = urllib.request.Request(_ig().URL + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        kinds = set()
        try:
            for node in (json.loads(raw).get("node_errors") or {}).values():
                kinds |= {x.get("type", "") for x in node.get("errors") or []}
        except (ValueError, AttributeError):
            pass
        raise Refused(reason(e.code, raw), kinds) from None
    return json.loads(raw) if raw.strip() else {}


# --- one picture at a time, and STOP --------------------------------------------------------
def run_prompt(wf, timeout):
    ig = _ig()
    if not _lock.acquire(blocking=False):
        took = int(time.time() - _now["since"])
        raise RuntimeError(f"A picture is being drawn already ({_now['what'] or 'started'} {took}s ago). "
                           "Wait for it, or press STOP beside ENGINE.")
    try:
        _now.update(run=_now["run"] + 1, since=time.time(), prompt_id="", what=_what(wf))
        me = _now["run"]
        try:
            pid = call("/prompt", {"prompt": wf, "client_id": "philibert-" + str(me)})["prompt_id"]
        except Refused as e:
            if "value_not_in_list" not in e.kinds or not _root["path"]:
                raise
            # a model file the engine has not seen since it started: start it again, once, and resubmit
            ig.stop()
            ig.start(_root["path"])
            pid = call("/prompt", {"prompt": wf, "client_id": "philibert-" + str(me)})["prompt_id"]
        _now["prompt_id"] = pid
        t0 = time.time()
        while time.time() - t0 < timeout:
            if _halt["run"] == me:
                for path, body in (("/queue", {"delete": [pid]}), ("/interrupt", {"prompt_id": pid})):
                    try:                        # STOP came between the submit and the queue being emptied
                        call(path, body, timeout=6)
                    except Exception:
                        pass
                raise RuntimeError("Stopped.")
            hist = call(f"/history/{pid}").get(pid)
            if hist:
                st = hist.get("status") or {}
                if st.get("status_str") == "error":
                    if _halt["run"] == me or any(m[0] == "execution_interrupted" for m in st.get("messages", [])):
                        raise RuntimeError("Stopped.")
                    msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError("ComfyUI said: " + ("; ".join(msgs) or "it failed")[:300])
                imgs = [im for out in (hist.get("outputs") or {}).values() for im in (out.get("images") or [])]
                if imgs or st.get("completed"):
                    return imgs
            time.sleep(0.7)
        raise RuntimeError("The picture took too long.")
    finally:
        _now.update(what="", prompt_id="", since=0.0)
        _lock.release()


def _what(wf):
    kinds = {n.get("class_type") for n in wf.values()}
    if "ImageUpscaleWithModel" in kinds:
        return "a 4x enlargement"
    n = max([int(n["inputs"].get("batch_size") or n["inputs"].get("amount") or 1) for n in wf.values()
             if n.get("class_type") in ("EmptyLatentImage", "EmptySD3LatentImage", "RepeatLatentBatch")] or [1])
    return ("a refined picture" if "LoadImage" in kinds else "a picture") if n == 1 else f"{n} pictures"


def busy():
    return _lock.locked()


# --- the panel's ops --------------------------------------------------------------------------
def _queue():
    try:
        q = call("/queue", timeout=4)
        return len(q.get("queue_running") or []), len(q.get("queue_pending") or [])
    except Exception:
        return None, None


def _card():
    try:
        d = (call("/system_stats", timeout=4).get("devices") or [{}])[0]
    except Exception:
        return {}
    gb = lambda b: round((b or 0) / 1e9, 1)                                   # noqa: E731
    return {"name": d.get("name", ""), "total_gb": gb(d.get("vram_total")), "free_gb": gb(d.get("vram_free")),
            "engine_gb": gb((d.get("torch_vram_total") or 0) - (d.get("torch_vram_free") or 0))}


def _orphan(root):
    """The engine's process when an earlier Philibert started it (this one has no handle on it): the process that
    listens on the engine's port AND runs the drive's own ComfyUI Python. None for anything else."""
    try:
        import psutil
    except ImportError:
        return None
    ig = _ig()
    want = Path(ig.paths(root)["py"]).resolve()
    try:
        conns = psutil.net_connections("tcp")
    except (psutil.AccessDenied, OSError):
        return None
    for c in conns:
        if c.laddr and c.laddr.port == ig.PORT and c.status == psutil.CONN_LISTEN and c.pid:
            try:
                p = psutil.Process(c.pid)
                if Path(p.exe()).resolve() == want:
                    return p
            except (psutil.Error, OSError):
                continue
    return None


def status(root):
    ig = _ig()
    if ig.remote_models() is not None:
        return {"ok": True, "remote": ig.REMOTE.get("name") or "your other computer", "running": False}
    run = ig.running()
    out = {"ok": True, "running": run, "drawing": busy(), "what": _now["what"],
           "seconds": int(time.time() - _now["since"]) if busy() and _now["since"] else 0}
    if run:
        out["running_n"], out["waiting_n"] = _queue()
        out["card"] = _card()
        out["ours"] = bool(ig._proc and ig._proc.poll() is None) or _orphan(root) is not None
    return out


def halt():
    """Stop the picture being drawn and empty ComfyUI's queue."""
    ig = _ig()
    was = busy()
    if was:
        _halt["run"] = _now["run"]
    cleared = 0
    if ig.running():
        _r, cleared = _queue()
        for path, body in (("/queue", {"clear": True}), ("/interrupt", {})):
            try:
                call(path, body, timeout=6)
            except Exception:
                pass
    end = time.time() + 8                       # the drawing request notices within a second
    while was and busy() and time.time() < end:
        time.sleep(0.2)
    return {"ok": True, "stopped": was, "cleared": cleared or 0,
            "msg": ("Stopped." if was else "Nothing was being drawn.") + (f" {cleared} waiting cleared." if cleared else "")}


def unload():
    ig = _ig()
    if not ig.running():
        return {"ok": True, "msg": "The picture engine is off: the graphics card is free."}
    if busy():
        return {"ok": False, "msg": "A picture is being drawn: STOP it first."}
    try:
        call("/free", {"unload_models": True, "free_memory": True}, timeout=20)
    except Exception as e:
        return {"ok": False, "msg": f"ComfyUI did not let go: {e}"}
    return {"ok": True, "msg": "Picture models unloaded: the graphics card is free. The engine stays on."}


def engine_stop(root):
    ig = _ig()
    h = halt() if busy() else None
    if ig._proc and ig._proc.poll() is None:
        ig.stop()
    else:
        p = _orphan(root)
        if p:
            p.terminate()
            try:
                p.wait(10)
            except Exception:
                p.kill()
        elif ig.running():
            return {"ok": False, "msg": "Something else is answering on the picture engine's port; Philibert left it alone."}
    return {"ok": True, "msg": ("Stopped, and " if h and h.get("stopped") else "") + "The picture engine is off."}


def handle(op, body, root):
    if op == "engine":
        return status(root)
    if op == "halt":
        return halt()
    if op == "unload":
        return unload()
    if op == "engine_stop":
        return engine_stop(root)
    return {"ok": False, "msg": f"unknown op {op!r}"}
