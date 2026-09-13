#!/usr/bin/env python3
"""Reopen the most recently closed herdr tab, agent session and all.

Pops the newest entry recorded by the plugin's watcher, recreates the tab in its
original workspace (its panes, their cwds and their split geometry), and
relaunches every Claude pane into the session it was holding. Repeated runs walk
further back through the stack.

  reopen.py            reopen the newest entry
  reopen.py --list     show what is on the stack
  reopen.py --clear    drop the stack
"""

import fcntl
import json
import os
import subprocess
import sys
import time

HERDR_BIN = os.environ.get("HERDR_BIN_PATH", "herdr")
STATE_DIR = os.environ.get(
    "HERDR_PLUGIN_STATE_DIR",
    os.path.expanduser("~/.local/state/herdr/plugins/reopen-tab"),
)
STACK_PATH = os.path.join(STATE_DIR, "closed-tabs.json")
LOCK_PATH = os.path.join(STATE_DIR, "closed-tabs.lock")

SHELL_READY_TIMEOUT = 5.0


def herdr(*args, check=True):
    proc = subprocess.run(
        (HERDR_BIN,) + args, capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        if check:
            raise RuntimeError(f"herdr {' '.join(args)}: {proc.stderr.strip()}")
        return None
    if not proc.stdout.strip():  # `pane run` and friends answer with nothing
        return None
    return json.loads(proc.stdout)["result"]


def notify(title, body=None):
    """herdr's own toast, or the desktop's when ui.toast delivery is off."""
    args = ["notification", "show", title]
    if body:
        args += ["--body", body]
    result = herdr(*args, check=False)
    if result and result.get("shown"):
        return
    try:
        subprocess.run(
            ["notify-send", "-a", "herdr", title] + ([body] if body else []),
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def read_stack():
    try:
        with open(STACK_PATH) as fh:
            return json.load(fh).get("entries", [])
    except (OSError, ValueError):
        return []


def pop_entry():
    """Take the newest entry off the stack atomically."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOCK_PATH, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            entries = read_stack()
            if not entries:
                return None
            entry, rest = entries[0], entries[1:]
            tmp = STACK_PATH + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"entries": rest}, fh, indent=1)
            os.replace(tmp, STACK_PATH)
            return entry
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# --- layout reconstruction -------------------------------------------------
# The recorded rects are the tab's final geometry. herdr lays panes out as a
# BSP tree, so that geometry always has a guillotine cut: find it, and the tree
# of splits that produced it falls out. `--ratio` is the share the *anchor*
# pane keeps, which is exactly the cut position as a fraction of the box.


def _bounds(rects):
    x0 = min(r["rect"]["x"] for r in rects)
    y0 = min(r["rect"]["y"] for r in rects)
    x1 = max(r["rect"]["x"] + r["rect"]["width"] for r in rects)
    y1 = max(r["rect"]["y"] + r["rect"]["height"] for r in rects)
    return x0, y0, x1, y1


def build_tree(rects):
    """Return {"pane": id} or {"direction", "ratio", "first", "second"}."""
    if len(rects) == 1:
        return {"pane": rects[0]["pane_id"]}
    x0, y0, x1, y1 = _bounds(rects)

    for cut in sorted({r["rect"]["x"] for r in rects} - {x0}):
        first = [r for r in rects if r["rect"]["x"] + r["rect"]["width"] <= cut]
        second = [r for r in rects if r["rect"]["x"] >= cut]
        if first and second and len(first) + len(second) == len(rects):
            left, right = build_tree(first), build_tree(second)
            if left and right:
                return {
                    "direction": "right",
                    "ratio": (cut - x0) / (x1 - x0),
                    "first": left,
                    "second": right,
                }

    for cut in sorted({r["rect"]["y"] for r in rects} - {y0}):
        first = [r for r in rects if r["rect"]["y"] + r["rect"]["height"] <= cut]
        second = [r for r in rects if r["rect"]["y"] >= cut]
        if first and second and len(first) + len(second) == len(rects):
            top, bottom = build_tree(first), build_tree(second)
            if top and bottom:
                return {
                    "direction": "down",
                    "ratio": (cut - y0) / (y1 - y0),
                    "first": top,
                    "second": bottom,
                }
    return None


def apply_tree(node, pane_id, cwds, placed):
    if "pane" in node:
        placed[node["pane"]] = pane_id
        return
    cwd = cwds.get(_first_pane(node["second"]))
    args = ["pane", "split", pane_id, "--direction", node["direction"],
            "--ratio", f"{node['ratio']:.4f}", "--no-focus"]
    if cwd:
        args += ["--cwd", cwd]
    new_pane = herdr(*args)["pane"]["pane_id"]
    apply_tree(node["first"], pane_id, cwds, placed)
    apply_tree(node["second"], new_pane, cwds, placed)


def _first_pane(node):
    return node["pane"] if "pane" in node else _first_pane(node["first"])


# --- restore ---------------------------------------------------------------


def wait_for_shell(pane_id):
    """Don't type into a pane before its shell owns the foreground."""
    deadline = time.monotonic() + SHELL_READY_TIMEOUT
    while time.monotonic() < deadline:
        info = herdr("pane", "process-info", "--pane", pane_id, check=False)
        if info:
            info = info["process_info"]
            if info.get("foreground_process_group_id") == info.get("shell_pid"):
                return True
        time.sleep(0.15)
    return False


def launch_agent(pane_id, pane):
    """Put the pane's Claude session back. Other agents have no resume-by-id
    contract here, so they come back as a plain shell at the right cwd."""
    if pane.get("agent") != "claude" or not pane.get("session_id"):
        return False
    wait_for_shell(pane_id)
    herdr("pane", "run", pane_id, f"claude --resume {pane['session_id']}")
    return True


def resolve_workspace(entry):
    workspaces = herdr("workspace", "list")["workspaces"]
    ids = {w["workspace_id"] for w in workspaces}
    if entry["workspace_id"] in ids:
        return entry["workspace_id"]
    label = entry.get("workspace_label")
    for workspace in workspaces:
        if label and workspace.get("label") == label:
            return workspace["workspace_id"]
    return None


def restore_tab(record, workspace_id, tab_id=None, pane_id=None, focus=True):
    """Rebuild one tab. An existing empty tab can be passed in to be reused."""
    panes = record.get("panes") or []
    first_cwd = panes[0].get("cwd") if panes else None
    label = record.get("label") or ""
    # herdr labels unnamed tabs by their number; only a real name is worth restoring.
    named = label and not label.isdigit()

    if tab_id is None:
        args = ["tab", "create", "--workspace", workspace_id,
                "--focus" if focus else "--no-focus"]
        if first_cwd:
            args += ["--cwd", first_cwd]
        if named:
            args += ["--label", label]
        result = herdr(*args)
        tab_id = result["tab"]["tab_id"]
        pane_id = result["root_pane"]["pane_id"]
    elif named:
        herdr("tab", "rename", tab_id, label)

    by_id = {p["pane_id"]: p for p in panes}
    cwds = {p["pane_id"]: p.get("cwd") for p in panes if p.get("cwd")}
    rects = [r for r in record.get("rects") or [] if r["pane_id"] in by_id]

    placed = {}
    tree = build_tree(rects) if rects else None
    if tree:
        apply_tree(tree, pane_id, cwds, placed)
    else:
        # Non-guillotine or missing geometry: keep the panes, drop the shape.
        placed[panes[0]["pane_id"]] = pane_id
        anchor = pane_id
        for pane in panes[1:]:
            args = ["pane", "split", anchor, "--direction", "right", "--no-focus"]
            if pane.get("cwd"):
                args += ["--cwd", pane["cwd"]]
            anchor = herdr(*args)["pane"]["pane_id"]
            placed[pane["pane_id"]] = anchor

    resumed = 0
    for old_id, new_id in placed.items():
        if launch_agent(new_id, by_id[old_id]):
            resumed += 1
    return tab_id, resumed


def restore_entry(entry):
    tabs = entry.get("tabs") or []
    if not tabs:
        return "Nothing to reopen", None

    if entry.get("kind") == "workspace":
        args = ["workspace", "create", "--focus"]
        if entry.get("workspace_label"):
            args += ["--label", entry["workspace_label"]]
        if tabs[0].get("panes"):
            cwd = tabs[0]["panes"][0].get("cwd")
            if cwd:
                args += ["--cwd", cwd]
        created = herdr(*args)
        workspace_id = created["workspace"]["workspace_id"]
        resumed = 0
        # The new workspace comes with one tab; the first record reuses it.
        _, count = restore_tab(
            tabs[0], workspace_id,
            tab_id=created["tab"]["tab_id"],
            pane_id=created["root_pane"]["pane_id"],
        )
        resumed += count
        for record in tabs[1:]:
            _, count = restore_tab(record, workspace_id, focus=False)
            resumed += count
        label = entry.get("workspace_label") or workspace_id
        return (
            f"Reopened workspace {label}",
            f"{len(tabs)} tab(s), {resumed} agent session(s) resumed",
        )

    workspace_id = resolve_workspace(entry)
    fallback = ""
    if workspace_id is None:
        args = ["workspace", "create", "--focus"]
        if entry.get("workspace_label"):
            args += ["--label", entry["workspace_label"]]
        cwd = (tabs[0].get("panes") or [{}])[0].get("cwd")
        if cwd:
            args += ["--cwd", cwd]
        created = herdr(*args)
        workspace_id = created["workspace"]["workspace_id"]
        fallback = " (workspace recreated)"
        _, resumed = restore_tab(
            tabs[0], workspace_id,
            tab_id=created["tab"]["tab_id"],
            pane_id=created["root_pane"]["pane_id"],
        )
    else:
        _, resumed = restore_tab(tabs[0], workspace_id)

    record = tabs[0]
    name = record.get("label") or record["tab_id"]
    panes = record.get("panes") or []
    title = panes[0].get("title") if panes else None
    body = title or (panes[0].get("cwd") if panes else "")
    if resumed:
        body = f"{body} - {resumed} agent session(s) resumed".strip(" -")
    return f"Reopened tab {name}{fallback}", body


def main():
    args = sys.argv[1:]
    if args and args[0] == "--list":
        entries = read_stack()
        if not entries:
            print("no closed tabs recorded")
            return 0
        for i, entry in enumerate(entries):
            when = time.strftime("%H:%M:%S", time.localtime(entry.get("closed_at", 0)))
            tabs = entry.get("tabs") or []
            names = ", ".join(
                (t.get("panes") or [{}])[0].get("title") or t.get("label") or t["tab_id"]
                for t in tabs
            )
            print(f"{i}: {when} {entry.get('kind')} "
                  f"[{entry.get('workspace_label')}] {names}")
        return 0
    if args and args[0] == "--clear":
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOCK_PATH, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with open(STACK_PATH, "w") as fh:
                json.dump({"entries": []}, fh)
        return 0

    entry = pop_entry()
    if entry is None:
        notify("No closed tabs to reopen")
        return 1
    try:
        title, body = restore_entry(entry)
    except Exception as exc:
        notify("Reopen failed", str(exc))
        print(f"reopen-tab: {exc}", file=sys.stderr)
        return 1
    notify(title, body)
    print(title, body or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
