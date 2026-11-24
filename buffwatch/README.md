# Buff Watch

A single web page that watches buff icons on your shared MapleStory window and sounds an alarm
when one needs you. It has two watchers, each in its own section with its own status, setup and
alarm sound:

- **Aurelia's Elixir** (or any buff): alarms when the icon disappears.
- **Stack counter** (e.g. the dice buff): alarms when the icon's number shows the value it had
  when you boxed it (e.g. 2).

Each can be turned off with its **Watch** checkbox and renamed.

## Use

1. Download `buff-watch.html` and open it in desktop Firefox, Chrome or Edge (double-click works).
2. **Share game window** → choose the MapleStory window.
3. In a watcher's section click **Box buff area**, then drag around the buff icon block on the game screen.
4. In that section's zoomed view, drag a tight box around the icon.
   - Elixir: while the buff is on.
   - Stack counter: while it shows the number you want to be warned about, number included.
5. Leave the page open in its own browser window. It keeps checking while it's behind the game.

While you set up one watcher, the others keep watching. The setup is saved in the browser, so
next time you only click Share. **Try a screenshot** tests a setup on a saved screenshot.

## How it detects

Four times a second each watcher searches its boxed area for its icon, comparing pixel colours.
The icon is scored as a 3×3 grid using its best 6 squares, so up to a third of it can be covered
(mouse, tooltip, damage numbers). Right after you box an icon it measures itself for 2 s: how well
the icon matches, and how well the best look-alike elsewhere in the area matches. The "found"
cutoff is set halfway between the two. Use **Recalibrate** any time the icon is on screen.

**Elixir:** the bottom 30% (timer numbers) is ignored. Alarm (square beeps + voice):
- about 0.5 s after it disappears, when its spot shows a different, unchanging picture
  (another icon slid in) for three checks in a row;
- after 1.5 s (adjustable) when something moving, like damage numbers, covers it.

**Stack counter:** the icon is found by the part above its number. The number is read by comparing
its bright white pixels with the ones you boxed (best overlap within ±1 px; 70% needed). A wider
number such as 12 doesn't count as 2. Two checks in a row at the boxed number → alarm (rising
chimes + voice). If it shows that number at setup, it stays quiet until the number changes. The
alarm stops once a different number shows, or the icon is gone for 3 s.

If the game picture stops changing for 20 s (e.g. the game was minimized) it also alarms, because
it can no longer see the buffs.
