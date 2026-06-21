from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from typing import TextIO


class TeeWriter:
    """Replica writes para vários destinos (ex.: arquivo NFS + stdout do pod)."""

    def __init__(self, *targets: TextIO) -> None:
        self._targets = targets

    def write(self, data: str) -> int:
        for target in self._targets:
            target.write(data)
        return len(data)

    def flush(self) -> None:
        for target in self._targets:
            target.flush()


def terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def run_command_with_cancel(
    command: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout: TextIO | None = None,
    should_cancel: Callable[[], bool] | None = None,
    poll_interval_sec: float = 1.0,
) -> int:
    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "stdout": stdout,
        "stderr": subprocess.STDOUT,
        "check": False,
    }
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(command, **kwargs)
    try:
        while proc.poll() is None:
            if should_cancel and should_cancel():
                terminate_process_tree(proc)
                return 130
            time.sleep(poll_interval_sec)
        return int(proc.returncode or 0)
    finally:
        if proc.poll() is None:
            terminate_process_tree(proc)
