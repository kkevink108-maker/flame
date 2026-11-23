"""Combat Power Change reroller.

Finds the reset window by itself (any monitor, resolution or window size),
reads the result numbers, and:
  - all negative / 0  -> clicks Reset x3 (or x1), presses Enter twice, repeats
  - any positive      -> clicks the highest positive number and stops
All mouse/keyboard input goes through the Raspberry Pi Pico.

  python bot.py pick-window         # capture a window, e.g. the OBS fullscreen projector
  python bot.py set-region          # ...or draw a rectangle over the game screen picture
  python bot.py run                 # live monitor + bot (starts PAUSED, press START)
  python bot.py monitor             # live monitor only, never sends inputs
  python bot.py monitor --image x   # try it on a screenshot
  python bot.py test-pico           # hover the mouse over what it found (no clicks)
  python bot.py calibrate           # only if it can't find the buttons by itself

Hotkeys (work while the game is focused): F8 start/pause, F7 change reset mode, F9 quit.
"""
import argparse
import json
import os
import random
import sys
import threading
import time

import cv2

import ocr
from capture import make_source, normalize
from detector import DEFAULT_LAYOUT, TEMPLATE_DIR, USER_TEMPLATE_DIR, Detector
from monitor import MODES, Monitor, State, fmt_result

from paths import DATA_DIR, RESOURCE_DIR

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
DEBUG_DIR = os.path.join(DATA_DIR, "debug")

DEFAULTS = {
    "setup": "two_pc",           # two_pc: bot on this PC, game + Pico on another PC | one_pc
    "source": "region",          # region | window | screen | obs
    "region": None,              # region: rectangle on this PC showing the game screen (set-region)
    "monitor": 0,                # screen: 0 = all monitors, 1 = first, 2 = second...
    "window_title": None,        # window: title of the window to capture (pick-window)
    "auto_crop_bars": True,      # window: trim OBS's black letterbox bars
    "discord_webhook": None,     # Discord webhook link for notifications (menu: Discord notifications)
    "discord_user_id": None,     # your Discord user ID to get pinged (optional)
    "discord_notify_stops": True,# also notify when it stops for other reasons
    "flame_screenshot_delay": 1.0,# after clicking a positive, wait this long before the screenshot
    "window_capture": "auto",    # window: auto (works when covered, falls back) | screen
    "obs_camera_index": 0,       # obs: OBS Virtual Camera device index
    "obs_width": 1920,
    "obs_height": 1080,
    "pico_covers": "primary",    # one_pc only: primary | all : what the Pico's absolute mouse spans
    "target_screen": None,       # one_pc only: set by hand to override pico_covers
    "pico_port": None,           # e.g. "COM5"; None = auto-detect
    "mode": "auto",              # auto (x3 if available, else x1) | x1 | x3
    "enters_after_reset": 2,
    "move_time_min": 0.18,       # mouse glide time (seconds) for short moves
    "move_time_max": 0.45,       # ... and the longest a glide may take
    "click_settle": [0.06, 0.15],# pause on the target before clicking (random in range)
    "require_plus": True,        # only trust a positive when the "+" was read
    "stop_after_positive": True,
    "max_resets": 200,           # pause after this many resets per START (also set in the monitor)
    "max_resets_on": True,       # False = no limit (LIMIT ON / NO LIMIT button in the monitor)
    "cost_x1": 3_000_000,        # mesos per Reset x1 (for the spent tracker)
    "cost_x3": 9_000_000,        # mesos per Reset x3
    "delay_before_reset_click": 0.5,  # extra wait after the results show, before clicking Reset
    "delay_jitter": 0.2,         # every reset-loop wait varies randomly by +-20%
    "wiggle_every": [5, 15],     # move to a new spot on the Reset button every 5-15 resets
    "delay_after_reset_click": 0.6,
    "delay_between_enters": 0.4,
    "delay_after_enters": 1.5,   # time for the new results to appear
    "stable_gap": 0.2,           # two reads this far apart must agree
    "change_timeout": 4.0,       # results must change within this after a reset, else retry
    "max_retries": 6,            # reset retries in a row (numbers not changing) before pausing
    "max_unreadable": 25,
    "last_found": None,          # remembered spot of the Reset buttons (auto-saved)
    "layout": {},                # overrides for detector.DEFAULT_LAYOUT (set by calibrate)
}


