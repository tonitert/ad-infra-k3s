from collections.abc import Iterable, Mapping
from typing import Any


def _leaf_strings(data: Any) -> Iterable[str]:
    if isinstance(data, dict):
        for value in data.values():
            yield from _leaf_strings(value)
    elif isinstance(data, list):
        for value in data:
            yield from _leaf_strings(value)
    elif isinstance(data, str) and data:
        yield data


def extract_flagids(payload: object, context: Mapping[str, str]) -> list[str]:
    team_address = context.get("TEAM_ADDRESS")
    if not team_address:
        raise ValueError("TEAM_ADDRESS is required by the ENOWARS flag-ID parser")
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), dict):
        raise ValueError("ENOWARS attack.json has no object-valued services field")

    flagids = set()
    for service_data in payload["services"].values():
        if isinstance(service_data, dict) and team_address in service_data:
            flagids.update(_leaf_strings(service_data[team_address]))
    return sorted(flagids)
