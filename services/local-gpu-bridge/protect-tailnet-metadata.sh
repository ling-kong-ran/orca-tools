#!/bin/sh
# Run as root on the VPS. Restricts LocalAPI metadata without restarting networking.
set -eu
worker_user=${1:?Usage: sudo sh protect-tailnet-metadata.sh WORKER_USER}
id "$worker_user" >/dev/null
test "$worker_user" != root || { echo 'Use a non-root worker account.' >&2; exit 1; }
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run this script as root; the worker has no permission to apply this change.' >&2
  exit 1
fi
test -S /run/tailscale/tailscaled.sock || { echo 'Expected Tailscale socket is missing.' >&2; exit 1; }
test ! -L /run/tailscale || { echo 'Refusing an unexpected symlink.' >&2; exit 1; }
test "$(stat -c %u /run/tailscale)" = 0 || { echo 'Unexpected Tailscale directory owner.' >&2; exit 1; }
systemctl show tailscaled.service -p RuntimeDirectory --value | tr ' ' '\n' | grep -qx tailscale || {
  echo 'This Tailscale service has an unexpected RuntimeDirectory; no changes made.' >&2; exit 1;
}
directory=/etc/systemd/system/tailscaled.service.d
file="$directory/50-local-api-private.conf"
test ! -L "$directory" && test ! -L "$file" || { echo 'Refusing a symlink.' >&2; exit 1; }
install -d -m 0755 "$directory"
if [ -f "$file" ] && ! grep -qx '# Managed by Local GPU Bridge' "$file"; then
  echo 'An existing unrelated drop-in uses this filename; no changes made.' >&2; exit 1
fi
printf '%s\n' '# Managed by Local GPU Bridge' '[Service]' 'RuntimeDirectoryMode=0700' > "$file"
chmod 0644 "$file"
systemctl daemon-reload
chmod 0700 /run/tailscale
if runuser -u "$worker_user" -- tailscale status --json >/dev/null 2>&1; then
  echo 'Privacy check failed: worker can still query Tailscale metadata.' >&2; exit 1
fi
echo 'Done. worker cannot query Tailscale metadata. The private network was not restarted.'
echo 'Tailscale administration now requires root. Start a new Claude session to use the GPU plugin.'