# ---------------------------------------------------------------- config
# Old default values that were written into config.json by earlier versions;
# drop them so the current defaults apply.
OLD_DEFAULTS = {"delay_before_reset_click": [0.3], "change_timeout": [6.0], "window_title": ["MapleStory"]}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        for k, olds in OLD_DEFAULTS.items():
            if saved.get(k) in olds:
                del saved[k]
        cfg.update(saved)
    return cfg


def save_config(cfg):
    """Only settings that differ from the defaults are written, so improved defaults
    in a new version still reach you."""
    out = {k: v for k, v in cfg.items() if k not in DEFAULTS or v != DEFAULTS[k]}
    with open(CONFIG_PATH, "w") as f:
        json.dump(out, f, indent=2)


def fill_target_screen(cfg):
    if cfg.get("target_screen") or cfg.get("setup", "two_pc") == "two_pc":
        return
    import mss
    mons = mss.mss().monitors
    if cfg["pico_covers"] == "all":
        m = mons[0]
    else:
        m = next((m for m in mons[1:] if m["left"] == 0 and m["top"] == 0), mons[1])
    cfg["target_screen"] = {k: m[k] for k in ("left", "top", "width", "height")}


def source_key(cfg, image=None):
    """Identifies the capture setup, so a remembered spot is only reused with the same one."""
    if image:
        return "image"
    return (f"{cfg['source']}:{cfg.get('monitor')}:{cfg.get('window_title')}:"
            f"{cfg.get('obs_camera_index')}:{json.dumps(cfg.get('region'), sort_keys=True)}")


def make_detector(cfg, image=None):
    hint = None
    lf = cfg.get("last_found")
    if lf and lf.get("source") == source_key(cfg, image):
        hint = {k: lf[k] for k in ("scale", "x", "y")}
    return Detector(cfg.get("layout"), hint=hint)


# ---------------------------------------------------------------- helpers
def crop(frame, box):
    x, y, w, h = box
    return frame[y:y + h, x:x + w]


def read_boxes(frame, det, cfg):
    font_scale = det.scale * cfg.get("layout", {}).get("font_scale", 1.0)
    return [ocr.read_number(crop(frame, b), cfg["require_plus"], font_scale) for b in det.boxes]


def summary(results):
    return tuple((r["kind"], r["value"]) for r in results)


def save_debug(frame, det, tag):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(os.path.join(DEBUG_DIR, f"{stamp}_{tag}.png"), frame)
    if det:
        for i, b in enumerate(det.boxes):
            c = crop(frame, b)
            if c.size:
                cv2.imwrite(os.path.join(DEBUG_DIR, f"{stamp}_{tag}_box{i + 1}.png"), c)


def button_point(rect):
    """A random spot anywhere on the button (away from its very edges)."""
    x, y, w, h = rect
    return x + w * random.uniform(0.12, 0.88), y + h * random.uniform(0.28, 0.72)


def box_point(box, jitter=True):
    """A point inside the box, randomly near the middle so clicks aren't pixel-identical."""
    x, y, w, h = box
    if jitter:
        return x + w * random.uniform(0.35, 0.65), y + h * random.uniform(0.35, 0.65)
    return x + w / 2, y + h / 2


def sleep(base, jitter=0.2):
    """Wait base seconds, randomly varied by +-jitter (0.2 = +-20%)."""
    time.sleep(max(0.0, base * random.uniform(1 - jitter, 1 + jitter)))


def blank_exclusion(frame, source, rect):
    """Black out our own monitor window if it's inside the captured area (only matters
    when photographing the screen; a direct window capture never contains it)."""
    if not rect or not hasattr(source, "from_desktop") or getattr(source, "using", None) == "window":
        return
    x, y, w, h = rect
    fx, fy = source.from_desktop(x, y)
    fx, fy = int(fx), int(fy)
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = max(0, fx), max(0, fy), min(fw, fx + w), min(fh, fy + h)
    if x0 < x1 and y0 < y1:
        frame[y0:y1, x0:x1] = 0


def pick_button(det, mode):
    """Which reset button to press -> ("x1"|"x3", rect) or (None, reason)."""
    if mode == "x3":
        return ("x3", det.x3) if det.x3 else (None, "Reset x3 not available")
    if mode == "x1":
        return ("x1", det.x1) if det.x1 else (None, "Reset x1 not available")
    if det.x3:
        return "x3", det.x3
    if det.x1:
        return "x1", det.x1
    return None, "No reset button available"


