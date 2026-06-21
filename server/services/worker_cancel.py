from __future__ import annotations

import logging
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_SA_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
_SA_CA = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
_K8S_HOST = "https://kubernetes.default.svc"
_DEFAULT_NAMESPACE = "track-fraude"


def delete_worker_pod(
    pod_name: str | None,
    *,
    namespace: str = _DEFAULT_NAMESPACE,
) -> bool:
    """Remove o pod worker em execução (KEDA job). Best-effort."""
    name = (pod_name or "").strip()
    if not name:
        return False

    if _delete_pod_in_cluster(name, namespace=namespace):
        return True
    return _delete_pod_kubectl(name, namespace=namespace)


def _delete_pod_in_cluster(pod_name: str, *, namespace: str) -> bool:
    if not _SA_TOKEN.is_file():
        return False
    token = _SA_TOKEN.read_text(encoding="utf-8").strip()
    url = f"{_K8S_HOST}/api/v1/namespaces/{namespace}/pods/{pod_name}"
    request = urllib.request.Request(
        url,
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
    )
    context = None
    if _SA_CA.is_file():
        context = ssl.create_default_context(cafile=str(_SA_CA))
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            body = response.read().decode("utf-8", errors="replace")
            logger.info("pod %s removido via API K8s: %s", pod_name, body[:200])
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("pod %s já não existe", pod_name)
            return True
        logger.warning("falha ao remover pod %s: HTTP %s", pod_name, exc.code)
    except OSError as exc:
        logger.warning("falha ao contactar API K8s para pod %s: %s", pod_name, exc)
    return False


def _delete_pod_kubectl(pod_name: str, *, namespace: str) -> bool:
    try:
        result = subprocess.run(
            [
                "kubectl",
                "delete",
                "pod",
                pod_name,
                "-n",
                namespace,
                "--grace-period=0",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("kubectl indisponível para cancelar pod: %s", exc)
        return False
    if result.returncode == 0:
        return True
    combined = f"{result.stdout}\n{result.stderr}".strip()
    if "NotFound" in combined or "not found" in combined.lower():
        return True
    logger.warning("kubectl delete pod falhou: %s", combined[:300])
    return False
