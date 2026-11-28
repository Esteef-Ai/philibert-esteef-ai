"""Android Bully - APK Pusher (a Philibert app; it began as TubeLoader, and its module, route and app id
keep that name so desktops that have it keep it): find the phones, TVs and streaming sticks on the
home network and put an app on one.

  Android phones / tablets                    an .apk through ADB - Wireless debugging (paired once with
                                              a code) or a USB cable - or with NO setup at all: a QR code
                                              the phone scans, and it downloads the APK from this computer

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

What Philibert knows when it assists (so a small model troubleshoots like it has seen it before):
  guides/tubeloader.md        the shipped guide - how Android Bully works, every known problem and its fix,
                              by device family (only the parts for this device go to the model)
  the household journal       <vault>/Philibert/Troubleshooting/Android Bully.md - one line per problem that
                              was FIXED here (a fix the push then proved), so "last time on this TV, X
                              worked" - never the model's guesses
  the health check            ADB, the network, the model, and this device's own doors (ports), run
                              before Philibert answers and on the page's Health check button

Roku: the zip is checked before it is sent (manifest at the top of the zip - a zipped FOLDER is the
usual mistake, repacked into a fixed copy automatically; title and versions; source/*.brs; the icons
the manifest names; a compression the Roku can read), and the Roku's debug console (port 8085) is read
during the install and the first seconds of the run, so compile and runtime errors come back with
their file and line.

Entry point: handle(body, root, data_dir, llm, model_name, vault) for /api/tubeloader;
llm(messages) -> str, or None.
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
ROKU_ECP, ROKU_WEB, ROKU_CONSOLE = 8060, 80, 8085      # control, developer installer, debug console
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
            req = urllib.request.Request(ADB_ZIP[_platform()], headers={"User-Agent": "Philibert-AndroidBully"})
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
MDNS_TYPES = ["_apple-mobdev2._tcp.local", "_googlecast._tcp.local", "_androidtvremote2._tcp.local", "_adb-tls-connect._tcp.local",
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
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Philibert-AndroidBully"}),
                                    timeout=timeout) as r:
            return r.read(200000).decode("utf-8", "replace")
    except Exception:
        return ""


def _get_code(url, timeout=3.0):
    """-> (HTTP status, body); status 0 = nothing answered."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Philibert-AndroidBully"}),
                                    timeout=timeout) as r:
            return r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def roku_info(ip):
    code, x = _get_code(f"http://{ip}:{ROKU_ECP}/query/device-info", 2.5)
    if code != 200 or not x:
        return {}
    t = _xml_tags(x, "friendly-device-name", "user-device-name", "model-name", "model-number", "is-tv",
                  "developer-enabled", "software-version", "vendor-name")
    return t


def roku_probe(ip):
    """Everything Android Bully needs from a Roku, each with what it means. -> {checks: [...], ...}"""
    code, x = _get_code(f"http://{ip}:{ROKU_ECP}/query/device-info", 3.0)
    info = _xml_tags(x, "user-device-name", "friendly-device-name", "model-name", "developer-enabled",
                     "software-version") if code == 200 else {}
    web = _open(ip, ROKU_WEB, 1.5)
    console = _open(ip, ROKU_CONSOLE, 1.5)
    checks = []
    if code == 200:
        checks.append({"name": "Roku control (port 8060)", "ok": True, "detail": "answers"})
    elif code == 403:
        checks.append({"name": "Roku control (port 8060)", "ok": False,
                       "detail": "refused (403): Control by mobile apps is limited or off",
                       "fix": "On the Roku: Settings > System > Advanced system settings > Control by mobile apps > "
                              "Network access > Default (or Permissive)."})
    else:
        checks.append({"name": "Roku control (port 8060)", "ok": False, "detail": "no answer",
                       "fix": "Check the Roku is on (not asleep) and on the same Wi-Fi; then Settings > System > Advanced "
                              "system settings > Control by mobile apps > Network access > Default."})
    dev = info.get("developer-enabled")
    if dev is not None or code == 200:
        checks.append({"name": "Developer mode", "ok": dev == "true", "detail": "on" if dev == "true" else "off",
                       "fix": "" if dev == "true" else " ".join(SETUP_STEPS["roku"])})
    checks.append({"name": "Developer installer (port 80)", "ok": web, "detail": "answers" if web else "no answer",
                   "fix": "" if web else "Do the remote code again (Home x3, Up x2, Right, Left, Right, Left, Right) and "
                                         "choose Enable installer and restart."})
    checks.append({"name": "Debug console (port 8085)", "ok": console,
                   "detail": "answers - compile and crash errors can be read" if console else
                   "no answer (only with developer mode on; errors can't be read without it)"})
    return {"ok": code == 200 and dev == "true" and web, "code": code, "info": info, "web": web,
            "console": console, "checks": checks}


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
    "phone": "Android phone", "apple": "Apple device", "other": "Other device",
}
APK_KINDS = {"firetv", "googletv", "androidtv", "shield", "phone"}
# what phones call themselves on the network (their DHCP names)
PHONE_HOST = re.compile(r"pixel|galaxy|\bsm-[a-z]\d|oneplus|redmi|xiaomi|poco|motorola|\bmoto|android-[0-9a-f]|"
                        r"\boppo|\bvivo|realme|nothing-phone|\bnokia|sony-?xperia|\bxperia|huawei|honor|\bphone|tablet|"
                        r"\btab-|galaxy-tab", re.I)