def start_hotkeys(state):
    try:
        from pynput import keyboard
    except ImportError:
        return

    def on_press(key):
        if key == keyboard.Key.f8:
            state.toggle_running()
        elif key == keyboard.Key.f7:
            state.cycle_mode()
        elif key == keyboard.Key.f9:
            state.set(quit=True)

    keyboard.Listener(on_press=on_press, daemon=True).start()


# ---------------------------------------------------------------- the bot
class Bot:
    def __init__(self, cfg, state, source, detector, pico=None, image=None):
        self.cfg, self.st, self.src, self.det, self.pico = cfg, state, source, detector, pico
        self.image = image
        self.last_reset = None   # (button, rect, spot) of the last reset click
        self.until_wiggle = 0    # resets left before moving to a new spot on the button

    def click(self, x, y):
        """Glide to a frame pixel (if not already there), click, and leave the mouse there."""
        cfg = self.cfg
        nx, ny = normalize(self.src, cfg, x, y)
        if self.pico.glide(nx, ny, cfg["move_time_min"], cfg["move_time_max"]):
            time.sleep(random.uniform(*cfg["click_settle"]))   # only pause after actually moving
        else:
            # Already there: nudge 1-2 px and back so the game sees the mouse over the
            # button again (a perfectly still mouse after a popup can have its click ignored).
            d = random.choice((-1, 1)) * random.uniform(0.0006, 0.0012)
            self.pico.move(nx + d, ny + random.choice((-1, 1)) * random.uniform(0.0006, 0.0012))
            time.sleep(random.uniform(0.03, 0.06))
            self.pico.move(nx, ny)
            time.sleep(random.uniform(0.04, 0.08))
        self.pico.click()

    def stop(self, message, frame=None, det=None, positive=False):
        """The bot pauses itself (positive found, limit hit, problem): the next START
        begins a new run, so the run counters start from 0 again."""
        self.st.set(running=False, message=message, run_finished=True)
        if not positive and self.cfg.get("discord_notify_stops", True):
            self.notify(f"Paused: {message}", frame, det)

    def notify(self, text, frame=None, det=None, tall=False, full=False):
        """Discord message (if a webhook is set), with a picture of the reset window.
        tall=True: the result columns from the top of the screen down to the Reset
        buttons, so the new flame's stats above the numbers are in the picture."""
        cfg = self.cfg
        if not cfg.get("discord_webhook") or self.image:
            return
        with self.st.lock:
            n, spent, total = self.st.run_resets, self.st.spent_run, self.st.spent_total
        text = f"{text}\nResets this run: {n} | mesos this run: {spent:,} | total: {total:,}"
        png = None
        if frame is not None and full:           # the whole screen, as a JPEG to keep it small
            ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            import notify
            notify.send(cfg["discord_webhook"], text, enc.tobytes() if ok else None,
                        cfg.get("discord_user_id"), filename="screen.jpg")
            return
        if frame is not None:
            img = frame
            region = det.region(margin=40) if det is not None else None
            if region:
                x, y, w, h = region
                top = 0 if tall else max(0, y)
                img = frame[top:y + h, max(0, x):x + w]
            ok, enc = cv2.imencode(".png", img)
            png = enc.tobytes() if ok else None
        import notify
        notify.send(cfg["discord_webhook"], text, png, cfg.get("discord_user_id"))

    def reset_spot(self, which, rect):
        """Keep clicking the same spot on the same button. Every few resets (wiggle_every)
        drift to a new spot on the button; also pick a new one if the button changes/moves."""
        old = self.last_reset
        same = old and old[0] == which and abs(old[1][0] - rect[0]) <= 3 and abs(old[1][1] - rect[1]) <= 3
        if same:
            self.until_wiggle -= 1
            if self.until_wiggle > 0:
                return old[2]
            spot = button_point(rect)
            for _ in range(20):     # make it a real move: at least a quarter of the button
                if abs(spot[0] - old[2][0]) >= rect[2] * 0.25:
                    break
                spot = button_point(rect)
        else:
            spot = button_point(rect)
        self.until_wiggle = random.randint(*self.cfg["wiggle_every"])
        self.last_reset = (which, rect, spot)
        return spot

    def loop(self):
        cfg, st = self.cfg, self.st
        prev = None              # last reading (need 2 equal in a row)
        awaiting = None          # {"before": reading, "t": time} after a reset
        stuck = unreadable = 0
        was_running = False

        while not st.quit:
            with st.lock:
                new_src, st.new_source = st.new_source, None
            if new_src is not None:          # capture changed from the monitor's WINDOW button
                self.src = new_src
                self.det.hint = None
                self.last_reset = None
                self.det.prev = None
                prev, awaiting = None, None
            try:
                frame = self.src.grab()
            except Exception as e:
                st.set(status=f"Capture error: {e}")
                time.sleep(1)
                continue
            blank_exclusion(frame, self.src, st.exclude)
            using = getattr(self.src, "using", None)
            if using != st.capture_using:
                st.set(capture_using=using)

            det = self.det.find(frame)
            if det and self.det.last_full_search:
                cfg["last_found"] = dict(self.det.hint, source=source_key(cfg, self.image))
                save_config(cfg)
            results = read_boxes(frame, det, cfg) if det else []
            with st.lock:
                running, mode = st.running, st.mode
            nxt = pick_button(det, mode)[0] if det else None
            st.set(frame=frame, det=det, results=results, next_button=nxt)

            if running and not was_running and st.run_finished:   # START after a finished run
                st.new_run()
                st.set(run_finished=False)
                stuck, unreadable, awaiting, prev = 0, 0, None, None
            was_running = running

            if det is None:
                st.set(status="Looking for the Reset buttons... (open the reset window)")
                prev = None
                time.sleep(0.3)
                continue
            shown = "  ".join(fmt_result(r) for r in results)
            st.set(status=f"Found (size {det.scale:.2f}x)  {shown}")

            if not running or self.pico is None:
                prev = None
                time.sleep(0.1)
                continue

            cur = summary(results)
            if any(r["kind"] == "unknown" for r in results):
                unreadable += 1
                prev = None
                if unreadable >= cfg["max_unreadable"]:
                    save_debug(frame, det, "unreadable")
                    self.stop("Can't read the numbers - paused. Screenshot saved in debug/", frame, det)
                    unreadable = 0
                time.sleep(cfg["stable_gap"])
                continue
            unreadable = 0
            if all(r["kind"] == "empty" for r in results):
                prev = None
                time.sleep(cfg["stable_gap"])
                continue
            if cur != prev:                      # wait for two equal reads in a row
                prev = cur
                time.sleep(cfg["stable_gap"])
                continue

            if awaiting:
                if cur == awaiting["before"]:
                    if time.time() - awaiting["t"] < cfg["change_timeout"]:
                        time.sleep(cfg["stable_gap"])
                        continue
                    # The reset didn't go through: not counted, click again.
                    stuck += 1
                    save_debug(frame, det, "nochange")
                    if stuck > cfg["max_retries"]:
                        self.stop("Reset isn't working (out of mesos? popup?) - paused.", frame, det)
                        stuck = 0
                        awaiting = None
                        continue
                    st.set(message=f"Numbers didn't change, clicking Reset again ({stuck}/{cfg['max_retries']})")
                    self.until_wiggle = 1   # retry from a fresh spot on the button
                else:
                    # Numbers changed: the reset really happened, count it now.
                    st.add_reset(awaiting["which"], awaiting["cost"])
                    stuck = 0
                awaiting = None

            positives = [i for i, r in enumerate(results) if r["kind"] == "positive"]
            if positives:
                best = max(positives, key=lambda i: results[i]["value"])
                val = results[best]["value"]
                self.click(*box_point(det.boxes[best]))
                self.last_reset = None
                save_debug(frame, det, "positive")
                with st.lock:
                    n, spent = st.run_resets, st.spent_run
                msg = f"POSITIVE +{val:,} in box {best + 1} - clicked it after {n} resets ({spent:,} mesos)."
                print(msg)
                beep()
                if cfg.get("discord_webhook"):
                    # Let the game show the new flame, then send a fresh screenshot of it.
                    time.sleep(cfg["flame_screenshot_delay"])
                    try:
                        after = self.src.grab()
                        after_det = self.det.find(after) or det
                    except Exception:
                        after, after_det = frame, det
                    others = " | ".join(fmt_result(r) for i, r in enumerate(results) if i != best)
                    self.notify(f"**New flame! Combat Power +{val:,}** (result {best + 1} of {len(results)})\n"
                                f"Other results: {others}", after, after_det, full=True)
                if cfg["stop_after_positive"]:
                    self.stop(msg, positive=True)
                else:
                    st.set(message=msg)
                    sleep(cfg["delay_after_enters"])
                prev = None
                continue

            which, rect = pick_button(det, mode)
            if which is None:
                self.stop(f"{rect} - paused. Pick another reset mode.")
                continue
            with st.lock:
                done, limit, limit_on = st.run_resets, st.max_resets, st.limit_on
            if limit_on and done >= limit:
                self.stop(f"Reached max resets ({limit}) - paused. Raise it or press START again.", frame, det)
                continue

            j = cfg["delay_jitter"]
            sleep(cfg["delay_before_reset_click"], j)
            self.click(*self.reset_spot(which, rect))   # mouse stays on the button after this
            sleep(cfg["delay_after_reset_click"], j)
            for i in range(cfg["enters_after_reset"]):
                if i:
                    sleep(cfg["delay_between_enters"], j)
                self.pico.key("ENTER")
            with st.lock:
                n, spent = st.run_resets, st.spent_run
            st.set(message=f"Reset {which} pressed ({n} done this run, {spent:,} mesos)")
            cost = cfg["cost_x3"] if which == "x3" else cfg["cost_x1"]
            awaiting = {"before": cur, "t": time.time(), "which": which, "cost": cost}
            prev = None
            sleep(cfg["delay_after_enters"], j)


