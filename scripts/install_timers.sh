#!/usr/bin/env bash
# Install / reconcile the systemd --user timers so the set of running timers
# always matches the registry: one sync timer per *enabled* channel in
# channels.json. Re-runnable and idempotent — run it after adding, enabling, or
# disabling a channel.
#
# The previous breakage this prevents: timers were enabled per-channel by hand,
# so a newly-added channel (kaishow) was simply forgotten and never synced.
# Now the registry is the single source of truth.
#
#   ./scripts/install_timers.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$PWD"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

# Survive logout/reboot without an active session (timers fire while logged out).
loginctl enable-linger "$USER" 2>/dev/null || true

# Install the unit templates as real files (not symlinks): systemd cannot
# `enable` an instance of a template that is symlinked in from outside the unit
# search path. The units use only %h/%i specifiers, so copies are portable;
# re-running this script re-copies, so repo edits propagate on the next run.
# rm first: an earlier setup may have left these as symlinks into the repo,
# and `cp` onto a symlink-to-source errors with "same file".
rm -f "$UNIT_DIR/standfm-sync@.service" "$UNIT_DIR/standfm-sync@.timer"
cp "$ROOT/systemd/standfm-sync@.service" "$UNIT_DIR/standfm-sync@.service"
cp "$ROOT/systemd/standfm-sync@.timer"   "$UNIT_DIR/standfm-sync@.timer"
systemctl --user daemon-reload

mapfile -t enabled < <(python3 "$ROOT/channels.py" slugs --enabled)

# Disable timers for channels no longer enabled, so the running set stays in
# sync. Skip the bare template ($slug empty) — it has no [Install] of its own.
while IFS= read -r unit; do
  slug="${unit#standfm-sync@}"; slug="${slug%.timer}"
  [ -n "$slug" ] || continue
  keep=0; for s in "${enabled[@]}"; do [ "$s" = "$slug" ] && keep=1; done
  if [ "$keep" = 0 ]; then
    echo "  ✗ disabling stale timer: $slug"
    systemctl --user disable --now "$unit" 2>/dev/null || true
  fi
done < <(systemctl --user list-unit-files 'standfm-sync@*.timer' --no-legend 2>/dev/null | awk '{print $1}')

# Enable (+ start) a timer for every enabled channel.
for slug in "${enabled[@]}"; do
  echo "  ✓ enabling timer: $slug"
  systemctl --user enable --now "standfm-sync@${slug}.timer"
done

echo
systemctl --user list-timers 'standfm-sync@*' --no-pager
