#!/usr/bin/env python3
import argparse
import ipaddress
import os
import random
import socket
import struct
import time
from pathlib import Path


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def ipv4_packet(src: str, dst: str, payload: bytes, ident: int) -> bytes:
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(payload),
        ident & 0xFFFF,
        0x4000,
        64,
        socket.IPPROTO_TCP,
        0,
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    return header[:10] + struct.pack("!H", checksum(header)) + header[12:] + payload


def tcp_segment(
    src_ip: str,
    dst_ip: str,
    sport: int,
    dport: int,
    seq: int,
    ack: int,
    flags: int,
    payload: bytes = b"",
) -> bytes:
    header = struct.pack(
        "!HHIIBBHHH",
        sport,
        dport,
        seq & 0xFFFFFFFF,
        ack & 0xFFFFFFFF,
        5 << 4,
        flags,
        64240,
        0,
        0,
    )
    pseudo = (
        socket.inet_aton(src_ip)
        + socket.inet_aton(dst_ip)
        + struct.pack("!BBH", 0, socket.IPPROTO_TCP, len(header) + len(payload))
    )
    tcp_sum = checksum(pseudo + header + payload)
    return header[:16] + struct.pack("!H", tcp_sum) + header[18:] + payload


def ethernet_frame(src_ip: str, dst_ip: str, tcp: bytes, ident: int) -> bytes:
    eth_dst = b"\x02\x00\x00\x00\x00\x01"
    eth_src = b"\x02\x00\x00\x00\x00\x02"
    return eth_dst + eth_src + struct.pack("!H", 0x0800) + ipv4_packet(src_ip, dst_ip, tcp, ident)


def pcap_write_packet(fh, ts: float, packet: bytes) -> None:
    sec = int(ts)
    usec = int((ts - sec) * 1_000_000)
    fh.write(struct.pack("<IIII", sec, usec, len(packet), len(packet)))
    fh.write(packet)


def http_request(i: int, src_ip: str, dst_ip: str, dport: int) -> bytes:
    methods = ("GET", "POST", "PUT", "DELETE")
    agents = ("curl/8.8.0", "python-requests/2.32", "Mozilla/5.0", "Go-http-client/1.1", "pwntools")
    paths = ("/", "/login", "/api/items", "/api/submit", "/static/app.js", "/search")
    method = methods[i % len(methods)]
    path = paths[i % len(paths)]
    query = f"?team={i % 64}&nonce={random.randrange(1 << 30):08x}"
    body = b""

    if method in {"POST", "PUT"}:
        body = (
            "{"
            f"\"user\":\"team{i % 64}\","
            f"\"password\":\"pw-{random.randrange(1 << 32):08x}\","
            f"\"flag\":\"SAAR{{{random.randrange(1 << 128):032x}}}\""
            "}"
        ).encode()

    headers = [
        f"{method} {path}{query} HTTP/1.1",
        f"Host: {dst_ip}:{dport}",
        f"User-Agent: {agents[i % len(agents)]}",
        f"X-Forwarded-For: {src_ip}",
        f"Cookie: session={random.randrange(1 << 64):016x}; team={i % 64}",
        "Accept: */*",
        "Connection: close",
        f"Content-Length: {len(body)}",
        "Content-Type: application/json",
        "",
        "",
    ]
    return "\r\n".join(headers).encode() + body