def beep():
    try:
        import winsound
        winsound.Beep(1200, 250)
    except Exception:
        print("\a", end="", flush=True)


# ---------------------------------------------------------------- commands
def ensure_region(cfg):
    """Make sure we know what to capture before starting."""
    if cfg["source"] == "window" and not cfg.get("window_title"):
        print("No window chosen yet - pick the window showing the game PC's screen.")
        cmd_pick_window(None, cfg)
        if not cfg.get("window_title"):
            sys.exit("No window chosen.")
    if cfg["source"] == "region" and not cfg.get("region"):
        print("No capture region yet - place the rectangle over the game screen picture, then ENTER.")
        cmd_set_region(None, cfg)
        if not cfg.get("region"):
            sys.exit("No region chosen.")


def cmd_pick_window(args, cfg):
    from windows import pick_window
    if sys.platform != "win32":
        sys.exit("Picking a window only works on Windows - use set-region instead.")
    title = pick_window(cfg.get("window_title"))
    if not title:
        print("Cancelled, capture not changed.")
        return
    cfg["window_title"] = title
    cfg["source"] = "window"
    cfg["last_found"] = None
    save_config(cfg)
    print(f"Capturing window: {title}")


def cmd_set_region(args, cfg):
    from region_picker import pick_region
    r = pick_region(cfg.get("region"))
    if r is None:
        print("Cancelled, region not changed.")
        return
    cfg["region"] = r
    cfg["source"] = "region"
    cfg["last_found"] = None
    save_config(cfg)
    print(f"Saved region {r['width']}x{r['height']} at ({r['left']}, {r['top']}).")


