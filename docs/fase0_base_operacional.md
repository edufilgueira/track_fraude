# Fase 0 — Base operacional

Objetivo: cluster estável; fila `track_fraude` funciona de ponta a ponta; **job enfileirado completa com a UI desligada**.

Relacionado: [plano_execucao.md](../plano_execucao.md), [config_control_plane.md](config_control_plane.md).

---

## Entregas

| # | Entrega | Status | Como validar |
|---|---------|--------|--------------|
| 0.1 | Control plane (registry, RabbitMQ, Postgres, K3s) | Operacional no ctrlp01 | `docker compose -f docker-compose.infra.yml ps` |
| 0.2 | Worker GPU via ScaledJob | Manifest em `infra/k8s/worker-scaledjob.yaml` | `kubectl get scaledjob -n track-fraude` |
| 0.3 | Sync código via Git | Manual no servidor | `git pull` no ctrlp01 antes de `kubectl apply` |
| 0.4 | Postgres para cadastros e `pipeline_runs` | Código + K8s config | Migração + `backend: postgres` no ConfigMap |
| 0.5 | Modo fila em produção | `pipeline.mode: queue` | Play enfileira; worker consome |

---

## 0.1 — Control plane

No **ctrlp01**:

```bash
cd ~/track_fraude   # ou caminho do clone
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.infra.yml ps
```

Serviços esperados:

| Serviço | Porta |
|---------|-------|
| Registry | `:5000` |
| RabbitMQ | `:5672`, gestão `:15672` |
| Postgres | `:5432` |

K3s server + KEDA conforme [config_control_plane.md](config_control_plane.md).

---

## 0.2 — Worker GPU

Build e push da imagem worker:

```bash
docker build -f Dockerfile.worker -t 192.168.0.199:5000/track-fraude-worker:latest .
docker push 192.168.0.199:5000/track-fraude-worker:latest
kubectl apply -f infra/k8s/worker-scaledjob.yaml
```

Com mensagem na fila e GPU node Ready, KEDA cria Job:

```bash
kubectl get jobs -n track-fraude
```

---

## 0.3 — Sync código

No ctrlp01, **sempre** após editar manifests no dev:

```bash
git pull
grep -E '192\.168|queue|postgres' infra/k8s/app-config.yaml
kubectl apply -f infra/k8s/app-config.yaml
kubectl apply -f infra/k8s/server-deployment.yaml
kubectl apply -f infra/k8s/worker-scaledjob.yaml
```

---

## 0.4 — Postgres

### Schema

O Postgres sobe com `infra/postgres/schema.sql` via compose (initdb).

### Migrar SQLite existente

No control plane (com SQLite em `data/track_fraude.db`):

```bash
pip install "psycopg[binary]>=3.1"
python tools/migrate_sqlite_to_postgres.py \
  --sqlite data/track_fraude.db \
  --postgres-url postgresql://track_fraude:track_fraude@127.0.0.1:5432/track_fraude
```

### Aplicação

- ConfigMap `infra/k8s/app-config.yaml`: `database.backend: postgres`
- Worker: env `TRACK_FRAUDE_DATABASE_URL` (Secret `postgres-url`)
- Alternativa local: variável `TRACK_FRAUDE_DATABASE_URL` ou `settings.production.example.yaml`

Repositórios em `core` aceitam DSN SQLite **ou** `postgresql://...`.

---

## 0.5 — Modo fila

Produção (K8s ConfigMap):

```yaml
pipeline:
  mode: queue
  queue_url: amqp://track_fraude:track_fraude@<IP-PC1>:5672/%2F
  queue_name: track-fraude-pipelines
```

Fluxo:

1. UI cria `pipeline_run` (status `queued`) e publica em RabbitMQ
2. KEDA observa fila → Job GPU
3. Worker consome mensagem, atualiza Postgres, grava artefatos em NFS

**Teste de isolamento (critério de saída):**

```bash
# Enfileire um pipeline pela UI, depois:
kubectl delete pod -n track-fraude -l app=track-fraude-server
kubectl get jobs -n track-fraude -w
# Job deve completar mesmo com UI offline
```

---

## Verificação automatizada

No repo (Windows ou Linux):

```bash
python tools/verify_fase0.py --skip-live
```

Com infra rodando localmente ou via SSH tunnel:

```bash
python tools/verify_fase0.py \
  --postgres-url postgresql://track_fraude:track_fraude@192.168.0.199:5432/track_fraude \
  --rabbitmq-api http://192.168.0.199:15672/api/queues/%2F
```

---

## Fora de escopo (Fase 0)

- Atlas Platform API / Hub
- Multi-workload (vLLM, Kiaia)
- Renomear imagens para `track-fraude-ui`

---

## Próximo passo

[Fase 1](../plano_execucao.md) — schema `atlas.*` + Platform API mínima.
