"""TubeLoader (a Philibert app): find the TVs and streaming sticks on the home network and put an app
on one.

  Android TV / Google TV / Fire TV / SHIELD   an .apk (or a split .apks / .xapk) through ADB over Wi-Fi
  Roku (developer mode)                       a .zip channel through the Roku's own developer installer
  Apple TV, Samsung (Tizen), LG (webOS), old  found and explained: they can't take an APK
  Chromecasts

ADB is Google's own platform-tools, downloaded on first use (with the person's OK) into
<drive>/tools/platform-tools - never bundled. Finding devices: they are asked to announce themselves
(mDNS / DNS-SD and SSDP), the router's ARP table names the rest, and a few ports are tried (5555 ADB,
8060 Roku, the Samsung, LG and AirPlay ports) - only on this computer's own local network, never the
VPN or Tailscale.

When an install fails, Philibert assists: a table of known errors says what it means at once, then
the local model (Philibert's chat model) works it out with the person - what to do on the TV, and at
most one fix from a short list of safe ones (SAFE), which only runs when the person taps it. With no
model on the computer the assistant says so, suggests adding one, and the job ends with the table's
advice.

Entry point: handle(body, root, data_dir, llm) for /api/tubeloader; llm(messages) -> str, or None.
"""
import base64
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ADB_ZIP = {"win32": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
           "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
           "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"}
ADB_MB = 13
_lock = threading.Lock()
_jobs = {}                  # id -> Job
_scan = {"state": "idle", "progress": 0, "devices": [], "msg": ""}
_adb_dl = {"state": "idle", "pct": 0, "msg": ""}


def _platform():
    return "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"


# ======================================================================================================
# ADB: Google's platform-tools, fetched on first use
# ======================================================================================================
def adb_path(root):
    return Path(root) / "tools" / "platform-tools" / ("adb.exe" if _platform() == "win32" else "adb")


def adb_ready(root):
    return adb_path(root).is_file()


