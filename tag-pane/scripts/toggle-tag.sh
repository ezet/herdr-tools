#!/usr/bin/env bash
# The tag is a pane metadata token, so it lives on herdr's own pane record: it
# follows the pane when it moves, and goes when the pane closes.
set -euo pipefail

herdr=${HERDR_BIN_PATH:-herdr}
dot=${TAG_PANE_DOT:-●}

pane_json=$("$herdr" pane current)
pane=$(jq -r '.result.pane.pane_id' <<<"$pane_json")

if jq -e '.result.pane.tokens.tag // empty' <<<"$pane_json" >/dev/null; then
  "$herdr" pane report-metadata "$pane" --source tag-pane --clear-token tag
else
  "$herdr" pane report-metadata "$pane" --source tag-pane --token "tag=$dot"
fi
