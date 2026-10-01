# herdr-tools

Five [herdr](https://herdr.dev) plugins for working with coding agents in panes.

| Plugin | What it does |
|--------|--------------|
| [`restart-agent`](restart-agent) | Restart the focused pane's Claude agent in place, resuming the same session |
| [`reopen-tab`](reopen-tab) | Reopen the last closed tab — panes, layout, cwds and Claude sessions |
| [`focus-previous-tab`](focus-previous-tab) | Closing the focused tab returns to the tab you were on before it, not its left neighbour; a key jumps back to the last tab |
| [`codex-switch`](codex-switch) | Codex accounts, quota pools and spend-control status in a popup |
| [`tag-pane`](tag-pane) | Toggle a tag dot on the focused pane, shown in the agent sidebar |

Each is an independent plugin with its own manifest; install any of them on its own.

```sh
herdr plugin install ezet/herdr-tools/restart-agent
herdr plugin install ezet/herdr-tools/reopen-tab
herdr plugin install ezet/herdr-tools/focus-previous-tab
herdr plugin install ezet/herdr-tools/codex-switch
herdr plugin install ezet/herdr-tools/tag-pane
```

A herdr plugin cannot declare its own keybinding, so after installing, add the
key to `~/.config/herdr/config.toml` yourself — see each plugin's README.

Requires herdr 0.7.0+ (0.8.0+ for `codex-switch` and `tag-pane`) and Linux or macOS.
`restart-agent` and `reopen-tab` need `claude` on `PATH`, plus `jq` and
`python3` respectively; `focus-previous-tab` needs `python3` and `jq`;
`codex-switch` needs `codex-switch`; and `tag-pane` needs `jq`.
