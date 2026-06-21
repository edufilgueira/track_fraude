O console do botão **Play** lê o **mesmo arquivo** no NFS (`/app/data/logs/pipeline_*.log`) via poll — deve mostrar a mesma saída que `kubectl logs`. O worker grava stdout **no arquivo e no pod** (tee).

**Cancelar (botão pause):** marca o run como `cancelled` no Postgres, escreve no log e remove o pod worker (`worker_id`) via API K8s. Requer `kubectl apply -f infra/k8s/server-rbac.yaml` e restart do server.

## Durante ou logo após o Play (ctrl-p01)

```bash
POD=$(kubectl get pods -n track-fraude -l job-name \
  --sort-by=.metadata.creationTimestamp \
  -o jsonpath='{.items[-1].metadata.name}')
kubectl logs -n track-fraude "$POD" -f --tail=50
# em outro terminal:
tail -f /srv/track_fraude/data/logs/pipeline_*.log

# Pod mais recente (Running, Completed ou Error)
POD=$(kubectl get pods -n track-fraude -l job-name \
  --sort-by=.metadata.creationTimestamp \
  -o jsonpath='{.items[-1].metadata.name}')

kubectl logs -n track-fraude "$POD" --tail=200
```

Seguir em tempo real (enquanto `Running`):

```bash
kubectl logs -n track-fraude "$POD" -f --tail=50
```

Se o pod já sumiu, liste e pegue o nome:

```bash
kubectl get pods -n track-fraude -l job-name --sort-by=.metadata.creationTimestamp
kubectl logs -n track-fraude track-fraude-worker-XXXXX-yyyyy --tail=200
```

---

## Arquivo no NFS (o que o painel lê)

```bash
ls -lt /srv/track_fraude/data/logs/pipeline_1_2026-05-22*.log | head -3
tail -f /srv/track_fraude/data/logs/pipeline_1_2026-05-22_20260621-204953.log
```

O worker grava stdout/stderr de `run_daily_pipeline.py` neste arquivo. Se o arquivo parar em `pipeline enfileirado` / `retirado da fila`, faça **rebuild e push** da imagem worker (e restart do server se o JS mudou):

```bash
docker build -f Dockerfile.worker -t 192.168.0.199:5000/track-fraude-worker:latest .
docker build -f Dockerfile.server -t 192.168.0.199:5000/track-fraude-server:latest .
docker push 192.168.0.199:5000/track-fraude-worker:latest
docker push 192.168.0.199:5000/track-fraude-server:latest
kubectl rollout restart deployment/track-fraude-server -n track-fraude
# no node-01, se IfNotPresent: sudo k3s crictl rmi 192.168.0.199:5000/track-fraude-worker:latest
```

Compare lado a lado:

```bash
tail -f /srv/track_fraude/data/logs/pipeline_*.log
kubectl logs -n track-fraude "$POD" -f --tail=50
```

---

## Resumo

| O quê | Comando / onde |
|--------|----------------|
| **Log original (kubectl)** | `kubectl logs -n track-fraude <pod-worker> --tail=200` |
| Ao vivo (kubectl) | `kubectl logs -n track-fraude <pod-worker> -f` |
| **Console Play (painel)** | Poll em `/api/pipeline/stores/{id}/log` → mesmo NFS |
| Cópia no host | `tail -f /srv/track_fraude/data/logs/pipeline_*.log` |

**Não use** `-l job-name -f` com vários jobs — mistura saídas. Use **um pod** pelo nome.
