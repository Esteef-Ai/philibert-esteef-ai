/* The desktop's wallpapers, all drawn here in the style of each era and branded
 * Philibert / Esteef.Ai. Nothing is copied from Microsoft, Apple, Google or
 * Commodore - these are our own designs that only borrow the period's feel.
 *
 *   PhilWalls.list[id] = {name, plain?, bg: CSS background, art?: (w, h) -> SVG/HTML}
 *   PhilWalls.themes[themeId] = [wallpaper ids], the first is the theme's default
 */
(function () {
  "use strict";
  var P1 = function (size, mark, bg) { return window.PhilIcons ? window.PhilIcons.p1(size, mark, bg) : ""; };
  function svg(w, h, body, extra) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="xMidYMid slice" ' +
           'style="position:absolute;inset:0;width:100%;height:100%"' + (extra || "") + ">" + body + "</svg>";
  }
  var W = 1600, H = 1000;          // every scene is drawn on this canvas and scaled to the screen

  var list = {
    // ---- plain colours (come with every theme) ----
    teal: { name: "(None) Teal", plain: true, bg: "#008080" },
    teal311: { name: "(None) Program Manager teal", plain: true, bg: "#008080" },
    slate: { name: "(None) Slate", plain: true, bg: "#3a5a7a" },
    plum: { name: "(None) Plum", plain: true, bg: "#5a2a6a" },
    xpblue: { name: "(None) Blue", plain: true, bg: "#3a6ea5" },
    platinum8: { name: "(None) Platinum", plain: true, bg: "#7d7d9e" },
    os9blue: { name: "(None) Nine Blue", plain: true, bg: "radial-gradient(ellipse at 30% 20%, #4a6fc4, #1f3478 75%)" },
    w11light: { name: "(None) Light", plain: true, bg: "#dfe8f3" },
    macgray: { name: "(None) Graphite", plain: true, bg: "#2b2d31" },
    phoneblack: { name: "(None) Black", plain: true, bg: "#000" },
    c64classic: { name: "Classic (blue)", plain: true, bg: "#6c5eb5" },

    // ---- 1993: Windows 3.11 - 16-colour bitmaps, tiles and a centred logo ----
    w311logo: { name: "Philibert Logo", bg: "#008080", art: function () {
      return '<div style="text-align:center;image-rendering:pixelated">' + P1(150, "#000080", "#00ffff") +
        '<div style="font:bold 34px/1.1 Arial,sans-serif;color:#fff;text-shadow:2px 2px #000;margin-top:8px">Philibert</div>' +
        '<div style="font:bold 15px Arial,sans-serif;color:#ffff00;text-shadow:1px 1px #000">for Workgroups 3.11 &middot; Esteef.Ai</div></div>';
    } },
    w311bricks: { name: "Philibert Bricks", bg: "repeating-linear-gradient(0deg, #c0c0c0 0 2px, transparent 2px 24px), " +
      "repeating-linear-gradient(90deg, #c0c0c0 0 2px, transparent 2px 48px) 0 0 / 48px 48px, #800000" },
    w311weave: { name: "Esteef.Ai Weave", bg: "repeating-linear-gradient(45deg, #000080 0 6px, #008080 6px 12px), #000080",
      art: function () { return '<div style="font:bold 64px Arial;color:#ffff00;text-shadow:3px 3px #000;letter-spacing:.05em">ESTEEF.AI</div>'; } },

    // ---- 1995: Windows 95 ----
    clouds: { name: "Clouds", bg: "linear-gradient(180deg, #2a6ad8 0%, #5a9ae8 50%, #a8cef4 100%)", art: function () {
      var c = function (x, y, rx, ry, o) { return '<ellipse cx="' + x + '" cy="' + y + '" rx="' + rx + '" ry="' + ry + '" fill="url(#cl)" opacity="' + o + '"/>'; };
      return svg(W, H, '<defs><radialGradient id="cl"><stop offset=".3" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>' +
        c(260, 200, 260, 80, .95) + c(1180, 140, 220, 70, .9) + c(700, 720, 360, 110, .95) + c(1450, 560, 200, 70, .8) + c(120, 820, 240, 80, .85));
    } },
    boombox: { name: "Boombox", bg: "#008080", art: function (w, h) {
      return P1(Math.round(Math.min(w, h) * 0.32) || 60, "rgba(0,0,0,.28)", "rgba(255,255,255,.12)");
    } },
    esteef: { name: "Esteef.Ai", bg: "radial-gradient(ellipse at 50% 45%, #13254a 0%, #0a1426 70%)", art: function () {
      return '<img src="/live/esteef-ai-e3.svg" alt="" style="width:46%;max-width:640px;filter:drop-shadow(0 0 18px rgba(0,242,254,.35))">';
    } },
    w95setup: { name: "Philibert 95 Setup", bg: "linear-gradient(180deg, #0000a8 0%, #000040 100%)", art: function () {
      return '<div style="text-align:center;color:#fff"><div style="font:italic 800 92px Montserrat,Arial;text-shadow:6px 6px 0 #000020">Philibert<span style="color:#ffe066;font-weight:400"> 95</span></div>' +
        '<div style="font:700 20px Arial;letter-spacing:.4em;color:#a8c8ff;margin-top:10px">ESTEEF.AI</div></div>';
    } },
    w95space: { name: "Philibert Plus! Space", bg: "radial-gradient(ellipse at 70% 30%, #1d1d5a 0%, #05050f 70%)", art: function () {
      var s = "";
      for (var i = 0; i < 160; i++) s += '<circle cx="' + (i * 977 % W) + '" cy="' + (i * 613 % H) + '" r="' + (i % 7 === 0 ? 2.2 : 1) + '" fill="#fff" opacity="' + (.3 + (i % 5) / 7) + '"/>';
      return svg(W, H, s + '<defs><radialGradient id="pl" cx=".35" cy=".35"><stop offset="0" stop-color="#ffd27a"/><stop offset=".6" stop-color="#d0602a"/><stop offset="1" stop-color="#3a1408"/></radialGradient></defs>' +
        '<circle cx="1180" cy="330" r="190" fill="url(#pl)"/><ellipse cx="1180" cy="330" rx="330" ry="54" fill="none" stroke="#e8b070" stroke-width="10" opacity=".7" transform="rotate(-14 1180 330)"/>' +
        '<text x="120" y="860" font-family="Montserrat,Arial" font-weight="800" font-style="italic" font-size="96" fill="#7ad4ff" opacity=".9">PHILIBERT</text>' +
        '<text x="126" y="905" font-family="Arial" font-weight="700" font-size="24" letter-spacing="12" fill="#ffd27a">PLUS! &#183; ESTEEF.AI</text>');
    } },

    // ---- 2001: Windows XP ----
    hills: { name: "Philibert Hills", bg: "#5a9ae8", art: function () {
      return svg(W, H, '<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3f7fe0"/><stop offset=".6" stop-color="#8fc0f2"/><stop offset="1" stop-color="#cfe6fb"/></linearGradient>' +
        '<linearGradient id="hill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5cb83a"/><stop offset="1" stop-color="#2a7d1c"/></linearGradient>' +
        '<radialGradient id="cl"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>' +
        '<rect width="1600" height="1000" fill="url(#sky)"/>' +
        '<ellipse cx="420" cy="230" rx="240" ry="60" fill="url(#cl)"/><ellipse cx="1180" cy="170" rx="300" ry="70" fill="url(#cl)"/><ellipse cx="900" cy="330" rx="180" ry="40" fill="url(#cl)" opacity=".7"/>' +
        '<path d="M0 720 Q 380 520 820 600 T 1600 640 V1000 H0Z" fill="url(#hill)"/><path d="M0 820 Q 500 700 1000 790 T 1600 760 V1000 H0Z" fill="#3f9a28" opacity=".8"/>' +
        '<text x="1530" y="960" text-anchor="end" font-family="Montserrat,Arial" font-style="italic" font-weight="800" font-size="30" fill="#fff" opacity=".55">philibert<tspan fill="#f47a1f" font-size="18" dy="-12">xp</tspan></text>');
    } },
    xpazul: { name: "Philibert Azul", bg: "linear-gradient(160deg, #0a3d91 0%, #2a7de1 55%, #8cc6ff 100%)", art: function () {
      var waves = "";
      for (var i = 0; i < 6; i++) waves += '<path d="M-100 ' + (560 + i * 50) + ' C 400 ' + (420 + i * 40) + ' 900 ' + (760 - i * 20) + ' 1700 ' + (500 + i * 45) + '" fill="none" stroke="#fff" stroke-width="' + (2 + i) + '" opacity="' + (.08 + i * .03) + '"/>';
      return svg(W, H, waves + '<text x="800" y="420" text-anchor="middle" font-family="Montserrat,Arial" font-style="italic" font-weight="800" font-size="120" fill="#fff" opacity=".22">philibert</text>');
    } },
    xpenergy: { name: "Esteef.Ai Energy", bg: "radial-gradient(ellipse at 50% 60%, #0b4f2a 0%, #031a10 70%)", art: function () {
      var r = "";
      for (var i = 0; i < 9; i++) r += '<ellipse cx="800" cy="560" rx="' + (720 - i * 40) + '" ry="' + (120 + i * 18) + '" fill="none" stroke="' + (i % 2 ? "#7dff9a" : "#20e0ff") + '" stroke-width="3" opacity="' + (.12 + i * .04) + '" transform="rotate(' + (-12 + i * 3) + ' 800 560)"/>';
      return svg(W, H, r + '<text x="800" y="580" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="64" letter-spacing="10" fill="#e6fff0" opacity=".85">ESTEEF.AI</text>');
    } },

    // ---- 2021: Windows 11 - soft blooms, glass, wide gradients ----
    w11bloom: { name: "Philibert Bloom", bg: "radial-gradient(ellipse at 50% 55%, #9cc8ff 0%, #4d86e6 40%, #1a3f9e 100%)", art: function () {
      var p = "";
      for (var i = 0; i < 7; i++) p += '<ellipse cx="800" cy="520" rx="330" ry="120" fill="url(#pt)" opacity=".55" transform="rotate(' + (i * 26 - 78) + ' 800 520) translate(0 -150)"/>';
      return svg(W, H, '<defs><linearGradient id="pt" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset=".5" stop-color="#7ab4ff"/><stop offset="1" stop-color="#1d5bd8"/></linearGradient>' +
        '<radialGradient id="ct"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>' + p +
        '<circle cx="800" cy="520" r="120" fill="url(#ct)" opacity=".7"/>' +
        '<text x="1560" y="970" text-anchor="end" font-family="Montserrat,Segoe UI,Arial" font-weight="600" font-size="22" fill="#fff" opacity=".7">Philibert 11 &#183; Esteef.Ai</text>');
    } },
    w11glow: { name: "Philibert Bloom (dark)", bg: "radial-gradient(ellipse at 50% 55%, #4b2a8a 0%, #1a1240 50%, #05040d 100%)", art: function () {
      var p = "";
      for (var i = 0; i < 7; i++) p += '<ellipse cx="800" cy="520" rx="330" ry="120" fill="url(#pt)" opacity=".5" transform="rotate(' + (i * 26 - 78) + ' 800 520) translate(0 -150)"/>';
      return svg(W, H, '<defs><linearGradient id="pt" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff9ee0"/><stop offset=".5" stop-color="#8a5cff"/><stop offset="1" stop-color="#2a1a7a"/></linearGradient></defs>' + p +
        '<text x="1560" y="970" text-anchor="end" font-family="Montserrat,Segoe UI,Arial" font-weight="600" font-size="22" fill="#fff" opacity=".6">Philibert 11 &#183; Esteef.Ai</text>');
    } },
    w11flow: { name: "Esteef.Ai Flow", bg: "linear-gradient(120deg, #e8f0ff 0%, #c4d8ff 45%, #f5d9f0 100%)", art: function () {
      var f = "";
      for (var i = 0; i < 5; i++) f += '<path d="M-100 ' + (300 + i * 120) + ' C 400 ' + (100 + i * 140) + ' 1100 ' + (700 - i * 60) + ' 1700 ' + (300 + i * 90) + ' L1700 1100 L-100 1100Z" fill="' + ["#9ec2ff", "#b7a6ff", "#f2a6de", "#7fd6ff", "#cfd9ff"][i] + '" opacity=".28"/>';
      return svg(W, H, f + '<g transform="translate(800 480)" opacity=".75"><ellipse rx="230" ry="80" fill="none" stroke="#2b5fd9" stroke-width="6"/>' +
        '<text y="22" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="64" letter-spacing="8" fill="#1b2a52">ESTEEF</text><circle cx="-190" cy="58" r="12" fill="#ff2e88"/></g>');
    } },

    // ---- 1997-1999: Mac OS 8 and 9 - platinum, patterns, soft photo-like gradients ----
    pattern7: { name: "Philibert Pattern", plain: true, bg: "radial-gradient(#6c6c88 1px, transparent 1.4px) 0 0 / 4px 4px, #9a9ab0" },
    esteefpat: { name: "Esteef.Ai Pattern", bg: "radial-gradient(circle at 10px 10px, #ff2e88 2px, transparent 2.5px) 0 0 / 40px 40px, " +
      "radial-gradient(ellipse 14px 7px at 24px 24px, transparent 11px, #00f2fe 11.5px 12.5px, transparent 13px) 0 0 / 40px 40px, #20304e" },
    os8logo: { name: "Philibert OS 8", bg: "linear-gradient(180deg, #8a8ab8 0%, #5c5c8e 100%)", art: function () {
      return '<div style="text-align:center">' + P1(180, "#2c2c66", "#d8d8ee") +
        '<div style="font:800 54px Charcoal,Montserrat,Arial;color:#fff;text-shadow:3px 3px 0 #2c2c66;margin-top:10px">Philibert OS 8</div>' +
        '<div style="font:600 14px Geneva,Arial;letter-spacing:.4em;color:#e0e0ff;margin-top:6px">ESTEEF.AI</div></div>';
    } },
    os9aqua: { name: "Philibert Aqua Drops", bg: "radial-gradient(ellipse at 40% 30%, #6fb6ff 0%, #2a5fc0 60%, #142c6a 100%)", art: function () {
      var d = "";
      for (var i = 0; i < 18; i++) {
        var x = (i * 389) % W, y = (i * 211) % H, r = 30 + (i * 37) % 90;
        d += '<circle cx="' + x + '" cy="' + y + '" r="' + r + '" fill="url(#dr)" opacity=".55"/>';
      }
      return svg(W, H, '<defs><radialGradient id="dr" cx=".35" cy=".3"><stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset=".4" stop-color="#9fd2ff" stop-opacity=".5"/><stop offset="1" stop-color="#2a5fc0" stop-opacity="0"/></radialGradient></defs>' + d +
        '<text x="800" y="540" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="88" fill="#fff" opacity=".85">Philibert OS 9</text>');
    } },
    os9mosaic: { name: "Esteef.Ai Mosaic", bg: "conic-gradient(from 45deg, #3f62c8 0 25%, #5a7ad8 0 50%, #2f4fa8 0 75%, #4a6ac8 0) 0 0 / 60px 60px", art: function () {
      return '<div style="background:rgba(255,255,255,.9);border:1px solid #000;box-shadow:2px 2px 0 rgba(0,0,0,.5);padding:18px 34px;font:800 40px Montserrat,Arial;letter-spacing:.12em;color:#1f3478">ESTEEF.AI</div>';
    } },

    // ---- today: macOS - dusk landscapes and liquid glass ----
    macdusk: { name: "Philibert Lake at Dusk", bg: "#1c1838", art: function () {
      return svg(W, H, '<defs><linearGradient id="sk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1e1b4b"/><stop offset=".45" stop-color="#8b3a8a"/><stop offset=".7" stop-color="#f08a5d"/><stop offset="1" stop-color="#ffd29a"/></linearGradient>' +
        '<linearGradient id="lk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6a86e"/><stop offset="1" stop-color="#1a1340"/></linearGradient></defs>' +
        '<rect width="1600" height="640" fill="url(#sk)"/><rect y="640" width="1600" height="360" fill="url(#lk)"/>' +
        '<path d="M0 640 L180 470 L330 560 L520 380 L700 520 L860 420 L1040 560 L1240 400 L1420 530 L1600 450 V640Z" fill="#2a1e4a"/>' +
        '<path d="M0 640 L240 560 L420 610 L640 540 L900 620 L1140 560 L1400 620 L1600 580 V640Z" fill="#160f30"/>' +
        '<path d="M0 640 L180 810 L330 720 L520 900 L700 760 L860 860 L1040 720 L1240 880 L1420 750 L1600 830 V640Z" fill="#2a1e4a" opacity=".35"/>' +
        '<text x="800" y="975" text-anchor="middle" font-family="Montserrat,Arial" font-weight="600" font-size="20" letter-spacing="10" fill="#fff" opacity=".45">PHILIBERT &#183; ESTEEF.AI</text>');
    } },
    macglass: { name: "Esteef.Ai Liquid Glass", bg: "linear-gradient(135deg, #0b1d4a 0%, #3a1c6e 50%, #0b3a5a 100%)", art: function () {
      return svg(W, H, '<defs><filter id="bl"><feGaussianBlur stdDeviation="60"/></filter><linearGradient id="gl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity=".05"/></linearGradient></defs>' +
        '<g filter="url(#bl)"><circle cx="420" cy="380" r="260" fill="#00c2ff"/><circle cx="1150" cy="300" r="240" fill="#ff4fa8"/><circle cx="900" cy="760" r="280" fill="#7a5cff"/></g>' +
        '<rect x="560" y="360" width="480" height="240" rx="120" fill="url(#gl)" stroke="#fff" stroke-opacity=".4" stroke-width="2"/>' +
        '<text x="800" y="500" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="54" letter-spacing="8" fill="#fff" opacity=".9">ESTEEF.AI</text>');
    } },

    // ---- today: iOS - vivid gradients, glass ----
    iosliquid: { name: "Philibert Liquid", bg: "linear-gradient(160deg, #ff7eb3 0%, #7a5cff 45%, #00c6ff 100%)", art: function () {
      return svg(W, H, '<defs><filter id="bl"><feGaussianBlur stdDeviation="80"/></filter></defs><g filter="url(#bl)" opacity=".9">' +
        '<circle cx="300" cy="250" r="320" fill="#ffd36e"/><circle cx="1300" cy="800" r="380" fill="#00e0c6"/><circle cx="900" cy="400" r="240" fill="#ff5f8f"/></g>' +
        '<text x="800" y="560" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="120" fill="#fff" opacity=".28">Philibert</text>');
    } },
    iosnight: { name: "Esteef.Ai Night", bg: "radial-gradient(ellipse at 50% 30%, #1b2a5a 0%, #05070f 70%)", art: function () {
      return svg(W, H, '<g transform="translate(800 470)"><ellipse rx="300" ry="110" fill="none" stroke="#00f2fe" stroke-width="5" opacity=".8"/>' +
        '<ellipse rx="300" ry="110" fill="none" stroke="#00f2fe" stroke-width="22" opacity=".12"/>' +
        '<text y="26" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="78" letter-spacing="10" fill="#fff">ESTEEF</text><circle cx="-250" cy="78" r="16" fill="#ff2e88"/></g>');
    } },

    // ---- today: Android - tonal Material shapes ----
    andmaterial: { name: "Philibert Material", bg: "#d8e9e2", art: function () {
      return svg(W, H, '<circle cx="300" cy="280" r="220" fill="#7fc8b0"/><rect x="980" y="120" width="520" height="260" rx="130" fill="#f4b8c8"/>' +
        '<path d="M760 620 m-200 0 a200 200 0 1 0 400 0 a200 200 0 1 0 -400 0" fill="#3f8f7a"/>' +
        '<path d="M1250 700 q60 -120 120 0 t120 0 t120 0 v300 h-360z" fill="#f9d58a"/>' +
        '<path d="M120 1000 c80 -200 260 -200 340 0z" fill="#a9b8f0"/>' +
        '<text x="800" y="640" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="74" fill="#fff">Philibert</text>');
    } },
    anddark: { name: "Esteef.Ai Tones (dark)", bg: "#141b19", art: function () {
      return svg(W, H, '<circle cx="1260" cy="260" r="240" fill="#2d4a42"/><rect x="120" y="600" width="600" height="300" rx="150" fill="#3a2f45"/>' +
        '<circle cx="520" cy="300" r="120" fill="#4f6b8a"/>' +
        '<text x="800" y="540" text-anchor="middle" font-family="Montserrat,Arial" font-weight="800" font-size="70" letter-spacing="10" fill="#bfe7d8">ESTEEF.AI</text>');
    } },

    // ---- 1982: Commodore 64 - the border is the wallpaper ----
    c64stripes: { name: "Philibert Loading Stripes", bg: "repeating-linear-gradient(180deg, #883932 0 9px, #67b6bd 9px 18px, #b8c76f 18px 27px, #8b5429 27px 36px, #6c5eb5 36px 45px, #9ad284 45px 54px)" },
    c64petscii: { name: "Esteef.Ai PETSCII", bg: "conic-gradient(#6c5eb5 0 25%, #352879 0 50%, #6c5eb5 0 75%, #352879 0) 0 0 / 16px 16px" },
  };

  var themes = {
    win311: ["teal311", "w311logo", "w311bricks", "w311weave", "slate", "esteef"],
    win95: ["teal", "clouds", "w95setup", "w95space", "boombox", "esteef", "slate", "plum"],
    winxp: ["hills", "xpazul", "xpenergy", "xpblue", "esteef", "boombox"],
    win11: ["w11bloom", "w11glow", "w11flow", "w11light", "esteef"],
    os8: ["platinum8", "os8logo", "esteefpat", "pattern7", "clouds", "boombox"],
    os9: ["os9blue", "os9aqua", "os9mosaic", "esteefpat", "clouds"],
    macos: ["macdusk", "macglass", "macgray", "esteef"],
    ios: ["iosliquid", "iosnight", "phoneblack"],
    android: ["andmaterial", "anddark", "phoneblack"],
    c64: ["c64classic", "c64stripes", "c64petscii"],
  };

  window.PhilWalls = { list: list, themes: themes };
})();
