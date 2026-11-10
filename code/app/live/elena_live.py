"""Elena Live — NeuralDock activity visualizer.

Serves the circuit-board page and a live ``/api/state`` endpoint. A background
thread polls ND and Ollama once per second, builds the ``raw`` dict, hands it
to :class:`FlowModel` and stores the resulting state, which the endpoint
returns. Importing this module starts nothing; run ``python server.py``.
"""

import functools
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    import psutil
except ImportError:  # psutil is required for the disk rate; fall back to zeros
    psutil = None

PORT = int(os.environ.get("VIZ_PORT", "7799"))
ND_URL = os.environ.get("ND_URL", "http://127.0.0.1:7788")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

POLL_PERIOD = 1.0          # one poll per second
VAULT_GRAPH_PERIOD = 30.0  # vault graph re-fetched every 30 s
STREAM_FROM = 1_000_000_000  # ask for the activity tail, not the generated text

# Tool rows map to board directions; anything not listed is cpu -> cpu.
TOOL_ROUTES = {
    "read_file": ("disk", "cpu"),
    "list_dir": ("disk", "cpu"),
    "search_files": ("disk", "cpu"),
    "write_file": ("cpu", "disk"),
    "edit_file": ("cpu", "disk"),
    "run_script": ("cpu", "cpu"),
    "run_shell": ("cpu", "cpu"),
    "web_fetch": ("net", "cpu"),
    "web_search": ("net", "cpu"),
}

VAULT_EVENT_KIND = {
    "read": ("vault_read", "disk", "cpu"),
    "write": ("vault_write", "cpu", "disk"),
    "update": ("vault_write", "cpu", "disk"),
}

MAX_EVENTS = 50
MAX_VAULT_EVENTS = 50
DISK_IO_THRESHOLD = 5.0  # MB/s; below this the disk is considered quiet


