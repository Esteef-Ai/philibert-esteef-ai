/* Philibert Chat — the one-stop page around Elena Live's board and vault.
 *
 * Unload GPU, the brand spark, the Notes button, the note card (click a star in
 * the vault: its title, and OPEN takes it to the Notes app), and fitting the
 * live board into the small panel under the vault. The chat history is chats.js.
 */
(function () {
  "use strict";

  var toastEl = document.getElementById("toast");
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("on");
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { toastEl.classList.remove("on"); }, 2800);
  }
  window.philToast = toast;
  function stem(id) { return String(id).replace(/\.md$/i, "").split("/").pop(); }

  /* ---------- unload the GPU ---------- */
  var unloadBtn = document.getElementById("btn-unload");
  unloadBtn.addEventListener("click", function () {
    unloadBtn.classList.add("busy");
    unloadBtn.textContent = "UNLOADING…";
    fetch("/api/unload_gpu", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ reason: "the Unload GPU button" }) })
      .then(function (r) { return r.json(); })
      .then(function () { toast("The model is off the graphics card. It loads again on your next message."); })
      .catch(function () { toast("Could not unload the GPU."); })
      .then(function () { unloadBtn.classList.remove("busy"); unloadBtn.textContent = "UNLOAD GPU"; });
  });

  /* ---------- the Notes app, in its own window so the chat keeps going ---------- */
  function openNotesApp(id) {
    window.open("/notes" + (id ? "#" + encodeURIComponent(id) : ""), "philibert-notes", "popup,width=1320,height=880");
  }
  document.getElementById("btn-notes").addEventListener("click", function (ev) { ev.preventDefault(); openNotesApp(); });

  /* ---------- a star clicked in the vault ---------- */
  var card = document.getElementById("vault-card"), cardId = null;
  window.addEventListener("vault-focus", function (ev) {
    if (!ev.detail) { card.classList.remove("on"); return; }
    cardId = ev.detail;
    document.getElementById("vault-card-t").textContent = stem(cardId);
    card.classList.add("on");
  });
  document.getElementById("vault-card-open").addEventListener("click", function () { if (cardId) openNotesApp(cardId); });
  document.getElementById("vault-card-x").addEventListener("click", function () { card.classList.remove("on"); });

  /* ---------- the live board, scaled into its panel ---------- */
  var stage = document.getElementById("mini-stage"), board = document.getElementById("board-wrap");
  var BW = 760, BH = 470;
  function fit() {
    var w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    var k = Math.min(w / BW, h / BH);
    board.style.transform = "translate(" + ((w - BW * k) / 2) + "px," + ((h - BH * k) / 2) + "px) scale(" + k + ")";
  }
  if (window.ResizeObserver) new ResizeObserver(fit).observe(stage);
  window.addEventListener("resize", fit);
  fit();

  /* ---------- the brand spark follows the task ---------- */
  var spark = document.getElementById("brand-spark");
  window.addEventListener("viz-state", function (ev) {
    var st = ev.detail || null;
    var kind = (st && st.task && st.task.kind) || "idle";
    if (spark) spark.className = "spark" + (kind === "idle" ? "" : " " + kind);
  });
})();
