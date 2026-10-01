# focus-previous-tab

When you close the focused tab, go back to the tab you were on before it, the
way a browser does. By default herdr always focuses the closed tab's left
neighbour.

## How it works

The plugin's `[[startup]]` process subscribes to `tab.focused` and `tab.closed`
and keeps a list of tabs, most recently focused first. When focus moves because
the previously focused tab is gone, it focuses the most recent surviving tab in
that workspace instead of herdr's pick.

`tab_closed` and herdr's replacement `tab_focused` can arrive in either order:
an agent pane's `tab_closed` lags until its processes exit. So the focus event
is the trigger, and the snapshot answers whether the previous tab still exists.
Focus events that don't match the snapshot's focused tab are ignored. That
covers the backlog herdr replays to a new subscriber.

Closing a whole workspace, or a tab that wasn't focused, is left to herdr. So is
closing a tab when no earlier tab in its workspace is in the history.

## Install

```sh
herdr plugin install ezet/herdr-tools/focus-previous-tab
```

The watcher starts with herdr, so restart your herdr server once after
installing. The history starts empty after each restart and fills as you switch
tabs.

## Last tab

The same history drives a `last` action: focus the tab you were on before this
one, in any workspace, like tmux's `last-window`. Press it again to come back.
The watcher saves the history to `$XDG_RUNTIME_DIR/herdr-focus-previous-tab.json`
for it. Bind a key in `~/.config/herdr/config.toml` (a plugin cannot declare one):

```toml
[[keys.command]]
key = "prefix+l"
type = "plugin_action"
command = "focus-previous-tab.last"
description = "focus the tab you were on before this one"
```

Requires `jq`.