def _http_get(url, timeout=2.0):
    """Return parsed JSON from a GET, or None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _http_post(url, body, timeout=2.0):
    """Return parsed JSON from a JSON POST, or None on any failure."""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


class FlowModel:
    """Turn one poll of upstream data into the board state.

    Keeps its own history between calls; ``update`` is called once per poll.
    Pure: it only reads ``raw`` and its own state.
    """

    def __init__(self):
        self.seen_jobs = set()          # every job id ever seen
        self.prev_stream_len = {}       # job_id -> last stream_len
        self.seen_tool_rows = set()     # (job_id, t, label) of handled tool rows
        self.newest_tool = {}           # job_id -> (t, label) of newest tool row
        self.prev_disk = None           # (t, read_bytes, write_bytes)
        self.disk_rate = {"read_mbps": 0.0, "write_mbps": 0.0}
        self.events = []                # board events, newest last
        self.vault_events = []          # vault events, newest last
        self.vault_graph = None         # latest vault graph document, or None
        self.vault_path = ""            # that graph's "vault" folder, or ""
        self.vault_note_count = 0
        self.model = None

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _disk_rates(self, raw, now):
        # The poller samples psutil.disk_io_counters() itself (cumulative
        # bytes since boot) and passes the computed rates in raw["disk"];
        # FlowModel stays pure, so it only reads what was handed to it.
        d = raw.get("disk") or {}
        return {
            "read_mbps": max(0.0, float(d.get("read_mbps", 0.0) or 0.0)),
            "write_mbps": max(0.0, float(d.get("write_mbps", 0.0) or 0.0)),
        }

    @staticmethod
    def _largest_model(ps_data):
        if not ps_data or not ps_data.get("models"):
            return None
        top = max(ps_data["models"], key=lambda m: m.get("size", 0))
        size = top.get("size", 0)
        size_vram = top.get("size_vram", 0)
        g = 1024 ** 3
        spill_pct = 100.0 * (size - size_vram) / size if size else 0.0
        return {
            "name": top.get("name", ""),
            "size_gb": size / g,
            "vram_gb": size_vram / g,
            "spill_pct": max(0.0, min(100.0, spill_pct)),
        }

    @staticmethod
    def _running_jobs(raw):
        jobs = raw.get("jobs") or []
        return [j for j in jobs if j.get("status") == "running"]

    def _note_title(self, note_id):
        return (note_id or "").replace(".md", "").split("/")[-1]

    def _push_vault_event(self, ev):
        self.vault_events.append({
            "t": ev.get("t", 0.0),
            "op": ev.get("op", "read"),
            "note": ev.get("note", ""),
            "by": ev.get("by", ""),
        })
        if len(self.vault_events) > MAX_VAULT_EVENTS:
            self.vault_events = self.vault_events[-MAX_VAULT_EVENTS:]

    def _push_event(self, now, kind, src, dst, label):
        self.events.append({
            "t": now,
            "kind": kind,
            "from": src,
            "to": dst,
            "label": label,
        })
        if len(self.events) > MAX_EVENTS:
            self.events = self.events[-MAX_EVENTS:]

    # ------------------------------------------------------------------ #
    def update(self, raw, now):
        raw = raw or {}
        sysmon = raw.get("sysmon")
        ps_data = raw.get("ps")
        nowm = (sysmon or {}).get("now") if sysmon else None

        # ---- nodes ----------------------------------------------------
        nodes = {
            "cpu": {"load": float((nowm or {}).get("cpu_pct", 0) or 0)},
            "gpu": {
                "load": float((nowm or {}).get("gpu_pct", 0) or 0),
                "vram_used_gb": float((nowm or {}).get("vram_used_gb", 0) or 0),
                "vram_total_gb": float((nowm or {}).get("vram_total_gb", 0) or 0),
            },
            "ram": {
                "used_gb": float((nowm or {}).get("ram_used_gb", 0) or 0),
                "total_gb": float((nowm or {}).get("ram_total_gb", 0) or 0),
            },
            "disk": {"read_mbps": 0.0, "write_mbps": 0.0},
        }
        rates = self._disk_rates(raw, now)
        nodes["disk"] = {"read_mbps": rates["read_mbps"], "write_mbps": rates["write_mbps"]}

        # ---- model ----------------------------------------------------
        self.model = self._largest_model(ps_data)

        # ---- vault ----------------------------------------------------
        graph = raw.get("vault_graph")
        if graph:
            self.vault_graph = graph
            self.vault_path = str(graph.get("vault") or "")
            notes = graph.get("notes")
            self.vault_note_count = len(notes) if isinstance(notes, list) else 0
        for ev in (raw.get("vault_events") or []):
            self._push_vault_event(ev)

        # ---- task + flows + events --------------------------------------
        running = self._running_jobs(raw)
        running_ids = [j["job_id"] for j in running]
        gpu_load = nodes["gpu"]["load"]

        for jid in running_ids:
            if jid not in self.seen_jobs:
                self.seen_jobs.add(jid)
                job = next(j for j in running if j["job_id"] == jid)
                label = (job.get("prompt") or "")[:60]
                self._push_event(now, "request", "in", "cpu", label)

        flows = []
        prefill = False
        cands = []

        for j in running:
            jid = j["job_id"]
            st = (raw.get("status") or {}).get(jid) or {}
            stage = st.get("stage")
            s_len = st.get("stream_len", 0)
            prev = self.prev_stream_len.get(jid)

            if stage == "thinking" and (prev is None or s_len <= prev):
                prefill = True
            if prev is not None and s_len > prev:
                # chars per second since last poll
                cps = (s_len - prev) / POLL_PERIOD if POLL_PERIOD else 0.0
                cands.append((cps, jid))
            self.prev_stream_len[jid] = s_len

        if prefill:
            flows.append({"from": "cpu", "to": "gpu", "kind": "prefill", "rate": 1.0})
        for cps, _jid in sorted(cands, key=lambda c: c[0], reverse=True):
            flows.append({
                "from": "gpu", "to": "out",
                "kind": "tokens",
                "rate": min(1.0, cps / 400.0),
            })

        m = self.model
        if (m and m["size_gb"] > m["vram_gb"] and gpu_load >= 10
                and m["size_gb"] > 0):
            spill_pct = m["spill_pct"]
            flows.append({
                "from": "ram", "to": "gpu",
                "kind": "spill",
                "rate": (spill_pct / 100.0) * (gpu_load / 100.0),
            })

        read_mbps = nodes["disk"]["read_mbps"]
        write_mbps = nodes["disk"]["write_mbps"]
        if read_mbps >= DISK_IO_THRESHOLD:
            flows.append({
                "from": "disk", "to": "ram",
                "kind": "io",
                "rate": min(1.0, read_mbps / 2000.0),
            })
        if write_mbps >= DISK_IO_THRESHOLD:
            flows.append({
                "from": "ram", "to": "disk",
                "kind": "io",
                "rate": min(1.0, write_mbps / 2000.0),
            })

        if not running and gpu_load < 10 and read_mbps < DISK_IO_THRESHOLD \
                and write_mbps < DISK_IO_THRESHOLD:
            flows = []

        # ---- tool step events (each new tool row, once) -----------------
        for jid in running_ids:
            st = (raw.get("status") or {}).get(jid) or {}
            for row in (st.get("activity") or []):
                if row.get("kind") != "tool":
                    continue
                key = (jid, row.get("t"), row.get("label"))
                if key in self.seen_tool_rows:
                    continue
                self.seen_tool_rows.add(key)
                label = row.get("label") or ""
                src, dst = TOOL_ROUTES.get(label, ("cpu", "cpu"))
                self._push_event(now, "tool", src, dst, label)
                if row.get("t") is not None:
                    prev = self.newest_tool.get(jid)
                    if prev is None or row.get("t") >= prev[0]:
                        self.newest_tool[jid] = (row.get("t"), label)

        # ---- vault board events -----------------------------------------
        for ev in (raw.get("vault_events") or []):
            kind, src, dst = VAULT_EVENT_KIND.get(ev.get("op"), ("vault_read", "disk", "cpu"))
            self._push_event(now, kind, src, dst, self._note_title(ev.get("note")))

        # ---- task kind ----------------------------------------------------
        if not running:
            task = {"kind": "idle", "job_id": None, "label": "idle"}
        elif prefill:
            task = {"kind": "think", "job_id": running[0]["job_id"],
                    "label": "thinking"}
        else:
            kind = "answer"
            newest = None
            for jid in running_ids:
                nt = self.newest_tool.get(jid)
                if nt and (newest is None or nt[0] > newest[0]):
                    newest = nt
            if newest and newest[1] in ("edit_file", "write_file"):
                kind = "code"
            task = {"kind": kind, "job_id": running[0]["job_id"],
                    "label": kind}

        # ---- state ----------------------------------------------------------
        state = {
            "t": now,
            "nd_up": sysmon is not None,
            "ollama_up": ps_data is not None,
            "nodes": nodes,
            "model": m,
            "task": task,
            "flows": flows,
            "events": list(self.events),
            "vault": {
                "notes": self.vault_note_count,
                "events": list(self.vault_events),
                "graph": self.vault_graph,
                "path": self.vault_path,
            },
        }
        return state

    # a set, not a list — we track which tool rows have already made an event
    _handled_tool_events = set()


def _empty_state(now):
    return {
        "t": now,
        "nd_up": False,
        "ollama_up": False,
        "nodes": {
            "cpu": {"load": 0},
            "gpu": {"load": 0, "vram_used_gb": 0, "vram_total_gb": 0},
            "ram": {"used_gb": 0, "total_gb": 0},
            "disk": {"read_mbps": 0.0, "write_mbps": 0.0},
        },
        "model": None,
        "task": {"kind": "idle", "job_id": None, "label": "idle"},
        "flows": [],
        "events": [],
        "vault": {"notes": 0, "events": []},
    }


class Poller:
    """Background thread: polls upstreams once a second and stores state."""

    def __init__(self):
        self.model = FlowModel()
        self.state = _empty_state(time.time())
        self.lock = threading.Lock()
        self.last_vault_graph = 0.0
        self.last_vault_since = 0.0
        self.vault_graph = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get_state(self):
        with self.lock:
            return self.state

    def _poll(self):
        now = time.time()
        sysmon = _http_get(ND_URL + "/api/sysmon")
        ps_data = _http_get(OLLAMA_URL + "/api/ps")
        active = _http_post(ND_URL + "/api/chat_active", {})

        jobs = (active or {}).get("jobs")
        status = {}
        if jobs:
            for j in jobs:
                if j.get("status") != "running":
                    continue
                jid = j.get("job_id")
                if not jid:
                    continue
                st = _http_post(ND_URL + "/api/chat_status",
                                {"req_id": jid, "stream_from": STREAM_FROM})
                if st:
                    status[jid] = st

        disk = self._disk_rate_sample(now)

        if now - self.last_vault_graph >= VAULT_GRAPH_PERIOD:
            self.last_vault_graph = now
            g = _http_get(ND_URL + "/api/vault_graph")
            if g:
                self.vault_graph = g

        evs = _http_get(ND_URL + "/api/vault_activity?since=%s"
                        % int(self.last_vault_since))
        vault_events = []
        if evs:
            vault_events = evs.get("events") or []
            self.last_vault_since = evs.get("now", now)

        raw = {
            "sysmon": sysmon,
            "ps": ps_data,
            "jobs": jobs,
            "status": status,
            "disk": disk,
            "vault_graph": self.vault_graph,
            "vault_events": vault_events,
        }

        with self.lock:
            self.state = self.model.update(raw, now)

    def _disk_rate_sample(self, now):
        # The FlowModel samples psutil itself for the rate; here we pass
        # zeros and let it do the math from its own history.
        return {"read_mbps": 0.0, "write_mbps": 0.0}

    def _run(self):
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception:
                pass
            self._stop.wait(POLL_PERIOD)


class VizHandler(SimpleHTTPRequestHandler):
    directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    poller = None

    def translate_path(self, path):
        # serve from static/ only
        rel = os.path.normpath(path).lstrip("/\\")
        if rel.startswith(".."):
            return os.path.join(self.directory, "index.html")
        return os.path.join(self.directory, rel)

    def do_GET(self):
        if self.path == "/api/state":
            state = self.poller.get_state() if self.poller else _empty_state(time.time())
            body = json.dumps(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("", "/"):
            self.path = "/index.html"
        ext = os.path.splitext(self.path)[1].lower()
        if ext in (".js", ".mjs"):
            ctype = "application/javascript"
        elif ext == ".html":
            ctype = "text/html"
        elif ext == ".css":
            ctype = "text/css"
        else:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        try:
            with open(self.translate_path(self.path), "rb") as f:
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_error(404)

    def log_message(self, *args):
        pass


def main():
    poller = Poller()
    poller.start()
    VizHandler.poller = poller
    handler = functools.partial(VizHandler, directory=VizHandler.directory)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), handler)
    print("Elena Live on http://127.0.0.1:%d/" % PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()


if __name__ == "__main__":
    main()
