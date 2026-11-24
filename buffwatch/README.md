# Buff Watch

A single web page that watches one buff icon (e.g. Aurelia's Elixir) on your shared
MapleStory window and plays an alarm when it disappears.

## Use

1. Download `buff-watch.html` and open it in desktop Firefox, Chrome or Edge (double-click works).
2. **Share game window** → choose the MapleStory window.
3. Drag a box around your whole buff icon block.
4. In the zoomed view, drag a tight box around the potion icon (buff must be active).
5. Leave the page open in its own browser window. It keeps checking while it's behind the game.

The setup is saved in the browser, so next time you only click Share.
**Try a screenshot** lets you test the setup on a saved screenshot instead of a live share.

## How it detects

Four times a second it searches the boxed buff area for the icon you boxed, comparing pixel
colours. The match score is the share of icon pixels whose colour lines up. The bottom 30% is
ignored by default so timer numbers don't matter. The icon is scored as a 3×3 grid using its best 6 squares, so up to a third of it can be covered (mouse, tooltip, damage numbers) without an alarm.

Right after you box the icon it measures itself for 2 s (buff must be on): how well the icon
matches, and how well the best look-alike elsewhere in the area matches. The alarm cutoff is
set halfway between the two. Use *Recalibrate* any time the buff is on.

Alarm (beeps + optional voice) until the buff is back or you press *Silence*:
- about 0.5 s after it disappears, when its spot shows a different, unchanging picture
  (another icon slid in) for three checks in a row;
- after 1.5 s (adjustable) when something moving, like damage numbers, covers it.

If the game picture stops changing for 20 s (e.g. the game was
minimized) it also alarms, because it can no longer see the buff.
