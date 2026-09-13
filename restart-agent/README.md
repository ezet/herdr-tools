# restart-agent

Restarts the Claude agent in the focused herdr pane, resuming the same session.

Sends Claude's double-tap `Ctrl+C` exit, waits for it to leave the foreground,
then relaunches it as `claude --resume <session id>`. The session id comes from
herdr's own pane record, because `claude -c` picks the most recently active
transcript in the cwd — the wrong session whenever several agents share a repo
directory.

A pane that is not running Claude is left alone rather than typed into.

## Install

```sh
herdr plugin install ezet/herdr-tools/restart-agent
```

Then bind a key in `~/.config/herdr/config.toml` (a plugin cannot declare one):

```toml
[[keys.command]]
key = "prefix+ctrl+r"
type = "plugin_action"
command = "restart-agent.restart"
description = "restart focused pane's agent, resuming its session"
```

Requires `jq` and `claude` on `PATH`.