def http_response(i: int) -> bytes:
    bodies = [
        f"ok {i}\n",
        f"<html><body>request {i}</body></html>\n",
        f"{{\"status\":\"ok\",\"request\":{i},\"token\":\"{random.randrange(1 << 64):016x}\"}}\n",
    ]
    body = bodies[i % len(bodies)].encode()
    headers = [
        "HTTP/1.1 200 OK",
        "Server: tulip-stress",
        "Content-Type: text/plain",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode() + body


def packet_sequence(i: int, ts: float, src_ip: str, dst_ip: str, sport: int, dport: int):
    client_seq = random.randrange(1 << 31)
    server_seq = random.randrange(1 << 31)
    req = http_request(i, src_ip, dst_ip, dport)
    resp = http_response(i)
    packets = [
        (0.0000, src_ip, dst_ip, sport, dport, client_seq, 0, 0x02, b""),
        (0.0004, dst_ip, src_ip, dport, sport, server_seq, client_seq + 1, 0x12, b""),
        (0.0008, src_ip, dst_ip, sport, dport, client_seq + 1, server_seq + 1, 0x10, b""),
        (0.0012, src_ip, dst_ip, sport, dport, client_seq + 1, server_seq + 1, 0x18, req),
        (0.0018, dst_ip, src_ip, dport, sport, server_seq + 1, client_seq + 1 + len(req), 0x18, resp),
        (0.0022, src_ip, dst_ip, sport, dport, client_seq + 1 + len(req), server_seq + 1 + len(resp), 0x11, b""),
        (0.0026, dst_ip, src_ip, dport, sport, server_seq + 1 + len(resp), client_seq + 2 + len(req), 0x11, b""),
    ]
    for offset, sip, dip, sp, dp, seq, ack, flags, payload in packets:
        tcp = tcp_segment(sip, dip, sp, dp, seq, ack, flags, payload)
        yield ts + offset, ethernet_frame(sip, dip, tcp, i)


def usable_hosts(network: ipaddress._BaseNetwork) -> tuple[int, int]:
    first = int(network.network_address)
    last = int(network.broadcast_address)
    if network.num_addresses > 2:
        first += 1
        last -= 1
    return first, max(1, last - first + 1)


def parse_ports(raw_ports: str) -> list[int]:
    ports = [int(port) for port in raw_ports.split(",") if port]
    if not ports or any(port < 1 or port > 65535 for port in ports):
        raise ValueError("--ports must contain one or more TCP ports in 1..65535")
    return ports


def generate_pcaps(
    *,
    rps: int,
    ports: list[int],
    duration: int,
    rotate_seconds: int,
    dst_ip: str,
    src_cidr: str,
    output_dir: Path,
) -> None:
    socket.inet_aton(dst_ip)
    network = ipaddress.ip_network(src_cidr, strict=False)
    host_first, host_count = usable_hosts(network)
    output_dir.mkdir(parents=True, exist_ok=True)

    random.seed()
    started = time.time()
    segment = 0
    generated_requests = 0

    while True:
        elapsed = time.time() - started
        if duration and elapsed >= duration:
            break

        segment_seconds = rotate_seconds
        if duration:
            segment_seconds = max(1, min(segment_seconds, int(duration - elapsed + 0.999999)))
        request_count = rps * segment_seconds
        segment_start = time.time()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(segment_start))
        final_path = output_dir / f"tulip-stress-{stamp}-rps{rps}-seg{segment:06d}.pcap"
        tmp_path = final_path.with_suffix(".pcap.tmp")

        with tmp_path.open("wb") as fh:
            fh.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1))
            for j in range(request_count):
                i = generated_requests + j
                src_ip = str(ipaddress.ip_address(host_first + (i % host_count)))
                sport = 1024 + (i % 60000)
                dport = ports[i % len(ports)]
                ts = segment_start + (j / rps)
                for packet_ts, packet in packet_sequence(i, ts, src_ip, dst_ip, sport, dport):
                    pcap_write_packet(fh, packet_ts, packet)

        os.replace(tmp_path, final_path)
        print(f"created {final_path} requests={request_count} ports={','.join(map(str, ports))}", flush=True)

        generated_requests += request_count
        segment += 1
        if duration and time.time() - started >= duration:
            break
        sleep_until = segment_start + segment_seconds
        while time.time() < sleep_until:
            time.sleep(min(1.0, sleep_until - time.time()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic HTTP PCAPs for Tulip stress tests.")
    parser.add_argument("--rps", type=int, required=True)
    parser.add_argument("--ports", required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--rotate-seconds", type=int, required=True)
    parser.add_argument("--dst-ip", required=True)
    parser.add_argument("--src-cidr", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    generate_pcaps(
        rps=args.rps,
        ports=parse_ports(args.ports),
        duration=args.duration,
        rotate_seconds=args.rotate_seconds,
        dst_ip=args.dst_ip,
        src_cidr=args.src_cidr,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