def capture_name(cfg, image=None):
    if image:
        return f"image {os.path.basename(image)}"
    src = cfg["source"]
    if src == "window":
        return f"window '{cfg.get('window_title')}'"
    if src == "region" and cfg.get("region"):
        r = cfg["region"]
        return f"region {r['width']}x{r['height']} at ({r['left']}, {r['top']})"
    if src == "obs":
        return f"OBS Virtual Camera {cfg.get('obs_camera_index', 0)}"
    return f"screen (monitor {cfg.get('monitor', 0)})"


def run_with_monitor(cfg, image=None, with_pico=True):
    if not image:
        ensure_region(cfg)
    fill_target_screen(cfg)
    source = make_source(cfg, image)
    detector = make_detector(cfg, image)
    pico = None
    if with_pico:
        from pico_link import Pico
        pico = Pico(cfg["pico_port"])
        print(f"Pico on {pico.port}")
    state = State(mode=cfg["mode"] if cfg["mode"] in MODES else "auto", max_resets=cfg["max_resets"],
                  limit_on=cfg["max_resets_on"])
    state.set(message="Press START (or F8) to begin" if pico else "View only - no inputs are sent")
    start_hotkeys(state)
    bot = Bot(cfg, state, source, detector, pico, image)
    t = threading.Thread(target=bot.loop, daemon=True)
    t.start()
    state.set(capture_name=capture_name(cfg, image))

    def pick_window_live():
        """WINDOW button: pause, show the window list, switch the capture."""
        if sys.platform != "win32":
            state.set(message="Picking a window only works on Windows")
            return
        from windows import pick_window
        state.set(running=False)
        title = pick_window(cfg.get("window_title"))
        if not title:
            state.set(message="Capture not changed")
            return
        try:
            new_cfg = dict(cfg, source="window", window_title=title)
            src = make_source(new_cfg)
        except Exception as e:
            state.set(message=f"Can't capture that window: {e}")
            return
        cfg.update(source="window", window_title=title, last_found=None)
        save_config(cfg)
        state.set(new_source=src, capture_name=capture_name(cfg),
                  message=f"Now capturing '{title}' - press START when ready")

    mon = Monitor(state, can_act=pico is not None, on_pick_window=None if image else pick_window_live)
    try:
        while mon.pump():
            pass
    except KeyboardInterrupt:
        state.set(quit=True)
    t.join(timeout=3)
    mon.close()
    cfg["mode"] = state.mode
    cfg["max_resets"] = state.max_resets
    cfg["max_resets_on"] = state.limit_on
    save_config(cfg)
    if state.resets:
        print(f"Total: {state.resets} resets ({state.n_x3} x3, {state.n_x1} x1), "
              f"{state.spent_total:,} mesos spent.")


