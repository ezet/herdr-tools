# tag-pane

Toggles a tag on the focused herdr pane: a small dot in the agent sidebar, for
marking the panes you mean to come back to.

The tag is a pane metadata token (`tag`) reported under the `tag-pane` source,
so it sits on herdr's own pane record and goes away when the pane closes. Set
`TAG_PANE_DOT` to use a glyph other than `●`.

## Install

```sh
herdr plugin install ezet/herdr-tools/tag-pane
```

Bind a key in `~/.config/herdr/config.toml` (a plugin cannot declare one):

```toml
[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "tag-pane.toggle"
description = "toggle a tag dot on the focused pane"
```

Then show the token in the sidebar rows, e.g. in `[ui.sidebar.agents]`:

```toml
{ token = "$tag", fg = "#ffffff", bold = true }
```

Requires `jq`.
