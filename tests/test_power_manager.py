from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_power_manager():
    module_path = Path(__file__).resolve().parents[1] / "infra" / "power-manager" / "power_manager.py"
    spec = importlib.util.spec_from_file_location("power_manager", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pm = _load_power_manager()
GpuNode = pm.GpuNode
NodeUsageState = pm.NodeUsageState
effective_on_sec = pm.effective_on_sec
pick_shutdown_candidate = pm.pick_shutdown_candidate
pick_wake_candidate = pm.pick_wake_candidate


def _node(name: str) -> GpuNode:
    return GpuNode(
        name=name,
        mac="AA:BB:CC:DD:EE:00",
        broadcast="192.168.0.255",
        ssh_host=f"{name}.local",
        ssh_user="ubuntu",
    )


def test_pick_wake_candidate_prefers_lowest_total_on_sec() -> None:
    nodes = [_node("node_01"), _node("node_02"), _node("node_03")]
    ready_nodes = {"node_01"}
    usage = {
        "node_01": NodeUsageState(total_on_sec=50000.0),
        "node_02": NodeUsageState(total_on_sec=12000.0),
        "node_03": NodeUsageState(total_on_sec=8000.0),
    }

    picked = pick_wake_candidate(nodes, ready_nodes, usage, now=1000.0)

    assert picked is not None
    assert picked.name == "node_03"


def test_pick_wake_candidate_includes_active_session() -> None:
    nodes = [_node("node_01"), _node("node_02")]
    ready_nodes: set[str] = set()
    usage = {
        "node_01": NodeUsageState(total_on_sec=5000.0, ready_since=900.0),
        "node_02": NodeUsageState(total_on_sec=1000.0),
    }

    picked = pick_wake_candidate(nodes, ready_nodes, usage, now=1000.0)

    assert picked is not None
    assert picked.name == "node_02"


def test_pick_shutdown_candidate_prefers_highest_total_on_sec() -> None:
    nodes = [_node("node_01"), _node("node_02")]
    ready_nodes = {"node_01", "node_02"}
    idle_since = {"node_01": 0.0, "node_02": 0.0}
    usage = {
        "node_01": NodeUsageState(total_on_sec=90000.0),
        "node_02": NodeUsageState(total_on_sec=10000.0),
    }

    picked = pick_shutdown_candidate(
        nodes,
        ready_nodes,
        idle_since,
        usage,
        now=1000.0,
        idle_shutdown_after_sec=900,
    )

    assert picked is not None
    assert picked.name == "node_01"


def test_effective_on_sec_adds_open_ready_session() -> None:
    state = NodeUsageState(total_on_sec=100.0, ready_since=50.0)

    assert effective_on_sec(state, 80.0) == 130.0
