#!/bin/sh
set -eu

config="${WIREGUARD_CONFIG:-/etc/wireguard/wg0.conf}"

mkdir -p /dev/net
if [ ! -c /dev/net/tun ]; then
  mknod /dev/net/tun c 10 200 || true
fi

wg-quick up "$config"

if [ "${WIREGUARD_GATEWAY:-false}" = "true" ]; then
  sysctl -w net.ipv4.ip_forward=1
  sysctl -w net.ipv6.conf.all.forwarding=1 || true

  for cidr in ${WIREGUARD_ROUTE_CIDRS:-10.99.0.2/32}; do
    if printf '%s' "$cidr" | grep -q ':'; then
      ip6tables -t nat -C POSTROUTING -d "$cidr" -o wg0 -j MASQUERADE 2>/dev/null \
        || ip6tables -t nat -A POSTROUTING -d "$cidr" -o wg0 -j MASQUERADE
    else
      iptables -t nat -C POSTROUTING -d "$cidr" -o wg0 -j MASQUERADE 2>/dev/null \
        || iptables -t nat -A POSTROUTING -d "$cidr" -o wg0 -j MASQUERADE
    fi
  done
fi

cleanup() {
  wg-quick down "$config" || true
}
trap cleanup INT TERM EXIT

tail -f /dev/null &
wait "$!"
