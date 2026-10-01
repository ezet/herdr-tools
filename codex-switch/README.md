# codex-switch

Opens the [codex-switch](https://github.com/xjoker/codex-switch) dashboard in a
herdr popup: Codex accounts, their 5h/7d quota pools with pace, reset cards, and
whichever account `~/.codex/auth.json` currently holds.

Worth knowing what the dashboard answers and what it does not. Codex reads its
account at startup, so switching there decides what the *next* Codex process
uses; a Codex already running in a pane keeps the account it started with.

## Install

```sh
herdr plugin install ezet/herdr-tools/codex-switch
```

Then bind a key in `~/.config/herdr/config.toml` (a plugin cannot declare one):

```toml
[[keys.command]]
key = "prefix+ctrl+o"
type = "plugin_action"
command = "codex-switch.open"
description = "codex accounts"
```

Requires `codex-switch` on `PATH`.
