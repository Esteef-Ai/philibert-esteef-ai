/* Feedback Shooter replies (Philibert only; shared/nd_feedback_replies.py does the work).
 * Under each sent message: the maker's replies and the person's own answers, newest last, with an
 * answer box once the maker has replied. Replies not seen before are marked NEW, then marked seen,
 * and the desktop is told so its badge goes. dev/patching.py FEEDBACK_REPLIES loads this after
 * feedback.js, which calls window.PhilFeedbackThread(item) for each row and exposes its list(). */
(function () {
  "use strict";
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function api(op, d) {
    return fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ op: op }, d || {})) })
      .then(function (r) { return r.json(); });
  }
  function text(s) {
    return esc(s).replace(/https?:\/\/[^\s<]+[^\s<.,;:!?)]/g, function (u) { return '<a href="' + u + '" target="_blank" rel="noopener">' + u + "</a>"; });
  }
  var css = document.createElement("style");
  css.textContent =
    ".thread{margin:-4px 0 12px 18px;padding:4px 0 2px 14px;border-left:2px solid var(--line)}" +
    ".reply{background:#0b1426;border:1px solid var(--line);border-radius:8px;padding:9px 12px;margin:6px 0}" +
    ".reply.maker{border-color:rgba(16,185,129,.45)}" +
    ".reply .who{font:10.5px var(--mono);color:var(--faint);margin-bottom:4px;display:flex;gap:10px}" +
    ".reply.maker .who b{color:var(--green)} .reply.mine .who b{color:var(--dim)}" +
    ".reply .new{color:var(--amber);font-weight:700}" +
    ".reply .body{white-space:pre-wrap;line-height:1.5;color:var(--txt)} .reply .body a{color:var(--cyan)}" +
    ".answer{display:flex;gap:8px;align-items:flex-start;margin-top:6px;flex-wrap:wrap}" +
    ".answer textarea{min-height:54px;flex:1 1 300px} .answer .msg{flex-basis:100%}";
  document.head.appendChild(css);

  var toSee = [];
  window.PhilFeedbackThread = function (i) {
    var thread = (i && i.status === "sent" && i.thread) || [];
    if (!thread.some(function (c) { return c.maker; })) return "";
    var seen = i.seen || [], fresh = false;
    var html = thread.map(function (c) {
      var isNew = c.maker && seen.indexOf(c.id) < 0;
      if (isNew) fresh = true;
      return '<div class="reply ' + (c.maker ? "maker" : "mine") + '"><div class="who"><b>' + (c.maker ? esc(c.by || "The maker") : "You") +
        "</b><span>" + new Date(c.at * 1000).toLocaleString() + "</span>" + (isNew ? '<span class="new">NEW</span>' : "") +
        '</div><div class="body">' + text(c.body) + "</div></div>";
    }).join("");
    if (fresh) toSee.push(i.id);
    return '<div class="thread">' + html +
      '<div class="answer"><textarea data-answer-text="' + esc(i.id) + '" maxlength="4000" placeholder="Answer the maker - this is public too, like your message"></textarea>' +
      '<button class="btn" data-answer="' + esc(i.id) + '">ANSWER</button><span class="msg" data-answer-msg="' + esc(i.id) + '"></span></div></div>';
  };
  // after a list is drawn: what it showed as NEW is now seen; the desktop drops its badge
  new MutationObserver(function () {
    if (!toSee.length) return;
    var ids = toSee;
    toSee = [];
    Promise.all(ids.map(function (id) { return api("seen", { id: id }).catch(function () {}); })).then(function () {
      try { if (parent !== window) parent.postMessage("feedback-seen", location.origin); } catch (e) { /* not in the desktop */ }
    });
  }).observe(document.getElementById("list"), { childList: true });

  document.getElementById("list").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-answer]");
    if (!b) return;
    var id = b.dataset.answer, box = document.querySelector('[data-answer-text="' + id + '"]'), msg = document.querySelector('[data-answer-msg="' + id + '"]');
    if (!box.value.trim()) { msg.textContent = "Write your answer first."; return; }
    b.disabled = true;
    msg.className = "msg"; msg.textContent = "Sending...";
    api("answer", { id: id, message: box.value }).then(function (r) {
      b.disabled = false;
      if (!r.ok) { msg.textContent = r.msg || "That did not work."; return; }
      if (window.PhilFeedbackList) window.PhilFeedbackList();
    }).catch(function () { b.disabled = false; msg.textContent = "Could not reach Philibert."; });
  });
})();
