#!/bin/sh
# Opens the plugin's popup entrypoint at the manifest placement.
#
# herdr's popup is a session singleton, so pressing the key again while the
# popup is up answers "popup already open". That is not an error — a second
# press is someone reaching for a dashboard that is already there — so it
# exits 0 rather than surfacing a failure.
set -eu

herdr_bin="${HERDR_BIN_PATH:-herdr}"
plugin_id="${HERDR_PLUGIN_ID:-codex-switch}"

out=$("$herdr_bin" plugin pane open --plugin "$plugin_id" --entrypoint tui 2>&1) && exit 0

case "$out" in
    *"popup already open"*) exit 0 ;;
esac

printf '%s\n' "$out" >&2
exit 1
