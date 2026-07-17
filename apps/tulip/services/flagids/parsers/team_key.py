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


def _values_for_key(data: Any, key: str) -> Iterable[Any]:
    if isinstance(data, dict):
        if key in data:
            yield data[key]
        for value in data.values():
            yield from _values_for_key(value, key)
    elif isinstance(data, list):
        for value in data:
            yield from _values_for_key(value, key)


def extract_flagids(payload: object, context: Mapping[str, str]) -> list[str]:
    team_key = context.get("TEAM_ID")
    if not team_key:
        raise ValueError("TEAM_ID is required by the team_key flag-ID parser")
    return sorted({flagid for value in _values_for_key(payload, team_key) for flagid in _leaf_strings(value)})