TV_WORDS = re.compile(r"android ?tv|google tv|bravia|\btv\b|shield|chromecast|fire ?tv|\baft", re.I)


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
    elif (("_adb-tls-connect._tcp" in svc or "_adb-tls-pairing._tcp" in svc or PHONE_HOST.search(host))
          and "_androidtvremote2._tcp" not in svc and "_googlecast._tcp" not in svc and not TV_WORDS.search(blob)):
        kind = "phone"                                    # Wireless debugging and nothing TV about it, or a phone's name
    elif "_androidtvremote2._tcp" in svc or "_adb-tls-connect._tcp" in svc or "_adb._tcp" in svc or 5555 in ports \
            or re.search(r"android ?tv|bravia|philips.*android|\btcl\b|hisense|xiaomi|\bmi ?box|\bonn\b", blob):
        kind = "androidtv"
    elif re.search(r"appletv", json.dumps(svc).lower()) or "apple tv" in blob:
        kind = "appletv"
    elif cast_md or "_googlecast._tcp" in svc:
        kind = "chromecast"
    elif "_apple-mobdev2._tcp" in svc or "_companion-link._tcp" in svc:
        kind = "apple"                                    # an iPhone, iPad or Mac
    elif "samsung" in blob:                              # (ports alone aren't proof: a Pi had 3001 open)
        kind = "samsung"
    elif re.search(r"\blg\b|webos|lg electronics", blob):
        kind = "lg"
    accepts = "apk" if kind in APK_KINDS else "zip" if kind == "roku" else ""
    tls = (svc.get("_adb-tls-connect._tcp") or {}).get("port")
    pairing = (svc.get("_adb-tls-pairing._tcp") or {}).get("port")
    if kind == "phone":
        name = name if name and not re.match(r"^_|adb-", name) else host
        name = re.sub(r"[-_]+", " ", name).strip() or "Android phone"
        if 5555 in ports:
            status, note = "ready", "ADB answers - ready to push."
        elif tls:
            status, note = "pair", "Wireless debugging is on - pair once with the code on the phone (after that it just connects)."
        else:
            status, note = "setup", ("Looks like a phone (by its name). Turn on Wireless debugging to push to it - or use "
                                     "Install by QR code, which needs no setup at all.")
    elif kind in APK_KINDS:
        if 5555 in ports:
            status, note = "ready", "ADB debugging is on - ready to push."
        elif tls:
            status, note = "pair", "Wireless debugging is on - pair once with the code on the TV."
        else:
            status, note = "setup", "Debugging is off on the TV - turn it on (Android Bully shows how)."
    elif kind == "roku":
        dev = (d.get("roku") or {}).get("developer-enabled", "")
        if not d.get("roku"):
            status, note = "setup", ("This Roku isn't answering its control port - on the Roku: Settings > System > "
                                     "Advanced system settings > Control by mobile apps > Network access > Default.")
        elif dev == "true":
            status, note = "ready", "Developer mode is on - ready for a .zip channel."
        else:
            status, note = "setup", "Developer mode is off - turn it on with the remote (Android Bully shows how)."
    elif kind == "appletv":
        status, note = "no", "Apple TV can't take an APK - it needs a tvOS app, signed by an Apple developer account."
    elif kind == "chromecast":
        status, note = "no", "An older Chromecast (without Google TV) can't install apps."
    elif kind in ("samsung", "lg"):
        status, note = "no", "Samsung and LG TVs run their own systems (Tizen / webOS) - they can't take an APK."
    elif kind == "apple":
        status, note = "no", "An iPhone, iPad or Mac - they can't take an Android app."
    elif vend == "(private address)" and not svc and not ports and not d.get("ssdp", {}).get("server"):
        # A private (random) Wi-Fi address and nothing else to say: phones and tablets do this. A silent
        # Pixel at .194 landed in "Everything else" and couldn't be pushed to (2026-11-27).
        kind = "phone"
        accepts = "apk"
        name = re.sub(r"[-_]+", " ", host).strip() if host else "Phone or tablet"
        status, note = "setup", ("Probably a phone or tablet (it uses a private Wi-Fi address). Turn on Wireless debugging "
                                 "on it, then press Check again - or just press Push: Android Bully looks for it again.")
    else:
        status, note = "unknown", ""
    d.update(kind=kind, kind_name=("Phone or tablet?" if kind == "phone" and status == "setup" and not tls
                                   and not PHONE_HOST.search(host) else KINDS[kind]), name=name or KINDS[kind], model=model, accepts=accepts,
             status=status, note=note, tls_port=tls, pairing_port=pairing)
    return d


def usb_devices(root):
    """Phones and sticks on a USB cable, from adb devices -l."""
    if not adb_ready(root):
        return []
    rc, out = adb(root, "devices", "-l", timeout=15)
    devs = []
    for line in out.splitlines()[1:]:
        m = re.match(r"^(\S+)\s+(device|unauthorized|offline|recovery|sideload|no permissions)\b(.*)$", line.strip())
        if not m or ":" in m.group(1) or m.group(1).startswith(("emulator-", "adb-")):
            continue                                          # (network ones are found on the network)
        serial, state, rest = m.groups()
        kv = dict(re.findall(r"(\w+):(\S+)", rest))
        model = kv.get("model", "").replace("_", " ")
        kind = "firetv" if model.upper().startswith("AFT") else "phone"
        ready = state == "device"
        devs.append({"ip": "usb:" + serial, "serial": serial, "usb": True, "kind": kind, "kind_name": KINDS[kind] + " (USB)",
                     "name": model or serial, "model": model, "accepts": "apk", "ports": [], "media": True,
                     "status": "ready" if ready else "setup",
                     "note": "On a USB cable - ready to push." if ready else
                     ("Look at the phone: allow USB debugging from this computer (tick Always allow)." if state == "unauthorized"
                      else f"ADB sees it, but it's {state} - unplug it and plug it in again.")})
    return devs


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
            out = [classify(d) for d in devs.values()] + usb_devices(root)
            order = {"ready": 0, "pair": 1, "setup": 2, "no": 3, "unknown": 4}
            out.sort(key=lambda d: (0 if d["accepts"] else 1 if d["kind"] != "other" else 2,
                                    order.get(d["status"], 5), d["name"].lower()))
            for d in out:
                d["media"] = bool(_is_media(d))
                for k in ("mdns", "ssdp"):
                    d.pop(k, None)
            _scan.update(state="done", progress=100, devices=out,
                         msg=f"Found {sum(1 for d in out if d['kind'] == 'phone')} phones and "
                             f"{sum(1 for d in out if d['kind'] not in ('other', 'phone'))} TVs and streaming devices.")
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
    if d["kind"] == "other":                      # typed in by hand: it's meant to take an app - let it try ADB
        guess = "phone" if d.get("vendor") == "(private address)" else "androidtv"
        d.update(kind=guess, kind_name="Phone or tablet?" if guess == "phone" else "Android TV (assumed)", accepts="apk",
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
            if "manifest" in names or any(re.fullmatch(r"[^/]+/manifest", n) for n in names):   # a Roku channel
                return {**base, "type": "roku", **roku_check(z)}
    except zipfile.BadZipFile:
        return {"ok": False, "msg": "That isn't an app file (not a zip / APK)."}
    except Exception as e:
        return {"ok": False, "msg": f"That file couldn't be read ({str(e)[:160]})."}
    return {"ok": False, "msg": "That zip isn't an Android app or a Roku channel (no AndroidManifest.xml or manifest)."}


ROKU_IMAGE_KEYS = ("mm_icon_focus_fhd", "mm_icon_focus_hd", "mm_icon_focus_sd", "splash_screen_fhd",
                   "splash_screen_hd", "splash_screen_sd")
_JUNK = re.compile(r"(^|/)(__MACOSX/|\.DS_Store$|Thumbs\.db$|desktop\.ini$)", re.I)


def roku_check(z):
    """A Roku channel zip -> title, version, and what's wrong with it before it is sent:
    problems (the Roku will refuse it), warnings (it may install but look or run wrong), and whether
    Android Bully can repack it (a zipped folder, junk files, a compression the Roku can't read)."""
    names = [n for n in z.namelist() if not n.endswith("/")]
    root = ""
    if "manifest" not in names:
        nested = [n for n in names if re.fullmatch(r"[^/]+/manifest", n) and not _JUNK.search(n)]
        root = nested[0][:-len("manifest")] if nested else ""
    inside = [n[len(root):] for n in names if n.startswith(root) and not _JUNK.search(n)]
    problems, warnings, repack = [], [], False
    if root:
        repack = True
        warnings.append(f"The channel is inside a folder in the zip ({root.rstrip('/')}/) - the Roku needs the manifest "
                        "at the top. Android Bully sends a fixed copy (your file isn't changed).")
    if any(_JUNK.search(n) for n in names):
        repack = True
        warnings.append("The zip has Mac / Windows junk files (__MACOSX, .DS_Store, Thumbs.db) - left out of the copy sent.")
    odd = [i.filename for i in z.infolist() if i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)]
    if odd:
        repack = True
        warnings.append("The zip uses a compression the Roku can't read (7-Zip's LZMA/BZip2) - repacked as a normal zip.")
    m = z.read(root + "manifest").decode("utf-8", "replace") if (root + "manifest") in names else ""
    kv = dict(re.findall(r"^\s*([A-Za-z_]+)\s*=\s*(.*?)\s*$", m, re.M))
    if not kv.get("title"):
        problems.append("The manifest has no title= line - the Roku refuses a channel without one.")
    for k in ("major_version", "minor_version", "build_version"):
        if not kv.get(k):
            warnings.append(f"The manifest has no {k}= line (add it - Roku's tools expect all three versions).")
    if not any(re.fullmatch(r"source/[^/]+\.brs", n, re.I) for n in inside):
        problems.append("There's no source/*.brs file (the code the Roku runs, e.g. source/main.brs).")
    for k in ROKU_IMAGE_KEYS:
        v = kv.get(k, "")
        if v.startswith("pkg:/") and v[5:] not in inside:
            warnings.append(f"The manifest's {k} points to {v}, which isn't in the zip - the Roku shows a blank there.")
    if not any(kv.get(k) for k in ROKU_IMAGE_KEYS[:3]):
        warnings.append("No channel icon in the manifest (mm_icon_focus_hd) - it shows as a blank tile on the Home screen.")
    if any(re.fullmatch(r"components/[^/]+\.xml", n, re.I) for n in inside):
        kind = "SceneGraph"
    else:
        kind = "BrightScript"
    return {"title": kv.get("title") or "(no title)", "version_name": ".".join(
        x for x in (kv.get("major_version"), kv.get("minor_version"), kv.get("build_version")) if x),
        "roku_root": root, "roku_kind": kind, "roku_files": len(inside), "problems": problems,
        "warnings": warnings, "repack": repack}


