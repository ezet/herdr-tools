#!/usr/bin/env bash
# Focus the tab focused before this one, in any workspace -- tmux's last-window.
# The watcher keeps the history; a second press comes back, because the focus
# event it triggers puts this tab first again.
set -euo pipefail

herdr=${HERDR_BIN_PATH:-herdr}
history="${XDG_RUNTIME_DIR:-/tmp}/herdr-focus-previous-tab.json"
[[ -r $history ]] || exit 0

tabs=$("$herdr" tab list)
current=$(jq -r '.result.tabs[] | select(.focused) | .tab_id' <<<"$tabs")
live=$(jq -c '[.result.tabs[].tab_id]' <<<"$tabs")
# Most recent tab that is not this one and still exists.
target=$(jq -r --arg cur "$current" --argjson live "$live" \
  'map(select(. != $cur and (. as $t | $live | index($t)))) | first // empty' "$history")
[[ -n $target ]] && "$herdr" tab focus "$target" >/dev/null