def adb_download(root):
    """Download and unpack platform-tools (background; _adb_dl reports progress)."""
    if _adb_dl["state"] == "running":
        return
    _adb_dl.update(state="running", pct=0, msg="Downloading Google's ADB tool…")

    def go():
        tools = Path(root) / "tools"
        part = tools / "platform-tools.zip.part"
        try:
            tools.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(ADB_ZIP[_platform()], headers={"User-Agent": "Philibert-TubeLoader"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0) or ADB_MB * 2**20
                got = 0
                while True:
                    b = r.read(256 * 1024)
                    if not b:
                        break
                    f.write(b)
                    got += len(b)
                    _adb_dl["pct"] = min(99, int(got * 100 / total))
            _adb_dl["msg"] = "Unpacking…"
            with zipfile.ZipFile(part) as z:
                for m in z.infolist():
                    if not m.filename.startswith("platform-tools/") or ".." in m.filename:
                        continue
                    z.extract(m, tools)
            part.unlink(missing_ok=True)
            if _platform() != "win32":
                for n in ("adb", "fastboot"):
                    p = tools / "platform-tools" / n
                    if p.exists():
                        p.chmod(0o755)
            if not adb_ready(root):
                raise RuntimeError("adb wasn't in the download")
            _adb_dl.update(state="done", pct=100, msg="ADB is ready.")
        except Exception as e:
            part.unlink(missing_ok=True)
            _adb_dl.update(state="error", msg=f"The download didn't work ({e}). Check the internet and try again.")

    threading.Thread(target=go, daemon=True).start()


def adb(root, *args, timeout=40):
    """Run adb -> (exit code, combined output)."""
    try:
        r = subprocess.run([str(adb_path(root)), *[str(a) for a in args]], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, f"adb {' '.join(map(str, args[:2]))} took longer than {timeout} s"
    except OSError as e:
        return 127, f"adb couldn't run ({e})"


# ======================================================================================================
# Finding devices
# ======================================================================================================
_SKIP_IF = re.compile(r"tailscale|vpn|tap|tun|wintun|openvpn|wireguard|pia|vethernet|hyper-v|virtualbox|vmware|"
                      r"wsl|docker|loopback|npcap|bluetooth|zerotier|hamachi", re.I)


def local_nets():
    """[(this computer's ip, the /24 around it)] on the real home network interfaces."""
    import psutil
    out = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if _SKIP_IF.search(name) or (name in stats and not stats[name].isup):
            continue
        for a in addrs:
            if a.family != socket.AF_INET:
                continue
            try:
                ip = ipaddress.ip_address(a.address)
            except ValueError:
                continue
            if not ip.is_private or ip.is_loopback or ip.is_link_local or ip in ipaddress.ip_network("100.64.0.0/10"):
                continue
            net = ipaddress.ip_network(f"{a.address}/24", strict=False)
            if all(net != n for _, n in out):
                out.append((str(ip), net))
    return out


def arp_table():
    """ip -> mac, from the computer's ARP cache."""
    out = {}
    try:
        r = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\D+?([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})", r.stdout or ""):
            mac = m.group(2).replace("-", ":").lower()
            if mac not in ("ff:ff:ff:ff:ff:ff",) and not mac.startswith("01:00:5e"):
                out[m.group(1)] = mac
    except Exception:
        pass
    return out


# who made the network card - a hint only (many sticks use a private, random address)
OUI = {
    "Roku": ["b0:a7:37", "d8:31:34", "ac:3a:7a", "cc:6d:a0", "dc:3a:5e", "88:de:a9", "b8:3e:59", "08:05:81"],
    "Amazon": ["44:65:0d", "68:54:fd", "f0:27:2d", "fc:65:de", "74:c2:46", "0c:47:c9", "a0:02:dc", "34:d2:70",
               "40:b4:cd", "84:d6:d0"],
    "Google": ["f4:f5:d8", "f4:f5:e8", "54:60:09", "1c:f2:9a", "3c:5a:b4", "6c:ad:f8", "d8:6c:63", "a4:77:33"],
    "NVIDIA": ["00:04:4b", "48:b0:2d"],
}


def vendor_of(mac):
    if not mac:
        return ""
    if int(mac[1], 16) & 2:
        return "(private address)"
    for v, prefixes in OUI.items():
        if mac[:8] in prefixes:
            return v
    return ""


PORTS = {5555: "adb", 8060: "roku", 8008: "cast", 8009: "cast", 8001: "samsung", 8002: "samsung",
         3000: "lg", 3001: "lg", 7000: "airplay", 6466: "androidtv", 6467: "androidtv"}


def _open(ip, port, t=0.4):
    try:
        with socket.create_connection((ip, port), timeout=t):
            return True
    except OSError:
        return False


def _wake_arp(net, mine):
    """A tiny UDP packet to every address, so the ARP table fills in with who is there."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for h in net.hosts():
        if str(h) != mine:
            try:
                s.sendto(b"\0", (str(h), 9))
            except OSError:
                pass
    s.close()


# ---- mDNS / DNS-SD ------------------------------------------------------------------------------------
MDNS_TYPES = ["_googlecast._tcp.local", "_androidtvremote2._tcp.local", "_adb-tls-connect._tcp.local",
              "_adb-tls-pairing._tcp.local", "_adb._tcp.local", "_amzn-wplay._tcp.local", "_airplay._tcp.local",
              "_companion-link._tcp.local", "_raop._tcp.local"]


def _qname(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"


def mdns_query(types, qu=True):
    q = struct.pack(">HHHHHH", 0, 0, len(types), 0, 0, 0)
    for t in types:
        q += _qname(t) + struct.pack(">HH", 12, 0x8001 if qu else 1)       # PTR, (unicast-response) IN
    return q


def _rname(buf, off, depth=0):
    labels = []
    while off < len(buf) and depth < 20:
        n = buf[off]
        if n == 0:
            return ".".join(labels), off + 1
        if n & 0xC0 == 0xC0:
            ptr = struct.unpack(">H", buf[off:off + 2])[0] & 0x3FFF
            name, _ = _rname(buf, ptr, depth + 1)
            return ".".join(labels + ([name] if name else [])), off + 2
        labels.append(buf[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    return ".".join(labels), off


def mdns_parse(buf):
    """-> [(type, name, data)]: PTR data = target, SRV = (port, target), TXT = {k: v}, A = ip."""
    out = []
    try:
        _, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", buf[:12])
        off = 12
        for _ in range(qd):
            _, off = _rname(buf, off)
            off += 4
        for _ in range(an + ns + ar):
            name, off = _rname(buf, off)
            rtype, _cls, _ttl, rlen = struct.unpack(">HHIH", buf[off:off + 10])
            off += 10
            rd = buf[off:off + rlen]
            if rtype == 12:
                out.append(("PTR", name, _rname(buf, off)[0]))
            elif rtype == 33 and rlen >= 6:
                out.append(("SRV", name, (struct.unpack(">H", rd[4:6])[0], _rname(buf, off + 6)[0])))
            elif rtype == 16:
                kv, i = {}, 0
                while i < len(rd):
                    n = rd[i]
                    s = rd[i + 1:i + 1 + n].decode("utf-8", "replace")
                    if "=" in s:
                        k, v = s.split("=", 1)
                        kv[k.lower()] = v
                    i += 1 + n
                out.append(("TXT", name, kv))
            elif rtype == 1 and rlen == 4:
                out.append(("A", name, socket.inet_ntoa(rd)))
            off += rlen
    except Exception:
        pass
    return out


def mdns_browse(mine_ips, wait=2.5):
    """ip -> {services: {type: {name, port, txt}}} from everything that answered."""
    found = {}
    socks = []
    for mine in mine_ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((mine, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(mine))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            s.setblocking(False)
            s.sendto(mdns_query(MDNS_TYPES), ("224.0.0.251", 5353))
            socks.append(s)
        except OSError:
            pass
    end = time.time() + wait
    import select
    while socks and time.time() < end:
        r, _, _ = select.select(socks, [], [], max(0.0, end - time.time()))
        for s in r:
            try:
                buf, (ip, _) = s.recvfrom(9000)
            except OSError:
                continue
            recs = mdns_parse(buf)
            dev = found.setdefault(ip, {"services": {}})
            inst = {}
            for typ, name, data in recs:
                if typ == "PTR" and data.endswith(name):
                    inst[data] = name
            for typ, name, data in recs:
                svc = inst.get(name) or next((t for t in MDNS_TYPES if name.endswith(t)), None)
                if not svc:
                    continue
                e = dev["services"].setdefault(svc.replace(".local", ""), {})
                # the device's own name: the instance part in front of the service type
                who = data if typ == "PTR" else name
                if isinstance(who, str) and who.endswith("." + svc) and not e.get("name"):
                    e["name"] = who[:-(len(svc) + 1)]
                if typ == "SRV":
                    e["port"] = data[0]
                elif typ == "TXT":
                    e["txt"] = data
    for s in socks:
        s.close()
    return found


# ---- SSDP / UPnP -------------------------------------------------------------------------------------
def ssdp_browse(mine_ips, wait=2.5):
    """ip -> {server, location, st} from M-SEARCH answers (Roku answers roku:ecp)."""
    found = {}
    socks = []
    for mine in mine_ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.bind((mine, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.setblocking(False)
            for st in ("ssdp:all", "roku:ecp"):
                msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                       f"MX: 2\r\nST: {st}\r\n\r\n").encode()
                s.sendto(msg, ("239.255.255.250", 1900))
            socks.append(s)
        except OSError:
            pass
    end = time.time() + wait
    import select
    while socks and time.time() < end:
        r, _, _ = select.select(socks, [], [], max(0.0, end - time.time()))
        for s in r:
            try:
                buf, (ip, _) = s.recvfrom(4096)
            except OSError:
                continue
            h = {}
            for line in buf.decode("utf-8", "replace").split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    h[k.strip().lower()] = v.strip()
            d = found.setdefault(ip, {"server": "", "locations": [], "st": []})
            d["server"] = d["server"] or h.get("server", "")
            if h.get("location") and h["location"] not in d["locations"]:
                d["locations"].append(h["location"])
            if h.get("st"):
                d["st"].append(h["st"])
    for s in socks:
        s.close()
    return found


def _xml_tags(text, *tags):
    out = {}
    for t in tags:
        m = re.search(rf"<{t}>([^<]*)</{t}>", text or "", re.I)
        if m:
            out[t] = m.group(1).strip()
    return out


def _get(url, timeout=2.0):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Philibert-TubeLoader"}),
                                    timeout=timeout) as r:
            return r.read(200000).decode("utf-8", "replace")
    except Exception:
        return ""


def roku_info(ip):
    x = _get(f"http://{ip}:8060/query/device-info")
    if not x:
        return {}
    t = _xml_tags(x, "friendly-device-name", "user-device-name", "model-name", "model-number", "is-tv",
                  "developer-enabled", "software-version", "vendor-name")
    return t


def upnp_info(location):
    t = _xml_tags(_get(location), "friendlyName", "manufacturer", "modelName", "modelNumber", "modelDescription")
    return t


def _hostname(ip):
    try:
        n = socket.gethostbyaddr(ip)[0]
        return "" if n == ip else n.split(".")[0]
    except OSError:
        return ""


# ---- what each device is -------------------------------------------------------------------------------
KINDS = {
    "firetv": "Fire TV", "googletv": "Google TV", "androidtv": "Android TV", "shield": "NVIDIA SHIELD",
    "roku": "Roku", "appletv": "Apple TV", "samsung": "Samsung TV", "lg": "LG TV", "chromecast": "Chromecast",
    "other": "Other device",
}
APK_KINDS = {"firetv", "googletv", "androidtv", "shield"}


def classify(d):
    """d: the evidence for one ip -> d with kind, name, model, accepts ('apk' | 'zip' | ''), status, note."""
    svc = d.get("mdns", {}).get("services", {})
    ports = set(d.get("ports", []))
    up = d.get("upnp", {})
    srv = (d.get("ssdp", {}) or {}).get("server", "")
    host = d.get("hostname", "")
    vend = d.get("vendor", "")
    cast = (svc.get("_googlecast._tcp") or {}).get("txt", {})
    cast_md = cast.get("md", "")
    air = (svc.get("_airplay._tcp") or {}).get("txt", {})
    st = " ".join((d.get("ssdp", {}) or {}).get("st", []))
    blob = " ".join([host, srv, up.get("manufacturer", ""), up.get("modelName", ""), up.get("friendlyName", ""),
                     cast_md, vend, air.get("manufacturer", ""), air.get("model", ""), st]).lower()
    name = (d.get("roku", {}).get("user-device-name") or d.get("roku", {}).get("friendly-device-name")
            or cast.get("fn") or up.get("friendlyName")
            or next((v.get("name") for v in svc.values() if v.get("name") and not re.match(r"^_|adb-", v["name"])), "")
            or host)
    model = (d.get("roku", {}).get("model-name") or cast_md or up.get("modelName")
             or (svc.get("_airplay._tcp") or {}).get("txt", {}).get("model", ""))
    if model.upper().startswith("AFT"):
        model = "Fire TV (" + model + ")"
    kind = "other"
    if d.get("roku") or 8060 in ports or "roku" in blob:
        kind = "roku"
    elif "_amzn-wplay._tcp" in svc or vend == "Amazon" or re.search(r"\bfire ?tv|amazon|\baft[a-z]|amazoaft", blob):
        kind = "firetv"
    elif "shield" in blob or vend == "NVIDIA":
        kind = "shield"
    elif "google tv" in blob:
        kind = "googletv"
    elif "_androidtvremote2._tcp" in svc or "_adb-tls-connect._tcp" in svc or "_adb._tcp" in svc or 5555 in ports \
            or re.search(r"android ?tv|bravia|philips.*android|\btcl\b|hisense|xiaomi|\bmi ?box|\bonn\b", blob):
        kind = "androidtv"
    elif re.search(r"appletv", json.dumps(svc).lower()) or "apple tv" in blob:
        kind = "appletv"
    elif cast_md or "_googlecast._tcp" in svc:
        kind = "chromecast"
    elif "samsung" in blob:                              # (ports alone aren't proof: a Pi had 3001 open)
        kind = "samsung"
    elif re.search(r"\blg\b|webos|lg electronics", blob):
        kind = "lg"
    accepts = "apk" if kind in APK_KINDS else "zip" if kind == "roku" else ""
    tls = (svc.get("_adb-tls-connect._tcp") or {}).get("port")
    pairing = (svc.get("_adb-tls-pairing._tcp") or {}).get("port")
    if kind in APK_KINDS:
        if 5555 in ports:
            status, note = "ready", "ADB debugging is on - ready to push."
        elif tls:
            status, note = "pair", "Wireless debugging is on - pair once with the code on the TV."
        else:
            status, note = "setup", "Debugging is off on the TV - turn it on (TubeLoader shows how)."
    elif kind == "roku":
        dev = (d.get("roku") or {}).get("developer-enabled", "")
        status, note = ("ready", "Developer mode is on - ready for a .zip channel.") if dev == "true" else \
            ("setup", "Developer mode is off - turn it on with the remote (TubeLoader shows how).")
    elif kind == "appletv":
        status, note = "no", "Apple TV can't take an APK - it needs a tvOS app, signed by an Apple developer account."
    elif kind == "chromecast":
        status, note = "no", "An older Chromecast (without Google TV) can't install apps."
    elif kind in ("samsung", "lg"):
        status, note = "no", "Samsung and LG TVs run their own systems (Tizen / webOS) - they can't take an APK."
    else:
        status, note = "unknown", ""
    d.update(kind=kind, kind_name=KINDS[kind], name=name or KINDS[kind], model=model, accepts=accepts,
             status=status, note=note, tls_port=tls, pairing_port=pairing)
    return d


def _is_media(d):
    return d["kind"] != "other" or d.get("ports") or d.get("mdns") or d.get("upnp")


def scan(root):
    """Background: everything on the home network, TVs first (_scan reports progress)."""
    if _scan["state"] == "running":
        return
    _scan.update(state="running", progress=2, msg="Looking at the home network…", devices=[])

    def go():
        try:
            nets = local_nets()
            if not nets:
                raise RuntimeError("This computer doesn't seem to be on a home network (only VPN or none).")
            mine = [m for m, _ in nets]
            _scan.update(progress=5, msg="Asking the TVs and sticks to say who they are…")
            for m, n in nets:
                _wake_arp(n, m)
            md = mdns_browse(mine)
            _scan.update(progress=35, msg="Asking the media devices (UPnP)…")
            sd = ssdp_browse(mine)
            arp = arp_table()
            ips = set(md) | set(sd) | {ip for ip in arp if any(ipaddress.ip_address(ip) in n for _, n in nets)}
            ips -= set(mine)
            ips = {i for i in ips if not i.endswith(".255") and not i.endswith(".1") or i in md or i in sd}
            _scan.update(progress=50, msg=f"Checking {len(ips)} devices…")
            devs = {ip: {"ip": ip, "mac": arp.get(ip, ""), "vendor": vendor_of(arp.get(ip, "")),
                         "mdns": md.get(ip, {}), "ssdp": sd.get(ip, {}), "ports": []} for ip in ips}

            def probe(ip):
                d = devs[ip]
                d["ports"] = [p for p in PORTS if _open(ip, p)]
                d["hostname"] = _hostname(ip)
                if 8060 in d["ports"]:
                    d["roku"] = roku_info(ip)
                for loc in (d["ssdp"] or {}).get("locations", [])[:2]:
                    info = upnp_info(loc)
                    if info:
                        d["upnp"] = info
                        break
                return ip

            done = 0
            with ThreadPoolExecutor(48) as ex:
                for _ in ex.map(probe, list(ips)):
                    done += 1
                    _scan["progress"] = 50 + int(48 * done / max(1, len(ips)))
            out = [classify(d) for d in devs.values()]
            order = {"ready": 0, "pair": 1, "setup": 2, "no": 3, "unknown": 4}
            out.sort(key=lambda d: (0 if d["accepts"] else 1 if d["kind"] != "other" else 2,
                                    order.get(d["status"], 5), d["name"].lower()))
            for d in out:
                d["media"] = bool(_is_media(d))
                for k in ("mdns", "ssdp"):
                    d.pop(k, None)
            _scan.update(state="done", progress=100, devices=out,
                         msg=f"Found {sum(1 for d in out if d['kind'] != 'other')} TVs and streaming devices.")
        except Exception as e:
            _scan.update(state="error", msg=str(e)[:300])

    threading.Thread(target=go, daemon=True).start()


def probe_one(ip):
    """A device typed in by hand (the scan missed it)."""
    ipaddress.ip_address(ip)
    # everything at once (one by one took 22 s), with a short listen for what it announces about itself
    mine = [m for m, _ in local_nets()]
    ex = ThreadPoolExecutor(len(PORTS) + 3)
    host = ex.submit(_hostname, ip)
    md = ex.submit(mdns_browse, mine, 2.0)
    sd = ex.submit(ssdp_browse, mine, 2.0)
    opens = dict(zip(PORTS, ex.map(lambda p: _open(ip, p, 1.0), list(PORTS))))
    try:
        name = host.result(timeout=3)
    except Exception:
        name = ""                                     # a name lookup that hangs isn't waited for
    d = {"ip": ip, "mac": arp_table().get(ip, ""), "ports": [p for p in PORTS if opens[p]],
         "hostname": name, "mdns": md.result().get(ip, {}), "ssdp": sd.result().get(ip, {})}
    ex.shutdown(wait=False)
    d["vendor"] = vendor_of(d["mac"])
    for loc in (d["ssdp"] or {}).get("locations", [])[:1]:
        d["upnp"] = upnp_info(loc)
    if 8060 in d["ports"]:
        d["roku"] = roku_info(ip)
    d = classify(d)
    if d["kind"] == "other":                      # typed in as a TV: let it try ADB
        d.update(kind="androidtv", kind_name="Android TV (assumed)", accepts="apk",
                 status="ready" if 5555 in d["ports"] else "setup",
                 note="Treated as an Android TV. " + ("ADB answers." if 5555 in d["ports"] else "ADB doesn't answer yet."))
    d["media"] = True
    d.pop("mdns", None)
    d.pop("ssdp", None)
    return d


# ======================================================================================================
# What's in the file: an APK's manifest (binary XML), a split bundle, or a Roku .zip
# ======================================================================================================
ATTR_IDS = {0x01010003: "name", 0x0101020c: "minSdkVersion", 0x01010270: "targetSdkVersion",
            0x0101021b: "versionCode", 0x0101021c: "versionName", 0x01010001: "label", 0x0101028e: "required"}


def axml(data):
    """Android binary XML -> [(depth, tag, {attr: value})]."""
    def u16(o):
        return struct.unpack_from("<H", data, o)[0]

    def u32(o):
        return struct.unpack_from("<I", data, o)[0]

    strings, resmap, out = [], [], []
    off, depth = 8, 0
    while off + 8 <= len(data):
        typ, hsize, size = u16(off), u16(off + 2), u32(off + 4)
        if size < 8:
            break
        if typ == 0x0001:                                    # string pool
            count, flags, sstart = u32(off + 8), u32(off + 16), u32(off + 20)
            utf8 = bool(flags & 0x100)
            for i in range(count):
                p = off + sstart + u32(off + hsize + i * 4)
                try:
                    if utf8:
                        n = data[p]
                        p += 2 if n & 0x80 else 1
                        blen = data[p]
                        if blen & 0x80:
                            blen = ((blen & 0x7F) << 8) | data[p + 1]
                            p += 2
                        else:
                            p += 1
                        strings.append(data[p:p + blen].decode("utf-8", "replace"))
                    else:
                        n = u16(p)
                        if n & 0x8000:
                            n = ((n & 0x7FFF) << 16) | u16(p + 2)
                            p += 4
                        else:
                            p += 2
                        strings.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
                except Exception:
                    strings.append("")
        elif typ == 0x0180:                                  # resource ids of the attribute names
            resmap = [u32(off + 8 + i * 4) for i in range((size - 8) // 4)]
        elif typ == 0x0102:                                  # start element
            name_i = u32(off + 20)
            astart, asize, acount = u16(off + 24), u16(off + 26), u16(off + 28)
            attrs = {}
            for i in range(acount):
                a = off + 16 + astart + i * asize
                an, raw, dtype, val = u32(a + 4), u32(a + 8), data[a + 15], u32(a + 16)
                key = ATTR_IDS.get(resmap[an]) if an < len(resmap) and resmap[an] in ATTR_IDS else \
                    (strings[an] if an < len(strings) else "")
                if dtype == 0x03 and raw < len(strings):
                    v = strings[raw]
                elif dtype == 0x12:
                    v = val != 0
                elif dtype in (0x10, 0x11):
                    v = val
                elif dtype == 0x01:
                    v = f"@0x{val:08x}"
                else:
                    v = strings[raw] if raw < len(strings) else val
                if key:
                    attrs[key] = v
            out.append((depth, strings[name_i] if name_i < len(strings) else "", attrs))
            depth += 1
        elif typ == 0x0103:
            depth -= 1
        off += size
    return out


def apk_info(z):
    """A zipfile of an APK -> its facts."""
    nodes = axml(z.read("AndroidManifest.xml"))
    info = {"package": "", "version_name": "", "version_code": 0, "min_sdk": 1, "target_sdk": 0,
            "tv_launcher": False, "leanback": False, "touch_required": False}
    for _, tag, a in nodes:
        if tag == "manifest":
            info["package"] = str(a.get("package", ""))
            info["version_name"] = str(a.get("versionName", ""))
            info["version_code"] = a.get("versionCode", 0) if isinstance(a.get("versionCode"), int) else 0
        elif tag == "uses-sdk":
            if isinstance(a.get("minSdkVersion"), int):
                info["min_sdk"] = a["minSdkVersion"]
            if isinstance(a.get("targetSdkVersion"), int):
                info["target_sdk"] = a["targetSdkVersion"]
        elif tag == "category" and a.get("name") == "android.intent.category.LEANBACK_LAUNCHER":
            info["tv_launcher"] = True
        elif tag == "uses-feature" and a.get("name") == "android.software.leanback":
            info["leanback"] = True
        elif tag == "uses-feature" and a.get("name") == "android.hardware.touchscreen" and a.get("required", True) is not False:
            info["touch_required"] = True
    info["abis"] = sorted({n.split("/")[1] for n in z.namelist() if n.startswith("lib/") and n.count("/") >= 2})
    return info


SDK_NAMES = {21: "5.0", 22: "5.1", 23: "6", 24: "7", 25: "7.1", 26: "8", 27: "8.1", 28: "9", 29: "10", 30: "11",
             31: "12", 32: "12L", 33: "13", 34: "14", 35: "15", 36: "16"}


def inspect(path):
    p = Path(str(path or ""))
    if not p.is_file():
        return {"ok": False, "msg": "That file isn't there."}
    ext = p.suffix.lower()
    base = {"ok": True, "path": str(p), "name": p.name, "size": p.stat().st_size}
    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if ext == ".apk" or "AndroidManifest.xml" in names:
                return {**base, "type": "apk", **apk_info(z)}
            apks = [n for n in names if n.lower().endswith(".apk")]
            if apks:                                          # .apks / .xapk: a base and its splits
                main = next((n for n in apks if re.search(r"(^|/)base(-master)?\.apk$", n)), apks[0])
                with zipfile.ZipFile(io.BytesIO(z.read(main))) as b:
                    return {**base, "type": "bundle", "parts": len(apks), **apk_info(b)}
            if "manifest" in names:                           # a Roku channel
                m = z.read("manifest").decode("utf-8", "replace")
                kv = dict(re.findall(r"^\s*([a-z_]+)\s*=\s*(.*?)\s*$", m, re.M))
                return {**base, "type": "roku", "title": kv.get("title", p.stem),
                        "version_name": ".".join(x for x in (kv.get("major_version"), kv.get("minor_version"),
                                                             kv.get("build_version")) if x)}
    except zipfile.BadZipFile:
        return {"ok": False, "msg": "That isn't an app file (not a zip / APK)."}
    except Exception as e:
        return {"ok": False, "msg": f"That file couldn't be read ({str(e)[:160]})."}
    return {"ok": False, "msg": "That zip isn't an Android app or a Roku channel (no AndroidManifest.xml or manifest)."}


def pick_file():
    """This computer's own Open dialog."""
    try:
        if sys.platform == "win32":
            ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;Add-Type -AssemblyName System.Windows.Forms;"
                  "$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true;ShowInTaskbar=$false};"
                  "$d=New-Object System.Windows.Forms.OpenFileDialog;$d.Title='Choose the app to put on the TV';"
                  "$d.Filter='TV apps (*.apk;*.apks;*.xapk;*.zip)|*.apk;*.apks;*.xapk;*.zip|All files|*.*';"
                  "if($d.ShowDialog($o) -eq 'OK'){[Console]::Out.Write($d.FileName)}")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                               timeout=600, encoding="utf-8", creationflags=NO_WINDOW)
        elif sys.platform == "darwin":
            r = subprocess.run(["osascript", "-e", 'POSIX path of (choose file with prompt "Choose the app to put on the TV")'],
                               capture_output=True, text=True, timeout=600)
        else:
            return ""
    except (OSError, subprocess.SubprocessError):
        return ""
    out = (r.stdout or "").strip()
    return out if out and Path(out).is_file() else ""


