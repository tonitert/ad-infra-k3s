#!/usr/bin/env bash
set -euo pipefail

host="${WG_TARGET_HOST:-$(read -p 'Enter the WireGuard target host (IP or hostname): ' input && echo "$input")}"
port="${WG_TARGET_PORT:-51820}"
server_ip="${WG_SERVER_IP:-10.99.0.2}"
client_ip="${WG_CLIENT_IP:-10.99.0.1}"
flag="${WG_TEST_FLAG:-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=}"
ssh_key="${WG_SSH_KEY:-$(pwd)/keys/ssh}"
workdir="${WG_WORKDIR:-$(pwd)/.terraform/ataka-wireguard}"
namespace="${WG_K8S_NAMESPACE:-ataka}"
secret_name="${WG_K8S_SECRET_NAME:-ataka-wireguard-config}"

install -m 700 -d "$workdir"
known_hosts="$workdir/known_hosts"
touch "$known_hosts"
chmod 600 "$known_hosts"

ssh_opts=(
  -i "$ssh_key"
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$known_hosts"
  -o ConnectTimeout=10
)

connected=0
for attempt in 1 2 3 4 5; do
  if ssh "${ssh_opts[@]}" "root@$host" true; then
    connected=1
    break
  fi
  echo "SSH to root@$host failed, retrying ($attempt/5)..." >&2
  sleep 5
done

if [ "$connected" -ne 1 ]; then
  echo "Unable to connect to root@$host after retries" >&2
  exit 1
fi

ssh "${ssh_opts[@]}" "root@$host" 'bash -s' <<'REMOTE_INSTALL'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y wireguard nftables nginx

install -m 700 -d /etc/wireguard
umask 077
if [ ! -s /etc/wireguard/server_private.key ]; then
  wg genkey > /etc/wireguard/server_private.key
  wg pubkey < /etc/wireguard/server_private.key > /etc/wireguard/server_public.key
fi
if [ ! -s /etc/wireguard/client_private.key ]; then
  wg genkey > /etc/wireguard/client_private.key
  wg pubkey < /etc/wireguard/client_private.key > /etc/wireguard/client_public.key
fi
REMOTE_INSTALL

server_public="$(ssh "${ssh_opts[@]}" "root@$host" 'cat /etc/wireguard/server_public.key')"
client_private="$(ssh "${ssh_opts[@]}" "root@$host" 'cat /etc/wireguard/client_private.key')"
client_public="$(ssh "${ssh_opts[@]}" "root@$host" 'cat /etc/wireguard/client_public.key')"

printf '%s\n' "$server_public" > "$workdir/server_public.key"
printf '%s\n' "$client_private" > "$workdir/client_private.key"
printf '%s\n' "$client_public" > "$workdir/client_public.key"
chmod 600 "$workdir"/*.key

ssh "${ssh_opts[@]}" "root@$host" \
  CLIENT_PUBLIC="$client_public" \
  WG_PORT="$port" \
  SERVER_IP="$server_ip" \
  CLIENT_IP="$client_ip" \
  TEST_FLAG="$flag" \
  'bash -s' <<'REMOTE_CONFIG'
set -euo pipefail

cat > /etc/wireguard/wg0.conf <<EOF_WG
[Interface]
Address = $SERVER_IP/32
ListenPort = $WG_PORT
PrivateKey = $(cat /etc/wireguard/server_private.key)

[Peer]
PublicKey = $CLIENT_PUBLIC
AllowedIPs = $CLIENT_IP/32
EOF_WG
chmod 600 /etc/wireguard/wg0.conf

cat > /etc/nftables.conf <<EOF_NFT
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
  chain input {
    type filter hook input priority 0;
    policy drop;

    ct state established,related accept
    iif "lo" accept
    ip protocol icmp accept
    ip6 nexthdr icmpv6 accept
    tcp dport 22 accept
    udp dport $WG_PORT accept
    iifname "wg0" ip saddr $CLIENT_IP tcp dport 80 accept
  }

  chain forward {
    type filter hook forward priority 0;
    policy drop;
  }

  chain output {
    type filter hook output priority 0;
    policy accept;
  }
}
EOF_NFT

cat > /etc/nginx/sites-available/ataka-wireguard-test <<EOF_NGINX
server {
  listen $SERVER_IP:80 default_server;
  server_name _;

  location / {
    default_type text/plain;
    return 200 "$TEST_FLAG\n";
  }
}
EOF_NGINX

rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/ataka-wireguard-test /etc/nginx/sites-enabled/ataka-wireguard-test

install -d /etc/systemd/system/nginx.service.d
cat > /etc/systemd/system/nginx.service.d/wireguard.conf <<'EOF_SYSTEMD'
[Unit]
Requires=wg-quick@wg0.service
After=wg-quick@wg0.service
EOF_SYSTEMD

systemctl daemon-reload
systemctl enable nftables wg-quick@wg0 nginx
nft -f /etc/nftables.conf
systemctl restart wg-quick@wg0
nginx -t
systemctl restart nginx
REMOTE_CONFIG

client_config="$workdir/wg0.conf"
cat > "$client_config" <<EOF_CLIENT
[Interface]
Address = $client_ip/32
PrivateKey = $client_private

[Peer]
PublicKey = $server_public
Endpoint = $host:$port
AllowedIPs = $server_ip/32
PersistentKeepalive = 25
EOF_CLIENT
chmod 600 "$client_config"

echo "Wrote WireGuard client config to $client_config"

if [ "${WG_APPLY_K8S_SECRET:-1}" = "1" ]; then
  if [ -z "${KUBECONFIG:-}" ] && [ -s "$(pwd)/k3s_kubeconfig.yaml" ]; then
    export KUBECONFIG="$(pwd)/k3s_kubeconfig.yaml"
  fi

  if command -v kubectl >/dev/null 2>&1 && [ -n "${KUBECONFIG:-}" ]; then
    ready=0
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
      if kubectl get --raw=/readyz >/dev/null 2>&1; then
        ready=1
        break
      fi
      sleep 10
    done

    if [ "$ready" -ne 1 ]; then
      echo "Kubernetes API did not become ready; leaving $secret_name unapplied" >&2
      exit 1
    fi

    kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n "$namespace" create secret generic "$secret_name" \
      --from-file=wg0.conf="$client_config" \
      --dry-run=client -o yaml | kubectl apply -f -
    echo "Applied Kubernetes secret $namespace/$secret_name"
  else
    echo "Skipping Kubernetes secret apply; set KUBECONFIG and ensure kubectl is available to apply it." >&2
  fi
fi
