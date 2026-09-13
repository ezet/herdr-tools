# herdr-tools

Two [herdr](https://herdr.dev) plugins for working with Claude Code agents in panes.

| Plugin | What it does |
|--------|--------------|
| [`restart-agent`](restart-agent) | Restart the focused pane's Claude agent in place, resuming the same session |
| [`reopen-tab`](reopen-tab) | Reopen the last closed tab — panes, layout, cwds and Claude sessions |

Each is an independent plugin with its own manifest; install either on its own.

```sh
herdr plugin install ezet/herdr-tools/restart-agent
herdr plugin install ezet/herdr-tools/reopen-tab
```

A herdr plugin cannot declare its own keybinding, so after installing, add the
key to `~/.config/herdr/config.toml` yourself — see each plugin's README.

Requires herdr 0.7.0+, Linux or macOS, and `claude` on `PATH`.
`restart-agent` also needs `jq`; `reopen-tab` needs `python3`.
