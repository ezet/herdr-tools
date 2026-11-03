#!/usr/bin/env bash
# The PR comes from the pane's `pr` metadata token when something reports one
# (a Claude status line can, from the PR its footer shows), and otherwise from
# the branch checked out in the pane's directory, looked up on GitHub.
set -euo pipefail

herdr=${HERDR_BIN_PATH:-herdr}

notify() {
  "$herdr" notification show "$1" ${2:+--body "$2"} >/dev/null 2>&1 || true
}

pane_json=$("$herdr" pane current)
url=$(jq -r '.result.pane.tokens.pr // empty' <<<"$pane_json")

if [[ -z $url ]]; then
  dir=$(jq -r '.result.pane.foreground_cwd // .result.pane.cwd // empty' <<<"$pane_json")
  branch=$(git -C "$dir" symbolic-ref --short HEAD 2>/dev/null || true)
  remote=$(git -C "$dir" remote get-url origin 2>/dev/null || true)
  # owner/repo from git@github.com:o/r.git or http(s)://github.com/o/r(.git)
  repo=$(sed -nE 's#^(git@|ssh://git@|https?://)github\.com[:/]([^/]+/[^/]+)$#\2#p' <<<"$remote")
  repo=${repo%.git}
  if [[ -z $branch || -z $repo ]]; then
    notify "No PR" "The pane is not on a branch of a GitHub repo."
    exit 0
  fi
  # The default branch is no PR's head here; a lookup would find a stray one.
  default=$(git -C "$dir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)
  if [[ $branch == "${default#origin/}" ]]; then
    notify "No PR" "The pane is on $branch, the default branch."
    exit 0
  fi
  # Newest first, so a merged PR still opens once the branch's work has landed.
  url=$(gh api "repos/$repo/pulls?head=${repo%%/*}:$branch&state=all&sort=created&direction=desc&per_page=1" \
    --jq '.[0].html_url // empty' 2>/dev/null || true)
  if [[ -z $url ]]; then
    notify "No PR" "No pull request for $branch in $repo."
    exit 0
  fi
fi

if command -v open >/dev/null && [[ $(uname) == Darwin ]]; then
  open "$url"
elif command -v systemd-run >/dev/null; then
  # A herdr server started outside the graphical session lacks WAYLAND_DISPLAY
  # and DISPLAY, and xdg-open then finds no browser. The systemd user manager
  # has the session's environment, and the unit outlives this action.
  systemd-run --user --quiet --collect xdg-open "$url"
else
  xdg-open "$url" &
fi
