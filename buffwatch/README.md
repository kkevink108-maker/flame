# Buff Watch

A single web page that watches one buff icon (e.g. Aurelia's Elixir) on your shared
MapleStory window and plays an alarm when it disappears.

## Use

1. Download `buff-watch.html` and open it in desktop Chrome or Edge (double-click works).
2. **Share game window** → *Window* tab → MapleStory.
3. Drag a box around your whole buff icon block.
4. In the zoomed view, drag a tight box around the potion icon (buff must be active).
5. Leave the page open in its own browser window. It keeps checking while it's behind the game.

The setup is saved in the browser, so next time you only click Share.
**Try a screenshot** lets you test the setup on a saved screenshot instead of a live share.

## How it detects

Twice a second it searches the boxed buff area for the icon you boxed, comparing pixel
colours. The match score is the share of icon pixels that line up (the bottom 30% is ignored
by default so timer numbers don't matter, and partial cover by the mouse is tolerated).
Below 70% for 4 checks in a row (2 s) → alarm (beeps + optional voice) until the buff is back
or you press *Silence*. All thresholds are adjustable under *Alarm → Fine-tuning*.
