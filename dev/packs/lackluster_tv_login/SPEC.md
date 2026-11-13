# Lackluster Plus+: a sign-in that works on a TV

Lackluster Plus+ is a running app (Philibert TV, by Esteef.Ai): always-on TV channels built from a Plex library.
A small gateway (Node, `dist/`) signs viewers in with their own Plex account and serves one page
(`public/index.html`). This is a change to that app, not a new one.

## The problem
Pressing "Sign in with Plex" opens Plex's sign-in page in a popup window. A TV browser cannot handle a popup:
the window does not open, or opens where the remote cannot reach it. So the app cannot be used on a TV.

## What sign-in must be
- **Never a popup.** No window or tab is opened, on any device.
- **On a TV: a code.** The screen shows `plex.tv/link` and a 4-character code, big enough to read from a sofa,
  with a QR picture beside it. The viewer goes to plex.tv/link on a phone or computer, signs in to Plex there and
  types the code. The TV notices by itself and opens the guide. Nothing is typed on the TV.
  - A TV browser gets the code straight away, without pressing anything. So does any browser opened at `/?tv=1`.
  - A code lasts 15 minutes. When it runs out a new one replaces it by itself.
  - The whole screen fits a TV browser's 960x540 with nothing cut off.
- **On a computer or phone: two buttons.** "Sign in with Plex" takes this same tab to Plex's sign-in page; Plex
  sends it back to the app (`/?signin=return`), which finishes by itself and tidies the address. "On a TV? Sign in
  with a code" shows the code, with a Back button.
- **A remote or keyboard is enough.** The main button has the focus; Enter (a remote's OK) presses it.
- **Who gets in is unchanged.** Only Plex accounts the server is shared with; others are told why, on the screen.
- **A page cached before the change still signs in** (the old request with no body still works).

## Safety
- The pin a browser is signing in with is kept in a signed, HttpOnly cookie. The server never takes a pin id from
  the request. (Plex's pin ids count up: before this change anyone could poll a neighbour's pin and receive
  that person's session.)
- No tokens, secrets or addresses in the code. Tests never talk to the real Plex.

## What does not change
Everything else: the guide, the player, chat, casting, favourites, the admin pages, the brand.