# ======================================================================================================
# Known errors -> what they mean, what the person does, and the fix TubeLoader can run
# ======================================================================================================
SAFE = {   # the only fixes TubeLoader runs (each after the person taps it); danger = asked twice
    "reconnect": ("Reconnect to the TV", False),
    "restart_adb": ("Restart ADB on this computer and reconnect", False),
    "wake_tv": ("Wake the TV up", False),
    "open_developer_settings": ("Open Developer options on the TV", False),
    "retry": ("Try the install again", False),
    "retry_allow_downgrade": ("Install over the newer version (keeps its data)", False),
    "uninstall_then_install": ("Remove the old copy, then install (deletes that app's data on the TV)", True),
    "pair": ("Pair with the code on the TV", False),
    "roku_replace": ("Replace the channel on the Roku", False),
    "roku_launch": ("Open the channel on the Roku", False),
}

RULES = [
    (r"unauthori[sz]ed|failed to authenticate",
     "The TV hasn't allowed this computer yet.",
     ["Look at the TV: a box asks \"Allow USB debugging?\" (or \"Allow debugging?\").",
      "Tick \"Always allow from this computer\" and choose Allow / OK.",
      "No box? Turn ADB debugging off and on again on the TV, then reconnect."], "reconnect"),
    (r"connection refused|cannot connect|failed to connect|actively refused|10061|no route|unable to connect",
     "The TV isn't accepting connections - debugging is off, or it's asleep.",
     ["Make sure the TV is on (not in standby).",
      "Turn on debugging on the TV (TubeLoader's steps for this TV are below).",
      "Fire TV: Settings > My Fire TV > Developer options > ADB debugging ON."], "wake_tv"),
    (r"timed out|timeout|took longer",
     "The TV didn't answer in time.",
     ["Check the TV is on and on the same Wi-Fi as this computer.", "Try again in a moment."], "restart_adb"),
    (r"offline", "The TV is connected but not responding (offline).",
     ["Wake the TV, then try again."], "reconnect"),
    (r"INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match|INSTALL_FAILED_SHARED_USER_INCOMPATIBLE",
     "A copy of this app is already on the TV, signed by someone else (or a different build), so Android won't "
     "install over it.",
     ["Removing the old copy fixes it - but that deletes the app's data and settings on the TV."], "uninstall_then_install"),
    (r"INSTALL_FAILED_VERSION_DOWNGRADE|downgrade",
     "The TV has a newer version of this app than the one you picked.",
     ["Install over it anyway (keeps the data), or pick the newer APK."], "retry_allow_downgrade"),
    (r"INSTALL_FAILED_NO_MATCHING_ABIS|no matching abis",
     "This APK is built for a different processor than the TV's (e.g. only 64-bit, or only x86).",
     ["Get the build of the app for this TV's processor (often called armeabi-v7a or arm64-v8a)."], None),
    (r"INSTALL_FAILED_OLDER_SDK|requires newer sdk|minSdk",
     "The app needs a newer Android version than the TV has.",
     ["Look for an older version of the app that supports this TV's Android version."], None),
    (r"INSTALL_FAILED_INSUFFICIENT_STORAGE|not enough space|no space",
     "The TV is out of space.",
     ["On the TV: Settings > Applications > Manage installed applications - remove apps you don't use, "
      "or clear the cache of big ones."], None),
    (r"INSTALL_PARSE_FAILED_NO_CERTIFICATES|INSTALL_PARSE_FAILED|INSTALL_FAILED_INVALID_APK|not a valid",
     "The APK file is damaged or not signed.",
     ["Download the APK again, or rebuild it signed."], None),
    (r"INSTALL_FAILED_USER_RESTRICTED|blocked|INSTALL_FAILED_VERIFICATION_FAILURE|Play Protect",
     "The TV blocked the install (unknown sources or Play Protect).",
     ["On the TV allow installing unknown apps (Fire TV: Developer options > Install unknown apps / Apps from "
      "Unknown Sources).", "If Google Play Protect asks, choose Install anyway."], "retry"),
    (r"INSTALL_FAILED_MISSING_SPLIT|split",
     "This app comes in several pieces and only one was given.",
     ["Pick the whole bundle (.apks / .xapk), not a single piece."], None),
    (r"more than one device|device not found|no devices",
     "ADB lost track of the TV.", ["Reconnect and try again."], "reconnect"),
    (r"401|unauthori[sz]ed.*roku|password",
     "The Roku didn't accept the developer password.",
     ["Use the password you set when you turned on Developer mode (user name rokudev).",
      "Forgot it? Do the remote code again (Home x3, Up x2, Right, Left, Right, Left, Right) and set a new one."], None),
    (r"Identical to previous version",
     "That exact channel is already on the Roku.", ["Nothing to do - or replace it if you changed it."], "roku_launch"),
]