def roku_repack(src, root, out_dir):
    """A copy of the channel zip the Roku can take: its contents at the top, no junk, normal compression.
    The original is only read."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (Path(src).stem + "-for-roku.zip")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            n = i.filename
            if n.endswith("/") or _JUNK.search(n) or not n.startswith(root):
                continue
            zout.writestr(n[len(root):], zin.read(n))
    return str(dest)


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
# Known errors -> what they mean, what the person does, and the fix Android Bully can run
# ======================================================================================================
SAFE = {   # the only fixes Android Bully runs (each after the person taps it); danger = asked twice
    "reconnect": ("Reconnect to the TV", False),
    "restart_adb": ("Restart ADB on this computer and reconnect", False),
    "wake_tv": ("Wake the TV up", False),
    "open_developer_settings": ("Open Developer options on the TV", False),
    "retry": ("Try the install again", False),
    "retry_allow_downgrade": ("Install over the newer version (keeps its data)", False),
    "retry_old_app": ("Install it anyway - Android 14+ blocks apps made for very old Android", False),
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
      "Turn on debugging on the TV (Android Bully's steps for this TV are below).",
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
    (r"INSTALL_FAILED_DEPRECATED_SDK_VERSION|deprecated sdk|low target sdk",
     "Android 14 and newer block apps made for very old Android (this app targets Android 5 or older).",
     ["Best: get a newer version of the app.", "Or install it anyway - Android allows that from a computer."], "retry_old_app"),
    (r"Auto Blocker|blocked by .*security|AUTO_BLOCKER",
     "Samsung's Auto Blocker stops apps from outside the Play / Galaxy Store, and debugging commands.",
     ["On the phone: Settings > Security and privacy > Auto Blocker - turn it off while you install.",
      "Turn it back on afterwards if you like (installed apps stay)."], "retry"),
    (r"INSTALL_FAILED_ABORTED|User rejected|install.*canceled|cancelled by user",
     "The install was stopped on the phone - a question on its screen was declined or timed out.",
     ["Watch the phone's screen while installing: allow the install when it asks.",
      "Xiaomi / Redmi / POCO: Developer options > Install via USB ON (it asks for a Mi account) and USB debugging "
      "(Security settings) ON."], "retry"),
    (r"INSTALL_FAILED_USER_RESTRICTED|blocked|INSTALL_FAILED_VERIFICATION_FAILURE|Play Protect",
     "The TV blocked the install (unknown sources or Play Protect).",
     ["On the TV allow installing unknown apps (Fire TV: Developer options > Install unknown apps / Apps from "
      "Unknown Sources).", "If Google Play Protect asks, choose Install anyway.",
      "On a Xiaomi / Redmi / POCO phone: Developer options > Install via USB ON (it asks for a Mi account)."], "retry"),
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


ROKU_RULES = [
    (r"\b403\b|Forbidden|Control by mobile apps",
     "The Roku is refusing outside control (Control by mobile apps is limited or off).",
     ["On the Roku: Settings > System > Advanced system settings > Control by mobile apps.",
      "Set Network access to Default (or Permissive), then try again."], "retry"),
    (r"HTTP 401|wrong developer password|401",
     "The Roku didn't accept the developer password.",
     ["The user name is rokudev and the password is the one set when Developer mode was turned on.",
      "Forgot it? Do the remote code again (Home x3, Up x2, Right, Left, Right, Left, Right) - the Developer "
      "Settings screen lets you set a new one."], "retry"),
    (r"Developer mode is off",
     "Developer mode is off on this Roku.",
     ["On the Roku remote: Home x3, Up x2, Right, Left, Right, Left, Right.",
      "Choose Enable installer and restart, agree to the license, and set a developer password.",
      "After the Roku restarts, try again."], "retry"),
    (r"installer isn't answering|port 80|Connection refused|10061|No route",
     "The Roku's developer installer isn't running (or the Roku is asleep).",
     ["Wake the Roku with the remote.", "Do the remote code again and choose Enable installer and restart."], "retry"),
    (r"Compil|Syntax Error|ERROR compiling|BRIGHTSCRIPT: ERROR|Error parsing XML|SceneGraph.*error",
     "The channel's code has an error, so the Roku can't build it.",
     ["The exact error - file and line - is in the Roku's log above.",
      "Fix it in the channel's code, zip it again, and push again."], None),
    (r"Runtime Error|BrightScript Micro Debugger|Brightscript Debugger|STOP \(runtime|crash",
     "The channel installed but stopped with an error as it started.",
     ["The Roku's log above shows the error and the line it stopped on.",
      "Fix it in the channel's code, zip it again, and push again."], "roku_launch"),
    (r"No manifest|manifest",
     "The Roku couldn't find the channel's manifest.",
     ["The manifest must be at the top of the zip, not inside a folder - zip the folder's CONTENTS.",
      "Android Bully repacks a zipped folder by itself; if this still shows, the manifest is missing."], None),
    (r"too (big|large)|size|space",
     "The channel is too big for the Roku's developer slot.",
     ["Make the images smaller (Roku channel images are small PNG/JPGs) and leave out anything unused."], None),
    (r"Identical to previous version",
     "That exact channel is already on the Roku.", ["Nothing to do - or replace it if you changed it."], "roku_launch"),
]


def rule_for(text, kind=""):
    for pat, what, steps, fix in (ROKU_RULES if kind == "roku" else []) + RULES:
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
                 "Pair device with pairing code - Android Bully asks for that code.",
                 "Then press Push - the TV asks to allow this computer: tick Always allow and choose Allow."],
    "roku": ["On the Roku remote, press: Home 3 times, Up 2 times, Right, Left, Right, Left, Right.",
             "The Developer Settings screen opens: choose Enable installer and restart, agree, and set a "
             "developer password (write it down).",
             "After the restart, press Push here and type that password (user name is rokudev)."],
}
SETUP_STEPS["androidtv"] = SETUP_STEPS["shield"] = SETUP_STEPS["googletv"]
SETUP_STEPS["phone"] = [
    "Easiest, no setup: use Install by QR code (top of the list) - the phone scans it and downloads the app.",
    "To push over Wi-Fi instead: Settings > About phone > tap Build number 7 times (Samsung: About phone > Software "
    "information > Build number; Xiaomi: tap MIUI / HyperOS version) - \"You are now a developer\".",
    "Settings > System > Developer options (Samsung: Settings > Developer options) > Wireless debugging ON "
    "(the phone must be on the same Wi-Fi). Then press Scan here.",
    "Push: Android Bully shows a QR code - on the phone tap Wireless debugging > Pair device with QR code and scan "
    "it (or Pair device with pairing code, and type the code and port). That's once; after that it connects by itself.",
    "Samsung: turn off Auto Blocker first (Settings > Security and privacy > Auto Blocker).",
    "Or plug the phone into this computer with a USB cable: Developer options > USB debugging ON, allow this "
    "computer on the phone, and press Scan.",
    "Wireless debugging switches itself off when the phone restarts or changes Wi-Fi - turn it on again before a push."]


# ======================================================================================================
# What Philibert knows: the shipped guide, the household journal, the health check
# ======================================================================================================
GUIDE = Path(__file__).resolve().parent / "guides" / "tubeloader.md"
FAMILY = {"firetv": "Android", "googletv": "Android", "androidtv": "Android", "shield": "Android", "roku": "Roku",
          "phone": "Phone",
          "appletv": "Other", "samsung": "Other", "lg": "Other", "chromecast": "Other", "other": "Other"}


def guide_for(kind):
    """The parts of the guide for this kind of device: General, its family's section, Safe fixes."""
    try:
        text = GUIDE.read_text(encoding="utf-8")
    except OSError:
        return ""
    parts = re.split(r"(?m)^## ", text)
    fam = FAMILY.get(kind, "Other")
    want = ("General", fam, "Safe") + (("Android",) if fam == "Phone" else ())   # (headings: first word)
    keep = [p for p in parts[1:] if p.split("\n", 1)[0].strip().split(" ")[0].strip(":") in want]
    return "\n".join("## " + p.strip() for p in keep)[:14000]     # (a phone gets Android + Phone: ~8.5k)


