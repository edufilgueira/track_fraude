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


@dataclass
class NodeUsageState:
    total_on_sec: float = 0.0
    ready_since: float | None = None


def effective_on_sec(state: NodeUsageState, now: float) -> float:
    total = state.total_on_sec
    if state.ready_since is not None:
        total += now - state.ready_since
    return total


def pick_wake_candidate(
    nodes: list[GpuNode],
    ready_nodes: set[str],
    usage: dict[str, NodeUsageState],
    now: float,
) -> GpuNode | None:
    offline = [node for node in nodes if node.name not in ready_nodes]
    if not offline:
        return None
    return min(offline, key=lambda node: effective_on_sec(usage[node.name], now))


def pick_shutdown_candidate(
    nodes: list[GpuNode],
    ready_nodes: set[str],
    idle_since: dict[str, float],
    usage: dict[str, NodeUsageState],
    now: float,
    idle_shutdown_after_sec: int,
) -> GpuNode | None:
    candidates: list[GpuNode] = []
    for node in nodes:
        if node.name not in ready_nodes:
            continue
        started = idle_since.get(node.name)
        if started is None:
            continue
        if now - started < idle_shutdown_after_sec:
            continue
        candidates.append(node)
    if not candidates:
        return None
    return max(candidates, key=lambda node: effective_on_sec(usage[node.name], now))


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _state_path(config: dict, config_path: Path) -> Path:
    raw = config.get("state_file")
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else config_path.parent / path
    return config_path.parent / "power_state.json"


def _load_usage(path: Path, node_names: list[str]) -> dict[str, NodeUsageState]:
    if not path.exists():
        return {name: NodeUsageState() for name in node_names}
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    usage: dict[str, NodeUsageState] = {}
    for name in node_names:
        item = raw.get(name, {})
        usage[name] = NodeUsageState(
            total_on_sec=float(item.get("total_on_sec", 0.0)),
            ready_since=None,
        )
    return usage