def rule_for(text):
    for pat, what, steps, fix in RULES:
        if re.search(pat, text or "", re.I):
            return {"what": what, "steps": steps, "fix": fix}
    return None


SETUP_STEPS = {
    "firetv": ["On the Fire TV: Settings > My Fire TV > Developer options.",
               "No Developer options? Settings > My Fire TV > About, then click the device name (Fire TV Stick) "
               "7 times - \"You are now a developer\".",
               "Turn ON ADB debugging.",
               "Turn ON Apps from Unknown Sources (or Install unknown apps > allow).",
               "Then come back and press Push - the first time, the TV asks to allow this computer."],
    "googletv": ["On the TV: Settings > System > About, then click Android TV OS build 7 times - "
                 "\"You are now a developer\".",
                 "Back in Settings > System > Developer options: turn ON USB debugging.",
                 "Newer TVs (Android 11+) also have Wireless debugging: turn it ON, open it, and choose "
                 "Pair device with pairing code - TubeLoader asks for that code.",
                 "Then press Push - the TV asks to allow this computer: tick Always allow and choose Allow."],
    "roku": ["On the Roku remote, press: Home 3 times, Up 2 times, Right, Left, Right, Left, Right.",
             "The Developer Settings screen opens: choose Enable installer and restart, agree, and set a "
             "developer password (write it down).",
             "After the restart, press Push here and type that password (user name is rokudev)."],
}
SETUP_STEPS["androidtv"] = SETUP_STEPS["shield"] = SETUP_STEPS["googletv"]


