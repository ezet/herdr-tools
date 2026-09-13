# reopen-tab

Undo-close for herdr tabs, like a browser's `Ctrl+Shift+T`. Brings back the
tab's panes, their split geometry and cwds, and resumes every Claude session
those panes were holding. Repeated presses walk back through the stack; a closed
workspace comes back in one press, all its tabs at once.

## How it works

herdr's `tab_closed` event carries only ids, and by the time it fires the tab's
panes, cwds and session ids are already gone from the session snapshot. So an
event hook alone cannot record enough to rebuild the tab.

Instead the plugin's `[[startup]]` process keeps a live cache of every tab,
refreshed over herdr's socket, and subscribes to `tab.closed` /
`workspace.closed`. On a close it pushes the last-known record onto a stack in
the plugin's state directory, which the `reopen` action pops.

Layout is rebuilt from the recorded pane rectangles: herdr lays panes out as a
BSP tree, so the geometry always has a guillotine cut, and the tree of splits
that produced it falls out of finding those cuts. Geometry that is not
reconstructible keeps the panes and drops the shape.

Only Claude panes are resumed by session id — other agents have no
resume-by-id contract here, so they come back as a plain shell at the right cwd.

## Install

```sh
herdr plugin install ezet/herdr-tools/reopen-tab
```

The watcher starts with herdr, so restart your herdr server once after
installing for it to begin recording.

Then bind a key in `~/.config/herdr/config.toml` (a plugin cannot declare one):

```toml
[[keys.command]]
key = "prefix+shift+t"
type = "plugin_action"
command = "reopen-tab.reopen"
description = "reopen last closed tab, resuming its agent session"
```

## Inspecting the stack

```sh
root=$(herdr plugin list --plugin reopen-tab --json | jq -r '.result.plugins[0].plugin_root')
python3 "$root/scripts/reopen.py" --list    # what is on the stack
python3 "$root/scripts/reopen.py" --clear   # drop it
```

Requires `python3` and `claude` on `PATH`.