def journal_path(vault, data_dir):
    if vault:
        return Path(vault) / "Philibert" / "Troubleshooting" / "Android Bully.md"   # (was TubeLoader.md)
    return Path(data_dir) / "tubeloader" / "journal.md"


def journal_note(path, line):
    """One line for a problem that was fixed here - written only after the push proved the fix."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Android Bully - what fixed what, here\n\nPhilibert writes a line when a problem with "
                            "Android Bully was fixed and the app went on the TV. It reads them the next time something "
                            "goes wrong.\n\n", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write("- " + line.replace("\n", " ") + "\n")
    except OSError:
        pass


_ERR_KEYS = re.compile(r"INSTALL_[A-Z_]+|unauthori[sz]ed|refused|timed out|offline|\b40[13]\b|Compil\w*|Runtime Error|"
                       r"Developer mode is off|installer|manifest|Syntax Error", re.I)


def journal_recall(path, dev, text, n=5):
    """The journal lines about this device or this kind of error, newest last."""
    lines = []
    for f in (Path(path), Path(path).with_name("TubeLoader.md")):      # (its notes from before the new name)
        try:
            lines += [l[2:].strip() for l in f.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
        except OSError:
            pass
    keys = {k.lower() for k in _ERR_KEYS.findall(text or "")}
    who = {str(dev.get("name", "")).lower(), str(dev.get("ip", ""))} - {""}
    hits = [l for l in lines if any(w in l.lower() for w in who) or any(k in l.lower() for k in keys)]
    return hits[-n:]


def health(root, dev, model_name=""):
    """What works and what doesn't, for the page's Health check and for Philibert. -> [{name, ok, detail, fix}]"""
    out = []
    if dev.get("accepts") != "zip":
        if adb_ready(root):
            rc, v = adb(root, "version", timeout=15)
            out.append({"name": "ADB on this computer", "ok": rc == 0,
                        "detail": (re.search(r"Version \S+", v) or re.search(r".*", v)).group(0) if v else "",
                        "fix": "" if rc == 0 else "Download ADB again (the button at the top)."})
        else:
            out.append({"name": "ADB on this computer", "ok": False, "detail": "not downloaded",
                        "fix": "Press Get ADB at the top (about 13 MB, from Google)."})
    nets = []
    try:
        nets = local_nets()
    except Exception:
        pass
    out.append({"name": "Home network", "ok": bool(nets), "detail": ", ".join(m for m, _ in nets) or "none found",
                "fix": "" if nets else "Connect this computer to the same Wi-Fi / network as the TV."})
    out.append({"name": "Philibert's AI model", "ok": bool(model_name), "detail": model_name or "none",
                "fix": "" if model_name else "Add a model in the Model Manager so Philibert can help with problems."})
    ip = dev.get("ip")
    if dev.get("usb"):
        rc, stt = adb(root, "-s", dev.get("serial", ""), "get-state", timeout=10) if adb_ready(root) else (1, "")
        stt = (stt.strip().splitlines() or [""])[-1]
        out.append({"name": "On the USB cable", "ok": stt == "device", "detail": stt or "not seen",
                    "fix": "" if stt == "device" else "Unplug and plug in the cable; on the phone allow USB debugging "
                                                      "from this computer (tick Always allow)."})
        return out
    if ip and dev.get("accepts") == "apk" and dev.get("kind") == "phone" and not _open(ip, 5555, 1.0):
        tls = dev.get("tls_port")
        live = tls and _open(ip, int(tls), 1.5)
        out.append({"name": "Wireless debugging on the phone", "ok": bool(live),
                    "detail": f"answers on port {tls}" if live else "off (or the port changed - press Scan again)",
                    "fix": "" if live else " ".join(SETUP_STEPS["phone"][1:3])})
        return out
    if ip and dev.get("accepts") == "zip":
        out += roku_probe(ip)["checks"]
    elif ip and dev.get("accepts") == "apk":
        p5555 = _open(ip, 5555, 1.5)
        out.append({"name": "ADB on the TV (port 5555)", "ok": p5555 or bool(dev.get("tls_port")),
                    "detail": "answers" if p5555 else ("Wireless debugging (pair once)" if dev.get("tls_port") else "no answer"),
                    "fix": "" if p5555 or dev.get("tls_port") else " ".join(SETUP_STEPS.get(dev.get("kind"), []))})
        if p5555 and adb_ready(root):
            serial = f"{ip}:5555"
            adb(root, "connect", serial, timeout=15)
            rc, stt = adb(root, "-s", serial, "get-state", timeout=10)
            stt = (stt.strip().splitlines() or [""])[-1]
            out.append({"name": "This computer allowed on the TV", "ok": stt == "device", "detail": stt or "unknown",
                        "fix": "" if stt == "device" else "Look at the TV: allow debugging from this computer "
                                                          "(tick Always allow)."})
    return out


# ======================================================================================================
# The push job: steps the person watches, Philibert's help when something fails
# ======================================================================================================
class Job:
    def __init__(self, root, device, file, llm, journal=None, model_name="", work_dir=None):
        self.id = uuid.uuid4().hex[:12]
        self.root, self.dev, self.file, self.llm = root, device, file, llm
        self.journal, self.model_name, self.work_dir = journal, model_name, work_dir
        self.first_error = ""                  # what went wrong first, and the fixes that followed (the journal)
        self.fixes = []
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
            self.log.append(f"[{kind}] {text}" + (f" :: {str(detail)[:1500]}" if detail else ""))
        if kind == "fail" and not self.first_error:
            self.first_error = (text + " " + str(detail or "")).strip()[:200]

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
        if self.state == "done" and self.first_error and self.journal:
            # proved: it failed, something was done, and now it's on the TV
            what = self.file.get("title") or self.file.get("package") or self.file.get("name")
            journal_note(self.journal, f"{time.strftime('%Y-%m-%d')} · {self.dev.get('name')} ({self.dev.get('kind_name')}"
                         f"{' ' + self.dev['model'] if self.dev.get('model') else ''}, {self.dev.get('ip')}) · "
                         f"{self.first_error} → " + (", ".join(self.fixes) or "tried again after the steps on the TV") +
                         f" → {what} installed.")

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
        if self.dev.get("usb"):
            self.serial = self.dev["serial"]
        else:
            self.serial = f"{ip}:5555" if not self.dev.get("tls_port") or 5555 in self.dev.get("ports", []) else \
                f"{ip}:{self.dev['tls_port']}"
        flags = []
        if self.dev.get("kind") == "phone" and not self.dev.get("usb") and 5555 not in self.dev.get("ports", []):
            # Wireless debugging: find it (it may have been turned on since the scan, on a new port)
            port = self._fresh_port() or self.dev.get("tls_port")
            while not port:
                self.ev("fail", "The phone isn't offering Wireless debugging yet.", json.dumps(SETUP_STEPS["phone"][1:3]))
                fix = self.assist()
                if not fix:
                    self.state = "cancelled" if self.cancelled else "failed"
                    return
                self.ev("step", "Looking for the phone's Wireless debugging…")
                port = self._fresh_port()
            self.dev["tls_port"] = port
            self.dev["status"] = "pair"
            self.serial = f"{ip}:{port}"
            self.ev("ok", f"Found Wireless debugging on the phone (port {port}).")
        if not self.dev.get("usb") and self.dev.get("status") == "pair" and 5555 not in self.dev.get("ports", []):
            if not self.connect(quiet=True):              # paired before: it just connects
                self.ev("info", f"This {self.thing} uses Wireless debugging: it pairs once with a code it shows.")
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

    @property
    def thing(self):
        return "phone" if self.dev.get("kind") == "phone" else "TV"

    def _fresh_port(self):
        """Wireless debugging moves to a new port each time it's turned on: where is it now? (ADB's own
        look-up first, then Android Bully's.)"""
        ip = self.dev.get("ip", "")
        rc, out = self.adb("mdns", "services", timeout=10)
        m = re.search(r"_adb-tls-connect\S*\s+" + re.escape(ip) + r":(\d+)", out or "")
        if m:
            return m.group(1)
        try:
            mine = [x for x, _ in local_nets()]
            svc = (mdns_browse(mine, 2.0).get(ip) or {}).get("services", {})
            port = (svc.get("_adb-tls-connect._tcp") or {}).get("port")
            return str(port) if port else ""
        except Exception:
            return ""

    def connect(self, quiet=False):
        if self.dev.get("usb"):
            self.ev("ok", f"{self.dev['name']} is on the USB cable.")
            return True
        self.ev("step", f"Connecting to {self.dev['name']} at {self.serial}…")
        rc, out = self.adb("connect", self.serial, timeout=20)
        if re.search(r"connected to|already connected", out) and not re.search(r"failed|unable|cannot", out, re.I):
            self.ev("ok", "Connected.", out)
            return True
        if self.dev.get("tls_port") and not self.serial.endswith(":5555"):
            port = self._fresh_port()
            if port and not self.serial.endswith(":" + port):
                self.serial = f"{self.dev['ip']}:{port}"
                self.ev("info", f"Wireless debugging moved to port {port} - trying there.")
                rc, out = self.adb("connect", self.serial, timeout=20)
                if re.search(r"connected to|already connected", out) and not re.search(r"failed|unable|cannot", out, re.I):
                    self.ev("ok", "Connected.", out)
                    return True
        if quiet:
            self.ev("info", "Not paired with this computer yet.", out)
            return False
        self.ev("fail", f"The {self.thing} didn't accept the connection.", out)
        return False

    def state_of(self):
        rc, out = self.adb("-s", self.serial, "get-state", timeout=10)
        return out.strip().splitlines()[-1].strip() if out.strip() else "unknown"

    def authorise(self):
        st = self.state_of()
        if st == "device":
            return True
        if "unauthorized" in st:
            self.ev("info", f"Look at the {self.thing}: allow debugging from this computer.",
                    "Tick \"Always allow from this computer\", then choose Allow. Waiting up to a minute…")
            for _ in range(30):
                if self.cancelled:
                    return False
                time.sleep(2)
                st = self.state_of()
                if st == "device":
                    self.ev("ok", "The TV allowed this computer.")
                    return True
            self.ev("fail", f"The {self.thing} didn't allow this computer (no answer on it).", f"state: {st}")
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
                            "show on the TV's home row - find it in Settings > Apps, or open it from Android Bully.")
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
    def assist(self, explain_only=False):
        """Something failed: what it means, what to do, and maybe one safe fix. -> the fix id, or None.
        explain_only: a problem in the app itself (a broken zip, an error in the code) - explained, nothing offered."""
        self.rounds += 1
        if self.rounds > 5:
            self.ev("philibert", "We've tried a few things and it still isn't working. The steps above are the best "
                                 "next move - when you've done them, press Push to start again.")
            return None
        last = "\n".join(self.log[-6:])
        rule = rule_for(last, self.dev.get("kind", ""))
        if rule:
            self.ev("rule", rule["what"], json.dumps(rule["steps"]))
        steps = SETUP_STEPS.get(self.dev.get("kind"), [])
        if not self.llm:
            self.ev("philibert-off", "Philibert can't help work this out: there's no AI model on this computer. "
                                     "Add one in the Model Manager (a small one like Qwen3 4B or 8B is plenty) and "
                                     "Philibert will walk you through problems like this.",
                    json.dumps(steps if not rule else []))
            if rule and rule["fix"] and not explain_only:
                return self.offer(rule["fix"], rule["what"], [])
            return None
        self.ev("thinking", "Philibert is looking at what happened…")
        fix, say, todo = self.ask_model(last, rule)
        self.ev("philibert", say, json.dumps(todo))
        if explain_only:
            return None
        return self.offer(fix, say, todo) if fix else self.wait_user(todo)

    def ask_model(self, last, rule):
        roku = self.dev.get("accepts") == "zip"
        allowed = [k for k in SAFE if k.startswith("roku_") or k == "retry"] if roku else \
            [k for k in SAFE if not k.startswith("roku_")]
        self.ev("step", "Philibert is checking what works and what doesn't…")
        checks = health(self.root, self.dev, self.model_name)
        bad = [c for c in checks if not c["ok"]]
        if bad:
            self.ev("info", "Health check: " + "; ".join(f"{c['name']}: {c['detail']}" for c in bad))
        past = journal_recall(self.journal, self.dev, last) if self.journal else []
        if past:
            self.ev("info", "Philibert remembers fixing this kind of thing here before.", "\n".join(past))
        facts = {"device": {k: self.dev.get(k) for k in ("name", "kind_name", "model", "ip", "ports", "status")},
                 "tv_reports": self.facts, "app": {k: self.file.get(k) for k in
                                                   ("name", "type", "package", "version_name", "version_code",
                                                    "min_sdk", "abis", "tv_launcher", "title", "roku_kind",
                                                    "problems", "warnings")},
                 "health_check": [{k: c.get(k) for k in ("name", "ok", "detail", "fix")} for c in checks],
                 "fixed_here_before": past,
                 "how_to_set_up_this_kind_of_tv": SETUP_STEPS.get(self.dev.get("kind"), [])}
        system = (
            "You are Philibert, helping someone put an app on their phone or TV with Android Bully - APK Pusher (ADB over "
            "Wi-Fi or USB for Android phones, Android TV, Google TV and Fire TV; the developer installer for Roku). The install just failed. Work out why from the "
            "facts and the log, and tell them plainly what to do. Answer ONLY with JSON:\n"
            '{"say": "2-4 short, friendly sentences: what went wrong and what happens next",\n'
            ' "steps": ["what the person does on the TV or remote, one short step each - empty if none"],\n'
            ' "fix": "one of: ' + ", ".join(allowed) + ', none",\n'
            ' "why": "one sentence: why that fix"}\n'
            "Rules: pick a fix only if it can help with THIS error. uninstall_then_install only for a signature "
            "mismatch (INSTALL_FAILED_UPDATE_INCOMPATIBLE) - and say it deletes the app's data on the TV. pair only "
            "when the TV uses Wireless debugging with a pairing code. Never invent settings or menus that aren't in "
            "the facts. If the person must do something on the TV first, give the steps and fix \"retry\" or none.")
        guide = guide_for(self.dev.get("kind", ""))
        if guide:
            system += ("\n\nTUBELOADER'S GUIDE (what is known about these problems - trust it over guesses):\n" + guide)
        if past:
            system += ("\n\nFIXED HERE BEFORE (this household's own record - if the same problem is back, the same fix "
                       "is the best first move):\n- " + "\n- ".join(past))
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
        self.fixes.append(label.lower())
        return fix

    def wait_user(self, todo):
        a = self.ask("retry", steps=todo)
        if not a or not a.get("yes"):
            return None
        if todo:
            self.fixes.append("the person did: " + "; ".join(todo)[:160])
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
        elif fix == "retry_old_app":
            if "--bypass-low-target-sdk-block" not in flags:
                flags.append("--bypass-low-target-sdk-block")
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

    def _watch_qr_pairing(self, name, password, stop):
        """The phone scanned the pairing QR: it now offers _adb-tls-pairing under our name - pair with it."""
        while not stop.is_set() and not self.cancelled:
            rc, out = self.adb("mdns", "services", timeout=10)
            m = re.search(re.escape(name) + r"\S*\s+_adb-tls-pairing\S*\s+(\d+\.\d+\.\d+\.\d+):(\d+)", out or "")
            where = m.groups() if m else None
            if not where:
                try:
                    found = mdns_browse([x for x, _ in local_nets()], 1.5)
                    for ip, d in found.items():
                        e = d.get("services", {}).get("_adb-tls-pairing._tcp") or {}
                        if e.get("name", "").startswith(name) and e.get("port"):
                            where = (ip, str(e["port"]))
                except Exception:
                    pass
            if where and not stop.is_set():
                ip, port = where
                rc, o = self.adb("pair", f"{ip}:{port}", password, timeout=30)
                if "Successfully paired" in o:
                    self.give({"qr": True, "ip": ip, "out": o})
                    return
                self.ev("info", "The phone answered the QR code, but pairing didn't finish - try scanning again.", o)
            stop.wait(1.5)

    def pair(self):
        pp = self.dev.get("pairing_port") or ""
        import secrets
        import nd_qr
        name = "ADB_WIFI_" + secrets.token_hex(4)
        password = "".join(secrets.choice("0123456789") for _ in range(8))
        self.qr_pair_name = name                  # (what the phone will offer once it has scanned)
        stop = threading.Event()
        threading.Thread(target=self._watch_qr_pairing, args=(name, password, stop), daemon=True).start()
        a = self.ask("pair", port=pp, qr=nd_qr.svg(f"WIFI:T:ADB;S:{name};P:{password};;", px=5),
                     text=f"On the {self.thing}: Developer options > Wireless debugging > Pair device with QR code, and "
                          "scan this. (Or choose Pair device with pairing code and type the code and port it shows.)")
        stop.set()
        if not a:
            return False
        if a.get("qr"):
            self.ev("ok", f"Paired with the {self.thing} by QR code.", a.get("out", ""))
            cport = self._fresh_port()
            if cport:
                self.dev["tls_port"] = cport
                self.serial = f"{self.dev['ip']}:{cport}"
            return True
        code, port = re.sub(r"\D", "", str(a.get("code", ""))), re.sub(r"\D", "", str(a.get("port", "") or pp))
        if not code or not port:
            self.ev("fail", f"That needs the 6-digit code and the port the {self.thing} shows.")
            return True
        self.ev("step", f"Pairing with the {self.thing}…")
        rc, out = self.adb("pair", f"{self.dev['ip']}:{port}", code, timeout=30)
        if "Successfully paired" in out:
            self.ev("ok", "Paired.", out)
            cport = a.get("connect_port") or self._fresh_port()
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
        path = f["path"]
        # 1. the zip, before anything is sent
        self.ev("step", f"Checking the channel zip ({f.get('roku_files', '?')} files, {f.get('roku_kind', '')})…")
        for w in f.get("warnings", []):
            self.ev("info", w)
        if f.get("problems"):
            self.ev("fail", "The channel zip has a problem the Roku will refuse:", "\n".join(f["problems"]))
            self.assist(explain_only=True)
            self.state = "failed"
            return
        if f.get("repack"):
            path = roku_repack(f["path"], f.get("roku_root", ""), self.work_dir or tempfile.gettempdir())
            self.ev("ok", f"Made a fixed copy for the Roku: {Path(path).name} (your zip is unchanged).")
        else:
            self.ev("ok", "The zip looks right.")
        while True:
            # 2. the Roku: control, developer mode, installer, console
            self.ev("step", f"Checking {self.dev['name']}…")
            pr = roku_probe(ip)
            for c in pr["checks"]:
                if not c["ok"] and c["name"] != "Debug console (port 8085)":
                    self.ev("fail", f"{c['name']}: {c['detail']}.", c.get("fix", ""))
            if not pr["ok"]:
                if pr["code"] == 200 and pr["info"].get("developer-enabled") != "true":
                    self.log.append("[fail] Developer mode is off")
                fix = self.assist()
                if not fix:
                    self.state = "failed"
                    return
                continue
            info = pr["info"]
            self.ev("ok", f"Developer mode is on ({info.get('model-name', 'Roku')}, OS {info.get('software-version', '?')})"
                          + ("; its debug console answers, so errors can be read." if pr["console"] else "."))
            if not self.password:
                a = self.ask("password", text="The Roku's developer password (the one set when Developer mode was "
                                              "turned on; the user name is rokudev).")
                if not a:
                    self.state = "cancelled"
                    return
                self.password = str(a.get("password", ""))
            # 3. send it, with the debug console open to catch compile errors
            con = RokuConsole(ip) if pr["console"] else None
            self.ev("step", f"Sending {Path(path).name} to the Roku…")
            ok, msg = roku_install(ip, self.password, path, mode)
            if not ok:
                log = con.stop(1.5) if con else ""
                self.ev("fail", "The Roku didn't take the channel.", msg + (("\n--- the Roku's log ---\n" + log) if log else ""))
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
                continue
            self.ev("ok", msg)
            # 4. run it, and watch the first seconds for a crash
            self.roku_open(ip)
            log = con.stop(6.0) if con else ""
            bad = roku_log_errors(log)
            if bad:
                self.ev("fail", "It's on the Roku, but it stopped with an error as it started:", bad)
                self.assist(explain_only=True)
                self.state = "failed"
                return
            if log:
                self.ev("ok", "The Roku's log shows it running without errors.", log[-800:])
            self.state = "done"
            return


