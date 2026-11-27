"""A page that says why, for a person whose browser opens a phone or sharing address that does not work
(dev/patching.py PHONE_HELP hooks it into nd_modelshare._Relay._refuse).

The relay refuses with an empty body, and a phone's browser shows an empty body as a blank page: "nothing happens"
(an iPhone, 2026-11-26). Programs (the other computer's Philibert) never ask for text/html, so they still get the
plain refusal; a browser gets one of these instead, with the status code unchanged.

    send(handler, code) -> True when it answered with a page
"""
import ipaddress
import secrets
import urllib.parse

STEPS_PHONE = ("<li>In the <b>Tailscale</b> app on this phone, the switch at the top is on and it says <b>Connected</b>, "
               "signed in to the same account as the computer (or the computer was shared with you).</li>"
               "<li>Open the address in <b>Safari</b> (or Chrome), not inside another app's own browser: "
               "press and hold the link, then <i>Open in Safari</i>.</li>"
               "<li>Turn off any other VPN or ad blocker on the phone: only one VPN can be on at a time.</li>")

PAGES = {
    "tailscale": ("This only opens over Tailscale",
                  "<p>Philibert answers only your own devices, through Tailscale. This phone came in another way.</p>"
                  "<ol>" + STEPS_PHONE + "</ol>"),
    "old_address": ("This address does not work any more",
                    "<p>The computer answered, but this address is not its current one. Either a <b>NEW ADDRESS</b> was "
                    "made on the computer since it was sent, or the link was cut short on the way (some apps cut long links).</p>"
                    "<ol><li>On the computer: Philibert &gt; <b>Models</b> &gt; <i>Your other computers</i> &gt; "
                    "<b>COPY</b> beside the phone address.</li>"
                    "<li>Send it to this phone again and open the whole address. It ends in <code>/phone/</code>.</li></ol>"),
    "phone_off": ("Phone chat is turned off on that computer",
                  "<p>The computer answered, but its phone chat is off.</p>"
                  "<ol><li>On the computer: Philibert &gt; <b>Models</b> &gt; <i>Your other computers</i> &gt; "
                  "<b>OPEN A PHONE CHAT</b>.</li><li>Open the address it shows. It ends in <code>/phone/</code>.</li></ol>"),
    "laptop_address": ("This is the address for your other computers",
                       "<p>This address is the one a laptop pastes to use this computer's models. The phone has its own.</p>"
                       "<ol><li>On the computer: Philibert &gt; <b>Models</b> &gt; <i>Your other computers</i> &gt; "
                       "<b>OPEN A PHONE CHAT</b> (or <b>COPY</b> beside the phone address).</li>"
                       "<li>Open that one here. It ends in <code>/phone/</code>.</li></ol>"),
}

CSS = ("body{margin:0;background:#14161a;color:#e6e1d6;font:16px/1.5 -apple-system,system-ui,'Segoe UI',sans-serif}"
       "main{max-width:560px;margin:0 auto;padding:28px 18px}h1{font-size:21px;margin:0 0 12px;color:#e8c77a}"
       "p,li{color:#cfc9bc}ol{padding-left:22px}li{margin:8px 0}code{background:#22252b;padding:1px 5px;border-radius:4px}"
       ".by{margin-top:28px;font-size:12px;color:#7d786e}")


def why(h):
    """-> the page to show for this refused request."""
    import nd_modelshare
    try:
        if ipaddress.ip_address(h.client_address[0]) not in nd_modelshare.TAILNET:
            return "tailscale"
    except ValueError:
        return "tailscale"
    parts = urllib.parse.urlparse(h.path).path.split("/", 2)                 # "", key, rest
    key = parts[1] if len(parts) > 1 else ""
    if not key or not h.key or not secrets.compare_digest(key, h.key):
        return "old_address"
    rest = parts[2] if len(parts) > 2 else ""
    if rest == "phone" or rest.startswith("phone/"):
        return "phone_off"
    return "laptop_address"


def page(reason):
    title, body = PAGES[reason]
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Philibert - {title}</title><style>{CSS}</style></head><body><main>"
            f"<h1>{title}</h1>{body}<p class=\"by\">Philibert &middot; Esteef.Ai</p></main></body></html>").encode()


def send(h, code):
    if h.command not in ("GET", "HEAD") or "text/html" not in (h.headers.get("Accept") or ""):
        return False
    try:
        out = page(why(h))
    except Exception:
        return False
    h.close_connection = True
    h.send_response(code)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(out)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("Referrer-Policy", "no-referrer")
    h.send_header("Connection", "close")
    h.end_headers()
    if h.command == "GET":
        h.wfile.write(out)
    return True
