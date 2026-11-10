/* Reference a chat from the other app (Philibert <-> Philibert Code). Read-only, user-initiated.
 *
 *   ChatRef.attach(button, textarea)
 *
 * The button opens a picker of the OTHER app's chats (POST /api/chatref {op:"list"}); the chat picked
 * is put at the top of the message box as a quoted, labelled block ({op:"get"}), where the user can
 * read or trim it before sending. Nothing is sent or saved by this script. The button hides itself
 * when the other app is not installed. All text is set with textContent.
 * Owned by the Philibert repo (shared/), copied into both apps by their builds.
 */
(function () {
  "use strict";

  function api(op, extra) {
    return fetch("/api/chatref", {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(Object.assign({op: op}, extra || {}))
    }).then(function (r) { return r.json(); });
  }

  function el(tag, css, text) {
    var e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text != null) e.textContent = text;
    return e;
  }

  function when(t) {
    try { return new Date(t * 1000).toLocaleDateString(); } catch (e) { return ""; }
  }

  function insert(ta, text) {
    // the reference goes on top; whatever the user already typed stays below it
    ta.value = text + ta.value;
    ta.dispatchEvent(new Event("input", {bubbles: true}));   // enables Send, resizes the box
    ta.focus();
    try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) {}
  }

  var open = null;
  function close() { if (open) { open.remove(); open = null; document.removeEventListener("keydown", onKey, true); } }
  function onKey(e) { if (e.key === "Escape") { e.stopPropagation(); close(); } }

  function picker(btn, ta) {
    if (open) { close(); return; }
    var box = el("div", "position:fixed;z-index:99999;left:50%;top:12%;transform:translateX(-50%);" +
      "width:min(560px,92vw);max-height:70vh;display:flex;flex-direction:column;background:#1b1d22;color:#e8e8ea;" +
      "border:1px solid #4a4f5a;border-radius:8px;box-shadow:0 12px 40px rgba(0,0,0,.5);font:13px/1.4 system-ui,sans-serif");
    box.setAttribute("role", "dialog");
    box.className = "chatref-picker";
    var head = el("div", "display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #33363d");
    var title = el("div", "font-weight:600;flex:1", "Reference a chat");
    var x = el("button", "background:none;border:0;color:#aaa;font-size:18px;cursor:pointer", "×");
    x.title = "Close (Esc)";
    x.onclick = close;
    head.append(title, x);
    var note = el("div", "padding:6px 12px;color:#9aa0aa;font-size:12px",
      "The chat you pick goes into your message as a quoted block. You can edit it before you send.");
    var filter = el("input", "margin:6px 12px;padding:6px 8px;background:#111317;color:#e8e8ea;border:1px solid #3a3e47;border-radius:5px");
    filter.placeholder = "Filter by title or text";
    var list = el("div", "overflow:auto;padding:4px 6px 10px");
    list.append(el("div", "padding:10px;color:#9aa0aa", "Loading…"));
    box.append(head, note, filter, list);
    document.body.append(box);
    open = box;
    document.addEventListener("keydown", onKey, true);
    filter.focus();

    var all = [];
    function render() {
      var q = filter.value.trim().toLowerCase();
      list.textContent = "";
      var shown = all.filter(function (c) { return !q || (c.title + " " + c.preview).toLowerCase().indexOf(q) >= 0; });
      if (!shown.length) { list.append(el("div", "padding:10px;color:#9aa0aa", all.length ? "Nothing matches." : "No chats there yet.")); return; }
      shown.forEach(function (c) {
        var row = el("button", "display:block;width:100%;text-align:left;background:none;border:0;border-radius:5px;" +
          "padding:7px 8px;color:inherit;cursor:pointer");
        row.onmouseenter = function () { row.style.background = "#2a2e36"; };
        row.onmouseleave = function () { row.style.background = "none"; };
        var t = el("div", "font-weight:600", c.title);
        var meta = el("div", "color:#9aa0aa;font-size:12px", when(c.updated) + " · " + c.count + " messages · " + c.preview);
        row.append(t, meta);
        row.onclick = function () {
          row.disabled = true;
          api("get", {id: c.id}).then(function (r) {
            if (!r || !r.ok) { meta.textContent = (r && r.msg) || "Could not open that chat."; row.disabled = false; return; }
            insert(ta, r.text);
            close();
          }).catch(function () { meta.textContent = "Could not open that chat."; row.disabled = false; });
        };
        list.append(row);
      });
    }
    filter.oninput = render;
    api("list").then(function (r) {
      if (!r || !r.ok) { list.textContent = ""; list.append(el("div", "padding:10px;color:#e08a8a", (r && r.msg) || "Could not list the chats.")); return; }
      title.textContent = "Reference a chat from " + r.from;
      all = r.chats || [];
      render();
    }).catch(function () { list.textContent = ""; list.append(el("div", "padding:10px;color:#e08a8a", "Could not list the chats.")); });
  }

  window.ChatRef = {
    attach: function (btn, ta) {
      if (!btn || !ta) return;
      btn.hidden = true;
      api("list").then(function (r) {
        if (r && r.ok && r.installed) {
          btn.hidden = false;
          btn.title = "Reference a chat from " + r.from;
          btn.setAttribute("aria-label", btn.title);
        }
      }).catch(function () {});
      btn.addEventListener("click", function (e) { e.preventDefault(); picker(btn, ta); });
    }
  };
})();