def _save_usage(path: Path, usage: dict[str, NodeUsageState]) -> None:
    payload = {
        name: {"total_on_sec": round(state.total_on_sec, 3)}
        for name, state in sorted(usage.items())
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sync_usage(
    usage: dict[str, NodeUsageState],
    ready_nodes: set[str],
    configured_names: set[str],
    now: float,
) -> None:
    for name in configured_names:
        state = usage[name]
        is_ready = name in ready_nodes
        if is_ready and state.ready_since is None:
            state.ready_since = now
        elif not is_ready and state.ready_since is not None:
            state.total_on_sec += now - state.ready_since
            state.ready_since = None


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


def _kubectl_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kubectl falhou")
    return json.loads(result.stdout)


def _active_worker_nodes(config: dict) -> set[str]:
    payload = _kubectl_json(
        [
            "-n",
            config["namespace"],
            "get",
            "pods",
            "-l",
            config["worker_label_selector"],
        ]
    )
    nodes: set[str] = set()
    for item in payload.get("items", []):
        phase = item.get("status", {}).get("phase")
        node_name = item.get("spec", {}).get("nodeName")
        if phase in {"Pending", "Running"} and node_name:
            nodes.add(str(node_name))
    return nodes


def _pending_worker_pods(config: dict) -> int:
    payload = _kubectl_json(
        [
            "-n",
            config["namespace"],
            "get",
            "pods",
            "-l",
            config["worker_label_selector"],
        ]
    )
    count = 0
    for item in payload.get("items", []):
        phase = item.get("status", {}).get("phase")
        if phase == "Pending":
            count += 1
    return count


def _known_ready_nodes() -> set[str]:
    try:
        payload = _kubectl_json(["get", "nodes"])
    except RuntimeError:
        return set()
    ready: set[str] = set()
    for item in payload.get("items", []):
        name = item.get("metadata", {}).get("name")
        conditions = item.get("status", {}).get("conditions", [])
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            ready.add(str(name))
    return ready


def _gpu_stats(configured_names: set[str]) -> tuple[int, int]:
    """Retorna (gpus_livres, gpus_alocáveis) nos nodes configurados Ready."""
    try:
        payload = _kubectl_json(["get", "nodes"])
    except RuntimeError:
        return 0, 0

    allocatable_by_node: dict[str, int] = {}
    for item in payload.get("items", []):
        name = item.get("metadata", {}).get("name")
        if name not in configured_names:
            continue
        conditions = item.get("status", {}).get("conditions", [])
        if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            continue
        allocatable = item.get("status", {}).get("allocatable", {})
        try:
            allocatable_by_node[str(name)] = int(allocatable.get("nvidia.com/gpu", 0))
        except (TypeError, ValueError):
            allocatable_by_node[str(name)] = 0

    allocated_by_node = {name: 0 for name in allocatable_by_node}
    try:
        pods_payload = _kubectl_json(["get", "pods", "-A"])
    except RuntimeError:
        pods_payload = {"items": []}

    for item in pods_payload.get("items", []):
        node_name = item.get("spec", {}).get("nodeName")
        if node_name not in allocated_by_node:
            continue
        phase = item.get("status", {}).get("phase")
        if phase not in {"Pending", "Running"}:
            continue
        for container in item.get("spec", {}).get("containers", []):
            limits = container.get("resources", {}).get("limits", {})
            try:
                allocated_by_node[node_name] += int(limits.get("nvidia.com/gpu", 0))
            except (TypeError, ValueError):
                continue

    total_allocatable = sum(allocatable_by_node.values())
    total_allocated = sum(allocated_by_node.values())
    return max(total_allocatable - total_allocated, 0), total_allocatable


def _needs_wake(
    *,
    queue_messages: int,
    free_gpus: int,
    pending_workers: int,
    offline_nodes: list[GpuNode],
) -> bool:
    if queue_messages <= 0 or not offline_nodes:
        return False
    if free_gpus <= 0:
        return True
    if pending_workers > 0:
        return True
    return queue_messages > free_gpus


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


def run_cycle(
    *,
    nodes: list[GpuNode],
    config: dict,
    usage: dict[str, NodeUsageState],
    idle_since: dict[str, float],
    now: float,
    queue_messages: int | None = None,
    ready_nodes: set[str] | None = None,
    active_nodes: set[str] | None = None,
    free_gpus: int | None = None,
    pending_workers: int | None = None,
) -> None:
    configured_names = {node.name for node in nodes}
    if queue_messages is None:
        queue_messages = _rabbitmq_messages(config)
    if ready_nodes is None:
        ready_nodes = _known_ready_nodes()
    if active_nodes is None:
        active_nodes = _active_worker_nodes(config)
    if free_gpus is None or pending_workers is None:
        computed_free, _ = _gpu_stats(configured_names & ready_nodes)
        if free_gpus is None:
            free_gpus = computed_free
        if pending_workers is None:
            pending_workers = _pending_worker_pods(config)

    _sync_usage(usage, ready_nodes, configured_names, now)

    offline_nodes = [node for node in nodes if node.name not in ready_nodes]
    wake_target = None
    if _needs_wake(
        queue_messages=queue_messages,
        free_gpus=free_gpus,
        pending_workers=pending_workers,
        offline_nodes=offline_nodes,
    ):
        wake_target = pick_wake_candidate(nodes, ready_nodes, usage, now)

    if wake_target is not None:
        on_sec = effective_on_sec(usage[wake_target.name], now)
        print(
            f"wake {wake_target.name}: queue={queue_messages} "
            f"free_gpus={free_gpus} pending_workers={pending_workers} "
            f"total_on_sec={on_sec:.0f}",
            flush=True,
        )
        _wake(wake_target)

    for node in nodes:
        if node.name not in ready_nodes:
            idle_since.pop(node.name, None)
            continue
        if queue_messages > 0 or node.name in active_nodes:
            idle_since.pop(node.name, None)
            continue
        idle_since.setdefault(node.name, now)

    shutdown_target = pick_shutdown_candidate(
        nodes,
        ready_nodes,
        idle_since,
        usage,
        now,
        int(config["idle_shutdown_after_sec"]),
    )
    if shutdown_target is not None:
        idle_for = now - idle_since[shutdown_target.name]
        on_sec = effective_on_sec(usage[shutdown_target.name], now)
        print(
            f"shutdown {shutdown_target.name}: idle_for={idle_for:.0f}s "
            f"total_on_sec={on_sec:.0f}",
            flush=True,
        )
        _shutdown(shutdown_target)
        idle_since.pop(shutdown_target.name, None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Power manager dos nós GPU.")
    parser.add_argument("--config", default="infra/power-manager/config.example.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = _load_config(config_path)
    nodes = [GpuNode(**item) for item in config["nodes"]]
    node_names = [node.name for node in nodes]
    state_path = _state_path(config, config_path)
    usage = _load_usage(state_path, node_names)
    idle_since: dict[str, float] = {}

    while True:
        try:
            run_cycle(
                nodes=nodes,
                config=config,
                usage=usage,
                idle_since=idle_since,
                now=time.monotonic(),
            )
            _save_usage(state_path, usage)
        except Exception as exc:
            print(f"power-manager error: {exc}", flush=True)
        time.sleep(int(config["poll_interval_sec"]))


if __name__ == "__main__":
    main()