def cmd_run(args, cfg):
    run_with_monitor(cfg, None, with_pico=True)


def cmd_monitor(args, cfg):
    run_with_monitor(cfg, args.image, with_pico=False)


def cmd_test_pico(args, cfg):
    from pico_link import Pico
    ensure_region(cfg)
    fill_target_screen(cfg)
    source = make_source(cfg)
    det = make_detector(cfg).find(source.grab())
    if det is None:
        sys.exit("Couldn't find the Reset buttons on screen. Open the reset window first.")
    pico = Pico(cfg["pico_port"])
    print(f"Pico on {pico.port}. Hovering each spot for 1.5s (no clicks)...")
    targets = [(f"number box {i + 1}", b) for i, b in enumerate(det.boxes)]
    targets += [(f"Reset {n}", r) for n, r in (("x1", det.x1), ("x3", det.x3)) if r]
    for name, b in targets:
        print(f"  {name}")
        pico.glide(*normalize(source, cfg, *box_point(b, jitter=False)), cfg["move_time_min"], cfg["move_time_max"])
        time.sleep(1.5)
    print("If the cursor landed on each spot you're good. If it's off, the capture region doesn't"
          " match the laptop's screen exactly - run set-region again (see README).")


def cmd_calibrate(args, cfg):
    """Teach it the buttons from your own screen (only needed if auto-detect fails)."""
    if args.image:
        frame = cv2.imread(args.image)
    else:
        ensure_region(cfg)
        source = make_source(cfg)
        print("Grabbing a frame in 3 seconds - show the reset window...")
        time.sleep(3)
        frame = source.grab()
    win = "Calibrate"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    def pick(msg):
        print(msg)
        r = cv2.selectROI(win, frame, showCrosshair=False)
        return list(map(int, r)) if r[2] > 0 and r[3] > 0 else None

    x1 = pick("\n1) Drag a box EXACTLY around the whole 'Reset x1' button, then ENTER.")
    if not x1:
        sys.exit("Nothing drawn, nothing saved.")
    x3 = pick("2) Drag a box around the whole 'Reset x3' button, then ENTER (ESC/C to skip).")
    print("3) Drag a box around EACH result number, ENTER after each; ESC when done."
          "\n   (Just press ESC to keep the default number positions.)")
    boxes = [list(map(int, b)) for b in cv2.selectROIs(win, frame, showCrosshair=False) if b[2] > 0]
    cv2.destroyAllWindows()

    dl = DEFAULT_LAYOUT
    k = x1[2] / dl["button_size"][0]      # user's pixels per default pixel
    tr = dl["template_rect"]

    def tmpl(r):
        x, y, w, h = r
        return frame[int(y + tr[1] * h):int(y + (tr[1] + tr[3]) * h), int(x + tr[0] * w):int(x + (tr[0] + tr[2]) * w)]

    lay = {"button_size": [x1[2], x1[3]], "font_scale": k}
    os.makedirs(USER_TEMPLATE_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(USER_TEMPLATE_DIR, "user_reset_x1.png"), tmpl(x1))
    if x3:
        cv2.imwrite(os.path.join(USER_TEMPLATE_DIR, "user_reset_x3.png"), tmpl(x3))
        lay["x3_offset"] = [x3[0] - x1[0], x3[1] - x1[1]]
    else:
        # No x3 on screen: make one from the x1 template so matching still works.
        cv2.imwrite(os.path.join(USER_TEMPLATE_DIR, "user_reset_x3.png"),
                    cv2.resize(cv2.imread(os.path.join(TEMPLATE_DIR, "reset_x3.png")), None, fx=k, fy=k))
        lay["x3_offset"] = [v * k for v in dl["x3_offset"]]
    if boxes:
        boxes.sort(key=lambda b: b[0])
        lay["box_centers"] = [[b[0] + b[2] / 2 - x1[0], b[1] + b[3] / 2 - x1[1]] for b in boxes]
        lay["box_size"] = [max(b[2] for b in boxes) + 20, max(b[3] for b in boxes) + 6]
    else:
        lay["box_centers"] = [[c[0] * k, c[1] * k] for c in dl["box_centers"]]
        lay["box_size"] = [v * k for v in dl["box_size"]]
    cfg["layout"] = lay
    cfg["last_found"] = None
    save_config(cfg)

    det = Detector(lay).find(frame)
    if det is None:
        print("Saved, but it still can't find the buttons in this frame - try again, drawing tighter boxes.")
        return
    res = read_boxes(frame, det, cfg)
    print("Saved. It now reads:", "  ".join(fmt_result(r) for r in res))