class RokuConsole:
    """The Roku's debug console (port 8085) read in the background: compile output during the install,
    and the first seconds of the run."""

    def __init__(self, ip):
        self.buf, self.alive = [], True
        try:
            self.sock = socket.create_connection((ip, ROKU_CONSOLE), timeout=3)
            self.sock.settimeout(0.5)
        except OSError:
            self.sock, self.alive = None, False
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while self.alive and self.sock:
            try:
                b = self.sock.recv(4096)
                if not b:
                    break
                self.buf.append(b.decode("utf-8", "replace"))
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self, wait=0.0):
        time.sleep(wait)
        self.alive = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        return "".join(self.buf)[-6000:].replace("\r", "")


_ROKU_ERR = re.compile(r"Syntax Error|Runtime Error|ERROR compiling|BRIGHTSCRIPT: ERROR|Micro Debugger|Brightscript Debugger|"
                       r"STOP \(runtime error|Error parsing XML|Crash|Backtrace", re.I)


def roku_log_errors(log):
    """The lines of the Roku's log that say something went wrong (with a little before them), or ""."""
    lines = (log or "").splitlines()
    hit = [i for i, l in enumerate(lines) if _ROKU_ERR.search(l)]
    if not hit:
        return ""
    a = max(0, hit[0] - 3)
    return "\n".join(lines[a:hit[0] + 12]).strip()


