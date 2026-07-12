#!/bin/sh
set -eu

config="${OPENVPN_CONFIG:-/vpn/vpn.conf}"
dev="${OPENVPN_DEV:-tun0}"
route_cidrs="${OPENVPN_ROUTE_CIDRS:-}"

mkdir -p /dev/net
if [ ! -c /dev/net/tun ]; then
  mknod /dev/net/tun c 10 200 || true
fi

openvpn --config "$config" --route-noexec &
pid="$!"

for _ in $(seq 1 60); do
  if ip link show "$dev" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid"
  fi
  sleep 1
done

ip link show "$dev" >/dev/null 2>&1

sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv6.conf.all.forwarding=1 || true

for cidr in $route_cidrs; do
  if printf '%s' "$cidr" | grep -q ':'; then
    ip -6 route replace "$cidr" dev "$dev" || true
    ip6tables -t nat -C POSTROUTING -d "$cidr" -o "$dev" -j MASQUERADE 2>/dev/null \
      || ip6tables -t nat -A POSTROUTING -d "$cidr" -o "$dev" -j MASQUERADE
  else
    ip route replace "$cidr" dev "$dev" || true
    iptables -t nat -C POSTROUTING -d "$cidr" -o "$dev" -j MASQUERADE 2>/dev/null \
      || iptables -t nat -A POSTROUTING -d "$cidr" -o "$dev" -j MASQUERADE
  fi
done

cleanup() {
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

wait "$pid"
