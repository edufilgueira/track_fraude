# Fase 1 — Fundação Atlas

Objetivo: Platform API enfileira jobs; track_fraude UI deixa de publicar direto no RabbitMQ.

Relacionado: [plano_execucao.md](../plano_execucao.md), [fase0_base_operacional.md](fase0_base_operacional.md).

---

## Entregas

| # | Entrega | Arquivo / serviço |
|---|---------|-------------------|
| 1.1 | Schema `atlas.*` | `infra/postgres/schema_atlas.sql` |
| 1.2 | Seed workload | `track-fraude` + pool `video` no schema |
| 1.3 | Platform API | `atlas/platform/` — `POST/GET /v1/jobs`, `GET /v1/health` |
| 1.4 | UI via API | `server/services/atlas_client.py` + `atlas.api_url` no ConfigMap |
| 1.5 | Contrato fila | Payload `PipelineQueueMessage` inalterado |
| 1.6 | Docker/K8s | `Dockerfile.atlas-platform-api`, `infra/k8s/atlas-platform-api.yaml` |

---

## Aplicar schema (Postgres já existente)

```bash
python tools/apply_atlas_schema.py \
  --postgres-url postgresql://track_fraude:track_fraude@127.0.0.1:5432/track_fraude
```

Instalações novas via `docker compose` já rodam `002_schema_atlas.sql` no initdb.

---

## Build e deploy (ctrlp01)

```bash
cd ~/track_fraude
git pull

# Schema
python tools/apply_atlas_schema.py

# Imagens
docker build -f Dockerfile.atlas-platform-api -t 192.168.0.199:5000/atlas-platform-api:latest .
docker push 192.168.0.199:5000/atlas-platform-api:latest

docker build -f Dockerfile.server -t 192.168.0.199:5000/track-fraude-server:latest .
docker push 192.168.0.199:5000/track-fraude-server:latest

# K8s
kubectl apply -f infra/k8s/app-config.yaml
kubectl apply -f infra/k8s/atlas-platform-api.yaml
kubectl rollout restart deployment/atlas-platform-api -n track-fraude
kubectl rollout restart deployment/track-fraude-server -n track-fraude
```

---

## Verificação

```bash
python tools/verify_fase1.py --skip-live
curl -s http://127.0.0.1:30090/v1/health
python tools/verify_fase1.py --api-url http://127.0.0.1:30090
```

**Critério de saída:** Play na UI → Platform API → fila RabbitMQ → worker; registros em `atlas.jobs` e `pipeline_runs`.

---

## API key (dev)

| Campo | Valor |
|-------|-------|
| Secret K8s | `track-fraude-secrets` → `atlas-api-key` |
| Valor padrão | `atlas-dev-internal-key` |
| Scopes seed | `*` (internal-ui) |

Header: `Authorization: Bearer atlas-dev-internal-key`

---

## Fluxo

```text
Play (UI) → POST /v1/jobs (Atlas API) → atlas.jobs + RabbitMQ
         → KEDA → track-fraude-worker → pipeline_runs atualizado
```

---

## Próximo passo

[Fase 2](../plano_execucao.md) — renomear imagens UI/worker e remover modo local.
