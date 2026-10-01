#!/usr/bin/env bash
# Checks that IPv4 still goes out through WARP; if not, rebuilds the tunnel and
# restarts the bot so it does not sit in discord.py's long reconnect backoff.
# Run by mafuyu-netwatch.timer.
set -uo pipefail

ipv4_ok() {
  ip -4 rule | grep -q 'lookup 51820' \
    && curl -4 -fsS -m 10 -o /dev/null https://1.1.1.1/cdn-cgi/trace
}

if ipv4_ok; then
  exit 0
fi
# One retry so a single dropped request does not trigger a restart.
sleep 15
if ipv4_ok; then
  exit 0
fi

echo "IPv4 via WARP is down; restarting wg-quick@wgcf"
systemctl restart wg-quick@wgcf
sleep 5
if ipv4_ok; then
  echo "IPv4 is back; restarting mafuyu"
  systemctl restart mafuyu
else
  echo "IPv4 is still down after restarting the tunnel" >&2
  exit 1
fi
