# Buff Watch

A single web page that watches buff icons on your shared MapleStory window and sounds an alarm
when one needs you. It has two watchers, each in its own section with its own status, setup and
alarm sound:

- **Aurelia's Elixir** (or any buff): alarms when the icon disappears.
- **Stack counter** (the dice buff): alarms when the icon's number reaches the number you choose
  (default 2). The dice icon is built in, so only its buff area needs a box, and that can be drawn
  before the buff has ever shown up. Untick **Use the built-in dice icon** to box a different icon
  yourself (at any number, e.g. while it's 1).

- **Loot timer**: reads the map's *Time Left* box and plays a ka-ching every 1:50 (counted down
  from the 30:00 start: 28:10, 26:20 … 0:40), plus a warning sound and voice at 0:30.

Each can be turned off with its **Watch** checkbox, muted with its own **Mute** button, and the
buffs can be renamed. **Mute all** silences everything.

## Use

1. Download `buff-watch.html` and open it in desktop Firefox, Chrome or Edge (double-click works).
2. **Share game window** → choose the MapleStory window.
3. In a watcher's section click **Box buff area**, then drag around the buff icon block on the game screen.
4. In that section's zoomed view, drag a tight box around the icon.
   - Elixir: while the buff is on.
   - Stack counter: nothing to box with the built-in dice icon. With your own icon: box it while
     it shows any number (e.g. 1), number included. Type the number to alarm at under its icon.
5. Leave the page open in its own browser window. It keeps checking while it's behind the game.

**Redo a box any time:** drag on the game screen to redo an area (the chips above the screen
pick which buff it's for), or drag in a buff's zoomed view to redo its icon box. Redoing only the
area keeps the icon and just re-measures. The **Redo…** buttons in each section do the same.

The game view stays live; it only pauses while you drag a box, and each box is cut from the frame
at the moment you start dragging.

While you set up one watcher, the others keep watching. The setup is saved in the browser, so
next time you only click Share. Firefox keeps that saved setup per file name: save new versions over
the old `buff-watch.html` (not as `buff-watch(6).html`) to keep it. **Try a screenshot** tests a setup on a saved screenshot.

**Mini view**: a compact panel for a small window beside the game (loot timer, a row per buff,
Pause, Mute all, Share/Stop). It switches on by itself when the window is narrower than 600 px;
**Expand** / **Mini view** switch by hand. The game preview isn't drawn while it's up.

## How it detects

Each check, every watcher searches its boxed area for its icon, comparing pixel colours.
The icon is scored as a 3×3 grid using its best 6 squares, so up to a third of it can be covered
(mouse, tooltip, damage numbers). Right after you box an icon it measures itself for 2 s: how well
the icon matches, and how well the best look-alike elsewhere in the area matches. The "found"
cutoff is set halfway between the two. Use **Recalibrate** any time the icon is on screen.

**Elixir:** the bottom 30% (timer numbers) is ignored. Alarm (square beeps + voice):
- about 0.5 s after it disappears, when its spot shows a different, unchanging picture
  (another icon slid in) for three checks in a row;
- after 1.5 s (adjustable) when something moving, like damage numbers, covers it.

**Stack counter:** the icon is found by the part above its number. The built-in dice icon is cut
from a screenshot with only the dice's own pixels kept (map background and the number corner are
transparent), and a fixed cutoff of 75% (Recalibrate while it's on screen to measure one). With your
own icon, the boxed number only tells it where the number sits. The live number is compared with the alarm number drawn in the game's own
5×7 digit font (built in, taken from screenshots), right-aligned at that spot (best overlap within
±3 px; 80% needed). Only
digit-shaped strokes count: bright, 1 px thin, outlined by darker pixels and sitting on the number's
baseline. Light map background showing through a round icon is ignored, so changing maps doesn't
break it. The section shows the alarm number next to what it reads now. A wider
number such as 12 doesn't count as 2. Two checks in a row at the boxed number → alarm (rising
chimes + voice). If it shows that number at setup, it stays quiet until the number changes. The
alarm stops once a different number shows, or the icon is gone for 3 s.

If the game picture stops changing for 20 s (e.g. the game was minimized) it also alarms, because
it can no longer see the buffs. That alarm can be turned off under **Alarm**.

**Loot timer:** box the *Time Left* box once. Its digits are seven-segment bars, so each digit is
read by checking which bars are lit (it ignores the box border, the "min"/"sec" text and things
showing through the box, and rejects a reading where a digit is missing). Once two readings agree
it counts down by the clock, and re-reads the box every 10 s: small drift is corrected, a jump up
means a new run (you re-entered the map), and if the timer can't be seen for 25 s the dings stop.
Missed ka-chings are never played in a burst. The interval (1:50), warning (0:30) and run length
(30:00) can be changed in its section.

**CPU use** (under **Alarm**): *Balanced* (default) checks twice a second and jumps to four times a
second the moment an icon looks off, so alarms stay quick; *Saver* checks once a second when calm;
*Fast* always checks four times a second. To keep CPU low it also asks the browser for only 8
frames a second, reads the screen once per check for all buffs, reuses the last result when the buff
areas haven't changed, skips the area search while an icon is clearly at its last spot, and
refreshes the preview once a second while just watching.

**Pause** (top of the page) stops all checks and alarms until you click **Resume**, e.g. while AFK.
