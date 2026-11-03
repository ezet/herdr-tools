#!/usr/bin/env python3
"""Record closed herdr tabs so they can be reopened with their agent sessions.

herdr has no undo-close, and its `tab_closed` event carries only ids -- by the
time it fires, the tab's panes, cwds and Claude session ids are already gone
from the session snapshot. So this keeps a live cache of every tab, subscribes
to the close events, and pushes the last-known record onto a stack that
`reopen.py` pops.

Talks to the herdr socket directly rather than shelling out to the CLI: one
`session.snapshot` every REFRESH_SECONDS is cheap over a socket and expensive
as a process spawn.

Started by herdr as the plugin's [[startup]] process.
"""

import fcntl
import json
import os
import socket
import sys
import threading
import time

SOCKET_PATH = os.environ.get(
    "HERDR_SOCKET_PATH", os.path.expanduser("~/.config/herdr/herdr.sock")
)
STATE_DIR = os.environ.get(
    "HERDR_PLUGIN_STATE_DIR",
    os.path.expanduser("~/.local/state/herdr/plugins/reopen-tab"),
)
STACK_PATH = os.path.join(STATE_DIR, "closed-tabs.json")
LOCK_PATH = os.path.join(STATE_DIR, "closed-tabs.lock")

MAX_ENTRIES = 20
REFRESH_SECONDS = 1.5
# A tab closed as part of a workspace close is held this long before it is
# pushed on its own, so a workspace_closed arriving either side of its
# tab_closed events still collects them into one grouped entry.
GROUPING_SECONDS = 0.75
RECONNECT_SECONDS = 3.0
# A tab leaves the session snapshot as soon as it is closed, but `tab_closed`
# only fires once its processes are gone -- for an agent pane that lags by a
# second or more. Vanished tabs are held this long so the event still finds
# them. Nothing is recorded without the event, so a server restart (every tab
# vanishing at once, no events) still records nothing.
GRACE_SECONDS = 60.0

# A pane that closes or exits sends `pane_closed` or `pane_exited` -- and when
# it was a tab's last pane, nothing else: the tab gets no `tab_closed`. So a pane
# event is resolved against the snapshot: the tab vanished with it (a tab
# close), or the tab is still open without it (a pane close).
CLOSE_SUBSCRIPTIONS = [
    {"type": "tab.closed"},
    {"type": "workspace.closed"},
    {"type": "pane.closed"},
    {"type": "pane.exited"},
]


def log(message):
    print(f"reopen-tab watcher: {message}", file=sys.stderr, flush=True)