# ======================================================================================================
# The push job: steps the person watches, Philibert's help when something fails
# ======================================================================================================
class Job:
    def __init__(self, root, device, file, llm):
        self.id = uuid.uuid4().hex[:12]
        self.root, self.dev, self.file, self.llm = root, device, file, llm
        self.events, self.state = [], "running"
        self.pending = None                    # what the person is asked: {kind, ...}
        self.answer = None
        self.cv = threading.Condition()
        self.rounds = 0
        self.log = []                          # what happened, for Philibert
        self.serial = ""
        self.facts = {}
        self.cancelled = False
        self.password = ""

    # ---- what the page sees ----
    def ev(self, kind, text, detail=""):
        with _lock:
            self.events.append({"i": len(self.events), "t": time.time(), "kind": kind, "text": text,
                                "detail": str(detail or "")[:3000]})
        if kind in ("step", "ok", "fail", "info"):
            self.log.append(f"[{kind}] {text}" + (f" :: {str(detail)[:600]}" if detail else ""))

    def ask(self, kind, **kw):
        """Wait for the person (a button, a code, a password). -> their answer dict, or None if cancelled."""
        with self.cv:
            self.pending = {"kind": kind, **kw}
            self.answer = None
            self.state = "waiting"
            while self.answer is None and not self.cancelled:
                self.cv.wait(1.0)
            self.pending = None
            self.state = "running"
            return None if self.cancelled else self.answer

    def give(self, ans):
        with self.cv:
            self.answer = ans or {}
            self.cv.notify_all()

    def view(self, since=0):
        with _lock:
            return {"ok": True, "id": self.id, "state": self.state, "events": self.events[since:],
                    "pending": self.pending, "total": len(self.events)}

    # ---- ADB ----
    def adb(self, *a, timeout=40):
        rc, out = adb(self.root, *a, timeout=timeout)
        return rc, out

    def sh(self, *a, timeout=20):
        return self.adb("-s", self.serial, "shell", *a, timeout=timeout)

    def run(self):
        try:
            if self.dev.get("accepts") == "zip" or self.file.get("type") == "roku":
                self.roku()
            else:
                self.android()
        except Exception as e:
            self.ev("fail", "Something unexpected went wrong.", f"{type(e).__name__}: {e}")
            self.state = "failed"
        if self.cancelled and self.state != "done":
            self.state = "cancelled"

    # ================================================== Android ===========================================
    def android(self):
        if not adb_ready(self.root):
            self.ev("fail", "ADB isn't on this computer yet - download it first (the button at the top).")
            self.state = "failed"
            return
        f = self.file
        if f.get("type") not in ("apk", "bundle"):
            self.ev("fail", "That file isn't an Android app (.apk). A Roku takes the .zip channels.")
            self.state = "failed"
            return
        ip = self.dev["ip"]
        self.serial = f"{ip}:5555" if not self.dev.get("tls_port") or 5555 in self.dev.get("ports", []) else \
            f"{ip}:{self.dev['tls_port']}"
        flags = []
        if self.dev.get("status") == "pair" and 5555 not in self.dev.get("ports", []):
            self.ev("info", "This TV uses Wireless debugging: it pairs once with a code it shows.")
            if not self.pair():
                self.state = "cancelled"
                return
        while True:
            ok = self.connect() and self.authorise() and self.check(flags) and self.install(flags)
            if ok:
                self.state = "done"
                return
            if self.cancelled:
                self.state = "cancelled"
                return
            fix = self.assist()
            if not fix:
                self.state = "failed"
                return
            if not self.do_fix(fix, flags):
                self.state = "failed"
                return

    def connect(self):
        self.ev("step", f"Connecting to {self.dev['name']} at {self.serial}…")
        rc, out = self.adb("connect", self.serial, timeout=20)
        if re.search(r"connected to|already connected", out) and not re.search(r"failed|unable|cannot", out, re.I):
            self.ev("ok", "Connected.", out)
            return True
        self.ev("fail", "The TV didn't accept the connection.", out)
        return False

    def state_of(self):
        rc, out = self.adb("-s", self.serial, "get-state", timeout=10)
        return out.strip().splitlines()[-1].strip() if out.strip() else "unknown"

    def authorise(self):
        st = self.state_of()
        if st == "device":
            return True
        if "unauthorized" in st:
            self.ev("info", "Look at the TV: allow debugging from this computer.",
                    "Tick \"Always allow from this computer\", then choose Allow. Waiting up to a minute…")
            for _ in range(30):
                if self.cancelled:
                    return False
                time.sleep(2)
                st = self.state_of()
                if st == "device":
                    self.ev("ok", "The TV allowed this computer.")
                    return True
            self.ev("fail", "The TV didn't allow this computer (no answer on the TV).", f"state: {st}")
            return False
        self.ev("fail", "The TV is connected but not ready.", f"state: {st}")
        return False

    def check(self, flags):
        props = {}
        rc, out = self.sh("getprop", timeout=15)
        for m in re.finditer(r"\[([^\]]+)\]: \[([^\]]*)\]", out):
            props[m.group(1)] = m.group(2)
        sdk = int(props.get("ro.build.version.sdk", "0") or 0)
        abis = [a for a in (props.get("ro.product.cpu.abilist", "") or props.get("ro.product.cpu.abi", "")).split(",") if a]
        self.facts = {"maker": props.get("ro.product.manufacturer", ""), "model": props.get("ro.product.model", ""),
                      "android": props.get("ro.build.version.release", ""), "sdk": sdk, "abis": abis}
        self.ev("ok", f"It's a {self.facts['maker']} {self.facts['model']}, Android {self.facts['android']}"
                      f" (API {sdk}), {', '.join(abis) or 'unknown processor'}.")
        f = self.file
        problems = []
        if sdk and f.get("min_sdk", 1) > sdk:
            problems.append(f"The app needs Android {SDK_NAMES.get(f['min_sdk'], f['min_sdk'])} (API {f['min_sdk']}) "
                            f"and the TV has Android {self.facts['android']} (API {sdk}) - Android will refuse it.")
        if f.get("abis") and abis and not set(f["abis"]) & set(abis):
            problems.append(f"The app is built for {', '.join(f['abis'])} and the TV's processor is {', '.join(abis)}.")
        for p in problems:
            self.ev("info", "Heads-up before installing: " + p)
        if f.get("package"):
            rc, out = self.sh("dumpsys", "package", f["package"], timeout=20)
            m = re.search(r"versionCode=(\d+)", out)
            if m:
                have = int(m.group(1))
                vn = re.search(r"versionName=(\S+)", out)
                self.ev("info", f"The TV already has {f['package']} {vn.group(1) if vn else ''} - it will be updated."
                        if have <= f.get("version_code", 0) else
                        f"The TV has a newer version of this app ({vn.group(1) if vn else have}) than your file.")
        if not f.get("tv_launcher") and f.get("type") in ("apk", "bundle"):
            self.ev("info", "Note: this app has no TV home-screen entry (it's a phone app). It may install fine but not "
                            "show on the TV's home row - find it in Settings > Apps, or open it from TubeLoader.")
        return True

    def install(self, flags):
        f = self.file
        args = ["-s", self.serial]
        if f["type"] == "bundle":
            tmp = Path(tempfile.mkdtemp(prefix="tubeloader-"))
            try:
                with zipfile.ZipFile(f["path"]) as z:
                    parts = []
                    for n in z.namelist():
                        if n.lower().endswith(".apk"):
                            out = tmp / Path(n).name
                            out.write_bytes(z.read(n))
                            parts.append(str(out))
                self.ev("step", f"Installing {f['name']} ({len(parts)} pieces) - this can take a minute…")
                rc, out = self.adb(*args, "install-multiple", "-r", *flags, *parts, timeout=900)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            mb = f.get("size", 0) / 2**20
            self.ev("step", f"Sending {f['name']} ({mb:.1f} MB) and installing - this can take a minute…")
            rc, out = self.adb(*args, "install", "-r", *flags, f["path"], timeout=900)
        if "Success" in out and "Failure" not in out:
            self.ev("ok", "Installed!", out)
            self.launch()
            return True
        self.ev("fail", "The install didn't go through.", out)
        return False

    def launch(self):
        pkg = self.file.get("package")
        if not pkg:
            return
        for cat in ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER"):
            rc, out = self.sh("monkey", "-p", pkg, "-c", cat, "1", timeout=20)
            if "Events injected: 1" in out:
                self.ev("ok", "Opened it on the TV.")
                return
        self.ev("info", "It's installed - open it from the TV's apps (it didn't open by itself).")

    # ---- Philibert assists ----
    def assist(self):
        """Something failed: what it means, what to do, and maybe one safe fix. -> the fix id, or None."""
        self.rounds += 1
        if self.rounds > 5:
            self.ev("philibert", "We've tried a few things and it still isn't working. The steps above are the best "
                                 "next move - when you've done them, press Push to start again.")
            return None
        last = "\n".join(self.log[-6:])
        rule = rule_for(last)
        if rule:
            self.ev("rule", rule["what"], json.dumps(rule["steps"]))
        steps = SETUP_STEPS.get(self.dev.get("kind"), [])
        if not self.llm:
            self.ev("philibert-off", "Philibert can't help work this out: there's no AI model on this computer. "
                                     "Add one in the Model Manager (a small one like Qwen3 4B or 8B is plenty) and "
                                     "Philibert will walk you through problems like this.",
                    json.dumps(steps if not rule else []))
            if rule and rule["fix"]:
                return self.offer(rule["fix"], rule["what"], [])
            return None
        self.ev("thinking", "Philibert is looking at what happened…")
        fix, say, todo = self.ask_model(last, rule)
        self.ev("philibert", say, json.dumps(todo))
        return self.offer(fix, say, todo) if fix else self.wait_user(todo)

    def ask_model(self, last, rule):
        allowed = list(SAFE)
        facts = {"device": {k: self.dev.get(k) for k in ("name", "kind_name", "model", "ip", "ports", "status")},
                 "tv_reports": self.facts, "app": {k: self.file.get(k) for k in
                                                   ("name", "type", "package", "version_name", "version_code",
                                                    "min_sdk", "abis", "tv_launcher", "title")},
                 "how_to_turn_on_debugging_on_this_kind_of_tv": SETUP_STEPS.get(self.dev.get("kind"), [])}
        system = (
            "You are Philibert, helping someone put an app on their TV with TubeLoader (ADB over Wi-Fi for Android TV, "
            "Google TV and Fire TV; the developer installer for Roku). The install just failed. Work out why from the "
            "facts and the log, and tell them plainly what to do. Answer ONLY with JSON:\n"
            '{"say": "2-4 short, friendly sentences: what went wrong and what happens next",\n'
            ' "steps": ["what the person does on the TV or remote, one short step each - empty if none"],\n'
            ' "fix": "one of: ' + ", ".join(allowed) + ', none",\n'
            ' "why": "one sentence: why that fix"}\n'
            "Rules: pick a fix only if it can help with THIS error. uninstall_then_install only for a signature "
            "mismatch (INSTALL_FAILED_UPDATE_INCOMPATIBLE) - and say it deletes the app's data on the TV. pair only "
            "when the TV uses Wireless debugging with a pairing code. Never invent settings or menus that aren't in "
            "the facts. If the person must do something on the TV first, give the steps and fix \"retry\" or none.")
        user = ("FACTS:\n" + json.dumps(facts, indent=1) + "\n\nWHAT HAPPENED (latest last):\n" + last +
                ("\n\nWHAT THIS ERROR USUALLY MEANS: " + rule["what"] + " " + " ".join(rule["steps"]) if rule else ""))
        try:
            text = self.llm([{"role": "system", "content": system}, {"role": "user", "content": user}]) or ""
        except Exception as e:
            text = ""
            self.ev("info", "Philibert couldn't answer just now.", str(e)[:300])
        m = re.search(r"\{.*\}", re.sub(r"(?s)<think>.*?</think>", "", text), re.S)
        data = {}
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                data = {}
        fix = str(data.get("fix") or "").strip()
        if fix not in SAFE:
            fix = (rule or {}).get("fix") or ""
        say = str(data.get("say") or (rule or {}).get("what") or "I couldn't work out what went wrong.").strip()
        steps = [str(s) for s in (data.get("steps") or (rule or {}).get("steps") or []) if str(s).strip()][:8]
        if data.get("why") and fix:
            say += " " + str(data["why"]).strip()
        return fix, say, steps

    def offer(self, fix, say, todo):
        label, danger = SAFE[fix]
        a = self.ask("fix", fix=fix, label=label, danger=danger, steps=todo,
                     confirm=("This deletes the app's data and settings on the TV. Remove it and install again?"
                              if danger else ""))
        if not a or not a.get("yes"):
            self.ev("info", "Okay - not doing that." if a else "Stopped.")
            return self.wait_user(todo) if a else None
        self.ev("step", f"Philibert: {label}…")
        return fix

    def wait_user(self, todo):
        a = self.ask("retry", steps=todo)
        if not a or not a.get("yes"):
            return None
        return "retry"

    def do_fix(self, fix, flags):
        s = self.serial
        if fix == "reconnect":
            self.adb("disconnect", s, timeout=10)
        elif fix == "restart_adb":
            self.adb("kill-server", timeout=15)
            self.adb("start-server", timeout=30)
        elif fix == "wake_tv":
            self.adb("connect", s, timeout=15)
            self.sh("input", "keyevent", "KEYCODE_WAKEUP", timeout=10)
            time.sleep(2)
        elif fix == "open_developer_settings":
            self.sh("am", "start", "-a", "android.settings.APPLICATION_DEVELOPMENT_SETTINGS", timeout=15)
            self.ev("info", "Developer options are open on the TV.")
            return self.wait_user([]) is not None
        elif fix == "retry_allow_downgrade":
            if "-d" not in flags:
                flags.append("-d")
        elif fix == "uninstall_then_install":
            pkg = self.file.get("package")
            rc, out = self.sh("pm", "uninstall", pkg, timeout=60) if pkg else (1, "no package name")
            self.ev("ok" if "Success" in out else "fail", f"Removed the old copy of {pkg}." if "Success" in out
                    else "The old copy couldn't be removed.", out)
        elif fix == "pair":
            return self.pair()
        return True

    def pair(self):
        pp = self.dev.get("pairing_port") or ""
        a = self.ask("pair", port=pp, text="On the TV: Developer options > Wireless debugging > Pair device with "
                                           "pairing code. Type the code and the port it shows (the number after the colon).")
        if not a:
            return False
        code, port = re.sub(r"\D", "", str(a.get("code", ""))), re.sub(r"\D", "", str(a.get("port", "") or pp))
        if not code or not port:
            self.ev("fail", "That needs the 6-digit code and the port the TV shows.")
            return True
        self.ev("step", "Pairing with the TV…")
        rc, out = self.adb("pair", f"{self.dev['ip']}:{port}", code, timeout=30)
        if "Successfully paired" in out:
            self.ev("ok", "Paired.", out)
            m = re.search(r"_adb-tls-connect\S*\s+" + re.escape(self.dev["ip"]) + r":(\d+)",
                          self.adb("mdns", "services", timeout=10)[1] or "")
            cport = a.get("connect_port") or (m.group(1) if m else "")
            if cport:
                self.serial = f"{self.dev['ip']}:{re.sub(r'[^0-9]', '', str(cport))}"
        else:
            self.ev("fail", "Pairing didn't work.", out)
        return True

    # ================================================== Roku ===============================================
    def roku(self):
        f = self.file
        if f.get("type") != "roku":
            self.ev("fail", "A Roku can't install an APK (it isn't Android). It takes a Roku channel .zip - "
                            "made with Roku's developer tools.")
            self.state = "failed"
            return
        ip = self.dev["ip"]
        mode = "Install"
        while True:
            self.ev("step", f"Checking {self.dev['name']}'s developer mode…")
            info = roku_info(ip)
            if info.get("developer-enabled") != "true":
                self.ev("fail", "Developer mode is off on this Roku.", json.dumps(SETUP_STEPS["roku"]))
                fix = self.assist()
                if not fix:
                    self.state = "failed"
                    return
                continue
            self.ev("ok", f"Developer mode is on ({info.get('model-name', 'Roku')}, OS {info.get('software-version', '?')}).")
            if not self.password:
                a = self.ask("password", text="The Roku's developer password (the one set when Developer mode was "
                                              "turned on; the user name is rokudev).")
                if not a:
                    self.state = "cancelled"
                    return
                self.password = str(a.get("password", ""))
            self.ev("step", f"Sending {f['name']} to the Roku…")
            ok, msg = roku_install(ip, self.password, f["path"], mode)
            if ok:
                self.ev("ok", msg)
                self.roku_open(ip)
                self.state = "done"
                return
            self.ev("fail", "The Roku didn't take the channel.", msg)
            if "401" in msg:
                self.password = ""
            fix = self.assist()
            if not fix:
                self.state = "failed"
                return
            if fix == "roku_replace":
                mode = "Replace"
            elif fix == "roku_launch":
                self.roku_open(ip)
                self.state = "done"
                return


