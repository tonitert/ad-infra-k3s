#!/usr/bin/env python3
import importlib.util
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import psycopg_pool
import requests


DELAY_SECONDS = 5
REQUEST_TIMEOUT = (3.05, 10)


def load_parser(name: str) -> Callable[[object, Mapping[str, str]], list[str]]:
    if not name.isidentifier():
        raise ValueError("FLAGID_PARSER must be a Python identifier")

    parser_path = Path(__file__).with_name("parsers") / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"flagid_parser_{name}", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load flag-ID parser {name!r}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = getattr(module, "extract_flagids", None)
    if not callable(parser):
        raise RuntimeError(f"Flag-ID parser {name!r} must define extract_flagids")
    return parser


def update_flagids(
    db: psycopg_pool.ConnectionPool,
    endpoint: str,
    parser: Callable[[object, Mapping[str, str]], list[str]],
    context: Mapping[str, str],
) -> int:
    response = requests.get(endpoint, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    flagids = parser(response.json(), context)

    with db.connection() as conn:
        with conn.cursor() as cur:
            # Replacing the cache keeps it aligned with the parser's current
            # validity window and prevents old IDs accumulating.
            cur.execute("DELETE FROM flag_id")
            if flagids:
                cur.executemany(
                    "INSERT INTO flag_id (content) VALUES (%s)",
                    [(flagid,) for flagid in flagids],
                )
        conn.commit()
    return len(flagids)


def parse_start_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def seconds_until_next_scrape(now: float, start: float, tick_length: float) -> float:
    first_scrape = start + DELAY_SECONDS
    if now < first_scrape:
        return first_scrape - now
    elapsed_since_first_scrape = now - first_scrape
    next_scrape = first_scrape + (int(elapsed_since_first_scrape // tick_length) + 1) * tick_length
    return max(1.0, next_scrape - now)


def main() -> None:
    enabled = os.getenv("FLAGID_SCRAPE", "") not in {"", "0", "false", "False"}
    if not enabled:
        print("FLAGID SCRAPE DISABLED", flush=True)
        while True:
            time.sleep(60)

    tick_length_ms = int(os.getenv("TICK_LENGTH", "60000"))
    if tick_length_ms <= 0:
        raise ValueError("TICK_LENGTH must be positive")
    tick_length = tick_length_ms / 1000
    start = parse_start_time(os.environ["TICK_START"])
    endpoint = os.environ["FLAGID_ENDPOINT"]
    parser_name = os.getenv("FLAGID_PARSER", "team_key")
    parser = load_parser(parser_name)
    db = psycopg_pool.ConnectionPool(os.environ["TIMESCALE"])

    print(
        f"Starting flag-ID scraper with parser {parser_name}; "
        f"tick={tick_length}s endpoint={endpoint}",
        flush=True,
    )
    while True:
        now = time.time()
        try:
            if now >= start:
                count = update_flagids(db, endpoint, parser, os.environ)
                print(f"Updated flag IDs ({count})", flush=True)
        except Exception:
            print("Unable to update flag IDs", flush=True)
            import traceback
            traceback.print_exc()

        time.sleep(seconds_until_next_scrape(time.time(), start, tick_length))


if __name__ == "__main__":
    main()
