"""Finding and measuring windows (Windows only), plus the "pick a window" list."""
import sys


def list_windows():
    """Visible, non-minimized windows with a title -> [(title, hwnd)]."""
    if sys.platform != "win32":
        return []
    import pygetwindow
    out, seen = [], set()
    for w in pygetwindow.getAllWindows():
        t = (w.title or "").strip()
        if not t or t in seen or w.isMinimized or w.width < 200 or w.height < 150:
            continue
        seen.add(t)
        out.append((t, w._hWnd))
    # OBS projectors first, then alphabetical.
    out.sort(key=lambda x: ("projector" not in x[0].lower(), x[0].lower()))
    return out


def find_window(title):
    """hwnd of the window with exactly this title, else the first containing it."""
    wins = list_windows()
    for t, h in wins:
        if t == title:
            return h
    for t, h in wins:
        if title.lower() in t.lower():
            return h
    return None


def client_rect(hwnd):
    """Inside of a window (no title bar / borders) in screen pixels: (left, top, width, height)."""
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def print_window(hwnd, width, height):
    """The window's own picture, even when other windows cover it (asks Windows to
    render its client area, like OBS's Window Capture). Returns a BGR array, or None
    if it didn't work. Doesn't work for minimized windows."""
    import ctypes
    from ctypes import wintypes

    import numpy as np

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    # Proper 64-bit handle types (the defaults would truncate them).
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    PW_CLIENTONLY, PW_RENDERFULLCONTENT = 0x1, 0x2
    hdc = user32.GetDC(hwnd)
    if not hdc:
        return None
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    old = gdi32.SelectObject(mem, bmp)
    try:
        ok = user32.PrintWindow(hwnd, mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        gdi32.SelectObject(mem, old)   # the bitmap must be deselected before GetDIBits
        if not ok:
            return None
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width,
                               biHeight=-height, biPlanes=1, biBitCount=32, biCompression=0)
        buf = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(bmi), 0):
            return None
        return np.frombuffer(buf, np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def pick_window(current=None, windows=None):
    """Small list dialog. Returns the chosen window title or None."""
    import tkinter as tk
    from region_picker import make_dpi_aware
    make_dpi_aware()
    get = (lambda: windows) if windows is not None else list_windows

    root = tk.Tk()
    root.title("Pick the window to capture")
    root.configure(bg="#1e1e1e", padx=12, pady=10)
    root.attributes("-topmost", True)
    tk.Label(root, text="Pick the window that shows the game PC's screen\n"
                        "(e.g. OBS \"Fullscreen Projector\" / \"Windowed Projector\")",
             fg="white", bg="#1e1e1e", justify="left", font=("Segoe UI", 10)).pack(anchor="w")
    lb = tk.Listbox(root, width=70, height=14, bg="#2b2b2b", fg="white", selectbackground="#2e7d32",
                    font=("Segoe UI", 10), activestyle="none")
    lb.pack(pady=8, fill="both", expand=True)
    result = {"title": None}
    titles = []

    def refresh():
        lb.delete(0, "end")
        titles.clear()
        for t, _ in get():
            titles.append(t)
            lb.insert("end", t)
        if current in titles:
            lb.selection_set(titles.index(current))
            lb.see(titles.index(current))
        elif titles:
            lb.selection_set(0)

    def ok(_=None):
        sel = lb.curselection()
        if sel:
            result["title"] = titles[sel[0]]
            root.destroy()

    row = tk.Frame(root, bg="#1e1e1e")
    row.pack(fill="x")
    for text, cmd in (("Use this window", ok), ("Refresh", refresh), ("Cancel", root.destroy)):
        tk.Button(row, text=text, command=cmd, bg="#333", fg="white", relief="flat",
                  padx=10, pady=3).pack(side="left", padx=(0, 6))
    lb.bind("<Double-Button-1>", ok)
    root.bind("<Return>", ok)
    root.bind("<Escape>", lambda e: root.destroy())
    refresh()
    root.focus_force()
    lb.focus_set()
    root.mainloop()
    return result["title"]


if __name__ == "__main__":
    print(pick_window())
