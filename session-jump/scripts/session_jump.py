#!/usr/bin/env python3
"""Search the Claude prompt history and jump to a prompt's session.

  session_jump.py pick              fzf over the history; jump to the pick
  session_jump.py preview N FILE    fzf's preview of row N (internal)

A pick whose session is open in a pane of this herdr session focuses that
pane. One open in another herdr session (the dispatcher's, say) is left alone
and named in a toast, since resuming it twice would fork the transcript.
Otherwise the session is resumed in a new tab at the prompt's directory, in the
workspace that already holds that repo's panes.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

HERDR_BIN = os.environ.get("HERDR_BIN_PATH", "herdr")
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
HISTORY_PATH = os.path.join(CLAUDE_DIR, "history.jsonl")
CONFIG_DIR = os.environ.get(
    "HERDR_PLUGIN_CONFIG_DIR",
    os.path.expanduser("~/.config/herdr/plugins/config/session-jump"),
)
DEFAULT_RESUME_COMMAND = "claude --resume"
SHELL_READY_TIMEOUT = 5.0
ROW_TEXT_LIMIT = 400

PASTE_RE = re.compile(r"\[Pasted text #(\d+)(?: \+\d+ lines)?\]")
OPEN_HERE, OPEN_ELSEWHERE, CLOSED = "here", "elsewhere", "closed"
MARKERS = {
    OPEN_HERE: "\033[32m●\033[0m",
    OPEN_ELSEWHERE: "\033[33m◇\033[0m",
    CLOSED: " ",
}


# --- herdr -----------------------------------------------------------------


def run_herdr(args, socket=None, check=True):
    env = dict(os.environ)
    if socket:
        env["HERDR_SOCKET_PATH"] = socket
    proc = subprocess.run(
        [HERDR_BIN] + list(args), capture_output=True, text=True, timeout=30, env=env
    )
    if proc.returncode != 0:
        if check:
            raise RuntimeError(f"herdr {' '.join(args)}: {proc.stderr.strip()}")
        return None
    if not proc.stdout.strip():
        return None
    data = json.loads(proc.stdout)
    return data.get("result", data)


def notify(title, body=None):
    """herdr's own toast, or the desktop's when ui.toast delivery is off."""
    args = ["notification", "show", title]
    if body:
        args += ["--body", body]
    result = run_herdr(args, check=False)
    if result and result.get("shown"):
        return
    try:
        subprocess.run(
            ["notify-send", "-a", "herdr", title] + ([body] if body else []),
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def live_sessions():
    """Claude session id -> (herdr session name, pane, is_own) across every
    running herdr session, plus this session's own pane list."""
    own_socket = os.environ.get("HERDR_SOCKET_PATH")
    listing = run_herdr(["session", "list", "--json"], check=False) or {}
    sessions = [s for s in listing.get("sessions", []) if s.get("running")]
    if not own_socket:
        own_socket = next(
            (s["socket_path"] for s in sessions if s.get("default")), None
        )

    live, own_panes = {}, []
    for session in sessions:
        is_own = session["socket_path"] == own_socket
        result = run_herdr(["pane", "list"], socket=session["socket_path"], check=False)
        panes = (result or {}).get("panes", [])
        if is_own:
            own_panes = panes
        for pane in panes:
            agent_session = pane.get("agent_session") or {}
            if agent_session.get("kind") != "id" or not agent_session.get("value"):
                continue
            sid = agent_session["value"]
            # A pane in this session wins over one elsewhere holding the same id.
            if sid not in live or is_own:
                live[sid] = (session["name"], pane, is_own)
    return live, own_panes


def wait_for_shell(pane_id):
    """Don't type into a pane before its shell owns the foreground."""
    deadline = time.monotonic() + SHELL_READY_TIMEOUT
    while time.monotonic() < deadline:
        info = run_herdr(["pane", "process-info", "--pane", pane_id], check=False)
        if info:
            info = info["process_info"]
            if info.get("foreground_process_group_id") == info.get("shell_pid"):
                return True
        time.sleep(0.15)
    return False


# --- history ---------------------------------------------------------------


def expand_pastes(entry):
    """Put pasted text back where its placeholder sits, so it is searchable."""
    pasted = entry.get("pastedContents") or {}

    def sub(match):
        paste = pasted.get(match.group(1)) or {}
        if paste.get("type") == "text" and paste.get("content"):
            return paste["content"]
        return match.group(0)

    return PASTE_RE.sub(sub, entry.get("display") or "")


def load_history():
    """Newest first, one item per distinct prompt in a session."""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    items, seen = [], set()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        sid, project = entry.get("sessionId"), entry.get("project")
        text = expand_pastes(entry).strip()
        if not sid or not project or not text:
            continue
        key = (sid, text)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "sid": sid,
            "project": project,
            "ts": (entry.get("timestamp") or 0) / 1000,
            "text": text,
        })
    return items


def short_project(path):
    """`api`, or `api:<worktree>` for a worktree inside a repo."""
    parts = path.rstrip("/").split("/")
    for marker in (".worktrees", "worktrees"):
        if marker in parts[1:-1]:
            i = parts.index(marker)
            repo = parts[i - 1]
            if repo == ".claude" and i >= 2:
                repo = parts[i - 2]
            return f"{repo}:{parts[i + 1]}"
    return parts[-1] or path


def age(ts):
    seconds = max(time.time() - ts, 0)
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return "now"