def _roku_open(job, ip):
    try:
        urllib.request.urlopen(urllib.request.Request(f"http://{ip}:8060/launch/dev", data=b"", method="POST"),
                               timeout=5).read()
        job.ev("ok", "Opened it on the Roku.")
    except Exception:
        job.ev("info", "It's on the Roku - open it from the Home screen (the channel at the end of the list).")


Job.roku_open = lambda self, ip: _roku_open(self, ip)


def roku_install(ip, password, path, mode="Install"):
    """The Roku developer installer (digest auth, user rokudev). -> (ok, message)."""
    boundary = "----TubeLoader" + uuid.uuid4().hex
    data = Path(path).read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"mysubmit\"\r\n\r\n{mode}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"archive\"; filename=\"{Path(path).name}\"\r\n"
            f"Content-Type: application/zip\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, f"http://{ip}/", "rokudev", password)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))
    req = urllib.request.Request(f"http://{ip}/plugin_install", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with opener.open(req, timeout=120) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: " + ("wrong developer password (401)" if e.code == 401 else e.reason)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    msgs = re.findall(r"<font color=\"?red\"?>(.*?)</font>", html, re.S | re.I) + \
        re.findall(r"'text': '([^']+)'", html)
    text = " ".join(re.sub(r"<[^>]+>", " ", m).strip() for m in msgs) or re.sub(r"<[^>]+>", " ", html)[:400]
    if re.search(r"Install Success|Received.*Install Success|Identical to previous version", text, re.I):
        return True, "Installed on the Roku." if "Identical" not in text else "Already on the Roku (identical)."
    return False, text.strip()[:600]


