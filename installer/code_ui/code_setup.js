/* Philibert Code Setup - the wizard. Talks to installer/code_app.py through pywebview's js_api.
 * Opened in a plain browser with ?mock=1 it uses a stand-in API with sample data (design previews only;
 * inside Setup's window every call waits for the real one - see installer/ui/setup.js for why).
 * Text from the computer (paths, versions, messages) is always escaped. */
(function () {
  "use strict";
  var PREVIEW = /[?&]mock=1/.test(location.search);
  var mockState = { n: 0 };
  var mock = {
    github_status: function () { return { needed: /[?&]signin=1/.test(location.search), device: true, signed_in: false }; },
    github_start: function () { return { ok: true, user_code: "WDJB-MJHT", uri: "https://github.com/login/device", interval: 1 }; },
    github_poll: function () { return { state: "ok", user: "tester" }; },
    github_token: function () { return { state: "ok", user: "tester" }; },
    installs: function () {
      return [{ path: "E:\\Philibert", version: "64735b0 2026-11-09 Philibert Code Setup: the repository comes from philibert.json", code_installed: null },
              { path: "K:\\Philibert", version: "27eb118 2026-11-09 Philibert: Ollama 0.40.4 -> 0.40.15", code_installed: "2026-11-09T21:40:00" }];
    },
    choose_folder: function () { return null; },
    check: function (root) {
      var slow = /[?&]slow=1/.test(location.search), old = /[?&]old=1/.test(location.search);
      return { path: root, problem: null, code_installed: null,
        ollama: { have: old ? "0.40.4" : "0.40.15", need: "0.40.15", ok: !old },
        hardware: { ok: !slow, gpu: slow ? "NVIDIA GeForce RTX 3060" : "NVIDIA GeForce RTX 5070 Ti", vram_gb: slow ? 12 : 15.9, ram_gb: slow ? 16 : 63.8,
          message: slow ? "This computer has 12 GB of graphics memory (it wants 16 GB) and 16 GB of memory (it wants 32 GB). Coding jobs will be very slow here, or the coding model will not load at all. You can install Philibert Code anyway."
                        : "This computer is ready for coding jobs: 15.9 GB graphics memory, 63.8 GB memory." },
        space: { free_gb: 412.3, need_gb: 22.6, ok: true } };
    },
    start_install: function () { mockState.n = 0; return true; },
    progress: function () {
      mockState.n = Math.min(mockState.n + 1, 30);
      var titles = ["Checking Philibert and this computer", "Copying Philibert Code", "Getting OpenCode and Git",
                    "Getting Philibert Code's Python packages", "Getting the coding model", "Finishing"];
      var step = Math.min(5, Math.floor(mockState.n / 5));
      return { steps: titles.map(function (t) { return { title: t, weight: 1 }; }), step: step, step_pct: (mockState.n % 5) / 5,
               overall: mockState.n / 30, detail: step === 4 ? "The coding model (Qwen3.6 coding, about 22 GB) - 8.4 of 22.0 GB" : "",
               done: mockState.n >= 30, error: "", warnings: [] };
    },
    cancel: function () { return true; },
    open_code: function () { return true; },
    close: function () { return true; }
  };
  var READY = new Promise(function (res) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.installs) return res();
    window.addEventListener("pywebviewready", function () { res(); });
    if (PREVIEW) setTimeout(res, 300);
  });
  function api(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    return READY.then(function () {
      if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) return window.pywebview.api[name].apply(null, args);
      if (PREVIEW) return mock[name].apply(null, args);
      throw new Error("Setup's window is not ready: " + name);
    });
  }

  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function gb(x) { x = Number(x) || 0; return (x >= 10 ? Math.round(x) : Math.round(x * 10) / 10) + " GB"; }

  var pages = Array.prototype.slice.call(document.querySelectorAll("section.page"));
  var rail = $("rail"), nextBtn = $("next"), backBtn = $("back"), msg = $("msg");
  var state = { page: 0, installs: [], pick: null, check: null, running: false };
  rail.innerHTML = pages.map(function (p, i) {
    return '<li><span class="n">' + (i + 1) + "</span>" + esc(p.getAttribute("data-title")) + "</li>";
  }).join("");

  function show(i) {
    state.page = i;
    pages.forEach(function (p, k) { p.classList.toggle("on", k === i); });
    Array.prototype.forEach.call(rail.children, function (li, k) { li.className = k < i ? "done" : (k === i ? "on" : ""); });
    backBtn.classList.toggle("hide", i === 0 || i === 4);
    backBtn.textContent = i === 3 ? "Cancel" : "Back";
    nextBtn.textContent = i === 2 ? "Install" : (i === 4 ? "Open Philibert Code" : "Next");
    nextBtn.classList.toggle("hide", i === 3);
    msg.textContent = "";
    if (ENTER[i]) ENTER[i]();
    validate();
    $("main").scrollTop = 0;
  }

  /* ---------- GitHub sign-in (only when the repository is private) ---------- */
  var gh = { needed: false, ok: false, polling: null };
  function ghDone(user) {
    gh.ok = true;
    clearTimeout(gh.polling);
    $("signin").classList.add("ok");
    $("gh-device").classList.add("hide"); $("gh-tokenbox").classList.add("hide");
    $("gh-msg").innerHTML = '<span class="good">Signed in as ' + esc(user || "you") + ".</span> You can go on.";
    validate();
  }
  function ghCheck() { api("github_status").then(function (s) {
    gh.needed = !!(s && s.needed);
    if (s && s.offline) {
      $("netnote").innerHTML = '<span class="warn">Setup could not reach GitHub just now' + (s.why ? " (" + esc(s.why) + ")" : "") +
        ". You can still go on - the download tries again.</span>";
      $("netnote").classList.remove("hide");
    }
    if (!gh.needed) return validate();
    $("signin").classList.remove("hide");
    if (!s.device) { $("gh-device").classList.add("hide"); $("gh-tokenbox").open = true; }
    if (s.signed_in) ghDone(s.user);
    validate();
  }); }
  $("gh-start").addEventListener("click", function () {
    $("gh-msg").textContent = "";
    api("github_start").then(function (d) {
      if (!d.ok) { $("gh-msg").innerHTML = '<span class="bad">' + esc(d.message) + "</span>"; return; }
      $("gh-code").textContent = d.user_code;
      $("gh-codebox").classList.remove("hide");
      var every = Math.max(1, d.interval || 5) * 1000;
      (function tick() {
        gh.polling = setTimeout(function () {
          api("github_poll").then(function (r) {
            if (r.state === "ok") return ghDone(r.user);
            if (r.state === "slow_down") every += 5000;
            if (r.state === "pending" || r.state === "slow_down") return tick();
            $("gh-wait").textContent = "";
            $("gh-msg").innerHTML = '<span class="bad">' + esc(r.message || (r.state === "expired" ? "The code ran out. Click Sign in again." :
              r.state === "denied" ? "The sign-in was not approved." : "Signing in did not work.")) + "</span>";
          });
        }, every);
      })();
    });
  });
  $("gh-use").addEventListener("click", function () {
    api("github_token", $("gh-token").value).then(function (r) {
      if (r.state === "ok") ghDone(r.user);
      else $("gh-msg").innerHTML = '<span class="bad">' + esc(r.message) + "</span>";
    });
  });

  /* ---------- page 2: which Philibert ---------- */
  function renderInstalls() {
    var box = $("installs");
    if (!state.installs.length) {
      box.innerHTML = '<div class="verdict no"><b>No Philibert found on this computer\'s drives.</b> Install Philibert first ' +
        "(Philibert Setup), start it once, then run this Setup again - or choose its folder below.</div>";
      return;
    }
    box.innerHTML = state.installs.map(function (x, i) {
      var sel = state.pick && state.pick.path === x.path ? " sel" : "";
      return '<div class="card' + sel + '" data-i="' + i + '"><h3>Philibert</h3><div class="path">' + esc(x.path) + "</div>" +
        (x.version ? '<div class="ver">' + esc(x.version) + "</div>" : "") +
        (x.code_installed ? '<div class="has">Philibert Code is already here - Setup will update it (your chats and settings stay).</div>' : "") + "</div>";
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll(".card"), function (c) {
      c.addEventListener("click", function () { pick(state.installs[+c.getAttribute("data-i")]); });
    });
  }
  function pick(x) {
    state.pick = x; state.check = null;
    $("pickmsg").classList.add("hide");
    renderInstalls();
    validate();
  }
  $("browse").addEventListener("click", function () {
    api("choose_folder").then(function (x) {
      if (!x) return;
      if (x.problem) {
        $("pickmsg").className = "verdict no";
        $("pickmsg").innerHTML = "<b>That folder will not do.</b> " + esc(x.problem);
        state.pick = null; renderInstalls(); validate(); return;
      }
      if (!state.installs.some(function (y) { return y.path === x.path; })) state.installs.push(x);
      pick(x);
    });
  });

  /* ---------- page 3: checks ---------- */
  function row(kind, title, text) {
    return '<div class="row"><span class="dot ' + kind + '"></span><div class="t"><b>' + esc(title) + "</b><small>" + text + "</small></div></div>";
  }
  function runCheck() {
    $("checks").innerHTML = '<div class="detail">Checking…</div>';
    state.check = null; validate();
    api("check", state.pick.path, $("opt-model").checked).then(function (c) {
      state.check = c;
      var h = [];
      if (c.problem) h.push(row("red", "Philibert", esc(c.problem)));
      else {
        h.push(row("green", "Philibert", esc(c.path) + (c.code_installed ? " - Philibert Code is already here; this updates it." : "")));
        h.push(c.ollama.ok ? row("green", "Philibert's Ollama", "Version " + esc(c.ollama.have) + " runs the coding model.")
          : row("red", "Philibert's Ollama", "Version " + esc(c.ollama.have || "unknown") + " is too old for the coding model (it needs " +
                esc(c.ollama.need) + " or newer). Update Philibert with its UPDATE button and start it once, then run this Setup again."));
        h.push(row(c.hardware.ok ? "green" : "yellow", "This computer", "Graphics: " + esc(c.hardware.gpu) + ". " + esc(c.hardware.message) +
          (c.hardware.ok ? "" : '<label class="ck" style="margin-top:8px"><input type="checkbox" id="opt-slow"' +
            (state.slow ? " checked" : "") + "> Install anyway</label>")));
        h.push(row(c.space.ok ? "green" : "red", "Space", gb(c.space.free_gb) + " free where Philibert is; this needs about " + gb(c.space.need_gb) + "."));
      }
      $("checks").innerHTML = h.join("");
      validate();
    });
  }
  $("opt-model").addEventListener("change", function () { if (state.page === 2) runCheck(); });
  $("checks").addEventListener("change", function (e) {          // "Install anyway" lives in the yellow row
    if (e.target && e.target.id === "opt-slow") { state.slow = e.target.checked; validate(); }
  });

  /* ---------- page 4: installing ---------- */
  function startInstall() {
    state.running = true;
    $("insterr").classList.add("hide");
    api("start_install", { philibert: state.pick.path, model: $("opt-model").checked, accept_slow: !!state.slow })
      .then(function () { setTimeout(poll, 400); });
  }
  function poll() {
    api("progress").then(function (s) {
      if (!s) return setTimeout(poll, 500);
      $("overall").style.width = Math.round((s.overall || 0) * 100) + "%";
      var sweep = s.step_pct < 0;
      $("stepbar").classList.toggle("sweep", sweep);
      $("steppct").style.width = sweep ? "" : Math.round((s.step_pct || 0) * 100) + "%";
      $("detail").textContent = s.detail || "";
      $("steps").innerHTML = (s.steps || []).map(function (st, k) {
        return '<li class="' + (k < s.step || s.done ? "done" : (k === s.step ? "on" : "")) + '">' + esc(st.title) + "</li>";
      }).join("");
      if (s.error) {
        state.running = false;
        $("insttitle").textContent = s.error === "cancelled" ? "Stopped" : "Setup stopped";
        $("insterr").innerHTML = s.error === "cancelled" ? "Nothing was harmed. Run Setup again to continue." : "<b>What happened:</b> " + esc(s.error);
        $("insterr").classList.remove("hide");
        backBtn.textContent = "Back"; backBtn.classList.remove("hide");
        return;
      }
      if (s.done) {
        state.running = false;
        $("warns").innerHTML = (s.warnings || []).map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("");
        return show(4);
      }
      setTimeout(poll, 500);
    });
  }

  /* ---------- moving between pages ---------- */
  var ENTER = {
    1: function () { api("installs").then(function (list) {
      list.forEach(function (x) { if (!state.installs.some(function (y) { return y.path === x.path; })) state.installs.push(x); });
      if (!state.pick && state.installs.length === 1) state.pick = state.installs[0];
      renderInstalls(); validate();
    }); },
    2: runCheck,
    3: startInstall,
    4: function () { $("donepath").textContent = state.pick.path + "\\code\\Start-Philibert-Code.bat"; }
  };
  function validate() {
    var ok = true, why = "";
    if (state.page === 0 && gh.needed && !gh.ok) { ok = false; why = "Sign in to GitHub first."; }
    if (state.page === 1 && !state.pick) { ok = false; why = state.installs.length ? "Pick a Philibert." : ""; }
    if (state.page === 2) {
      var c = state.check;
      if (!c) { ok = false; }
      else if (c.problem || !c.ollama.ok) { ok = false; why = "Fix the red item first."; }
      else if (!c.space.ok) { ok = false; why = "Not enough space where Philibert is."; }
      else if (!c.hardware.ok && !state.slow) { ok = false; why = "Tick 'Install anyway' (under This computer) to go on."; }
    }
    nextBtn.disabled = !ok;
    msg.textContent = why;
  }
  nextBtn.addEventListener("click", function () {
    if (state.page === 4) { api("open_code", state.pick.path).then(function () { api("close"); }); return; }
    show(state.page + 1);
  });
  backBtn.addEventListener("click", function () {
    if (state.page === 3) {
      if (state.running) { api("cancel"); return; }
      return show(2);
    }
    show(state.page - 1);
  });

  show(0);
  ghCheck();

  // design previews only (?mock=1&go=N): step forward N pages, picking the first Philibert on the way
  var go = PREVIEW && /[?&]go=(\d)/.exec(location.search);
  if (go) {
    var left = +go[1];
    (function step() {
      if (!left) return;
      if (state.page === 1 && !state.pick && state.installs.length) pick(state.installs[0]);
      if (nextBtn.disabled) return setTimeout(step, 150);
      left--; nextBtn.click(); setTimeout(step, 400);
    })();
  }
})();