# --- picking ---------------------------------------------------------------


def pick():
    if not shutil.which("fzf"):
        notify("session-jump needs fzf on PATH")
        return 1
    items = load_history()
    if not items:
        notify("No Claude prompt history", HISTORY_PATH)
        return 1
    live, own_panes = live_sessions()
    for item in items:
        hit = live.get(item["sid"])
        item["state"] = CLOSED if hit is None else (OPEN_HERE if hit[2] else OPEN_ELSEWHERE)
        item["where"] = hit[0] if hit else None

    with tempfile.NamedTemporaryFile(
        "w", prefix="session-jump-", suffix=".json", delete=False
    ) as cache:
        json.dump(items, cache)
    try:
        rows = []
        for i, item in enumerate(items):
            text = " ".join(item["text"].split())[:ROW_TEXT_LIMIT]
            rows.append(
                f"{i}\t{MARKERS[item['state']]} {age(item['ts']):>4}  "
                f"\033[34m{short_project(item['project'])[:22]:<22}\033[0m  {text}"
            )
        preview = (
            f"{shlex.quote(sys.executable)} {shlex.quote(os.path.abspath(__file__))} "
            f"preview {{1}} {shlex.quote(cache.name)}"
        )
        proc = subprocess.run(
            [
                "fzf", "--ansi", "--scheme=history", "--layout=reverse",
                "--delimiter=\t", "--with-nth=2..", "--prompt=session> ",
                "--header=enter: jump · ● open here · ◇ open in another herdr session",
                f"--preview={preview}", "--preview-window=down,40%,wrap",
            ],
            input="\n".join(rows), stdout=subprocess.PIPE, text=True,
        )
    finally:
        os.unlink(cache.name)

    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    item = items[int(proc.stdout.split("\t", 1)[0])]
    try:
        jump(item, live, own_panes)
    except Exception as exc:
        notify("Jump failed", str(exc))
        print(f"session-jump: {exc}", file=sys.stderr)
        return 1
    return 0


def preview(index, cache_path):
    with open(cache_path, encoding="utf-8") as fh:
        item = json.load(fh)[int(index)]
    state = {
        OPEN_HERE: "\033[32mopen in a pane here\033[0m",
        OPEN_ELSEWHERE: f"\033[33mopen in herdr session '{item['where']}'\033[0m",
        CLOSED: "not open (enter resumes it in a new tab)",
    }[item["state"]]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item["ts"]))
    print(f"{state}\n\033[2m{when}  {item['project']}\n{item['sid']}\033[0m\n")
    print(item["text"])
    return 0


# --- jumping ---------------------------------------------------------------


def find_transcript(sid):
    projects = os.path.join(CLAUDE_DIR, "projects")
    try:
        for slug in os.listdir(projects):
            path = os.path.join(projects, slug, f"{sid}.jsonl")
            if os.path.exists(path):
                return path
    except OSError:
        pass
    return None


def running_outside_herdr(sid):
    """A `claude --resume <sid>` herdr cannot see, in some other terminal."""
    try:
        out = subprocess.run(
            ["ps", "-ax", "-o", "args="], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(sid in line and "claude" in line for line in out.splitlines())


def repo_root(path):
    """The main checkout of the repo holding `path`, worktrees included."""
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common = out.stdout.strip()
    if out.returncode != 0 or not common:
        return None
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


def pick_workspace(cwd, panes):
    """The workspace with the most panes in this repo, if any has one."""
    root = repo_root(cwd) or cwd
    counts = {}
    for pane in panes:
        pane_cwd = pane.get("foreground_cwd") or pane.get("cwd") or ""
        if pane_cwd == root or pane_cwd.startswith(root.rstrip("/") + "/"):
            counts[pane["workspace_id"]] = counts.get(pane["workspace_id"], 0) + 1
    return max(counts, key=counts.get) if counts else None


def resume_command():
    try:
        with open(os.path.join(CONFIG_DIR, "config.toml"), "rb") as fh:
            command = tomllib.load(fh).get("resume_command")
    except (OSError, tomllib.TOMLDecodeError):
        command = None
    return command or DEFAULT_RESUME_COMMAND


def jump(item, live, own_panes):
    sid = item["sid"]
    hit = live.get(sid)
    if hit:
        session, pane, is_own = hit
        if is_own:
            run_herdr(["agent", "focus", pane["pane_id"]])
            return
        notify(
            f"That session is open in herdr session '{session}'",
            f"pane {pane['pane_id']} - herdr session attach {session}",
        )
        return

    if not find_transcript(sid):
        notify("No transcript left for that session", sid)
        return
    cwd = item["project"]
    if not os.path.isdir(cwd):
        notify("The session's directory is gone", cwd)
        return
    if running_outside_herdr(sid):
        notify("That session is running outside herdr", sid)
        return

    args = ["tab", "create", "--cwd", cwd, "--focus"]
    workspace = pick_workspace(cwd, own_panes)
    if workspace:
        args += ["--workspace", workspace]
    pane_id = run_herdr(args)["root_pane"]["pane_id"]
    wait_for_shell(pane_id)
    run_herdr(["pane", "run", pane_id, f"{resume_command()} {shlex.quote(sid)}"])


def main():
    args = sys.argv[1:]
    if args[:1] == ["preview"] and len(args) == 3:
        return preview(args[1], args[2])
    if args[:1] == ["pick"]:
        return pick()
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
