# Lackluster Plus+: the whole app with a TV remote

Lackluster Plus+ (Philibert TV, by Esteef.Ai) is a running app: a channel guide and a player in one page. It was
made for a mouse or a finger. A Fire TV stick and a TCL Fire TV have neither: their remote sends the four arrow
keys, OK (Enter), Back and Play/Pause. This change makes every part of the app usable with those keys. It is
also what the Fire TV app (the next step) needs, since that app is this page in a frame without a pointer.

## What a person with a remote can do
- **See where they are.** One thing at a time has a bright outline (it is the real keyboard focus).
- **Move.** An arrow key moves the outline to the nearest thing in that direction. It never gets lost and never
  lands on something hidden, on a link that would open another window, or behind an open pop-up.
- **Press.** OK does what a click does, on buttons and on the things that are not real buttons.
- **The guide.** Left and Right walk along one channel's programmes; Up and Down go channel by channel and stay
  at the same time of day. Hidden channels are skipped. The guide scrolls so the outline is always on screen.
  When the guide redraws itself (every minute) the outline stays on the same programme.
- **Watch.** OK on a programme opens its info with Watch Live outlined; OK again starts the channel. On a
  channel's logo: OK shows what is on, OK again starts it.
- **In the player.** Up and Down change channel (wrapping round). OK and the Play/Pause button pause and resume.
  Left or Right reach the player's buttons; Up returns to the picture.
- **Back.** Back closes the top-most open thing: a pop-up, the chat panel, the player, the options, the info
  drawer, in that order, and puts the outline back where it was. With nothing open it tells the TV app so
  (`window.tvBack()` answers false) and the app may leave.
- **On a TV the picture fills the screen.** The channel line and the buttons lie over its bottom edge and fade
  after five seconds without a key; any key brings them back.

## What does not change
- A computer or phone user sees nothing different until they press an arrow key. Mouse and touch work as before.
- Text boxes keep Left and Right for the caret.
- Favourite stars and drawing stay mouse and touch features.
- The sign-in (code for TVs, same-tab for computers) works as it does now; its tests guard it.

## How it is built
One new file, `public/tvnav.js`, and one new line in `public/index.html` to load it. Nothing else changes.
