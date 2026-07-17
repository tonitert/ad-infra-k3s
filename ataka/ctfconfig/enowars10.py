import ipaddress
import json
import logging
import os

import requests
from pwn import remote

from ataka.common.flag_status import FlagStatus


BASE_URL = os.getenv("ENOWARS_BASE_URL", "https://10.enowars.com").rstrip("/")
ATTACK_INFO_URL = f"{BASE_URL}/scoreboard/attack.json"
OPPONENT_IPS_URL = f"{BASE_URL}/api/data/ips"

FLAG_SUBMIT_HOST = os.getenv("ENOWARS_FLAG_SUBMIT_HOST", "10.0.13.37")
FLAG_SUBMIT_PORT = int(os.getenv("ENOWARS_FLAG_SUBMIT_PORT", "1337"))

TEAM_ID = int(os.getenv("ENOWARS_TEAM_ID", "15"))
OWN_HOST = f"10.1.{TEAM_ID}.1"
ATAKA_HOST = "ataka.local"

RUNLOCAL_TARGETS = [OWN_HOST]
STATIC_EXCLUSIONS = {OWN_HOST}

ROUND_TIME = 60
START_TIME = 1784376000  # 2026-07-18T12:00:00Z
FLAG_REGEX = r"ENO[A-Za-z0-9+/=]{48}", 0
FLAG_BATCHSIZE = 1000
FLAG_RATELIMIT = 5
# Do not submit generated flags to the live EnoFlagSink at pod startup.
LIVE_SELF_TEST = False

REQUEST_TIMEOUT = (3.05, 10)
SUBMISSION_TIMEOUT = 5
WELCOME_BANNER = (
    b"Welcome to the EnoEngine's EnoFlagSink\xe2\x84\xa2!\n"
    b"Please submit one flag per line. Responses are NOT guaranteed to be in chronological order.\n\n"
)


def _get_json(url: str) -> dict:
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return payload


def get_all_target_ips() -> list[str]:
    response = requests.get(OPPONENT_IPS_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    ips = set()
    for line in response.text.splitlines():
        address = line.strip()
        if not address:
            continue
        ipaddress.ip_address(address)
        if address != OWN_HOST:
            ips.add(address)
    return sorted(ips, key=ipaddress.ip_address)


def get_targets() -> dict[str, list[dict[str, str]]]:
    """Return attack-info targets for every service currently announced by ENOWARS."""
    payload = _get_json(ATTACK_INFO_URL)
    services = payload.get("services", {})
    if not isinstance(services, dict):
        raise ValueError("attack.json has no object-valued services field")

    targets = {}
    for service, service_targets in services.items():
        if not isinstance(service, str) or not isinstance(service_targets, dict):
            logging.warning("Ignoring malformed attack-info service entry: %r", service)
            continue
        targets[service] = [
            {
                "ip": address,
                "extra": json.dumps(attack_info, separators=(",", ":")),
            }
            for address, attack_info in service_targets.items()
            if isinstance(address, str) and address != OWN_HOST
        ]
    return targets


def get_fallback_targets(services: set[str]) -> dict[str, list[dict[str, str]]]:
    """Supply IP-only targets for exploit services without ENOWARS attack info."""
    ips = get_all_target_ips()
    return {
        service: [{"ip": address, "extra": "[]"} for address in ips]
        for service in services
    }


def _status_from_response(response: bytes) -> FlagStatus:
    if response.endswith(b" INV\n"):
        return FlagStatus.INVALID
    if response.endswith(b" OLD\n"):
        return FlagStatus.INACTIVE
    if response.endswith(b" OK\n"):
        return FlagStatus.OK
    if response.endswith(b" OWN\n"):
        return FlagStatus.OWNFLAG
    if response.endswith(b" DUP\n"):
        return FlagStatus.DUPLICATE
    logging.error("Unexpected EnoFlagSink response: %r", response)
    return FlagStatus.ERROR


def submit_flags(flags: list[str]) -> list[FlagStatus]:
    """Submit synchronously so every response belongs to the sole in-flight flag."""
    results: list[FlagStatus] = []
    server = None
    try:
        server = remote(FLAG_SUBMIT_HOST, FLAG_SUBMIT_PORT, timeout=SUBMISSION_TIMEOUT)
        server.recvuntil(WELCOME_BANNER, timeout=SUBMISSION_TIMEOUT)
        for flag in flags:
            server.sendline(flag.encode())
            results.append(_status_from_response(server.recvline(timeout=SUBMISSION_TIMEOUT)))
    except Exception:
        logging.exception("ENOWARS flag submission failed")
        results.extend(FlagStatus.ERROR for _ in flags[len(results):])
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:
                logging.warning("Failed to close the EnoFlagSink connection", exc_info=True)
    return results
