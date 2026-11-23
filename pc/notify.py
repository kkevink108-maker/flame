"""Discord notifications through a webhook (Server Settings -> Integrations -> Webhooks).

Sends in the background so the bot never waits on the network.
"""
import json
import threading
import urllib.error
import urllib.request
import uuid

USER_AGENT = "FlameBot (webhook notifications, 1.0)"   # Discord rejects urllib's default


def _post(url, content, image_png=None, filename="results.png"):
    payload = {"content": content[:1900], "username": "Flame Bot",
               "allowed_mentions": {"parse": ["users"]}}
    if image_png is None:
        data = json.dumps(payload).encode()
        ctype = "application/json"
    else:
        boundary = uuid.uuid4().hex
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
            f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {'image/jpeg' if filename.endswith('.jpg') else 'image/png'}\r\n\r\n".encode()
            + image_png + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        data = b"".join(parts)
        ctype = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": ctype, "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def send(url, content, image_png=None, mention=None, wait=False, filename="results.png"):
    """Post a message (and optional PNG) to the webhook. Returns None, or with wait=True
    an error string / "" on success."""
    if not url:
        return "No webhook link set" if wait else None
    if mention:
        content = f"<@{str(mention).strip().lstrip('<@').rstrip('>')}> {content}"

    def run():
        try:
            _post(url, content, image_png, filename)
            return ""
        except urllib.error.HTTPError as e:
            msg = f"Discord said {e.code} ({e.reason})"
        except Exception as e:
            msg = f"Couldn't reach Discord: {e}"
        print(f"Discord notification failed: {msg}")
        return msg

    if wait:
        return run()
    threading.Thread(target=run, daemon=True).start()
    return None


def settings_dialog(cfg):
    """Small window to paste the webhook link and your Discord user ID. Returns True if saved."""
    import tkinter as tk
    from region_picker import make_dpi_aware
    make_dpi_aware()
    root = tk.Tk()
    root.title("Discord notifications")
    root.configure(bg="#1e1e1e", padx=14, pady=10)
    root.attributes("-topmost", True)
    fg, bg = "white", "#1e1e1e"

    def label(t, small=False):
        tk.Label(root, text=t, fg="#aaa" if small else fg, bg=bg, justify="left",
                 font=("Segoe UI", 9 if small else 10)).pack(anchor="w")

    label("Webhook link")
    label("Discord: channel settings (gear) -> Integrations -> Webhooks -> New Webhook -> Copy Webhook URL", True)
    url = tk.Entry(root, width=80, bg="#2b2b2b", fg=fg, insertbackground=fg)
    url.insert(0, cfg.get("discord_webhook") or "")
    url.pack(anchor="w", pady=(2, 8))
    label("Ping me - your Discord user ID (optional)")
    label("Discord: Settings -> Advanced -> Developer Mode on, then right-click your name -> Copy User ID", True)
    uid = tk.Entry(root, width=30, bg="#2b2b2b", fg=fg, insertbackground=fg)
    uid.insert(0, cfg.get("discord_user_id") or "")
    uid.pack(anchor="w", pady=(2, 8))
    stops = tk.BooleanVar(value=cfg.get("discord_notify_stops", True))
    tk.Checkbutton(root, text="Also notify when it stops for another reason (max resets, out of mesos, ...)",
                   variable=stops, fg=fg, bg=bg, selectcolor="#2b2b2b", activebackground=bg,
                   activeforeground=fg).pack(anchor="w")
    status = tk.Label(root, text="", fg="#9cdcfe", bg=bg, font=("Segoe UI", 9))
    status.pack(anchor="w", pady=(6, 0))
    saved = {"ok": False}

    def test():
        status.config(text="Sending...")
        root.update()
        err = send(url.get().strip(), "Test from Flame Bot - notifications work!",
                   mention=uid.get().strip() or None, wait=True)
        status.config(text=err or "Sent! Check your Discord channel.")

    def save():
        cfg["discord_webhook"] = url.get().strip() or None
        cfg["discord_user_id"] = uid.get().strip() or None
        cfg["discord_notify_stops"] = bool(stops.get())
        saved["ok"] = True
        root.destroy()

    row = tk.Frame(root, bg=bg)
    row.pack(anchor="w", pady=(8, 0))
    for text, cmd in (("Send test", test), ("Save", save), ("Cancel", root.destroy)):
        tk.Button(row, text=text, command=cmd, bg="#333", fg=fg, relief="flat", padx=10,
                  pady=3).pack(side="left", padx=(0, 6))
    root.mainloop()
    return saved["ok"]
