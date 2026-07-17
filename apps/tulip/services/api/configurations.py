#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of Flower.
#
# Copyright ©2018 Nicolò Mazzucato
# Copyright ©2018 Antonio Groza
# Copyright ©2018 Brunello Simone
# Copyright ©2018 Alessio Marotta
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# Flower is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Flower is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Flower.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
from pathlib import Path

traffic_dir = Path(os.getenv("TULIP_TRAFFIC_DIR", "/traffic"))
dump_pcaps_dir = Path(os.getenv("DUMP_PCAPS", "/traffic"))
tick_length = int(os.getenv("TICK_LENGTH", "60000"))
flag_lifetime = int(os.getenv("FLAG_LIFETIME", "-1"))
start_date = os.getenv("TICK_START", "2026-07-18T12:00:00Z")
flag_regex = os.getenv("FLAG_REGEX", r"ENO[A-Za-z0-9+/=]{48}")
vm_ip = os.getenv("VM_IP", "10.1.15.1")
visualizer_url = os.getenv("VISUALIZER_URL", "http://127.0.0.1:1337")


def _load_services() -> list[dict[str, object]]:
    raw_services = os.getenv("TULIP_SERVICES", "[]")
    try:
        configured_services = json.loads(raw_services)
    except json.JSONDecodeError as exc:
        raise RuntimeError("TULIP_SERVICES must contain a JSON array") from exc
    if not isinstance(configured_services, list):
        raise RuntimeError("TULIP_SERVICES must contain a JSON array")

    services = []
    for service in configured_services:
        if not isinstance(service, dict):
            raise RuntimeError("Every TULIP_SERVICES entry must be an object")
        ip, port, name = service.get("ip"), service.get("port"), service.get("name")
        if not isinstance(ip, str) or not isinstance(port, int) or not isinstance(name, str):
            raise RuntimeError("TULIP_SERVICES entries require string ip/name and integer port")
        services.append({"ip": ip, "port": port, "name": name})

    if not any(service["port"] == -1 for service in services):
        services.append({"ip": vm_ip, "port": -1, "name": "other"})
    return services


services = _load_services()
