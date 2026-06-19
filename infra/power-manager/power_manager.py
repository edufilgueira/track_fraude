#!/usr/bin/env python3
"""Liga/desliga nós GPU bare-metal conforme fila e pods ativos."""

from __future__ import annotations

import argparse
import base64
import json
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GpuNode:
    name: str
    mac: str
    broadcast: str
    ssh_host: str
    ssh_user: str


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _rabbitmq_messages(config: dict) -> int:
    token = base64.b64encode(
        f"{config['rabbitmq_username']}:{config['rabbitmq_password']}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        config["rabbitmq_api_url"],
        headers={"Authorization": f"Basic {token}"},
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return int(payload.get("messages_ready", 0)) + int(payload.get("messages_unacknowledged", 0))


def _active_worker_nodes(config: dict) -> set[str]:
    command = [
        "kubectl",
        "-n",
        config["namespace"],
        "get",
        "pods",
        "-l",
        config["worker_label_selector"],
        "-o",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kubectl get pods falhou")
    payload = json.loads(result.stdout)
    nodes: set[str] = set()
    for item in payload.get("items", []):
        phase = item.get("status", {}).get("phase")
        node_name = item.get("spec", {}).get("nodeName")
        if phase in {"Pending", "Running"} and node_name:
            nodes.add(str(node_name))
    return nodes


def _known_ready_nodes() -> set[str]:
    result = subprocess.run(
        ["kubectl", "get", "nodes", "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    payload = json.loads(result.stdout)
    ready: set[str] = set()
    for item in payload.get("items", []):
        name = item.get("metadata", {}).get("name")
        conditions = item.get("status", {}).get("conditions", [])
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            ready.add(str(name))
    return ready


def _wake(node: GpuNode) -> None:
    mac_bytes = bytes.fromhex(node.mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (node.broadcast, 9))


def _shutdown(node: GpuNode) -> None:
    subprocess.run(
        ["kubectl", "drain", node.name, "--ignore-daemonsets", "--delete-emptydir-data"],
        check=False,
    )
    subprocess.run(
        [
            "ssh",
            f"{node.ssh_user}@{node.ssh_host}",
            "sudo shutdown -h now",
        ],
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Power manager dos nós GPU.")
    parser.add_argument("--config", default="infra/power-manager/config.example.json")
    args = parser.parse_args()

    config = _load_config(Path(args.config))
    nodes = [GpuNode(**item) for item in config["nodes"]]
    idle_since: dict[str, float] = {}

    while True:
        queue_messages = _rabbitmq_messages(config)
        ready_nodes = _known_ready_nodes()
        active_nodes = _active_worker_nodes(config)

        if queue_messages > 0:
            for node in nodes:
                if node.name not in ready_nodes:
                    print(f"wake {node.name}: queue={queue_messages}", flush=True)
                    _wake(node)
                    break

        now = time.monotonic()
        for node in nodes:
            if node.name not in ready_nodes:
                idle_since.pop(node.name, None)
                continue
            if queue_messages > 0 or node.name in active_nodes:
                idle_since.pop(node.name, None)
                continue
            idle_since.setdefault(node.name, now)
            idle_for = now - idle_since[node.name]
            if idle_for >= int(config["idle_shutdown_after_sec"]):
                print(f"shutdown {node.name}: idle_for={idle_for:.0f}s", flush=True)
                _shutdown(node)
                idle_since.pop(node.name, None)

        time.sleep(int(config["poll_interval_sec"]))


if __name__ == "__main__":
    main()
