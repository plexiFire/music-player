#!/usr/bin/env bash
# Run this ON the Oracle VM (Ubuntu), inside the cloned repo:   ./deploy/oracle-setup.sh
# It installs Docker, builds Senora, starts it, and puts free automatic HTTPS (Caddy) in front of it.
# Run it again after `git pull` to update. Your playlists live in /var/senora-data and are never touched by an update.
set -e
cd "$(dirname "$0")/.."

DOMAIN="${SENORA_DOMAIN:-}"
if [ -z "$DOMAIN" ]; then read -r -p "Your page address, e.g. myname.duckdns.org (no https://): " DOMAIN; fi
sudo mkdir -p /etc/senora /var/senora-data
if [ ! -f /etc/senora/env ]; then
  if [ -z "$SENORA_PASSWORD" ]; then read -r -s -p "Choose a password for the page: " SENORA_PASSWORD; echo; fi
  read -r -p "Contact e-mail for the description's copyright line (or leave empty): " MAIL
  printf 'SENORA_PASSWORD=%s\nSENORA_CONTACT_EMAIL=%s\nSENORA_MODE=cloud\nSENORA_DATA=/data\n' "$SENORA_PASSWORD" "$MAIL" | sudo tee /etc/senora/env >/dev/null
  sudo chmod 600 /etc/senora/env
fi

# 1. Docker
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi

# 2. let web traffic in (Oracle's Ubuntu image blocks it inside the VM as well; the cloud console needs ports 80 and 443 opened too)
for p in 80 443; do
  sudo iptables -C INPUT -m state --state NEW -p tcp --dport $p -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport $p -j ACCEPT
done
sudo sh -c 'command -v netfilter-persistent >/dev/null && netfilter-persistent save || true'

# 3. Senora itself (only reachable from this VM; Caddy is the public door)
sudo docker build -t senora .
sudo docker rm -f senora >/dev/null 2>&1 || true
sudo docker run -d --name senora --restart unless-stopped -p 127.0.0.1:8001:8001 -v /var/senora-data:/data --env-file /etc/senora/env senora

# 4. HTTPS with a free certificate
printf '%s {\n\treverse_proxy 127.0.0.1:8001\n\trequest_body {\n\t\tmax_size 500MB\n\t}\n}\n' "$DOMAIN" | sudo tee /etc/senora/Caddyfile >/dev/null
sudo docker rm -f caddy >/dev/null 2>&1 || true
sudo docker run -d --name caddy --restart unless-stopped --network host -v /etc/senora/Caddyfile:/etc/caddy/Caddyfile -v caddy_data:/data caddy:2

echo
echo "Done. Open https://$DOMAIN  (the first load can take a minute while the certificate is made)."
echo "Check:  sudo docker logs senora   |   sudo docker logs caddy"
