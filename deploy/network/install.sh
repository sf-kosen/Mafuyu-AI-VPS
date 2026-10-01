#!/usr/bin/env bash
# Installs the network safeguards. Run as root on the VPS (deploy.sh does this).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

install -d /etc/systemd/networkd.conf.d
install -m 644 "$here/10-keep-foreign-routes.conf" /etc/systemd/networkd.conf.d/
# Copied out of /opt/mafuyu/app because that tree is owned by the bot user and this runs as root.
install -m 755 -o root -g root "$here/netwatch.sh" /usr/local/sbin/mafuyu-netwatch
install -m 644 "$here/mafuyu-netwatch.service" "$here/mafuyu-netwatch.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mafuyu-netwatch.timer >/dev/null 2>&1
