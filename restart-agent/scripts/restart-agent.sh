#!/usr/bin/env bash
# `claude -c` picks the most recently active transcript in the cwd, which is the
# wrong session whenever several agents share a repo dir -- so resume by id.
set -euo pipefail

herdr=${HERDR_BIN_PATH:-herdr}

pane_json=$("$herdr" pane current)
pane=$(jq -r '.result.pane.pane_id' <<<"$pane_json")
agent=$(jq -r '.result.pane.agent // empty' <<<"$pane_json")
sid=$(jq -r '.result.pane.agent_session.value // empty' <<<"$pane_json")

# Not a Claude agent pane -> do nothing rather than typing into a shell.
[[ $agent == claude && -n $sid ]] || exit 0

# Two Ctrl+C in one call, so they land inside Claude's double-tap exit window.
"$herdr" agent send-keys "$pane" ctrl+c ctrl+c

# Wait for claude to leave the foreground before typing the relaunch.
for _ in $(seq 1 50); do
  if ! "$herdr" pane process-info --pane "$pane" \
      | jq -e '.result.process_info.foreground_processes[]? | select(.name == "claude")' >/dev/null; then
    "$herdr" pane run "$pane" "claude --resume $sid"
    exit 0
  fi
  sleep 0.1
done

echo "restart-agent: claude in $pane did not exit" >&2
exit 1
