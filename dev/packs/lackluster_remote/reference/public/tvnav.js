// Lackluster Plus+ remote control: the whole app with arrow keys, OK and Back.
//
// A TV remote (Fire TV, Android TV) sends the arrow keys, Enter for OK and, through the
// TV app's wrapper, Back (window.tvBack()). This file adds that on top of the page without
// changing how the mouse and touch work:
//   - arrow keys move a visible highlight (real keyboard focus) to the nearest thing in
//     that direction; inside the guide they move by channel row and by programme
//   - Enter presses what is highlighted
//   - Back / Escape closes the top-most thing that is open
//   - in the player: Up/Down change channel, Enter pauses and resumes
// It turns itself on at the first arrow key, or straight away on a TV browser.
(function(){
  'use strict';

  var on = false;
  var anchorX = null;   // screen x kept while moving up and down the guide, so the column does not drift
  var lastApp = null;   // the last thing highlighted in the guide screen: where Back returns to
  var lastSpot = null;  // {chan, logo, x}: the guide cell to highlight again after the guide redraws itself

  var SELECTOR = 'button, a[href], input, select, video, [tabindex], .fs-item, .prog-cell, .chip, .icon-btn, .avatar, .detail-chanlogo';

  function $(id){ return document.getElementById(id); }
  function isOpen(id){ var e = $(id); return !!e && e.classList.contains('open'); }
  function rect(el){ return el.getBoundingClientRect(); }

  function shown(el){
    if(!el || !el.isConnected || el.disabled) return false;
    var r = rect(el);
    if(r.width <= 0 || r.height <= 0) return false;
    var c = getComputedStyle(el);
    if(c.visibility === 'hidden' || c.pointerEvents === 'none') return false;
    if(el.closest('[hidden]')) return false;
    var drawer = el.closest('#detail-drawer');
    if(drawer && !drawer.classList.contains('open')) return false;
    return true;
  }

  // The layer the remote is working in: only things inside it can be reached.
  function scope(){
    var gate = $('gate');
    if(gate && !gate.classList.contains('hidden')) return [gate];
    if(isOpen('subs-modal')) return [$('subs-modal')];
    if(isOpen('playnow-modal')) return [$('playnow-modal')];
    if(isOpen('player-modal')) return isOpen('social-panel') ? [$('social-panel'), $('player-modal')] : [$('player-modal')];
    if(isOpen('options-dropdown')) return [$('options-dropdown')];
    return [$('app')];
  }
  function inScope(el){
    return !!el && scope().some(function(root){ return root && root.contains(el); });
  }
  function inGuide(el){ return !!el && !!el.closest && !!el.closest('#guide-rows'); }

  // Inside the guide only what is on screen counts (the rest is reached row by row, cell by cell).
  function onScreenInGuide(el){
    var sc = rect($('guide-scroll')), r = rect(el);
    return r.bottom > sc.top + 30 && r.top < sc.bottom && r.right > sc.left && r.left < sc.right;
  }

  function candidates(){
    var out = [];
    scope().forEach(function(root){
      if(!root) return;
      Array.prototype.forEach.call(root.querySelectorAll(SELECTOR), function(el){
        if(!shown(el)) return;
        if(el.closest('.chan-fav-controls')) return;                 // favourites stay a mouse and touch feature
        if(el.tagName === 'A' && el.target === '_blank') return;     // a TV cannot open another window
        if(inGuide(el) && !onScreenInGuide(el)) return;
        out.push(el);
      });
    });
    return out;
  }

  function highlight(el){
    if(!el) return false;
    if(!el.hasAttribute('tabindex') && !/^(BUTTON|A|INPUT|SELECT)$/.test(el.tagName)) el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
    if(inGuide(el)) revealInGuide(el);
    else if(el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    remember(el);   // again, now that the guide has scrolled: the place is remembered as the person sees it
    return true;
  }

  // ── the guide: rows of channels, each a logo and its programmes ──────────
  function guideRows(){
    return Array.prototype.filter.call(document.querySelectorAll('#guide-rows .guide-row'), function(r){
      return !r.classList.contains('row-hidden');
    });
  }
  function rowLogo(row){ return row.querySelector('.logo-tile'); }
  function rowCells(row){
    return Array.prototype.slice.call(row.querySelectorAll('.prog-cell')).sort(function(a, b){ return a.offsetLeft - b.offsetLeft; });
  }
  function stickyRight(row){ var c = row.querySelector('.chan-cell'); return c ? rect(c).right : rect($('guide-scroll')).left; }
  // The middle of the part of a cell a person can see (a long programme runs off both edges).
  function visibleX(cell){
    var row = cell.closest('.guide-row'), sc = rect($('guide-scroll')), r = rect(cell);
    var left = Math.max(r.left, stickyRight(row)), right = Math.min(r.right, sc.right);
    return right > left ? (left + right) / 2 : r.left + 4;
  }
  function cellAt(row, x){
    var cells = rowCells(row), best = null, bestD = Infinity;
    cells.forEach(function(c){
      var r = rect(c), d = x < r.left ? r.left - x : x > r.right ? x - r.right : 0;
      if(d < bestD){ bestD = d; best = c; }
    });
    return best;
  }
  function revealInGuide(el){
    var sc = $('guide-scroll'), s = rect(sc), row = el.closest('.guide-row'), r = rect(row);
    var ruler = sc.querySelector('.guide-ruler-row'), top = ruler ? rect(ruler).bottom : s.top;
    if(r.top < top) sc.scrollTop -= (top - r.top);
    else if(r.bottom > s.bottom) sc.scrollTop += (r.bottom - s.bottom);
    if(el.classList.contains('prog-cell')){
      var c = rect(el), left = stickyRight(row);
      if(c.left > s.right - 120) sc.scrollLeft += c.left - left - 40;      // starts off the right edge: bring its start in
      else if(c.right < left + 40) sc.scrollLeft -= (left + 40 - c.right) + Math.min(c.width - 40, 300);
    }
    var v = rect(el);
    if(v.bottom > window.innerHeight || v.top < 0) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  function remember(el){
    if(!inGuide(el)){ if($('app').contains(el)) lastSpot = null; return; }
    var row = el.closest('.guide-row');
    var isLogo = el.classList.contains('logo-tile');
    lastSpot = { chan: row.dataset.row, logo: isLogo, x: isLogo ? 0 : (anchorX != null ? anchorX : visibleX(el)) };
  }
  function spotElement(){
    if(!lastSpot) return null;
    var row = document.querySelector('#guide-rows .guide-row[data-row="' + lastSpot.chan + '"]');
    if(!row || row.classList.contains('row-hidden')) return null;
    return lastSpot.logo ? rowLogo(row) : (cellAt(row, lastSpot.x) || rowLogo(row));
  }
  // -> true when the key was used up inside the guide
  function moveInGuide(cur, dir){
    var row = cur.closest('.guide-row'), isLogo = cur.classList.contains('logo-tile');
    if(dir === 'left' || dir === 'right'){
      anchorX = null;
      var items = [rowLogo(row)].concat(rowCells(row));
      var i = items.indexOf(cur) + (dir === 'right' ? 1 : -1);
      if(i < 0) return false;                         // left of the logo: out to the Browse column, if it is showing
      if(i < items.length) highlight(items[i]);
      return true;
    }
    var rows = guideRows(), j = rows.indexOf(row) + (dir === 'down' ? 1 : -1);
    if(j < 0) return false;                           // above the first channel: out to the buttons over the guide
    if(j >= rows.length) return true;
    // a logo moves to a logo; but a logo reached while walking a column (an empty channel) keeps the column
    if(isLogo && anchorX == null){ highlight(rowLogo(rows[j])); return true; }
    if(anchorX == null) anchorX = visibleX(cur);
    highlight(cellAt(rows[j], anchorX) || rowLogo(rows[j]));
    return true;
  }

  // ── everywhere else: the nearest thing in that direction ────────────────
  function nearest(cur, dir, list){
    var a = rect(cur), best = null, bestScore = Infinity;
    var acx = (a.left + a.right) / 2, acy = (a.top + a.bottom) / 2;
    list.forEach(function(el){
      if(el === cur) return;
      var b = rect(el), bcx = (b.left + b.right) / 2, bcy = (b.top + b.bottom) / 2, gap, off;
      if(dir === 'left' || dir === 'right'){
        if(dir === 'right' ? !(bcx > acx && b.right > a.right) : !(bcx < acx && b.left < a.left)) return;
        gap = Math.max(0, dir === 'right' ? b.left - a.right : a.left - b.right);
        off = (b.bottom > a.top && b.top < a.bottom) ? 0 : Math.abs(bcy - acy);
      } else {
        if(dir === 'down' ? !(bcy > acy && b.bottom > a.bottom) : !(bcy < acy && b.top < a.top)) return;
        gap = Math.max(0, dir === 'down' ? b.top - a.bottom : a.top - b.bottom);
        off = (b.right > a.left && b.left < a.right) ? 0 : Math.abs(bcx - acx);
      }
      var score = gap + off * 3 + (off ? 0 : Math.abs(dir === 'left' || dir === 'right' ? bcy - acy : bcx - acx) / 10);
      if(score < bestScore){ bestScore = score; best = el; }
    });
    return best;
  }

  function firstChoice(){
    var s = scope()[0];
    if(s === $('player-modal') || s === $('social-panel')) return $('player-video');
    if(s === $('app')){
      var again = (lastApp && lastApp.isConnected && shown(lastApp)) ? lastApp : spotElement();
      if(again) return again;
      var rows = guideRows();
      if(rows.length) return rows[0].querySelector('.prog-cell.on-now') || rowLogo(rows[0]);
    }
    return candidates()[0] || null;
  }

  function move(dir){
    var cur = document.activeElement;
    if(!cur || cur === document.body || !inScope(cur) || !shown(cur)){ highlight(firstChoice()); return; }
    if(cur.id === 'player-video'){
      if(dir === 'up' || dir === 'down'){ changeChannel(dir === 'down' ? 1 : -1); return; }
      highlight(document.querySelector('#player-modal button[onclick="closePlayer()"]'));
      return;
    }
    if(inGuide(cur) && moveInGuide(cur, dir)) return;
    var list = candidates();
    if(inGuide(cur)) list = list.filter(function(el){ return !inGuide(el); });
    var next = nearest(cur, dir, list);
    if(next){ anchorX = null; highlight(next); }
    else if(dir === 'up' && $('player-modal').contains(cur)) highlight($('player-video'));
  }

  // ── the player ───────────────────────────────────────────────────────────
  function changeChannel(step){
    var ids = guideRows().map(function(r){ return r.dataset.row; });
    if(!ids.length) return;
    var i = ids.indexOf(String(currentChannelId));
    var id = ids[((i < 0 ? 0 : i + step) + ids.length) % ids.length];
    var chan = CHANNELS.find(function(c){ return String(c.id) === id; });
    if(chan) playChannel(chan.id, chan.name);
  }
  function playPause(){
    var v = $('player-video');
    if(v.paused){ var p = v.play(); if(p && p.catch) p.catch(function(){}); } else { v.pause(); }
  }

  // ── Back ─────────────────────────────────────────────────────────────────
  // Closes the top-most open thing. -> false when nothing was open (the TV app then leaves).
  function tvBack(){
    var gate = $('gate');
    if(gate && !gate.classList.contains('hidden')){
      if(!$('link-panel').hidden && !isTvFirst()){ cancelSignIn(); return true; }
      return false;
    }
    if(isOpen('subs-modal')){ closeSubtitleSearch(); return back(); }
    if(isOpen('playnow-modal')){ closePlayNow(); return back(); }
    if(isOpen('player-modal')){
      if(isOpen('social-panel')){ closeSocialPanel(); highlight($('player-video')); return true; }
      closePlayer();
      return back();
    }
    if(isOpen('options-dropdown')){ toggleOptions(); return back(); }
    if(isOpen('detail-drawer')){
      var spot = spotElement();
      closeDetail();
      if(on) highlight(spot || firstChoice());
      return true;
    }
    return false;
  }
  function back(){
    if(on){ var cur = document.activeElement; if(!inScope(cur) || !shown(cur)) highlight(firstChoice()); }
    return true;
  }
  function isTvFirst(){ return typeof isTvBrowser === 'function' && isTvBrowser(); }

  // ── keys ─────────────────────────────────────────────────────────────────
  var DIRS = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' };
  function typing(el){
    return !!el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !/^(checkbox|radio|button|submit)$/.test(el.type)));
  }
  function turnOn(){
    if(on) return;
    on = true;
    document.body.classList.add('tv-nav');
  }

  document.addEventListener('keydown', function(e){
    if(e.altKey || e.ctrlKey || e.metaKey) return;
    var cur = document.activeElement, dir = DIRS[e.key];
    if(dir){
      if(typing(cur) && (dir === 'left' || dir === 'right')) return;       // the caret moves inside a text box
      e.preventDefault();
      turnOn();
      move(dir);
      return;
    }
    if(e.key === 'Enter' || e.key === ' '){
      if(!on || !cur || cur === document.body || typing(cur)) return;
      if(cur.id === 'player-video'){ e.preventDefault(); playPause(); return; }
      if(/^(BUTTON|A|INPUT|SELECT)$/.test(cur.tagName) || cur.classList.contains('logo-tile')) return;   // these answer Enter themselves
      e.preventDefault();
      cur.click();
      return;
    }
    if(e.key === 'MediaPlayPause' || e.key === 'MediaPlay' || e.key === 'MediaPause'){
      if(isOpen('player-modal')){ e.preventDefault(); playPause(); }
      return;
    }
    if(e.key === 'Escape' || e.key === 'GoBack' || e.key === 'BrowserBack' || (e.key === 'Backspace' && !typing(cur))){
      if(tvBack()) e.preventDefault();
    }
  }, true);

  // Where the highlight is, is followed wherever it goes (arrows, a mouse click, the page's own focus()).
  document.addEventListener('focusin', function(e){
    var el = e.target;
    if(!$('app').contains(el) || scope()[0] !== $('app')) return;
    lastApp = el;
    remember(el);
  });

  // ── keeping the highlight when the page changes under it ─────────────────
  // The guide redraws itself every minute, which destroys the highlighted cell.
  new MutationObserver(function(){
    if(!on || !lastSpot || scope()[0] !== $('app')) return;
    var cur = document.activeElement;
    if(cur && cur !== document.body && cur.isConnected) return;
    var el = spotElement();
    if(el){ var keep = anchorX; highlight(el); anchorX = keep; }
  }).observe($('guide-rows'), { childList: true });

  // When the player opens the remote goes to the video; when it closes, back to the guide.
  new MutationObserver(function(){
    if(!on) return;
    if(isOpen('player-modal')){
      if(!$('player-modal').contains(document.activeElement)) highlight($('player-video'));
    } else if(!inScope(document.activeElement)){
      highlight(firstChoice());
    }
  }).observe($('player-modal'), { attributes: true, attributeFilter: ['class'] });

  // The info drawer opens above the guide. The page then puts the focus on Watch Live, which on a small screen
  // scrolls the title out of sight: bring the top of the screen back so the person sees what they opened.
  new MutationObserver(function(){
    if(!on || !isOpen('detail-drawer')) return;
    setTimeout(function(){ var v = document.querySelector('.view'); if(v && isOpen('detail-drawer')) v.scrollTop = 0; }, 400);
  }).observe($('detail-drawer'), { attributes: true, attributeFilter: ['class'] });

  // On a TV the picture fills the screen; the channel line and the buttons lie over its bottom edge and fade
  // away after five seconds without a key.
  var idleTimer = null;
  function wake(){
    document.body.classList.remove('tv-idle');
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function(){ document.body.classList.add('tv-idle'); }, 5000);
  }
  document.addEventListener('keydown', wake, true);

  var css = document.createElement('style');
  css.textContent =
    'body.tv-nav :focus{outline:3px solid #4CE0E8 !important; outline-offset:2px;}' +
    'body.tv-nav .prog-cell:focus, body.tv-nav .fs-item:focus, body.tv-nav #player-video:focus{outline-offset:-3px;}' +
    'body.tv-nav .prog-cell:focus{background:#1E2C63 !important; color:#F4F5F9;}' +
    'body.tv-device .player-modal{padding:0; gap:0;}' +
    'body.tv-device .player-modal .player-stage{width:100vw; height:100vh; display:flex; align-items:center; justify-content:center;}' +
    'body.tv-device .player-modal video{width:100%; height:100%; max-width:none; max-height:none; border-radius:0; object-fit:contain;}' +
    'body.tv-device .player-modal .player-info, body.tv-device .player-modal > div:last-child{position:absolute; bottom:12px; z-index:8; transition:opacity .4s ease;}' +
    'body.tv-device .player-modal .player-info{left:14px; background:rgba(8,10,15,.75); border-radius:10px; padding:6px 10px;}' +
    'body.tv-device .player-modal > div:last-child{right:14px;}' +
    'body.tv-device.tv-idle .player-modal .player-info, body.tv-device.tv-idle .player-modal > div:last-child{opacity:0;}';
  document.head.appendChild(css);

  window.tvBack = tvBack;
  window.tvNav = { isOn: function(){ return on; }, turnOn: turnOn };
  if(isTvFirst()){ document.body.classList.add('tv-device'); turnOn(); wake(); }
})();