class HerdrSocket:
    """One connection per request; the server closes it after replying."""

    @staticmethod
    def request(method, params=None):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            sock.connect(SOCKET_PATH)
            stream = sock.makefile("rwb")
            payload = {"id": "reopen-tab", "method": method, "params": params or {}}
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

    @staticmethod
    def subscribe(subscriptions):
        """Return an open stream that yields event dicts."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCKET_PATH)
        stream = sock.makefile("rwb")
        payload = {
            "id": "reopen-tab-sub",
            "method": "events.subscribe",
            "params": {"subscriptions": subscriptions},
        }
        stream.write((json.dumps(payload) + "\n").encode())
        stream.flush()
        return sock, stream


def tab_records(snapshot):
    """Index the snapshot as tab_id -> a record that can rebuild the tab."""
    workspace_labels = {
        w["workspace_id"]: w.get("label", "") for w in snapshot.get("workspaces", [])
    }
    layouts = {l["tab_id"]: l for l in snapshot.get("layouts", [])}

    panes_by_tab = {}
    for pane in snapshot.get("panes", []):
        session = pane.get("agent_session") or {}
        panes_by_tab.setdefault(pane["tab_id"], []).append(
            {
                "pane_id": pane["pane_id"],
                "cwd": pane.get("foreground_cwd") or pane.get("cwd"),
                "agent": pane.get("agent"),
                "session_id": session.get("value") if session.get("kind") == "id" else None,
                "session_kind": session.get("kind"),
                "title": pane.get("terminal_title_stripped"),
            }
        )

    records = {}
    for tab in snapshot.get("tabs", []):
        tab_id = tab["tab_id"]
        layout = layouts.get(tab_id, {})
        records[tab_id] = {
            "tab_id": tab_id,
            "workspace_id": tab["workspace_id"],
            "workspace_label": workspace_labels.get(tab["workspace_id"], ""),
            "label": tab.get("label", ""),
            "number": tab.get("number"),
            "panes": panes_by_tab.get(tab_id, []),
            "rects": [
                {"pane_id": p["pane_id"], "rect": p["rect"]}
                for p in layout.get("panes", [])
            ],
        }
    return records


def push_entries(entries):
    """Prepend entries (newest first) to the on-disk stack, under the lock."""
    if not entries:
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOCK_PATH, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            stack = []
            try:
                with open(STACK_PATH) as fh:
                    stack = json.load(fh).get("entries", [])
            except (OSError, ValueError):
                stack = []
            stack = entries + stack
            tmp = STACK_PATH + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"entries": stack[:MAX_ENTRIES]}, fh, indent=1)
            os.replace(tmp, STACK_PATH)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class History:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        # tab_id -> (record, expiry) for tabs that have left the snapshot but
        # whose tab_closed event may still be in flight.
        self.recent = {}
        # tab_id -> (record, deadline); held back in case a workspace close
        # arrives and wants to absorb them.
        self.pending = {}
        # pane_id -> (record of its tab as last seen with it, expiry) for panes
        # that have left the snapshot.
        self.recent_panes = {}
        # pane_id -> expiry for panes whose close event came while the snapshot
        # still showed them.
        self.suspects = {}

    def refresh(self):
        snapshot = HerdrSocket.request("session.snapshot")["snapshot"]
        records = tab_records(snapshot)
        live_panes = {p["pane_id"] for r in records.values() for p in r["panes"]}
        now = time.monotonic()
        with self.lock:
            for tab_id, record in self.cache.items():
                if tab_id not in records:
                    self.recent[tab_id] = (record, now + GRACE_SECONDS)
                for pane in record["panes"]:
                    if pane["pane_id"] not in live_panes:
                        self.recent_panes[pane["pane_id"]] = (record, now + GRACE_SECONDS)
            self.recent = {
                t: v for t, v in self.recent.items()
                if v[1] > now and t not in records
            }
            self.recent_panes = {
                p: v for p, v in self.recent_panes.items()
                if v[1] > now and p not in live_panes
            }
            self.cache = records
            outcomes = [
                self._resolve_pane(p) for p in list(self.suspects)
                if p in self.recent_panes
            ]
            self.suspects = {p: v for p, v in self.suspects.items() if v > now}
        for outcome in outcomes:
            self._apply(outcome)

    def _take(self, tab_id):
        record = self.cache.pop(tab_id, None)
        if record is None:
            entry = self.recent.pop(tab_id, None)
            record = entry[0] if entry else None
        return record

    def on_tab_closed(self, tab_id):
        with self.lock:
            record = self._take(tab_id)
            if record is None:
                # Unknown tab: an event replayed from the server's backlog, or
                # a tab that never lived long enough to be cached.
                return
            self.pending[tab_id] = (record, time.monotonic() + GROUPING_SECONDS)

    def on_pane_gone(self, pane_id):
        with self.lock:
            if pane_id in self.recent_panes:
                outcome = self._resolve_pane(pane_id)
            else:
                if any(
                    p["pane_id"] == pane_id
                    for r in self.cache.values() for p in r["panes"]
                ):
                    self.suspects[pane_id] = time.monotonic() + GRACE_SECONDS
                return
        self._apply(outcome)

    def _resolve_pane(self, pane_id):
        """Under the lock: a gone pane either took its tab with it, or left a
        tab that is still open. A tab already recorded some other way wins."""
        self.suspects.pop(pane_id, None)
        record, _ = self.recent_panes.pop(pane_id)
        tab_id = record["tab_id"]
        if tab_id in self.recent:
            return ("tab", tab_id)
        if tab_id not in self.cache:
            return None
        pane = next(p for p in record["panes"] if p["pane_id"] == pane_id)
        rect = next(
            (r["rect"] for r in record["rects"] if r["pane_id"] == pane_id), None
        )
        return ("pane", {
            "kind": "pane",
            "closed_at": time.time(),
            "workspace_id": record["workspace_id"],
            "workspace_label": record.get("workspace_label", ""),
            "tab_id": tab_id,
            "tab_label": record.get("label", ""),
            "pane": pane,
            "rect": rect,
        })

    def _apply(self, outcome):
        if outcome is None:
            return
        kind, value = outcome
        if kind == "tab":
            self.on_tab_closed(value)
        else:
            push_entries([value])
            log(f"recorded closed pane {value['pane']['pane_id']} of {value['tab_id']}")

    def on_workspace_closed(self, workspace_id, workspace):
        now = time.time()
        with self.lock:
            records = [
                r for r in list(self.cache.values()) + [v[0] for v in self.recent.values()]
                if r["workspace_id"] == workspace_id
            ]
            for record in records:
                self._take(record["tab_id"])
            for tab_id, (record, _) in list(self.pending.items()):
                if record["workspace_id"] == workspace_id:
                    records.append(record)
                    del self.pending[tab_id]
        if not records:
            return
        records.sort(key=lambda r: r.get("number") or 0)
        label = (workspace or {}).get("label") or records[0].get("workspace_label", "")
        push_entries(
            [
                {
                    "kind": "workspace",
                    "closed_at": now,
                    "workspace_id": workspace_id,
                    "workspace_label": label,
                    "tabs": records,
                }
            ]
        )
        log(f"recorded closed workspace {workspace_id} ({label}) with {len(records)} tab(s)")

    def flush_pending(self):
        now = time.monotonic()
        ready = []
        with self.lock:
            for tab_id, (record, deadline) in list(self.pending.items()):
                if deadline <= now:
                    ready.append(record)
                    del self.pending[tab_id]
        ready.sort(key=lambda r: r.get("number") or 0)
        entries = [
            {
                "kind": "tab",
                "closed_at": time.time(),
                "workspace_id": record["workspace_id"],
                "workspace_label": record.get("workspace_label", ""),
                "tabs": [record],
            }
            for record in reversed(ready)
        ]
        push_entries(entries)
        for record in ready:
            log(f"recorded closed tab {record['tab_id']} ({record.get('label')})")


def refresher(history, stop):
    while not stop.is_set():
        try:
            history.refresh()
        except Exception as exc:  # server restarting, socket gone, ...
            log(f"snapshot failed: {exc}")
        history.flush_pending()
        stop.wait(REFRESH_SECONDS)


def run():
    history = History()
    stop = threading.Event()
    thread = threading.Thread(target=refresher, args=(history, stop), daemon=True)
    thread.start()

    while True:
        sock = None
        try:
            sock, stream = HerdrSocket.subscribe(CLOSE_SUBSCRIPTIONS)
            # Prime the cache only after subscribing, so nothing closed between
            # the two is missed. Events for tabs the cache never saw -- the
            # backlog herdr replays to a new subscriber -- are ignored.
            history.refresh()
            for line in stream:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                data = message.get("data") or {}
                kind = data.get("type")
                if kind == "tab_closed":
                    history.on_tab_closed(data["tab_id"])
                elif kind in ("pane_closed", "pane_exited"):
                    history.on_pane_gone(data["pane_id"])
                elif kind == "workspace_closed":
                    history.on_workspace_closed(
                        data["workspace_id"], data.get("workspace")
                    )
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
