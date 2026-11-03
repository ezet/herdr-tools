# open-pr

Opens the focused herdr pane's pull request in the browser.

The PR comes from the pane's `pr` metadata token when one is set: a full PR
URL, which an agent's status line can report so the key opens the PR the agent
itself shows. Without it, the plugin looks up the branch checked out in the
pane's directory on GitHub and opens its newest PR, open or merged. If there is
none, a herdr notification says so.

A Claude Code status line can report the token from the `.pr.url` field of its
input:

```sh
pr_url=$(jq -r '.pr.url // empty' <<<"$input")
if [ -n "$pr_url" ]; then
  herdr pane report-metadata "$HERDR_PANE_ID" --source claude-statusline --token "pr=$pr_url"
else
  herdr pane report-metadata "$HERDR_PANE_ID" --source claude-statusline --clear-token pr
fi
```

## Install

```sh
herdr plugin install ezet/herdr-tools/open-pr
```

Bind a key in `~/.config/herdr/config.toml` (a plugin cannot declare one):

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "open-pr.open"
description = "open the focused pane's PR in the browser"
```

Requires `jq`, `git`, and an authenticated `gh` for the branch lookup.