# ======================================================================================================
# The page's ops
# ======================================================================================================
def handle(body, root, data_dir, llm=None, model_name=""):
    op = str(body.get("op") or "")
    if op == "status":
        return {"ok": True, "adb": adb_ready(root), "adb_mb": ADB_MB, "download": dict(_adb_dl),
                "model": model_name, "assistant": bool(llm), "platform": _platform()}
    if op == "adb_get":
        adb_download(root)
        return {"ok": True}
    if op == "adb_progress":
        return {"ok": True, **_adb_dl, "adb": adb_ready(root)}
    if op == "scan":
        scan(root)
        return {"ok": True}
    if op == "scan_status":
        return {"ok": True, **{k: _scan[k] for k in ("state", "progress", "msg", "devices")}}
    if op == "add":
        try:
            d = probe_one(str(body.get("ip") or "").strip())
        except ValueError:
            return {"ok": False, "msg": "That isn't an IP address (like 192.168.0.42)."}
        _scan["devices"] = [x for x in _scan["devices"] if x["ip"] != d["ip"]] + [d]
        return {"ok": True, "device": d}
    if op == "pick":
        p = pick_file()
        return inspect(p) if p else {"ok": False, "cancelled": True}
    if op == "inspect":
        return inspect(body.get("path"))
    if op == "steps":
        return {"ok": True, "steps": SETUP_STEPS.get(str(body.get("kind") or ""), [])}
    if op == "push":
        dev = body.get("device") or {}
        f = inspect(body.get("path"))
        if not f.get("ok"):
            return f
        if not dev.get("ip"):
            return {"ok": False, "msg": "Choose a TV first."}
        j = Job(root, dev, f, llm)
        with _lock:
            _jobs[j.id] = j
        threading.Thread(target=j.run, daemon=True).start()
        return {"ok": True, "id": j.id}
    if op == "job":
        j = _jobs.get(str(body.get("id") or ""))
        return j.view(int(body.get("since") or 0)) if j else {"ok": False, "msg": "no such push"}
    if op == "answer":
        j = _jobs.get(str(body.get("id") or ""))
        if not j:
            return {"ok": False, "msg": "no such push"}
        j.give(body.get("answer") or {})
        return {"ok": True}
    if op == "cancel":
        j = _jobs.get(str(body.get("id") or ""))
        if j:
            j.cancelled = True
            j.give(None)
        return {"ok": True}
    return {"ok": False, "msg": "unknown op"}
