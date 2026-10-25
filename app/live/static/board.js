/* Group Board (nd_board.py, /api/board): threads, replies, polls and attachments shared
 * between a group's Philibert drives. Opening it marks the news read (and tells the
 * desktop, which shows the badge). */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var st = {}, threads = [], cur = null, seenAtOpen = 0, newFiles = [];
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function api(op, d) {
    return fetch("/api/board", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ op: op }, d || {})) })
      .then(function (r) { return r.json(); })
      .catch(function (e) { return { ok: false, msg: "Philibert could not do that (" + e.message + ")." }; });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 3000); }
  function when(ms) {
    var d = new Date(ms), now = new Date();
    return d.toDateString() === now.toDateString() ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  function size(b) { return b >= 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB"; }
  function modal(id, on) { $(id).classList.toggle("on", on); }
  document.addEventListener("click", function (ev) { var c = ev.target.closest("[data-close]"); if (c) c.closest(".modal").classList.remove("on"); });

  function start() {
    return api("status").then(function (d) {
      st = d;
      $("joinview").hidden = !!d.joined; $("boardview").hidden = !d.joined;
      if (!d.joined) { $("jmsg").textContent = d.online ? "" : "Turn the Internet on first (INTERNET in Philibert Chat) - the board is shared online."; return; }
      seenAtOpen = d.seen || 0;
      $("gname").textContent = d.group.name; $("gname2").textContent = d.group.name;
      $("who").textContent = "you: " + d.member.name + (d.member.admin ? " (admin)" : "");
      $("topic").textContent = (d.phone && d.phone.topic) || "";
      $("invcode").textContent = d.group.invite || "";
      if (!d.online) { $("list").innerHTML = '<p class="empty">The board is online - turn the Internet on to see it.</p>'; return; }
      return loadList(true);
    });
  }
  function loadList(markSeen) {
    return api("threads").then(function (d) {
      if (!d.ok) { $("list").innerHTML = '<p class="empty">' + esc(d.msg) + "</p>"; return; }
      threads = d.threads || [];
      $("list").innerHTML = threads.map(function (t) {
        return '<div class="th' + (cur && cur.id === t.id ? " on" : "") + '" data-t="' + esc(t.id) + '">' + (t.last > seenAtOpen ? '<span class="new"></span>' : "") +
          "<b>" + (t.pinned ? '<span class="pin">&#9733; </span>' : "") + esc(t.title) + "</b>" +
          '<div class="meta">' + esc(t.by) + " · " + when(t.last) + " · " + t.replies + " repl" + (t.replies === 1 ? "y" : "ies") + (t.poll ? " · poll" : "") + "</div></div>";
      }).join("") || '<p class="empty">No posts yet - start one with + NEW POST.</p>';
      if (markSeen) seen();
    });
  }
  function seen() {
    api("changes").then(function (d) {
      if (d.ok) api("seen", { now: d.now }).then(function () { try { parent.postMessage("board-seen", location.origin); } catch (e) { /* not in the desktop */ } });
    });
  }
  function fileLink(f) {
    var u = "/api/board/file?id=" + encodeURIComponent(f.id);
    return /^image\//.test(f.type) ? '<a href="' + u + '" target="_blank" rel="noopener"><img src="' + u + '" alt="' + esc(f.name) + '"></a>'
      : '<a href="' + u + '&download=1">&#128206; ' + esc(f.name) + " · " + size(f.size) + "</a>";
  }
  function openThread(id) {
    $("view").innerHTML = '<p class="empty">Loading...</p>';
    return api("thread", { id: id }).then(function (d) {
      if (!d.ok) { $("view").innerHTML = '<p class="empty">' + esc(d.msg) + "</p>"; return; }
      cur = d.thread;
      [].forEach.call($("list").querySelectorAll(".th"), function (e) { e.classList.toggle("on", e.dataset.t === id); });
      var t = cur, p = t.poll, total = p ? p.counts.reduce(function (a, b) { return a + b; }, 0) : 0;
      $("view").innerHTML = '<div style="display:flex;gap:10px;align-items:center"><h2 style="margin-right:auto">' + esc(t.title) + "</h2>" +
        (st.member.admin ? '<button class="btn" id="pinbtn">' + (t.pinned ? "UNPIN" : "PIN TO TOP") + "</button>" : "") + "</div>" +
        (p ? '<div class="poll"><div class="q">' + esc(p.question) + (p.multi ? ' <span class="chip">pick any</span>' : "") +
          (p.closed ? ' <span class="chip">closed</span>' : p.closes ? ' <span class="chip">closes ' + esc(new Date(p.closes).toLocaleDateString()) + "</span>" : "") + "</div>" +
          p.options.map(function (o, i) {
            var pct = total ? Math.round(100 * p.counts[i] / total) : 0;
            return '<label class="opt"><input type="' + (p.multi ? "checkbox" : "radio") + '" name="pv" value="' + i + '"' + (p.mine.indexOf(i) >= 0 ? " checked" : "") +
              (p.closed ? " disabled" : "") + "><span>" + esc(o) + '</span><span class="n">' + p.counts[i] + "</span>" +
              '<span class="bar"><div style="width:' + pct + '%"></div></span>' +
              ((p.voters[i] || []).length ? '<span class="vs">' + esc(p.voters[i].join(", ")) + "</span>" : "") + "</label>";
          }).join("") + (p.closed ? "" : '<div class="acts"><button class="btn primary" id="votebtn">VOTE</button></div>') + "</div>" : "") +
        t.posts.map(function (x) {
          var mine = x.by_id === st.member.id;
          return '<div class="post' + (x.deleted ? " gone" : "") + '"><div class="hd"><b>' + esc(x.by) + "</b>" + esc(when(x.at)) +
            (!x.deleted && (mine || st.member.admin) ? '<button class="del" data-del="' + esc(x.id) + '">delete</button>' : "") + "</div>" +
            '<div class="bd">' + (x.deleted ? "(deleted)" : esc(x.body)) + "</div>" +
            ((x.files || []).length ? '<div class="files">' + x.files.map(fileLink).join("") + "</div>" : "") + "</div>";
        }).join("") +
        '<div class="compose"><textarea id="rb" rows="3" maxlength="10000" placeholder="Write a reply..."></textarea>' +
        '<div class="acts"><button class="btn primary" id="rsend">REPLY</button><input type="file" id="rf" multiple style="max-width:260px"><span class="msg" id="rmsg"></span></div></div>';
      $("rsend").onclick = reply;
      if ($("votebtn")) $("votebtn").onclick = vote;
      if ($("pinbtn")) $("pinbtn").onclick = function () { api("pin", { id: t.id }).then(function () { loadList(); openThread(t.id); }); };
    });
  }

  function upload(fileList, msgEl) {
    var files = [].slice.call(fileList || []);
    var big = files.filter(function (f) { return f.size > 5 * 1024 * 1024; });
    if (big.length) return Promise.reject(new Error(big[0].name + " is over 5 MB"));
    return files.reduce(function (p, f) {
      return p.then(function (ids) {
        msgEl.textContent = "Uploading " + f.name + "...";
        return new Promise(function (ok, no) {
          var r = new FileReader();
          r.onload = function () { ok(String(r.result).split(",")[1] || ""); };
          r.onerror = function () { no(new Error("could not read " + f.name)); };
          r.readAsDataURL(f);
        }).then(function (b64) { return api("upload", { name: f.name, type: f.type || "application/octet-stream", data: b64 }); })
          .then(function (d) { if (!d.ok) throw new Error(d.msg); return ids.concat([d.file.id]); });
      });
    }, Promise.resolve([]));
  }
  function reply() {
    var body = $("rb").value.trim(), files = $("rf").files;
    if (!body && !files.length) return;
    $("rsend").disabled = true;
    upload(files, $("rmsg")).then(function (ids) { return api("reply", { id: cur.id, body: body, files: ids }); })
      .then(function (d) { if (!d.ok) throw new Error(d.msg); $("rmsg").textContent = ""; openThread(cur.id); loadList(); })
      .catch(function (e) { $("rmsg").textContent = e.message; })
      .then(function () { if ($("rsend")) $("rsend").disabled = false; });
  }
  function vote() {
    var picked = [].map.call(document.querySelectorAll('input[name="pv"]:checked'), function (i) { return +i.value; });
    api("vote", { id: cur.id, options: picked }).then(function (d) { if (!d.ok) toast(d.msg); else { toast("Vote saved."); openThread(cur.id); } });
  }

  /* new post */
  function optRow(v) { var i = document.createElement("input"); i.type = "text"; i.maxLength = 100; i.placeholder = "A choice"; i.value = v || ""; $("po").appendChild(i); }
  $("b-new").onclick = function () {
    $("nt").value = ""; $("nb").value = ""; $("nf").value = ""; $("nfc").innerHTML = ""; $("np").checked = false; $("pollbox").hidden = true;
    $("po").innerHTML = ""; optRow(); optRow(); $("pq").value = ""; $("pm").checked = false; $("pc").value = ""; $("nmsg").textContent = "";
    modal("m-new", true); $("nt").focus();
  };
  $("np").onchange = function () { $("pollbox").hidden = !$("np").checked; };
  $("pa").onclick = function () { if ($("po").children.length < 10) optRow(); };
  $("nf").onchange = function () { $("nfc").innerHTML = [].map.call($("nf").files, function (f) { return '<span class="chip">' + esc(f.name) + " · " + size(f.size) + "</span>"; }).join(""); };
  $("n-send").onclick = function () {
    var title = $("nt").value.trim(), body = $("nb").value.trim(), poll = null;
    if (!title) { $("nmsg").textContent = "Give it a title."; return; }
    if ($("np").checked) {
      var opts = [].map.call($("po").children, function (i) { return i.value.trim(); }).filter(Boolean);
      if (opts.length < 2) { $("nmsg").textContent = "A poll needs at least two choices."; return; }
      var c = /^\d{4}-\d{2}-\d{2}$/.test($("pc").value.trim()) ? new Date($("pc").value.trim() + "T23:59:59").getTime() : null;
      poll = { question: $("pq").value.trim(), options: opts, multi: $("pm").checked, closes: c };
    }
    $("n-send").disabled = true;
    upload($("nf").files, $("nmsg")).then(function (ids) { return api("new_thread", { title: title, body: body, poll: poll, files: ids }); })
      .then(function (d) { if (!d.ok) throw new Error(d.msg); modal("m-new", false); toast("Posted."); return loadList().then(function () { return openThread(d.id); }); })
      .catch(function (e) { $("nmsg").textContent = e.message; })
      .then(function () { $("n-send").disabled = false; });
  };

  /* list, deleting, refresh */
  $("list").addEventListener("click", function (ev) { var t = ev.target.closest("[data-t]"); if (t) openThread(t.dataset.t); });
  $("view").addEventListener("click", function (ev) {
    var d = ev.target.closest("[data-del]"); if (!d) return;
    if (!confirm("Delete this post for everyone?" + (cur.posts[0].id === d.dataset.del ? "\n\nIt's the first post, so the whole thread goes." : ""))) return;
    api("delete_post", { id: cur.id, pid: d.dataset.del }).then(function (r) {
      if (!r.ok) { toast(r.msg); return; }
      if (cur.posts[0].id === d.dataset.del) { cur = null; $("view").innerHTML = '<p class="empty">Deleted.</p>'; loadList(); } else openThread(cur.id);
    });
  });
  $("b-refresh").onclick = function () { loadList(true).then(function () { if (cur) openThread(cur.id); }); };
  setInterval(function () { if (!$("boardview").hidden && st.online) loadList(true); }, 60000);

  /* phone, invite, joining, leaving */
  $("b-phone").onclick = function () { modal("m-phone", true); };
  $("b-invite").onclick = function () {
    modal("m-invite", true);
    api("me").then(function (d) { if (d.ok) $("members").innerHTML = d.members.map(function (m) { return '<span class="chip">' + esc(m.name) + (m.admin ? " (admin)" : "") + "</span>"; }).join(""); });
  };
  function copy(text) { (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () { toast("Copied."); }, function () { toast(text); }); }
  $("copytopic").onclick = function () { copy($("topic").textContent); };
  $("copyinv").onclick = function () { copy($("invcode").textContent); };
  $("leave").onclick = function () {
    if (!confirm("Leave the group on this drive? The group and its posts stay; you can join again with the invite code.")) return;
    api("leave").then(function () { modal("m-invite", false); cur = null; start(); });
  };
  function joinish(op, data) {
    $("jmsg").textContent = "";
    api(op, data).then(function (d) { if (!d.ok) { $("jmsg").textContent = d.msg; return; } toast(op === "create" ? "Group started - invite the others." : "Welcome!"); start(); });
  }
  $("create").onclick = function () { joinish("create", { group_name: $("cg").value, name: $("cn").value }); };
  $("join").onclick = function () { joinish("join", { invite: $("ji").value, name: $("jn").value }); };

  start();
})();
