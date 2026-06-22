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


def _job_name_from_pod(pod_name: str) -> str:
    """KEDA cria pod `<job>-<sufixo>`; remove o último segmento para obter o Job."""
    return pod_name.rsplit("-", 1)[0] if "-" in pod_name else pod_name


def stop_worker(
    pod_name: str | None,
    *,
    job_name: str | None = None,
    namespace: str = _DEFAULT_NAMESPACE,
) -> bool:
    """Para o worker: deleta o Job (cascade → pod). Fallback: deleta só o pod.

    Deletar o Job é essencial — apagar só o pod faz o ScaledJob recriar outro.
    """
    pod = (pod_name or "").strip()
    hint = (job_name or "").strip()

    # Mapeamento confiável: pod `<job>-<sufixo>` → Job. O job_id do banco pode ser
    # um UUID do Atlas, então só o usamos se parecer um Job do worker.
    candidates: list[str] = []
    if pod:
        candidates.append(_job_name_from_pod(pod))
    if hint and hint.startswith("track-fraude-worker") and hint not in candidates:
        candidates.append(hint)

    deleted = False
    for job in candidates:
        if _delete_job(job, namespace=namespace):
            deleted = True

    # Garante o pod fora mesmo que o nome do Job não bata.
    if pod:
        _delete_pod(pod, namespace=namespace)

    return deleted or bool(pod)


# Compat: chamadas antigas.
def delete_worker_pod(pod_name: str | None, *, namespace: str = _DEFAULT_NAMESPACE) -> bool:
    return stop_worker(pod_name, namespace=namespace)


def _sa_request(url: str, *, method: str) -> bool:
    if not _SA_TOKEN.is_file():
        return False
    token = _SA_TOKEN.read_text(encoding="utf-8").strip()
    request = urllib.request.Request(
        url,
        method=method,
        headers={"Authorization": f"Bearer {token}"},
    )
    context = None
    if _SA_CA.is_file():
        context = ssl.create_default_context(cafile=str(_SA_CA))
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            response.read()
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True
        logger.warning("K8s API %s %s → HTTP %s", method, url, exc.code)
    except OSError as exc:
        logger.warning("falha ao contactar API K8s (%s): %s", url, exc)
    return False


def _delete_job(job_name: str, *, namespace: str) -> bool:
    # propagationPolicy=Background remove os pods filhos junto.
    url = (
        f"{_K8S_HOST}/apis/batch/v1/namespaces/{namespace}/jobs/{job_name}"
        "?propagationPolicy=Background"
    )
    if _sa_request(url, method="DELETE"):
        logger.info("job %s removido (stop)", job_name)
        return True
    return _kubectl_delete("job", job_name, namespace=namespace)


def _delete_pod(pod_name: str, *, namespace: str) -> bool:
    url = f"{_K8S_HOST}/api/v1/namespaces/{namespace}/pods/{pod_name}"
    if _sa_request(url, method="DELETE"):
        return True
    return _kubectl_delete("pod", pod_name, namespace=namespace)


def _kubectl_delete(kind: str, name: str, *, namespace: str) -> bool:
    try:
        result = subprocess.run(
            [
                "kubectl",
                "delete",
                kind,
                name,
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
        logger.debug("kubectl indisponível para deletar %s/%s: %s", kind, name, exc)
        return False
    if result.returncode == 0:
        return True
    combined = f"{result.stdout}\n{result.stderr}".strip()
    if "NotFound" in combined or "not found" in combined.lower():
        return True
    logger.warning("kubectl delete %s %s falhou: %s", kind, name, combined[:300])
    return False
