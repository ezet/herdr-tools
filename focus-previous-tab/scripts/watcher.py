#!/usr/bin/env python3
"""When the focused herdr tab closes, focus the tab that was focused before it.

herdr hands focus to the closed tab's left neighbour. This keeps a
most-recently-focused list of tabs from `tab_focused` events and, when a focus
change turns out to be caused by the previous tab disappearing, moves focus to
the most recent surviving tab in the same workspace instead -- like a browser.

`tab_closed` and herdr's replacement `tab_focused` arrive in either order: a
plain shell tab closes at once, but an agent pane's `tab_closed` lags until its
processes are gone. So the trigger is the focus event, and "was it a close" is
answered by asking whether the previously focused tab still exists.

Started by herdr as the plugin's [[startup]] process.
"""

import json
import os
import socket
import sys
import time

SOCKET_PATH = os.environ.get(
    "HERDR_SOCKET_PATH", os.path.expanduser("~/.config/herdr/herdr.sock")
)
# The history, saved for the `last` action. Runtime dir: it is rebuilt from empty
# whenever the watcher starts, so nothing in it should outlive a reboot.
HISTORY_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "herdr-focus-previous-tab.json"
)
RECONNECT_SECONDS = 3.0
MAX_HISTORY = 200

SUBSCRIPTIONS = [{"type": "tab.focused"}, {"type": "tab.closed"}]


def log(message):
    print(f"focus-previous-tab: {message}", file=sys.stderr, flush=True)


def request(method, params=None):
    """One connection per request; the server closes it after replying."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect(SOCKET_PATH)
        stream = sock.makefile("rwb")
        payload = {"id": "focus-previous-tab", "method": method, "params": params or {}}
        stream.write((json.dumps(payload) + "\n").encode())
        stream.flush()
        line = stream.readline()
    finally:
        sock.close()
    if not line:
        raise ConnectionError(f"no response to {method}")
    message = json.loads(line)
    if "error" in message:
        raise RuntimeError(f"{method}: {message['error']}")
    return message["result"]


def live_tabs():
    """tab_id -> workspace_id for every tab that exists right now."""
    snapshot = request("session.snapshot")["snapshot"]
    return {t["tab_id"]: t["workspace_id"] for t in snapshot.get("tabs", [])}, snapshot


class History:
    def __init__(self):
        # Most recent first: [(tab_id, workspace_id), ...]
        self.mru = []
        self.current = None

    def prime(self):
        tabs, snapshot = live_tabs()
        self.mru = [(t, w) for t, w in self.mru if t in tabs]
        focused = snapshot.get("focused_tab_id")
        if focused in tabs:
            self.promote(focused, tabs[focused])
        self.current = focused

    def promote(self, tab_id, workspace_id):
        self.mru = [(tab_id, workspace_id)] + [e for e in self.mru if e[0] != tab_id]
        del self.mru[MAX_HISTORY:]
        self.save()

    def forget(self, tab_id):
        self.mru = [e for e in self.mru if e[0] != tab_id]
        self.save()

    def save(self):
        # Written whole and renamed into place, so the action never reads half.
        tmp = f"{HISTORY_PATH}.{os.getpid()}"
        try:
            with open(tmp, "w") as f:
                json.dump([t for t, _ in self.mru], f)
            os.replace(tmp, HISTORY_PATH)
        except OSError as exc:
            log(f"saving history failed: {exc}")

    def on_tab_closed(self, tab_id):
        # Only drop it from the history. If it was the focused tab, the focus
        # event that follows (or preceded it) does the redirect.
        if tab_id != self.current:
            self.forget(tab_id)

    def on_tab_focused(self, tab_id, workspace_id):
        tabs, snapshot = live_tabs()
        if snapshot.get("focused_tab_id") != tab_id:
            # Stale: the backlog herdr replays to a new subscriber, or focus has
            # already moved on. Acting on it would rewrite history wrongly.
            return
        previous = self.current
        self.current = tab_id
        if previous is None or previous == tab_id:
            self.promote(tab_id, workspace_id)
            return

        if previous in tabs:
            # An ordinary switch.
            self.promote(tab_id, workspace_id)
            return

        # The previous tab is gone, so herdr chose this one for us.
        closed_ws = next((w for t, w in self.mru if t == previous), None)
        self.forget(previous)
        target = next(
            (t for t, w in self.mru if w == closed_ws and tabs.get(t) == closed_ws),
            None,
        )
        if target is None or target == tab_id or tabs.get(tab_id) != closed_ws:
            # No history left in that workspace, herdr already picked the right
            # one, or focus left the workspace (the whole workspace closed).
            self.promote(tab_id, workspace_id)
            return

        # Leave herdr's pick where it was in the history: it was never chosen.
        # The focus event this triggers promotes the target.
        request("tab.focus", {"tab_id": target})
        log(f"{previous} closed: focused {target} instead of {tab_id}")


def subscribe():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCKET_PATH)
    stream = sock.makefile("rwb")
    payload = {
        "id": "focus-previous-tab-sub",
        "method": "events.subscribe",
        "params": {"subscriptions": SUBSCRIPTIONS},
    }
    stream.write((json.dumps(payload) + "\n").encode())
    stream.flush()
    return sock, stream


def run():
    history = History()
    while True:
        sock = None
        try:
            sock, stream = subscribe()
            # Prime after subscribing so nothing is missed in between.
            history.prime()
            for line in stream:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                data = message.get("data") or {}
                kind = data.get("type")
                try:
                    if kind == "tab_focused":
                        history.on_tab_focused(data["tab_id"], data["workspace_id"])
                    elif kind == "tab_closed":
                        history.on_tab_closed(data["tab_id"])
                except (OSError, RuntimeError, ConnectionError) as exc:
                    log(f"handling {kind} failed: {exc}")
        except Exception as exc:
            log(f"subscription ended: {exc}")
        finally:
            if sock is not None:
                sock.close()
        time.sleep(RECONNECT_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
