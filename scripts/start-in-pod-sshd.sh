set -eu

public_key="${1:-}"
if [ -z "$public_key" ]; then
  echo "missing SSH public key argument" >&2
  exit 2
fi

ssh-keygen -A >/dev/null 2>&1 || true
mkdir -p /run/sshd /root/.ssh
touch /root/.ssh/authorized_keys
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys

tmp="$(mktemp)"
printf '%s\n' "$public_key" > "$tmp"
cat /root/.ssh/authorized_keys "$tmp" | awk "NF && !seen[\$0]++" > /root/.ssh/authorized_keys.new
mv /root/.ssh/authorized_keys.new /root/.ssh/authorized_keys
rm -f "$tmp"
chmod 600 /root/.ssh/authorized_keys

if [ -f /tmp/tulip-pcap-stress-sshd.pid ]; then
  kill "$(cat /tmp/tulip-pcap-stress-sshd.pid)" >/dev/null 2>&1 || true
  rm -f /tmp/tulip-pcap-stress-sshd.pid
fi

{
  printf "%s\n" "Port 2222"
  printf "%s\n" "ListenAddress 127.0.0.1"
  printf "%s\n" "PidFile /tmp/tulip-pcap-stress-sshd.pid"
  printf "%s\n" "PermitRootLogin prohibit-password"
  printf "%s\n" "PasswordAuthentication no"
  printf "%s\n" "KbdInteractiveAuthentication no"
  printf "%s\n" "PubkeyAuthentication yes"
  printf "%s\n" "AuthorizedKeysFile /root/.ssh/authorized_keys"
  printf "%s\n" "AllowTcpForwarding remote"
  printf "%s\n" "GatewayPorts no"
  printf "%s\n" "X11Forwarding no"
  printf "%s\n" "AllowAgentForwarding no"
  printf "%s\n" "PermitTTY no"
  printf "%s\n" "LogLevel VERBOSE"
} > /tmp/tulip-pcap-stress-sshd_config

/usr/sbin/sshd -f /tmp/tulip-pcap-stress-sshd_config -E /tmp/tulip-pcap-stress-sshd.log
