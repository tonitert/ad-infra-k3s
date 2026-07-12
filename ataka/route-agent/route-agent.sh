#!/usr/bin/env bash
set -euo pipefail

namespace="${POD_NAMESPACE:-ataka}"
node_name="${NODE_NAME:?NODE_NAME is required}"
label_selector="${VPN_LABEL_SELECTOR:-ataka.ad.tertsonen.xyz/vpn-route=true}"
gateway_selector="${GATEWAY_LABEL_SELECTOR:-app.kubernetes.io/name=ataka-wireguard-gateway}"
vpn_interface="${VPN_INTERFACE:-wg0}"
route_table="${ROUTE_TABLE:-200}"
route_cidrs="${ROUTE_CIDRS:-10.99.0.2/32}"
mark="${ROUTE_MARK:-0x51}"

family_for() {
  case "$1" in
    *:*) printf '6' ;;
    *) printf '4' ;;
  esac
}

addr_for_family() {
  local family="$1"
  while read -r address; do
    [ -n "$address" ] || continue
    if [ "$(family_for "$address")" = "$family" ]; then
      printf '%s\n' "$address"
      return 0
    fi
  done
  return 1
}

node_ips() {
  kubectl get node "$node_name" -o json \
    | jq -r '.status.addresses[] | select(.type=="InternalIP") | .address'
}

