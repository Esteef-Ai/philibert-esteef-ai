# NeuralDock UI House Style (fallback copy)

The live copy lives in the Obsidian vault and wins when it is reachable.
This copy is what a machine with no vault uses. Only the block between
the ND:RULES markers is injected into the model prompt.

<!-- ND:RULES -->
COLOUR: pick ONE dominant surface colour and ONE accent. The accent is rare -
small deliberate marks, not large areas. Full-saturation colour across big
blocks reads as cheap. Build depth from shades of the surface colour, not from
more hues. Two hue families is a design; six is an accident.

TYPE: three roles, no more. A display face for identity and headings only, a
clean readable face for body text, monospace for IDs, codes and data. Never set
body copy in a display or pixel font.

SPACE: pick one spacing unit (8px is fine) and use multiples of it everywhere.
Generous whitespace is what makes a layout look expensive.

STRUCTURE: if it is an application, give it application chrome - a menu or
toolbar, a navigation region, a main content region, and a status area. A
centred hero above three cards is a marketing page; do not build one unless a
marketing page was asked for.

STATES - every screen must visibly handle all of these:
  - loading: a real progress or skeleton, not just a spinner
  - empty: says what the user should do next, in a friendly voice
  - error: says what went wrong AND the concrete next step
  - disabled: controls that need data are visibly inert until it exists
  - hover and focus: on every interactive element, focus visible for keyboard

MOTION: at least one considered transition that is not a fade; keep transitions
under 250ms. Animate only in response to something real - the user's action, or
live data or activity - never decorative motion on a loop.

ALWAYS: a viewport meta tag; inline SVG for icons; real seeded content so every
view has something in it, never Lorem Ipsum.

FILES: default to a self-contained single file (CSS in <style>, JS in <script>)
only when nothing says otherwise. If the request, a spec, or the project's
existing files name a layout (for example static/viz.js or style.css), use
exactly those files and paths; the layout you were given always wins over
this default.
<!-- /ND:RULES -->
