#!/usr/bin/env bash
# Install a local-only SearXNG for the bot's web_search tool. Run on the VPS as a sudoer.
# SearXNG needs Python 3.11+, and Ubuntu 22.04 ships 3.10, so a standalone CPython 3.12
# is installed with uv under /opt/searxng (the system Python is left alone).
# Afterwards set SEARXNG_URL=http://127.0.0.1:8888 in /opt/mafuyu/.env.
set -euo pipefail
cd "$(dirname "$0")"

sudo apt-get install -y -qq git build-essential python3-dev python3-venv \
  libxslt-dev zlib1g-dev libffi-dev libssl-dev
id searxng >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /opt/searxng \
  --shell /usr/sbin/nologin searxng
sudo test -d /opt/searxng/src || \
  sudo -u searxng git clone -q --depth 1 https://github.com/searxng/searxng.git /opt/searxng/src

# Python 3.12 via uv
sudo -u searxng python3 -m venv /opt/searxng/uv-venv
sudo -u searxng /opt/searxng/uv-venv/bin/pip install -q uv
UV_ENV=(env UV_PYTHON_INSTALL_DIR=/opt/searxng/python UV_CACHE_DIR=/opt/searxng/.cache/uv)
sudo -u searxng "${UV_ENV[@]}" /opt/searxng/uv-venv/bin/uv python install 3.12
PY=$(sudo -u searxng "${UV_ENV[@]}" /opt/searxng/uv-venv/bin/uv python find 3.12)

sudo test -x /opt/searxng/venv/bin/python || sudo -u searxng "$PY" -m venv /opt/searxng/venv
sudo -u searxng /opt/searxng/venv/bin/pip install -q --upgrade pip setuptools wheel
sudo -u searxng bash -c 'cd /opt/searxng/src &&
  /opt/searxng/venv/bin/pip install -q -r requirements.txt &&
  /opt/searxng/venv/bin/pip install -q --use-pep517 --no-build-isolation -e .'

# Settings with a fresh secret; keep an existing file so the secret doesn't change.
sudo install -d -m 755 /etc/searxng
if ! sudo test -f /etc/searxng/settings.yml; then
  sed "s/\"CHANGE_ME\"/\"$(openssl rand -hex 32)\"/" settings.yml \
    | sudo install -m 640 -o root -g searxng /dev/stdin /etc/searxng/settings.yml
fi

sudo install -m 644 searxng.service /etc/systemd/system/searxng.service
sudo systemctl daemon-reload
sudo systemctl enable --now searxng
echo "SearXNG is running on http://127.0.0.1:8888"
