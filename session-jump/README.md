# session-jump

Search your Claude prompt history in an overlay, the way Claude's own `ctrl+r` does, and jump
to the session the chosen prompt belongs to rather than pasting it.

- **Open in a pane of this herdr session** (`●`): that pane is focused.
- **Open in another herdr session** (`◇`, the dispatcher's `dispatch` session, say): a toast
  names the session and the pane. It is not resumed a second time, which would fork the
  transcript.
- **Not open**: a new tab opens at the prompt's directory and resumes the session there. The
  tab goes in the workspace that already holds panes in that repo, otherwise the focused
  one.

The preview shows the whole prompt, pasted text included, plus its directory, time and
session id.

## Install

```sh
herdr plugin install ezet/herdr-tools/session-jump
```

Then bind the action in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+/"
type = "plugin_action"
command = "session-jump.open"
description = "search prompt history and jump to its session"
```

## Configure

By default the new tab runs `claude --resume <id>`. To use another launcher, put it in
`config.toml` in the plugin's config dir (`herdr plugin config-dir session-jump`):

```toml
resume_command = "cx --resume"
```

The command is typed into the tab's interactive shell, so shell aliases work.

Requires herdr 0.9.0+, `python3` 3.11+, `fzf` 0.36+ and `git`. Reads `~/.claude/history.jsonl`,
or the file under `$CLAUDE_CONFIG_DIR` when that is set.