gateway_ips() {
  kubectl -n "$namespace" get pods -l "$gateway_selector" -o json \
    | jq -r '.items[] | select(.status.phase=="Running") |
      ((.status.hostIPs // [] | .[].ip), (.status.hostIP // empty), (.status.podIPs // [] | .[].ip), (.status.podIP // empty))' \
    | awk 'NF && !seen[$0]++'
}

gateway_pod_cidr_ips() {
  kubectl -n "$namespace" get pods -l "$gateway_selector" -o json \
    | jq -r '.items[] | select(.status.phase=="Running") | .spec.nodeName // empty' \
    | awk 'NF && !seen[$0]++' \
    | while read -r gateway_node; do
      kubectl get node "$gateway_node" -o json \
        | jq -r '((.spec.podCIDRs // [] | .[]), (.spec.podCIDR // empty))' \
        | awk -F/ 'NF { print $1 }'
    done \
    | awk 'NF && !seen[$0]++'
}

selected_pod_ips() {
  kubectl -n "$namespace" get pods \
    -l "$label_selector" \
    --field-selector "spec.nodeName=${node_name},status.phase=Running" \
    -o json \
    | jq -r '.items[] | ((.status.podIPs // [] | .[].ip), (.status.podIP // empty))' \
    | awk 'NF && !seen[$0]++'
}

route_dev_for() {
  local family="$1"
  local destination="$2"

  ip "-$family" route get "$destination" 2>/dev/null \
    | awk '{ for (i=1; i<=NF; i++) if ($i == "dev") { print $(i+1); exit } }'
}

existing_rule_sources() {
  local family="$1"
  local mask="/32"
  [ "$family" = "6" ] && mask="/128"

  ip "-$family" rule show \
    | awk -v table="$route_table" '$0 ~ "lookup " table { for (i=1; i<=NF; i++) if ($i == "from") print $(i+1) }' \
    | sed "s#${mask}\$##"
}

rule_exists() {
  local family="$1"
  local match="$2"

  ip "-$family" rule show | grep -Fq "$match"
}

ensure_fwmark_rule() {
  local family="$1"
  local match="fwmark $mark lookup $route_table"

  rule_exists "$family" "$match" || ip "-$family" rule add fwmark "$mark" table "$route_table" 2>/dev/null || true
}

ensure_destination_rule() {
  local family="$1"
  local cidr="$2"
  local match="to $cidr lookup $route_table"

  rule_exists "$family" "$match" || ip "-$family" rule add to "$cidr" table "$route_table" 2>/dev/null || true
}

install_routes() {
  local all_node_ips="$1"
  local all_gateway_ips="$2"
  local all_gateway_pod_cidr_ips="$3"
  local cidr
  local family
  local gw
  local self
  local gateway_pod_cidr_ip
  local dev

  for cidr in $route_cidrs; do
    family="$(family_for "$cidr")"
    gw="$(printf '%s\n' "$all_gateway_ips" | addr_for_family "$family" || true)"
    self="$(printf '%s\n' "$all_node_ips" | addr_for_family "$family" || true)"
    [ -n "$gw" ] || continue

    if [ -n "$self" ] && [ "$gw" = "$self" ] && ip link show "$vpn_interface" >/dev/null 2>&1; then
      ip "-$family" route replace "$cidr" dev "$vpn_interface" table "$route_table"
    else
      gateway_pod_cidr_ip="$(printf '%s\n' "$all_gateway_pod_cidr_ips" | addr_for_family "$family" || true)"
      if [ -n "$gateway_pod_cidr_ip" ]; then
        dev="$(route_dev_for "$family" "$gateway_pod_cidr_ip")"
        if [ -n "$dev" ]; then
          ip "-$family" route replace "$cidr" via "$gateway_pod_cidr_ip" dev "$dev" onlink table "$route_table"
        else
          ip "-$family" route replace "$cidr" via "$gateway_pod_cidr_ip" table "$route_table"
        fi
      else
        ip "-$family" route replace "$cidr" via "$gw" table "$route_table"
      fi
    fi

    ensure_fwmark_rule "$family"
    ensure_destination_rule "$family" "$cidr"
  done
}

reconcile_rules_for_family() {
  local family="$1"
  local desired="$2"
  local source

  while read -r source; do
    [ -n "$source" ] || continue
    if ! printf '%s\n' "$desired" | grep -Fxq "$source"; then
      ip "-$family" rule del from "$source" table "$route_table" 2>/dev/null || true
    fi
  done < <(existing_rule_sources "$family")

  while read -r source; do
    [ -n "$source" ] || continue
    rule_exists "$family" "from $source lookup $route_table" \
      || ip "-$family" rule add from "$source" table "$route_table" 2>/dev/null || true
  done <<< "$desired"
}

reconcile_rules() {
  local all_pod_ips="$1"
  local desired_v4
  local desired_v6

  desired_v4="$(printf '%s\n' "$all_pod_ips" | while read -r ipaddr; do [ "$(family_for "$ipaddr")" = "4" ] && printf '%s\n' "$ipaddr"; done)"
  desired_v6="$(printf '%s\n' "$all_pod_ips" | while read -r ipaddr; do [ "$(family_for "$ipaddr")" = "6" ] && printf '%s\n' "$ipaddr"; done)"

  reconcile_rules_for_family 4 "$desired_v4"
  reconcile_rules_for_family 6 "$desired_v6"
}

ensure_mangle_rule() {
  local family="$1"
  local cidr="$2"
  local tool="iptables"
  local chain="ATAKA_DIND_VPN"

  [ "$family" = "6" ] && tool="ip6tables"

  "$tool" -t mangle -N "$chain" 2>/dev/null || true
  "$tool" -t mangle -C "$chain" -d "$cidr" -j MARK --set-mark "$mark" 2>/dev/null \
    || "$tool" -t mangle -A "$chain" -d "$cidr" -j MARK --set-mark "$mark"
  "$tool" -t mangle -C PREROUTING -j "$chain" 2>/dev/null \
    || "$tool" -t mangle -A PREROUTING -j "$chain"
}

reconcile_dind_marking() {
  local cidr
  local family

  for cidr in $route_cidrs; do
    family="$(family_for "$cidr")"
    ensure_mangle_rule "$family" "$cidr"
  done
}

while true; do
  all_node_ips="$(node_ips || true)"
  all_gateway_ips="$(gateway_ips || true)"
  all_gateway_pod_cidr_ips="$(gateway_pod_cidr_ips || true)"

  if [ -n "$all_node_ips" ] && [ -n "$all_gateway_ips" ]; then
    install_routes "$all_node_ips" "$all_gateway_ips" "$all_gateway_pod_cidr_ips"
    reconcile_rules "$(selected_pod_ips || true)"
    if [ "${ENABLE_DIND_MARKING:-false}" = "true" ]; then
      reconcile_dind_marking
    fi
  fi

  sleep "${RECONCILE_INTERVAL_SECONDS:-5}"
done
