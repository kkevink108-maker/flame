"""Double-click menu for FlameBot (used when it's started without a command)."""
import tkinter as tk
import traceback
from tkinter import messagebox

from paths import DATA_DIR

ACTIONS = [
    ("pick-window", "1.  Capture a window (OBS projector)",
     "Pick the window showing the game PC's screen, e.g. OBS Fullscreen Projector."),
    ("set-region", "     ...or draw a capture region",
     "Place a rectangle over the game PC's screen picture instead."),
    ("monitor", "2.  Monitor (view only)",
     "See what the bot sees. Sends no inputs."),
    ("test-pico", "3.  Test Pico",
     "Hovers the laptop's mouse over each thing it found. No clicks."),
    ("run", "4.  RUN",
     "Live monitor + bot. Starts paused: press START or F8."),
    ("discord", "Discord notifications...", ""),
    ("calibrate", "Calibrate (only if it can't find the buttons)", ""),
    ("reset-calibration", "Undo calibration", ""),
]


def choose(cfg):
    """Show the menu; returns the chosen command or None when closed."""
    from region_picker import make_dpi_aware
    make_dpi_aware()
    root = tk.Tk()
    root.title("Flame Bot")
    root.configure(bg="#1e1e1e", padx=16, pady=12)
    root.resizable(False, False)
    choice = {"cmd": None}

    def pick(cmd):
        choice["cmd"] = cmd
        root.destroy()

    tk.Label(root, text="Flame Bot", font=("Segoe UI", 16, "bold"), fg="white", bg="#1e1e1e").pack(anchor="w")
    region = cfg.get("region")
    if cfg.get("source") == "window" and cfg.get("window_title"):
        info = f"Capturing window: {cfg['window_title']}"
    elif cfg.get("source") == "region" and region:
        info = f"Capturing region: {region['width']}x{region['height']} at ({region['left']}, {region['top']})"
    else:
        info = "Capture: not set yet - do step 1"
    info += "   |   Discord: " + ("on" if cfg.get("discord_webhook") else "off")
    if cfg.get("pico_port"):
        info += f"   |   Pico port: {cfg['pico_port']}"
    tk.Label(root, text=info, fg="#9cdcfe", bg="#1e1e1e", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 8))

    for cmd, label, desc in ACTIONS:
        main = cmd in ("pick-window", "set-region", "monitor", "test-pico", "run")
        b = tk.Button(root, text=label, anchor="w", width=44, command=lambda c=cmd: pick(c),
                      font=("Segoe UI", 11, "bold" if cmd == "run" else "normal"),
                      bg="#2e7d32" if cmd == "run" else ("#333" if main else "#262626"),
                      fg="white", activebackground="#444", activeforeground="white", relief="flat", pady=4)
        b.pack(anchor="w", pady=(2 if cmd == "set-region" else 6 if main else 2, 0))
        if desc:
            tk.Label(root, text=desc, fg="#aaa", bg="#1e1e1e", font=("Segoe UI", 9)).pack(anchor="w")

    tk.Label(root, text=f"Settings & screenshots: {DATA_DIR}", fg="#777", bg="#1e1e1e",
             font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 0))
    root.mainloop()
    return choice["cmd"]


def show_error(msg):
    r = tk.Tk()
    r.withdraw()
    messagebox.showerror("Flame Bot", msg)
    r.destroy()


def main(load_config, commands):
    """Menu -> run command -> back to the menu, until the menu is closed."""
    while True:
        cfg = load_config()
        cmd = choose(cfg)
        if cmd is None:
            return
        try:
            commands[cmd](None, cfg)
        except SystemExit as e:
            if e.code not in (None, 0):
                show_error(str(e.code))
        except Exception as e:
            traceback.print_exc()
            show_error(f"{e}\n\n(details in the console window)")
        finally:
            try:
                import cv2
                cv2.destroyAllWindows()
            except Exception:
                pass
