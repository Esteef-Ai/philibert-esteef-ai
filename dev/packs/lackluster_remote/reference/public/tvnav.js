(function(){ 'use strict';
var on = false;
var lastApp = null;
var anchorX = null;
var lastSpot = null;
var idleTimer = null;
var SELECTOR = 'button, a[href], input, select, video, [tabindex], .fs-item, .prog-cell, .chip, .icon-btn, .avatar, .detail-chanlogo';
function $(id){ return document.getElementById(id); }
function isOpen(id){ var e = $(id); return !!e && e.classList.contains('open'); }
function isTvFirst(){ return typeof isTvBrowser === 'function' && isTvBrowser(); }
function rect(el){ return el.getBoundingClientRect(); }

function shown(el){
  if(!el) return false;
  if(!el.isConnected) return false;
  if(el.disabled) return false;
  var r = rect(el);
  if(r.width <= 0 || r.height <= 0) return false;
  var cs = getComputedStyle(el);
  if(cs.visibility === 'hidden') return false;
  if(cs.pointerEvents === 'none') return false;
  if(el.closest('[hidden]')) return false;
  var drawer = $('detail-drawer');
  if(drawer && !drawer.classList.contains('open')){
    if(el.closest('#detail-drawer')) return false;
  }
  return true;
}

function scope(){
  var gate = $('gate');
  if(gate && !gate.classList.contains('hidden')) return [gate];
  var subs = $('subs-modal');
  if(subs && isOpen('subs-modal')) return [subs];
  var playnow = $('playnow-modal');
  if(playnow && isOpen('playnow-modal')) return [playnow];
  var player = $('player-modal');
  if(player && isOpen('player-modal')){
    var social = $('social-panel');
    if(social && isOpen('social-panel')) return [social, player];
    return [player];
  }
  var opt = $('options-dropdown');
  if(opt && isOpen('options-dropdown')) return [opt];
  return [$('app')];
}

function inScope(el){
  var roots = scope();
  for(var i = 0; i < roots.length; i++){
    if(roots[i].contains(el)) return true;
  }
  return false;
}

function inGuide(el){
  return !!el && !!el.closest && !!el.closest('#guide-rows');
}

function guideRows(){
  var rows = document.querySelectorAll('#guide-rows .guide-row');
  var result = [];
  for(var i = 0; i < rows.length; i++){
    if(!rows[i].classList.contains('row-hidden')) result.push(rows[i]);
  }
  return result;
}

function rowLogo(row){
  return row.querySelector('.logo-tile');
}

function rowCells(row){
  var cells = row.querySelectorAll('.prog-cell');
  var sorted = [];
  for(var i = 0; i < cells.length; i++) sorted.push(cells[i]);
  sorted.sort(function(a, b){ return a.offsetLeft - b.offsetLeft; });
  return sorted;
}

function stickyRight(row){
  return rect(row.querySelector('.chan-cell')).right;
}

function visibleX(cell){
  var row = cell.closest('.guide-row');
  var left = Math.max(rect(cell).left, stickyRight(row));
  var right = Math.min(rect(cell).right, rect($('guide-scroll')).right);
  return right > left ? (left + right) / 2 : rect(cell).left + 4;
}

function cellAt(row, x){
  var cells = rowCells(row);
  var best = null, bestDist = Infinity;
  for(var i = 0; i < cells.length; i++){
    var c = rect(cells[i]);
    if(c.left <= x && x <= c.right) return cells[i];
    var dist = Math.min(Math.abs(x - c.left), Math.abs(x - c.right));
    if(dist < bestDist){ bestDist = dist; best = cells[i]; }
  }
  return best;
}

function revealInGuide(el){
  var sc = $('guide-scroll'), s = rect(sc), row = el.closest('.guide-row'), r = rect(row);
  var ruler = sc.querySelector('.guide-ruler-row'), top = ruler ? rect(ruler).bottom : s.top;
  if(r.top < top) sc.scrollTop -= (top - r.top);
  else if(r.bottom > s.bottom) sc.scrollTop += (r.bottom - s.bottom);
  if(el.classList.contains('prog-cell')){
    var c = rect(el), left = stickyRight(row);
    if(c.left > s.right - 120) sc.scrollLeft += c.left - left - 40;
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
    if(i < 0) return false;
    if(i < items.length) highlight(items[i]);
    return true;
  }
  var rows = guideRows(), j = rows.indexOf(row) + (dir === 'down' ? 1 : -1);
  if(j < 0) return false;
  if(j >= rows.length) return true;
  if(isLogo && anchorX == null){ highlight(rowLogo(rows[j])); return true; }
  if(anchorX == null) anchorX = visibleX(cur);
  highlight(cellAt(rows[j], anchorX) || rowLogo(rows[j]));
  return true;
}

function candidates(){
  var roots = scope();
  var list = [];
  for(var si = 0; si < roots.length; si++){
    var els = roots[si].querySelectorAll(SELECTOR);
    for(var i = 0; i < els.length; i++){
      var el = els[i];
      if(!shown(el)) continue;
      if(el.closest('.chan-fav-controls')) continue;
      if(el.tagName === 'A' && el.getAttribute('target') === '_blank') continue;
      if(inGuide(el)){
        var sc = rect($('guide-scroll'));
        var r = rect(el);
        if(!(r.bottom > sc.top + 30 && r.top < sc.bottom && r.right > sc.left && r.left < sc.right)) continue;
      }
      list.push(el);
    }
  }
  return list;
}

function highlight(el){
  if(!el) return false;
  if(!el.hasAttribute('tabindex') && el.tagName !== 'BUTTON' && el.tagName !== 'A' && el.tagName !== 'INPUT' && el.tagName !== 'SELECT'){
    el.setAttribute('tabindex', '-1');
  }
  el.focus({ preventScroll: true });
  if(inGuide(el)) revealInGuide(el); else if(el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  remember(el);
  return true;
}

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
  var roots = scope();
  if(roots[0] === $('player-modal') || roots[0] === $('social-panel')) return $('player-video');
  if(roots[0] === $('app')){
    if(lastApp && lastApp.isConnected && shown(lastApp)) return lastApp;
    var spot = spotElement();
    if(spot) return spot;
    var rows = guideRows();
    for(var i = 0; i < rows.length; i++){
      var cell = rows[i].querySelector('.prog-cell.on-now');
      if(cell) return cell;
      var logo = rows[i].querySelector('.logo-tile');
      if(logo) return logo;
    }
  }
  var cands = candidates();
  return cands.length ? cands[0] : null;
}

function move(dir){
  var cur = document.activeElement;
  if(!cur || cur === document.body || !inScope(cur) || !shown(cur)){
    highlight(firstChoice());
    return;
  }
  if(cur.id === 'player-video'){
    if(dir === 'up' || dir === 'down'){
      changeChannel(dir === 'down' ? 1 : -1);
      return;
    }
    highlight(document.querySelector('#player-modal button[onclick="closePlayer()"]'));
    return;
  }
  if(inGuide(cur) && moveInGuide(cur, dir)) return;
  var list = candidates();
  if(inGuide(cur)) list = list.filter(function(el){ return !inGuide(el); });
  var next = nearest(cur, dir, list);
  if(next){ anchorX = null; highlight(next); }
  else if(dir === 'up' && $('player-modal') && $('player-modal').contains(cur)){
    highlight($('player-video'));
  }
}

function changeChannel(step){
  var ids = guideRows().map(function(row){ return row.dataset.row; });
  if(!ids.length) return;
  var i = ids.indexOf(String(currentChannelId));
  var ni = ((i < 0 ? 0 : i + step) + ids.length) % ids.length;
  var newId = ids[ni];
  for(var j = 0; j < CHANNELS.length; j++){
    if(String(CHANNELS[j].id) === String(newId)){
      playChannel(CHANNELS[j].id, CHANNELS[j].name);
      return;
    }
  }
}

function playPause(){
  var v = $('player-video');
  if(!v) return;
  if(v.paused){
    var p = v.play();
    if(p && p.catch) p.catch(function(){});
  } else {
    v.pause();
  }
}

function turnOn(){
  if(on) return;
  on = true;
  document.body.classList.add('tv-nav');
}

function typing(el){
  if(el.tagName === 'TEXTAREA') return true;
  if(el.tagName === 'INPUT'){
    var t = (el.type || '').toLowerCase();
    if(t !== 'checkbox' && t !== 'radio' && t !== 'button' && t !== 'submit') return true;
  }
  return false;
}

document.addEventListener('keydown', function(e){
  if(e.altKey || e.ctrlKey || e.metaKey) return;
  var cur = document.activeElement;
  if(e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowRight'){
    var dir = e.key.replace('Arrow', '');
    if(typing(cur) && (dir === 'Left' || dir === 'Right')) return;
    e.preventDefault();
    turnOn();
    move(dir.toLowerCase());
    return;
  }
  if(e.key === 'Enter' || e.key === ' '){
    if(!on || !cur || cur === document.body || typing(cur)) return;
    if(cur.tagName === 'BUTTON' || cur.tagName === 'A' || cur.tagName === 'INPUT' || cur.tagName === 'SELECT' || cur.classList.contains('logo-tile')) return;
    if(cur.id === 'player-video'){ e.preventDefault(); playPause(); return; }
    e.preventDefault();
    cur.click();
  }
  if(e.key === 'MediaPlayPause' || e.key === 'MediaPlay' || e.key === 'MediaPause'){
    if(on && $('player-modal') && isOpen('player-modal')){
      e.preventDefault();
      playPause();
      return;
    }
  }
  if(e.key === 'Escape' || e.key === 'GoBack' || e.key === 'BrowserBack' || e.key === 'Backspace'){
    if(!typing(cur) && tvBack()) e.preventDefault();
  }
}, true);

document.addEventListener('focusin', function(e){
  var el = e.target;
  if(!$('app').contains(el) || scope()[0] !== $('app')) return;
  lastApp = el;
  remember(el);
});

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

function wake(){ document.body.classList.remove('tv-idle'); clearTimeout(idleTimer); idleTimer = setTimeout(function(){ document.body.classList.add('tv-idle'); }, 5000); }
document.addEventListener('keydown', wake, true);

var style = document.createElement('style');
style.textContent = 'body.tv-nav :focus{outline:3px solid #4CE0E8 !important; outline-offset:2px;}\nbody.tv-nav .prog-cell:focus, body.tv-nav .fs-item:focus, body.tv-nav #player-video:focus{outline-offset:-3px;}\nbody.tv-nav .prog-cell:focus{background:#1E2C63 !important; color:#F4F5F9;}\nbody.tv-device .player-modal{padding:0; gap:0;}\nbody.tv-device .player-modal .player-stage{width:100vw; height:100vh; display:flex; align-items:center; justify-content:center;}\nbody.tv-device .player-modal video{width:100%; height:100%; max-width:none; max-height:none; border-radius:0; object-fit:contain;}\nbody.tv-device .player-modal .player-info, body.tv-device .player-modal > div:last-child{position:absolute; bottom:12px; z-index:8; transition:opacity .4s ease;}\nbody.tv-device .player-modal .player-info{left:14px; background:rgba(8,10,15,.75); border-radius:10px; padding:6px 10px;}\nbody.tv-device .player-modal > div:last-child{right:14px;}\nbody.tv-device.tv-idle .player-modal .player-info, body.tv-device.tv-idle .player-modal > div:last-child{opacity:0;}';
document.head.appendChild(style);

window.tvNav = { isOn: function(){ return on; }, turnOn: turnOn };
if(typeof isTvBrowser === 'function' && isTvBrowser()){ document.body.classList.add('tv-device'); turnOn(); wake(); }

new MutationObserver(function(){
  if(!on || !lastSpot || scope()[0] !== $('app')) return;
  var cur = document.activeElement;
  if(cur && cur !== document.body && cur.isConnected) return;
  var el = spotElement();
  if(el){ var keep = anchorX; highlight(el); anchorX = keep; }
}).observe($('guide-rows'), { childList: true });

new MutationObserver(function(){
  if(!on) return;
  if(isOpen('player-modal')){ if(!$('player-modal').contains(document.activeElement)) highlight($('player-video')); }
  else if(!inScope(document.activeElement)){ highlight(firstChoice()); }
}).observe($('player-modal'), { attributes: true, attributeFilter: ['class'] });

new MutationObserver(function(){
  if(!on || !isOpen('detail-drawer')) return;
  setTimeout(function(){ var v = document.querySelector('.view'); if(v && isOpen('detail-drawer')) v.scrollTop = 0; }, 400);
}).observe($('detail-drawer'), { attributes: true, attributeFilter: ['class'] });

window.tvBack = tvBack;

})();
