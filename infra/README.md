# Infra serverless on-prem

Esta pasta contém a base para rodar o `track_fraude` em servidores GPU escaláveis.

## 1. Control plane local

Suba registry, RabbitMQ e Postgres no servidor principal:

```bash
docker compose -f docker-compose.infra.yml up -d
```

O registry local fica em `http://<control-plane>:5000`.

## 2. Build e push das imagens

```bash
docker build -f Dockerfile.server -t <control-plane>:5000/track-fraude-server:latest .
docker build -f Dockerfile.worker -t <control-plane>:5000/track-fraude-worker:latest .

docker push <control-plane>:5000/track-fraude-server:latest
docker push <control-plane>:5000/track-fraude-worker:latest
```

Em cada nó K3s, configure `/etc/rancher/k3s/registries.yaml` com base em
`infra/k3s/registries.yaml.example` e reinicie o K3s.

## 3. Nós GPU

Cada servidor GPU precisa de:

- Ubuntu Server.
- Driver NVIDIA compatível com a RTX instalada.
- NVIDIA Container Toolkit.
- `k3s agent` conectado ao control plane.
- Acesso ao NAS/NFS usado por `data/`.

Depois aplique o device plugin:

```bash
kubectl apply -f infra/k8s/nvidia-device-plugin.yaml
kubectl describe nodes | grep -A5 nvidia.com/gpu
```

## 4. KEDA

Instale o KEDA no cluster antes do `ScaledJob`:

```bash
kubectl apply --server-side -f https://github.com/kedacore/keda/releases/latest/download/keda-2.16.1.yaml
```

## 5. Aplicar manifests

Edite os placeholders `CHANGE_ME_*` em `infra/k8s/*.yaml`, especialmente:

- IP e caminho do NAS em `data-nfs-pvc.yaml`.
- Host do registry nas imagens do server/worker.
- `secret_key`, usuários e senhas.
- Em `app-config.yaml`, `rabbitmq-url` e `queue_url` com o IP do control plane (`PC1_IP:5672`) quando RabbitMQ roda via `docker-compose` no host — **não** use `rabbitmq.track-fraude.svc.cluster.local` nesse cenário.
- `worker-scaledjob.yaml` não precisa da URL do RabbitMQ; o worker lê `rabbitmq-url` do Secret via `secretKeyRef`.

Depois:

```bash
kubectl apply -k infra/k8s
```

## 6. Modo fila no painel

O arquivo `server/config/settings.yaml` agora aceita:

```yaml
pipeline:
  mode: queue
  # Com docker-compose no host: use o IP do control plane, não cluster.local
  queue_url: amqp://track_fraude:track_fraude@<PC1_IP>:5672/%2F
  queue_name: track-fraude-pipelines
```

Em desenvolvimento, mantenha `mode: local`.

## 7. Migração para Postgres

O schema inicial está em `infra/postgres/schema.sql`. Para copiar dados do SQLite atual:

```bash
python -m pip install "psycopg[binary]>=3.1"
python tools/migrate_sqlite_to_postgres.py \
  --sqlite data/track_fraude.db \
  --postgres-url postgresql://track_fraude:track_fraude@localhost:5432/track_fraude
```

A aplicação ainda mantém compatibilidade com SQLite para desenvolvimento local. Use Postgres como base operacional da próxima etapa de refatoração dos repositórios.

## 8. Power manager

Configure `infra/power-manager/config.example.json` com os nós GPU reais e execute em uma máquina sempre ligada:

```bash
python infra/power-manager/power_manager.py --config infra/power-manager/config.example.json
```

O gerenciador acorda um nó via Wake-on-LAN quando há mensagens na fila e desliga nós prontos sem pods ativos após `idle_shutdown_after_sec`.
