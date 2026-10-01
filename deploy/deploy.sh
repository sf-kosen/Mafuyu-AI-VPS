#!/usr/bin/env bash
# Push the working tree to the VPS and restart the bot.
# Usage: deploy/deploy.sh   (run from the repo root, in Git Bash)
set -euo pipefail

# Connection settings live in deploy/.deploy.env (git-ignored); see deploy/.deploy.env.example.
DEPLOY_ENV="$(dirname "$0")/.deploy.env"
if [ -f "$DEPLOY_ENV" ]; then
  # shellcheck disable=SC1090
  . "$DEPLOY_ENV"
fi
: "${MAFUYU_HOST:?set MAFUYU_HOST (e.g. in deploy/.deploy.env)}"
KEY="${MAFUYU_KEY:-$HOME/.ssh/id_ed25519}"
SSH=(ssh -i "$KEY" -o BatchMode=yes "$MAFUYU_HOST")

# Runs on the VPS; the app tarball arrives on stdin.
read -r -d '' REMOTE <<'EOF' || true
set -euo pipefail
tmp=$(mktemp -d)
cat > "$tmp/app.tgz"
sudo rm -rf /opt/mafuyu/app.new
sudo install -d -o mafuyu -g mafuyu /opt/mafuyu/app.new /opt/mafuyu/data
sudo tar -xzf "$tmp/app.tgz" -C /opt/mafuyu/app.new
sudo chown -R mafuyu:mafuyu /opt/mafuyu/app.new
rm -rf "$tmp"
sudo rm -rf /opt/mafuyu/app.old
if sudo test -d /opt/mafuyu/app; then sudo mv /opt/mafuyu/app /opt/mafuyu/app.old; fi
sudo mv /opt/mafuyu/app.new /opt/mafuyu/app
sudo -u mafuyu /opt/mafuyu/venv/bin/pip install -q -r /opt/mafuyu/app/requirements.txt
sudo install -m 644 /opt/mafuyu/app/deploy/mafuyu.service /etc/systemd/system/mafuyu.service
sudo systemctl daemon-reload
sudo bash /opt/mafuyu/app/deploy/network/install.sh
if sudo test -s /opt/mafuyu/.env; then
  sudo systemctl enable mafuyu >/dev/null 2>&1
  sudo systemctl restart mafuyu
  echo "deployed and restarted"
else
  echo "deployed; /opt/mafuyu/.env is missing, so the bot was not started"
fi
EOF

git ls-files -z --cached --others --exclude-standard \
  | tar --null -T - -czf - \
  | "${SSH[@]}" "$REMOTE"
