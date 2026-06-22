from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import TextIO


class TeeWriter:
    """Replica writes para vários destinos (ex.: arquivo NFS + stdout do pod)."""

    def __init__(self, *targets: TextIO) -> None:
        self._targets = targets

    def write(self, data: str) -> int:
        for target in self._targets:
            try:
                target.write(data)
            except (OSError, ValueError):
                pass
        return len(data)

    def flush(self) -> None:
        for target in self._targets:
            try:
                target.flush()
            except (OSError, ValueError):
                pass


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


def _has_fileno(stream: object) -> bool:
    fileno = getattr(stream, "fileno", None)
    if not callable(fileno):
        return False
    try:
        fileno()
        return True
    except (OSError, ValueError):
        return False


def run_command_with_cancel(
    command: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout: object | None = None,
    should_cancel: Callable[[], bool] | None = None,
    poll_interval_sec: float = 1.0,
) -> int:
    """Executa um comando podendo cancelar via callback.

    Se `stdout` for um arquivo real (tem fileno), é passado direto ao processo
    filho. Se for um writer Python (ex.: TeeWriter, sem fileno), a saída é
    capturada via PIPE e replicada linha a linha.
    """
    use_pump = stdout is not None and not _has_fileno(stdout)

    popen_kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "stderr": subprocess.STDOUT,
    }
    if use_pump:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["text"] = True
        popen_kwargs["bufsize"] = 1
    else:
        popen_kwargs["stdout"] = stdout
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(command, **popen_kwargs)

    pump_thread: threading.Thread | None = None
    if use_pump:
        def _pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout.write(line)  # type: ignore[union-attr]
                stdout.flush()  # type: ignore[union-attr]

        pump_thread = threading.Thread(target=_pump, daemon=True)
        pump_thread.start()

    cancelled = False
    try:
        while proc.poll() is None:
            if should_cancel and should_cancel():
                cancelled = True
                terminate_process_tree(proc)
                break
            time.sleep(poll_interval_sec)
    finally:
        if proc.poll() is None:
            terminate_process_tree(proc)

    returncode = proc.wait()
    if pump_thread is not None:
        pump_thread.join(timeout=5)

    if cancelled:
        return 130
    return int(returncode or 0)
