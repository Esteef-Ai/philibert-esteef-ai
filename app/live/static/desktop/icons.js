/* The desktop's icons, drawn in-house in the spirit of mid-90s icons: 32x32,
 * the 16-colour palette, hard black outlines, crisp pixels. No Microsoft or
 * Apple artwork. PhilIcons.svg(name, size) -> an <svg> string.
 */
(function () {
  "use strict";
  var K = "#000", W = "#fff", LG = "#c0c0c0", DG = "#808080", NV = "#000080", TL = "#008080",
      RD = "#ff0000", MR = "#800000", YL = "#ffff00", OL = "#808000", GR = "#008000", LM = "#00ff00",
      CY = "#00ffff", BL = "#0000ff", PU = "#800080", MG = "#ff00ff";
  function r(x, y, w, h, f, s) {
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" fill="' + f + '"' +
           (s ? ' stroke="' + s + '" stroke-width="1"' : "") + "/>";
  }
  function p(d, f, s) { return '<path d="' + d + '" fill="' + (f || "none") + '"' + (s ? ' stroke="' + s + '"' : "") + "/>"; }

  var ART = {
    // Philibert Chat: the boombox with a speech bubble
    chat:
      p("M9 9V6h12v3", "none", K) +
      r(3.5, 9.5, 23, 14, LG, K) + r(4, 10, 22, 1, W) + r(4, 10, 1, 13, W) +
      '<circle cx="9.5" cy="16.5" r="4" fill="' + DG + '" stroke="' + K + '"/><circle cx="9.5" cy="16.5" r="1.5" fill="' + K + '"/>' +
      '<circle cx="20.5" cy="16.5" r="4" fill="' + DG + '" stroke="' + K + '"/><circle cx="20.5" cy="16.5" r="1.5" fill="' + K + '"/>' +
      r(13, 12, 4, 2, TL) + r(13, 19, 4, 1, K) +
      p("M18.5 20.5h12v8h-6l-3 3v-3h-3z", W, K) + r(21, 23, 7, 1, NV) + r(21, 25, 5, 1, NV),
    // Notes: a spiral notepad
    notes:
      r(6.5, 4.5, 19, 25, W, K) + r(7, 28, 18, 1, DG) + r(10, 5, 1, 24, RD) +
      r(12, 10, 11, 1, BL) + r(12, 13, 11, 1, BL) + r(12, 16, 11, 1, BL) + r(12, 19, 11, 1, BL) + r(12, 22, 8, 1, BL) +
      r(8, 2, 2, 5, DG) + r(13, 2, 2, 5, DG) + r(18, 2, 2, 5, DG) + r(23, 2, 2, 5, DG) +
      r(8, 2, 1, 5, K) + r(13, 2, 1, 5, K) + r(18, 2, 1, 5, K) + r(23, 2, 1, 5, K),
    // ND Suite: a chip
    suite:
      r(7.5, 7.5, 17, 17, DG, K) + r(8, 8, 16, 1, LG) + r(8, 8, 1, 16, LG) + r(11, 11, 10, 10, NV) +
      r(13, 13, 6, 6, CY) +
      [10, 14, 18, 22].map(function (x) { return r(x, 3, 1, 4, K) + r(x, 25, 1, 4, K) + r(3, x, 4, 1, K) + r(25, x, 4, 1, K); }).join(""),
    // Retro Vault: a game cartridge
    vault:
      p("M6.5 3.5h19v22h-3v3h-13v-3h-3z", LG, K) + r(7, 4, 18, 1, W) + r(7, 4, 1, 21, W) +
      r(9.5, 7.5, 13, 10, YL, K) + r(10, 8, 12, 2, RD) + r(12, 12, 8, 1, K) + r(12, 14, 6, 1, K) +
      r(11, 21, 1, 3, K) + r(14, 21, 1, 3, K) + r(17, 21, 1, 3, K) + r(20, 21, 1, 3, K),
    // Band Manager: an amp with a guitar leaning on it
    band:
      r(10.5, 8.5, 18, 20, "#404040", K) + r(11, 9, 17, 3, MR) + r(12, 13, 15, 13, K) +
      '<circle cx="19.5" cy="19.5" r="5" fill="#202020" stroke="' + DG + '"/>' +
      r(13, 10, 1, 1, YL) + r(16, 10, 1, 1, YL) + r(19, 10, 1, 1, YL) +
      p("M3 30l3-1 2-3 2 1-1 3-3 1z", MR, K) + p("M8 26l9-17", "none", K) + p("M15.5 8.5l3 -4 1 1-3 4", OL, K) +
      '<circle cx="6" cy="27" r="3.5" fill="' + RD + '" stroke="' + K + '"/>',
    // Image Generation: a painter's palette with a brush across it
    images:
      p("M16 4.5c7 0 12.5 4.5 12.5 10 0 3-2.5 4-4.5 3.5s-3.5 1-2.5 3c1 2.5-1 5-5.5 5C9 26 3.5 21 3.5 15S9 4.5 16 4.5z", "#c08040", K) +
      '<circle cx="9" cy="14" r="2" fill="' + RD + '" stroke="' + K + '"/><circle cx="13" cy="9" r="2" fill="' + YL + '" stroke="' + K + '"/>' +
      '<circle cx="19.5" cy="8.5" r="2" fill="' + LM + '" stroke="' + K + '"/><circle cx="24" cy="12.5" r="2" fill="' + BL + '" stroke="' + K + '"/>' +
      '<circle cx="11" cy="20" r="2.5" fill="' + W + '" stroke="' + K + '"/>' +
      p("M30 2.5l-10 13 1.5 1.5 10-12.5z", MR, K) + p("M20 15.5l-3 3 1 2 3.5-2z", LG, K) + r(15, 19, 2, 2, PU),
    // Control Panel: a window with sliders
    control:
      r(3.5, 5.5, 25, 21, LG, K) + r(4, 6, 24, 4, NV) + r(25, 7, 2, 2, LG) +
      r(7, 14, 18, 1, K) + r(7, 19, 18, 1, K) + r(7, 24, 18, 1, K) +
      r(10, 12, 3, 5, LG, K) + r(19, 17, 3, 5, LG, K) + r(14, 22, 3, 4, LG, K) + r(4, 25, 24, 1, DG),
    // Trash: a wire bin, empty
    trash:
      p("M8.5 9.5h15l-2 19h-11z", LG, K) + r(6.5, 7.5, 19, 2, DG, K) +
      p("M12 11v15M16 11v16M20 11v15", "none", DG) + p("M10 11l2 16", "none", W),
    trash_full:
      p("M8.5 9.5h15l-2 19h-11z", LG, K) + r(6.5, 7.5, 19, 2, DG, K) +
      p("M12 11v15M16 11v16M20 11v15", "none", DG) +
      p("M9 7l3-5 5 3 4-2 2 5z", W, K) + p("M12 6l3 1M17 5l2 2", "none", DG),
    // a published app: a plain program window
    app:
      r(4.5, 6.5, 23, 19, W, K) + r(5, 7, 22, 4, NV) + r(24, 8, 2, 2, LG) + r(7, 14, 10, 2, TL) + r(7, 18, 14, 1, DG) + r(7, 21, 12, 1, DG),
    // small things for menus
    folder:
      p("M3.5 9.5h9l2 2h13v15h-24z", YL, K) + r(4, 12, 23, 1, W),
    help:
      '<circle cx="16" cy="16" r="12.5" fill="' + YL + '" stroke="' + K + '"/>' +
      p("M12 13a4 4 0 1 1 6 3c-2 1-2 2-2 4", "none", K) + r(15, 22, 2, 2, K),
    find:
      '<circle cx="13" cy="13" r="7.5" fill="' + CY + '" stroke="' + K + '" stroke-width="2"/>' +
      '<path d="M18.5 18.5l8 8" stroke="' + K + '" stroke-width="3"/>',
    docs:
      r(7.5, 4.5, 15, 20, W, K) + r(10.5, 8.5, 15, 20, W, K) + r(13, 13, 9, 1, BL) + r(13, 16, 9, 1, BL) + r(13, 19, 6, 1, BL),
    gpu:
      r(3.5, 9.5, 25, 13, GR, K) + r(6, 12, 8, 8, K) + r(16, 12, 3, 3, YL) + r(20, 12, 3, 3, YL) + r(16, 17, 7, 2, LM) +
      [6, 9, 12, 15, 18, 21, 24].map(function (x) { return r(x, 23, 2, 3, OL); }).join(""),
    shutdown:
      r(3.5, 7.5, 25, 17, LG, K) + r(6, 10, 20, 12, NV) + '<circle cx="16" cy="16" r="4" fill="none" stroke="' + YL + '" stroke-width="2"/>' +
      r(15, 10, 2, 5, YL) + r(10, 25, 12, 2, DG, K),
    programs:
      r(4.5, 4.5, 11, 11, W, K) + r(16.5, 4.5, 11, 11, LG, K) + r(4.5, 16.5, 11, 11, LG, K) + r(16.5, 16.5, 11, 11, W, K) +
      r(5, 5, 10, 3, NV) + r(17, 17, 10, 3, NV),
    settings:
      r(5.5, 5.5, 21, 21, LG, K) + r(9, 9, 14, 3, NV) + r(9, 15, 14, 1, K) + r(9, 20, 14, 1, K) + r(12, 13, 3, 5, W, K) + r(18, 18, 3, 5, W, K),
  };

  function svg(name, size) {
    var art = ART[name] || ART.app;
    size = size || 32;
    return '<svg class="ico" viewBox="0 0 32 32" width="' + size + '" height="' + size +
           '" shape-rendering="crispEdges" aria-hidden="true">' + art + "</svg>";
  }

  // The P1 boombox for the Start button and the boot screen (one colour, or full).
  function p1(size, mark, bg) {
    mark = mark || K; bg = bg || LG;
    return '<svg viewBox="0 0 200 200" width="' + size + '" height="' + size + '" aria-hidden="true">' +
      '<path d="M62 62 V46 Q62 34 74 34 H126 Q138 34 138 46 V62" fill="none" stroke="' + mark + '" stroke-width="9" stroke-linecap="round"/>' +
      '<rect x="26" y="60" width="148" height="100" rx="16" fill="' + mark + '"/>' +
      '<circle cx="70" cy="104" r="25" fill="' + bg + '"/><circle cx="70" cy="104" r="17" fill="' + mark + '"/><circle cx="70" cy="104" r="6" fill="' + bg + '"/>' +
      '<circle cx="130" cy="104" r="25" fill="' + bg + '"/><circle cx="130" cy="104" r="17" fill="' + mark + '"/><circle cx="130" cy="104" r="6" fill="' + bg + '"/>' +
      '<path d="M48 143 H86 L93 134 L100 150 L107 138 L112 143 H152" fill="none" stroke="' + bg + '" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<rect x="44" y="160" width="20" height="10" rx="3" fill="' + mark + '"/><rect x="136" y="160" width="20" height="10" rx="3" fill="' + mark + '"/></svg>';
  }

  window.PhilIcons = { svg: svg, p1: p1, names: Object.keys(ART) };
})();