def _roku_open(job, ip):
    try:
        urllib.request.urlopen(urllib.request.Request(f"http://{ip}:{ROKU_ECP}/launch/dev", data=b"", method="POST"),
                               timeout=5).read()
        job.ev("ok", "Opened it on the Roku.")
    except Exception:
        job.ev("info", "It's on the Roku - open it from the Home screen (the channel at the end of the list).")


Job.roku_open = lambda self, ip: _roku_open(self, ip)


def roku_install(ip, password, path, mode="Install"):
    """The Roku developer installer (digest auth, user rokudev). -> (ok, message)."""
    boundary = "----AndroidBully" + uuid.uuid4().hex
    data = Path(path).read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"mysubmit\"\r\n\r\n{mode}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"archive\"; filename=\"{Path(path).name}\"\r\n"
            f"Content-Type: application/zip\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    host = ip if ROKU_WEB == 80 else f"{ip}:{ROKU_WEB}"
    pm.add_password(None, f"http://{host}/", "rokudev", password)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))
    req = urllib.request.Request(f"http://{host}/plugin_install", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with opener.open(req, timeout=120) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: " + ("wrong developer password (401)" if e.code == 401 else e.reason)
    except (ConnectionRefusedError, urllib.error.URLError) as e:
        return False, f"The Roku's developer installer isn't answering (port 80): {getattr(e, 'reason', e)}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    msgs = re.findall(r"<font color=\"?red\"?>(.*?)</font>", html, re.S | re.I) + \
        re.findall(r"'text': '([^']+)'", html)
    text = " ".join(re.sub(r"<[^>]+>", " ", m).strip() for m in msgs) or re.sub(r"<[^>]+>", " ", html)[:400]
    if re.search(r"Install Success|Received.*Install Success|Identical to previous version", text, re.I):
        return True, "Installed on the Roku." if "Identical" not in text else "Already on the Roku (identical)."
    return False, text.strip()[:600]


