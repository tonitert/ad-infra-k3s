import os
import subprocess
import time

from kubernetes import client, config


NAMESPACE = os.environ.get("POD_NAMESPACE", "ataka")
NODE_NAME = os.environ["NODE_NAME"]
LABEL_SELECTOR = os.environ.get("VPN_LABEL_SELECTOR", "ataka.ad.tertsonen.xyz/vpn-route=true")
GATEWAY_SELECTOR = os.environ.get("GATEWAY_LABEL_SELECTOR", "app.kubernetes.io/name=ataka-wireguard-gateway")
ROUTE_TABLE = os.environ.get("ROUTE_TABLE", "200")
ROUTE_CIDRS = os.environ.get("ROUTE_CIDRS", "10.99.0.2/32").split()
ROUTE_MARK = os.environ.get("ROUTE_MARK", "0x51")
ENABLE_DIND_MARKING = os.environ.get("ENABLE_DIND_MARKING", "false") == "true"
INTERVAL = int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "5"))


def run(*args, check=False):
    return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def family_for(value):
    return "6" if ":" in value else "4"


def first_for_family(values, family):
    for value in values:
        if value and family_for(value) == family:
            return value
    return None


def pod_ips(pod):
    ips = []
    for item in getattr(pod.status, "pod_ips", None) or []:
        ips.append(item.ip)
    if getattr(pod.status, "pod_ip", None):
        ips.append(pod.status.pod_ip)
    return list(dict.fromkeys(ips))


def gateway_ips(v1):
    ips = []
    pods = v1.list_namespaced_pod(NAMESPACE, label_selector=GATEWAY_SELECTOR).items
    for pod in pods:
        if pod.status.phase != "Running":
            continue
        for item in getattr(pod.status, "host_ips", None) or []:
            ips.append(item.ip)
        if getattr(pod.status, "host_ip", None):
            ips.append(pod.status.host_ip)
        ips.extend(pod_ips(pod))
    return list(dict.fromkeys(ips))


def node_ips(v1):
    node = v1.read_node(NODE_NAME)
    return [address.address for address in node.status.addresses if address.type == "InternalIP"]


def selected_pod_ips(v1):
    pods = v1.list_namespaced_pod(
        NAMESPACE,
        label_selector=LABEL_SELECTOR,
        field_selector=f"spec.nodeName={NODE_NAME},status.phase=Running",
    ).items
    ips = []
    for pod in pods:
        ips.extend(pod_ips(pod))
    return list(dict.fromkeys(ips))


def existing_rule_sources(family):
    result = run("ip", f"-{family}", "rule", "show")
    sources = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if "lookup" not in parts or parts[-1] != ROUTE_TABLE or "from" not in parts:
            continue
        source = parts[parts.index("from") + 1]
        sources.append(source.removesuffix("/32").removesuffix("/128"))
    return sources


def rule_exists(family, needle):
    return needle in run("ip", f"-{family}", "rule", "show").stdout


def ensure_fwmark_rule(family):
    needle = f"fwmark {ROUTE_MARK} lookup {ROUTE_TABLE}"
    if not rule_exists(family, needle):
        run("ip", f"-{family}", "rule", "add", "fwmark", ROUTE_MARK, "table", ROUTE_TABLE)


def install_routes(all_node_ips, all_gateway_ips):
    for cidr in ROUTE_CIDRS:
        family = family_for(cidr)
        gateway = first_for_family(all_gateway_ips, family)
        self_ip = first_for_family(all_node_ips, family)
        if not gateway:
            continue
        if self_ip and gateway == self_ip and run("ip", "link", "show", "wg0").returncode == 0:
            run("ip", f"-{family}", "route", "replace", cidr, "dev", "wg0", "table", ROUTE_TABLE)
        else:
            run("ip", f"-{family}", "route", "replace", cidr, "via", gateway, "table", ROUTE_TABLE)
        ensure_fwmark_rule(family)


def reconcile_rules_for_family(family, desired):
    desired = set(desired)
    for source in existing_rule_sources(family):
        if source not in desired:
            run("ip", f"-{family}", "rule", "del", "from", source, "table", ROUTE_TABLE)

    for source in desired:
        if not rule_exists(family, f"from {source} lookup {ROUTE_TABLE}"):
            run("ip", f"-{family}", "rule", "add", "from", source, "table", ROUTE_TABLE)


def reconcile_rules(ips):
    reconcile_rules_for_family("4", [ip for ip in ips if family_for(ip) == "4"])
    reconcile_rules_for_family("6", [ip for ip in ips if family_for(ip) == "6"])


def ensure_mangle_rule(cidr):
    family = family_for(cidr)
    tool = "ip6tables" if family == "6" else "iptables"
    chain = "ATAKA_DIND_VPN"
    run(tool, "-t", "mangle", "-N", chain)
    if run(tool, "-t", "mangle", "-C", chain, "-d", cidr, "-j", "MARK", "--set-mark", ROUTE_MARK).returncode != 0:
        run(tool, "-t", "mangle", "-A", chain, "-d", cidr, "-j", "MARK", "--set-mark", ROUTE_MARK)
    if run(tool, "-t", "mangle", "-C", "PREROUTING", "-j", chain).returncode != 0:
        run(tool, "-t", "mangle", "-A", "PREROUTING", "-j", chain)


def main():
    config.load_incluster_config()
    v1 = client.CoreV1Api()

    while True:
        try:
            install_routes(node_ips(v1), gateway_ips(v1))
            reconcile_rules(selected_pod_ips(v1))
            if ENABLE_DIND_MARKING:
                for cidr in ROUTE_CIDRS:
                    ensure_mangle_rule(cidr)
        except Exception as exc:
            print(f"route-agent reconcile failed: {exc}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