def cmd_reset_calibration(args, cfg):
    for n in ("user_reset_x1.png", "user_reset_x3.png"):
        p = os.path.join(USER_TEMPLATE_DIR, n)
        if os.path.exists(p):
            os.remove(p)
    cfg["layout"] = {}
    cfg["last_found"] = None
    save_config(cfg)
    print("Back to the built-in defaults.")


def cmd_discord(args, cfg):
    """Set up Discord notifications (webhook link + optional ping)."""
    import notify
    if notify.settings_dialog(cfg):
        save_config(cfg)
        print("Discord notifications " + ("on" if cfg.get("discord_webhook") else "off"))


def cmd_selftest(args, cfg):
    """Reads the bundled sample screenshot; checks the built-in files are all there."""
    path = os.path.join(RESOURCE_DIR, "samples", "one_positive.png")
    frame = cv2.imread(path)
    if frame is None:
        sys.exit(f"Sample missing: {path}")
    det = Detector().find(frame)
    if det is None:
        sys.exit("Selftest FAILED: Reset buttons not found in the sample.")
    res = read_boxes(frame, det, cfg)
    got = "  ".join(fmt_result(r) for r in res)
    ok = got == "0  +16,953  -718,815  -57,641"
    print(f"Selftest {'OK' if ok else 'FAILED'}: read {got}")
    if not ok:
        sys.exit(1)


COMMANDS = {"run": cmd_run, "monitor": cmd_monitor, "test-pico": cmd_test_pico, "set-region": cmd_set_region,
            "pick-window": cmd_pick_window, "discord": cmd_discord,
            "calibrate": cmd_calibrate, "reset-calibration": cmd_reset_calibration, "selftest": cmd_selftest}


def main():
    from region_picker import make_dpi_aware
    make_dpi_aware()
    if len(sys.argv) == 1:          # double-clicked: show the menu
        import launcher

        def menu_command(name):
            # Commands take argparse args; the menu has none of the optional flags.
            return lambda _args, cfg: COMMANDS[name](argparse.Namespace(image=None), cfg)

        launcher.main(load_config, {n: menu_command(n) for n in COMMANDS})
        return

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    s = sub.add_parser("monitor")
    s.add_argument("--image", help="use a screenshot instead of the live screen")
    sub.add_parser("test-pico")
    sub.add_parser("set-region")
    sub.add_parser("pick-window")
    sub.add_parser("discord")
    c = sub.add_parser("calibrate")
    c.add_argument("--image", help="calibrate on a screenshot")
    sub.add_parser("reset-calibration")
    sub.add_parser("selftest")
    args = p.parse_args()
    COMMANDS[args.cmd](args, load_config())


if __name__ == "__main__":
    main()
