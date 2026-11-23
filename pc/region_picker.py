"""A see-through, draggable, resizable rectangle for choosing the capture region.

Put it exactly over the picture of the game computer's screen (OBS preview /
projector / capture window) on this PC. Drag inside to move, drag an edge or
corner to resize, arrow keys nudge by 1px (Shift = 10px). Enter saves, Esc cancels.

Returns {"left", "top", "width", "height"} in physical screen pixels, or None.
"""
EDGE = 10
MIN_SIZE = 60


def make_dpi_aware():
    """So tkinter and the screen capture agree on pixel coordinates on scaled displays."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def pick_region(initial=None):
    import tkinter as tk
    make_dpi_aware()
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.35)
    root.configure(bg="#00a0ff", highlightthickness=3, highlightbackground="#ffcc00")

    r = dict(initial or {"left": 200, "top": 150, "width": 960, "height": 540})
    result = {"region": None}

    def apply():
        root.geometry(f"{r['width']}x{r['height']}+{r['left']}+{r['top']}")
        info.config(text=f"{r['width']} x {r['height']}  at ({r['left']}, {r['top']})\n"
                         "Cover the game screen picture exactly.\n"
                         "Drag = move, edges/corners = resize, arrows = nudge\n"
                         "ENTER = save     ESC = cancel")

    info = tk.Label(root, bg="#003050", fg="white", font=("Segoe UI", 11, "bold"), justify="center")
    info.place(relx=0.5, rely=0.5, anchor="center")

    drag = {}

    def edges_at(x, y):
        w, h = r["width"], r["height"]
        return (x < EDGE, y < EDGE, x > w - EDGE, y > h - EDGE)

    def on_motion(e):
        l, t, rr, b = edges_at(e.x, e.y)
        cur = "fleur"
        if (l or rr) and (t or b):
            cur = "sizing"
        elif l or rr:
            cur = "sb_h_double_arrow"
        elif t or b:
            cur = "sb_v_double_arrow"
        try:
            root.config(cursor=cur)
        except tk.TclError:
            pass

    def on_press(e):
        root.focus_force()  # borderless windows don't always get keyboard focus by themselves
        drag.update(x=e.x_root, y=e.y_root, r=dict(r), edges=edges_at(e.x, e.y))

    def on_drag(e):
        dx, dy = e.x_root - drag["x"], e.y_root - drag["y"]
        o = drag["r"]
        l, t, rr, b = drag["edges"]
        if not any(drag["edges"]):
            r["left"], r["top"] = o["left"] + dx, o["top"] + dy
        else:
            if l:
                nw = max(MIN_SIZE, o["width"] - dx)
                r["left"], r["width"] = o["left"] + o["width"] - nw, nw
            if rr:
                r["width"] = max(MIN_SIZE, o["width"] + dx)
            if t:
                nh = max(MIN_SIZE, o["height"] - dy)
                r["top"], r["height"] = o["top"] + o["height"] - nh, nh
            if b:
                r["height"] = max(MIN_SIZE, o["height"] + dy)
        apply()

    def nudge(dx, dy, resize=False):
        def f(e):
            step = 10 if e.state & 0x1 else 1
            if resize:
                r["width"] = max(MIN_SIZE, r["width"] + dx * step)
                r["height"] = max(MIN_SIZE, r["height"] + dy * step)
            else:
                r["left"] += dx * step
                r["top"] += dy * step
            apply()
        return f

    def save(_=None):
        result["region"] = dict(r)
        root.destroy()

    for w in (root, info):
        w.bind("<Motion>", on_motion)
        w.bind("<ButtonPress-1>", on_press)
        w.bind("<B1-Motion>", on_drag)
    root.bind("<Left>", nudge(-1, 0))
    root.bind("<Right>", nudge(1, 0))
    root.bind("<Up>", nudge(0, -1))
    root.bind("<Down>", nudge(0, 1))
    root.bind("<Control-Left>", nudge(-1, 0, True))
    root.bind("<Control-Right>", nudge(1, 0, True))
    root.bind("<Control-Up>", nudge(0, -1, True))
    root.bind("<Control-Down>", nudge(0, 1, True))
    root.bind("<Return>", save)
    root.bind("<Escape>", lambda e: root.destroy())
    apply()
    root.focus_force()
    root.mainloop()
    return result["region"]


if __name__ == "__main__":
    print(pick_region())
