#!/bin/sh
set -eu

config="${WIREGUARD_CONFIG:-/etc/wireguard/wg0.conf}"

mkdir -p /dev/net
if [ ! -c /dev/net/tun ]; then
  mknod /dev/net/tun c 10 200 || true
fi

wg-quick up "$config"

cleanup() {
  wg-quick down "$config" || true
}
trap cleanup INT TERM EXIT

tail -f /dev/null &
wait "$!"
