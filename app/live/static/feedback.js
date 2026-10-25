/* Feedback Shooter (nd_feedback.py, /api/feedback). Messages are saved on the drive and sent
 * as issues on Philibert's GitHub repository; the GitHub sign-in is the same device flow
 * as updates (/api/philibert/github_start|poll). */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var st = {}, kind = "idea", sys = null, signing = false;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function post(url, d) { return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d || {}) }).then(function (r) { return r.json(); }); }
  function api(op, d) { return post("/api/feedback", Object.assign({ op: op }, d || {})); }
  function say(t, ok) { $("msg").textContent = t || ""; $("msg").className = "msg" + (ok ? " ok" : ""); }

  function form() {
    return { kind: kind, part: $("part").value, title: $("title").value, message: $("message").value, include_system: $("sys").checked };
  }
  function status() {
    return api("status").then(function (d) {
      st = d;
      if (!$("kinds").children.length) {
        $("kinds").innerHTML = Object.keys(d.kinds).map(function (k) { return '<button type="button" data-k="' + k + '"' + (k === kind ? ' class="on"' : "") + ">" + esc(d.kinds[k]) + "</button>"; }).join("");
        $("part").innerHTML = d.parts.map(function (p) { return "<option>" + esc(p) + "</option>"; }).join("");
      }
      $("status").innerHTML = '<span class="' + (d.online ? "on" : "off") + '">INTERNET ' + (d.online ? "ON" : "OFF - messages wait on the drive") + "</span>" +
        "<span>" + (d.signed_in ? "GitHub: " + esc(d.user) : "GitHub: not signed in") + "</span>" +
        (d.waiting ? '<span class="off">' + d.waiting + " waiting to send</span>" : "") +
        (d.repo ? '<span>to github.com/' + esc(d.repo) + "</span>" : "");
      $("resend").hidden = !(d.waiting && d.online);
    });
  }
  function preview() {
    var f = form();
    if (!f.title.trim() || !f.message.trim()) { $("preview").textContent = "Write a title and a message to see it here."; return; }
    api("preview", f).then(function (d) {
      if (d.ok) $("preview").innerHTML = "<b>" + esc(d.title) + "</b>\n\n" + esc(d.body);
    });
  }
  var pt = 0;
  function later() { clearTimeout(pt); pt = setTimeout(preview, 300); }

  function list() {
    return api("list").then(function (d) {
      var items = d.items || [];
      $("list").innerHTML = items.map(function (i) {
        var tag = i.status === "sent" ? '<span class="tag sent">SENT #' + i.number + "</span>" + (i.state === "closed" ? '<span class="tag closed">CLOSED</span>' : "")
          : i.status === "failed" ? '<span class="tag failed">NOT SENT</span>' : '<span class="tag queued">WAITING</span>';
        return '<div class="item"><div><b>' + esc(i.title) + '</b><div class="meta">' + tag + "<span>" + esc((st.kinds || {})[i.kind] || i.kind) + " · " + esc(i.part) +
          "</span><span>" + new Date(i.at * 1000).toLocaleString() + "</span>" +
          (i.replies ? '<span style="color:#00f2fe">' + i.replies + " repl" + (i.replies === 1 ? "y" : "ies") + "</span>" : "") +
          (i.error ? '<span style="color:#ff2e88">' + esc(i.error) + "</span>" : "") + "</div></div><div>" +
          (i.url ? '<a class="btn" href="' + esc(i.url) + '" target="_blank" rel="noopener">OPEN</a>'
                 : '<button class="btn" data-del="' + esc(i.id) + '">DELETE</button>') + "</div></div>";
      }).join("") || '<p class="empty">Nothing sent yet.</p>';
    });
  }

  function signin() {
    if (signing) return Promise.resolve(false);
    signing = true;
    return post("/api/philibert/github_start", {}).then(function (s) {
      if (!s.ok) { signing = false; say(s.message || "Could not start signing in to GitHub."); return false; }
      $("signin").classList.add("on"); $("si-code").textContent = s.user_code; $("si-uri").textContent = s.uri;
      $("si-msg").textContent = "Waiting for you to approve it on GitHub...";
      var until = Date.now() + 15 * 60 * 1000, wait = (s.interval || 5) * 1000;
      return new Promise(function (done) {
        (function poll() {
          if (Date.now() > until) { $("si-msg").textContent = "The code expired - press SEND again."; signing = false; done(false); return; }
          setTimeout(function () {
            post("/api/philibert/github_poll", {}).then(function (p) {
              if (p.state === "ok") { $("signin").classList.remove("on"); signing = false; done(true); }
              else if (p.state === "slow_down") { wait += 5000; poll(); }
              else if (p.state === "pending") poll();
              else { $("si-msg").textContent = p.message || "GitHub sign-in did not finish."; signing = false; done(false); }
            }).catch(poll);
          }, wait);
        })();
      });
    });
  }
  function outcome(r) {
    if (r.need_signin) {
      say("Saved. Sign in to GitHub below to send it.");
      return signin().then(function (ok) { return ok ? api("send").then(outcome) : null; });
    }
    if (r.offline) say("Saved on the drive. It goes out when you turn the Internet on (INTERNET in Philibert Chat).", true);
    else if (r.error) say(r.error);
    else if (r.sent) say("Sent - thank you! You'll find it below.", true);
    return status().then(list);
  }
  function submit(sendNow) {
    var f = form();
    if (!f.title.trim() || !f.message.trim()) { say("Give it a short title and say what you'd like."); return; }
    $("send").disabled = $("later").disabled = true;
    say(sendNow ? "Sending..." : "");
    api("save", Object.assign(f, { send: sendNow })).then(function (d) {
      $("send").disabled = $("later").disabled = false;
      if (!d.ok) { say(d.msg || "That did not work."); return; }
      $("title").value = ""; $("message").value = ""; preview();
      if (!sendNow) { say("Saved for later.", true); return status().then(list); }
      return outcome(d);
    });
  }

  $("kinds").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-k]"); if (!b) return;
    kind = b.dataset.k;
    [].forEach.call($("kinds").children, function (x) { x.classList.toggle("on", x === b); });
    later();
  });
  ["part", "title", "message"].forEach(function (id) { $(id).addEventListener("input", later); });
  $("sys").addEventListener("change", function () { $("sysinfo").style.display = $("sys").checked ? "" : "none"; later(); });
  $("send").addEventListener("click", function () { submit(true); });
  $("later").addEventListener("click", function () { submit(false); });
  $("resend").addEventListener("click", function () { say("Sending..."); api("send").then(outcome); });
  $("list").addEventListener("click", function (ev) {
    var d = ev.target.closest("[data-del]"); if (!d) return;
    if (!confirm("Delete this message? It has not been sent.")) return;
    api("delete", { id: d.dataset.del }).then(function () { status().then(list); });
  });

  status().then(function () {
    api("system").then(function (d) {
      sys = d.system || {};
      $("sysinfo").innerHTML = Object.keys(sys).map(function (k) { return esc(k) + ": " + esc(sys[k]); }).join(" · ");
    });
    list();
    if (st.online) api("refresh").then(list);
  });
})();