# ======================================================================================================
# Install by QR code: the phone downloads the APK from this computer - no developer mode, no ADB
# ======================================================================================================
QR_MINUTES = 30
_share = {"s": None}


class QrShare:
    """One APK offered on the home network for QR_MINUTES: a page that explains the install, and the
    file, both at a secret address (a random token) on this computer's home-network address only."""

    def __init__(self, f, lan_ip, computer=""):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.f, self.computer = f, computer
        self.token = uuid.uuid4().hex[:16]
        self.until = time.time() + QR_MINUTES * 60
        self.fname = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(f["path"]).stem)[:60] + ".apk"
        self.downloads = {}                       # their ip -> {got, total, done, at}
        share = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"         # one request per connection: a phone's download manager
                                                  # re-asks on its own connection (the page "hung", 2026-11-27)

            def log_message(self, *a):
                pass

            def do_GET(self):
                share.serve(self)

            def do_HEAD(self):
                share.serve(self, head=True)

        class Server(ThreadingHTTPServer):
            # The port is ours alone. Python's server lets a second one bind a port in use, and on Windows
            # the first then answers both - a test share's link went to a real share's 404 (2026-11-27).
            allow_reuse_address = False

            def server_bind(self):
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()

        self.srv = None
        for port in (8770, 0):
            try:
                self.srv = Server((lan_ip, port), H)
                break
            except OSError:
                continue
        self.srv.daemon_threads = True
        self.url = f"http://{lan_ip}:{self.srv.server_address[1]}/a/{self.token}/"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def live(self):
        return self.srv is not None and time.time() < self.until

    def stop(self):
        s, self.srv = self.srv, None
        if s:
            threading.Thread(target=lambda: (s.shutdown(), s.server_close()), daemon=True).start()

    def _send(self, h, code, body, ctype="text/html; charset=utf-8", head=False):
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        if not head:
            h.wfile.write(body)

    def serve(self, h, head=False):
        path = urllib.parse.urlparse(h.path).path
        base = f"/a/{self.token}/"
        if path == "/favicon.ico":
            return self._send(h, 204, b"", "image/x-icon", head)
        if not path.startswith(base):
            return self._send(h, 404, b"Not here.", "text/plain")
        if not self.live():
            return self._send(h, 410, "<h2>This link has ended</h2><p>Show the QR code again on the computer.</p>".encode())
        if path == base:
            return self._send(h, 200, self.page().encode("utf-8"))
        if path == base + self.fname:
            size = Path(self.f["path"]).stat().st_size
            who = h.client_address[0]
            rec = self.downloads.setdefault(who, {"got": 0, "total": size, "done": False, "at": time.time()})
            rec.update(got=0, total=size, done=False, at=time.time())
            h.send_response(200)
            h.send_header("Content-Type", "application/vnd.android.package-archive")
            h.send_header("Content-Length", str(size))
            h.send_header("Content-Disposition", f'attachment; filename="{self.fname}"')
            h.end_headers()
            if head:
                return
            try:
                with open(self.f["path"], "rb") as fh:
                    while True:
                        b = fh.read(256 * 1024)
                        if not b:
                            break
                        h.wfile.write(b)
                        rec["got"] += len(b)
                rec["done"] = True
            except OSError:
                pass
            return
        self._send(h, 404, b"Not here.", "text/plain")

    def page(self):
        f = self.f
        esc = lambda t: (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))   # noqa: E731
        ver = f.get("version_name") or ""
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Install {esc(f.get('name'))}</title>
<style>body{{margin:0;background:#0f172a;color:#d7e3f4;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:520px;margin:0 auto;padding:24px 20px 40px}}.b{{font:800 13px system-ui;letter-spacing:.16em;color:#00f2fe}}
h1{{font-size:22px;margin:6px 0 2px;color:#fff}}.m{{color:#8ea3c4;font-size:14px}}
a.go{{display:block;text-align:center;background:#00f2fe;color:#04131c;font-weight:800;text-decoration:none;padding:16px;
border-radius:12px;margin:22px 0;font-size:18px}}ol{{padding-left:20px}}li{{margin:10px 0}}
.n{{background:#13203a;border:1px solid #1e3054;border-radius:10px;padding:12px 14px;font-size:14px;color:#8ea3c4}}</style></head>
<body><main><div class="b">ANDROID BULLY · APK PUSHER</div><h1>{esc(f.get('package') or f.get('name'))}</h1>
<div class="m">{esc(f.get('name'))}{' · version ' + esc(ver) if ver else ''} · {f.get('size', 0) / 1048576:.1f} MB
{' · from ' + esc(self.computer) if self.computer else ''}</div>
<a class="go" id="go" href="{self.fname}" download="{self.fname}">Download and install</a>
<p class="n" id="after" style="display:none">Downloading… When it's done, open it from the notification (or Downloads)
and tap Install. If Chrome says the file can't be downloaded securely or might be harmful, choose <b>Keep</b> /
<b>Download anyway</b> - it comes from your own computer.</p>
<script>document.getElementById("go").onclick=function(){{document.getElementById("after").style.display="block";}};</script>
<ol><li>Tap <b>Download and install</b>. If Chrome warns that the file isn't secure or might be harmful, choose
<b>Keep</b> / <b>Download anyway</b> (it's from your own computer, on your Wi-Fi).</li>
<li>Open the downloaded file (from the notification, or the browser's Downloads).</li>
<li>If the phone says it can't install unknown apps from this source: tap <b>Settings</b>, turn on
<b>Allow from this source</b>, and go back.</li>
<li>Tap <b>Install</b>. If Google Play Protect warns about an unknown app: <b>More details &gt; Install anyway</b>
(only for apps you trust - this one came from your own computer).</li></ol>
<p class="n">This link works for {QR_MINUTES} minutes and only on your home network.</p></main></body></html>"""

    def view(self):
        return {"active": self.live(), "url": self.url, "until": self.until, "left": max(0, int(self.until - time.time())),
                "file": {k: self.f.get(k) for k in ("name", "package", "version_name", "size")},
                "downloads": [{"ip": ip, "pct": int(100 * r["got"] / max(1, r["total"])), "done": r["done"]}
                              for ip, r in self.downloads.items()]}


def qr_start(path):
    f = inspect(path)
    if not f.get("ok"):
        return f
    if f.get("type") == "bundle":
        return {"ok": False, "msg": "A split app (.apks / .xapk) can't be installed from a download - push it with "
                                    "Wireless debugging or USB instead."}
    if f.get("type") != "apk":
        return {"ok": False, "msg": "Install by QR code is for Android apps (.apk)."}
    nets = local_nets()
    if not nets:
        return {"ok": False, "msg": "This computer isn't on a home network the phone could reach."}
    if _share["s"]:
        _share["s"].stop()
    try:
        sh = QrShare(f, nets[0][0], socket.gethostname())
    except Exception as e:
        return {"ok": False, "msg": f"Couldn't offer the file on the network ({e})."}
    _share["s"] = sh
    import nd_qr
    return {"ok": True, "svg": nd_qr.svg(sh.url, px=7), **sh.view()}


# ======================================================================================================
# The page's ops
# ======================================================================================================
def handle(body, root, data_dir, llm=None, model_name="", vault=None):
    op = str(body.get("op") or "")
    if op == "qr_start":
        return qr_start(body.get("path"))
    if op == "qr_status":
        sh = _share["s"]
        return {"ok": True, **(sh.view() if sh else {"active": False})}
    if op == "qr_stop":
        if _share["s"]:
            _share["s"].stop()
            _share["s"] = None
        return {"ok": True}
    if op == "usb":
        found = usb_devices(root)
        _scan["devices"] = [x for x in _scan["devices"] if not x.get("usb")] + found
        return {"ok": True, "devices": found}
    if op == "health":
        return {"ok": True, "checks": health(root, body.get("device") or {}, model_name)}
    if op == "journal":
        jp = journal_path(vault, data_dir)
        try:
            return {"ok": True, "path": str(jp), "lines": [l[2:] for l in jp.read_text(encoding="utf-8").splitlines()
                                                          if l.startswith("- ")][-30:]}
        except OSError:
            return {"ok": True, "path": str(jp), "lines": []}
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
        j = Job(root, dev, f, llm, journal_path(vault, data_dir), model_name, Path(data_dir) / "tubeloader" / "outbox")
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
