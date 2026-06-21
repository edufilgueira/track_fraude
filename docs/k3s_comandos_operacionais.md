# K3s / kubectl — comandos operacionais (track-fraude)

Guia prático para **listar**, **inspecionar**, **reiniciar** e **limpar** recursos no cluster K3s do projeto.

Relacionado: [config_control_plane.md](config_control_plane.md), [config_node.md](config_node.md), [fase0_base_operacional.md](fase0_base_operacional.md), [fase1_atlas_fundacao.md](fase1_atlas_fundacao.md).

---

## Contexto rápido


| Recurso K8s          | O que é no track_fraude                                                             |
| -------------------- | ----------------------------------------------------------------------------------- |
| **Deployment**       | Painel (`track-fraude-server`) e Atlas API (`atlas-platform-api`) — pods long-lived |
| **ScaledJob** (KEDA) | Worker GPU — cria **Jobs** quando a fila RabbitMQ tem mensagens                     |
| **Job**              | Uma execução do pipeline (1 pod worker)                                             |
| **Pod**              | Container rodando (ou tentando rodar)                                               |
| **Service**          | Expõe portas: painel `:30080`, Atlas `:30090`                                       |


Namespace usado em tudo abaixo:

```bash
export NS=track-fraude
```

Atalho mental: `-n track-fraude` em todo comando `kubectl`.

---

## 1. Listar recursos

### Visão geral

```bash
kubectl get all -n track-fraude
```

### Pods (processos/containers)

```bash
kubectl get pods -n track-fraude
kubectl get pods -n track-fraude -o wide    # inclui IP e node
kubectl get pods -n track-fraude -w         # acompanha em tempo real (Ctrl+C para sair)
```

Colunas importantes:


| STATUS                       | Significado                                   |
| ---------------------------- | --------------------------------------------- |
| **Running**                  | Container ok                                  |
| **Pending**                  | Ainda não agendou (ex.: sem GPU, PVC, imagem) |
| **Error / CrashLoopBackOff** | Subiu e caiu — ver logs                       |
| **Terminating**              | Sendo removido (normal após delete)           |


### Deployments (painel e Atlas API)

```bash
kubectl get deployments -n track-fraude
```

### Jobs e worker GPU

```bash
kubectl get jobs -n track-fraude
kubectl get scaledjob -n track-fraude
```

### Serviços e portas

```bash
kubectl get svc -n track-fraude
```

### Nodes do cluster

```bash
kubectl get nodes
kubectl describe node <nome-do-node> | grep -A5 nvidia.com/gpu
```

### PVC (dados NFS)

```bash
kubectl get pvc -n track-fraude
```

---

## 2. Inspecionar (por que está Pending / Error?)

### Descrever um pod

```bash
kubectl describe pod -n track-fraude <nome-do-pod>
```

Role até **Events** no final. Exemplos comuns:

```text
Insufficient nvidia.com/gpu     → sem GPU node no cluster
PersistentVolumeClaim not bound → PVC/NFS com problema
ImagePullBackOff                → imagem não existe no registry
```

Atalho por label:

```bash
# Pod do painel
kubectl describe pod -n track-fraude -l app=track-fraude-server

# Pod de um job worker (troque o prefixo do job)
kubectl describe pod -n track-fraude -l job-name=track-fraude-worker-xxxxx
```

### Logs

```bash
# Painel
kubectl logs -n track-fraude -l app=track-fraude-server --tail=50

# Atlas Platform API
kubectl logs -n track-fraude -l app=atlas-platform-api --tail=50

# Worker (job específico)
kubectl logs -n track-fraude <nome-do-pod-worker> --tail=100

# Pod que já reiniciou — log anterior
kubectl logs -n track-fraude <nome-do-pod> --previous --tail=100
```

### Entrar no container (debug)

```bash
kubectl exec -it -n track-fraude deploy/track-fraude-server -- bash
kubectl exec -n track-fraude deploy/track-fraude-server -- ls /app/data/raw/default/LOJA-01
```

---

## 3. Reiniciar (sem apagar configuração)

Deployments recriam o pod com a mesma config:

```bash
kubectl rollout restart deployment/track-fraude-server -n track-fraude
kubectl rollout restart deployment/atlas-platform-api -n track-fraude

kubectl rollout status deployment/track-fraude-server -n track-fraude
```

Útil após `docker push` de imagem nova ou mudança no ConfigMap:

```bash
kubectl apply -f infra/k8s/app-config.yaml
kubectl rollout restart deployment/track-fraude-server -n track-fraude
```

---

## 4. Deletar / limpar

### Um pod específico

Deployment **recria** o pod sozinho:

```bash
kubectl delete pod -n track-fraude <nome-do-pod>
```

Job **não** recria — KEDA só cria job novo se houver mensagem na fila.

### Todos os pods de um Deployment (força recriação)

```bash
kubectl delete pod -n track-fraude -l app=track-fraude-server
kubectl delete pod -n track-fraude -l app=atlas-platform-api
```

### Jobs worker presos em Pending

Quando **não há GPU node**, jobs acumulam em Pending. **Pode apagar** — não quebra o painel nem a API.

Listar:

```bash
kubectl get jobs -n track-fraude
```

Apagar um job (remove o pod junto):

```bash
kubectl delete job -n track-fraude track-fraude-worker-xxxxx
```

Apagar **todos** os jobs do namespace:

```bash
kubectl delete jobs -n track-fraude --all
```

Se preferir um a um:

```bash
kubectl get jobs -n track-fraude -o name | xargs -r kubectl delete -n track-fraude
```

> **Nota:** Se a fila RabbitMQ ainda tiver mensagens, o KEDA pode criar **novos** jobs em ~10s. Esvazie a fila ou cancele o run no painel (Pause) se não for processar agora.

### Ver fila RabbitMQ (host)

```bash
curl -s -u track_fraude:track_fraude \
  http://127.0.0.1:15672/api/queues/%2F/track-fraude-pipelines \
  | jq '.messages, .consumers'
```

Interface web: `http://<IP-do-servidor>:15672` (usuário `track_fraude`).

---

## 5. Cenários comuns

### Worker Pending (sem GPU)

**Sintoma:**

```text
track-fraude-worker-xxxxx-yyyyy   0/1   Pending
```

**Causa:** cluster só tem control plane; worker pede `nvidia.com/gpu: 1`.

**O que fazer:**

1. Limpar jobs Pending (seção 4) — opcional, recomendado para não poluir
2. Configurar GPU node → [config_node.md](config_node.md)
3. Confirmar GPU no node: `kubectl describe node <gpu-node> | grep nvidia.com/gpu`
4. Play de novo ou aguardar KEDA recriar job quando a fila tiver mensagem

**Não é necessário** derrubar `track-fraude-server` nem `atlas-platform-api`.

### Painel / `:30080` timeout (curl exit 28) com pod Running

**Sintoma:** logs do painel ok (`Uvicorn running`), mas `curl http://127.0.0.1:30080/health` trava; endpoints apontam IP `10.42.1.x` (node GPU) em vez de `10.42.0.x` (ctrl-p01).

**Causa:** Deployment sem `nodeAffinity` — após restart o pod pode subir no **node-01**. Com rede pod-to-pod quebrada (`CIDRAssignmentFailed` no node), NodePort no ctrl-p01 não alcança o pod.

**Correção:**

```bash
cd ~/track_fraude
git pull
kubectl apply -f infra/k8s/server-deployment.yaml
kubectl apply -f infra/k8s/atlas-platform-api.yaml
kubectl rollout restart deployment/track-fraude-server deployment/atlas-platform-api -n track-fraude
kubectl get pods -n track-fraude -o wide   # NODE deve ser ctrlp01 / ctrl-p01
curl -m 5 http://127.0.0.1:30080/health
```

**Workaround imediato (sem git):**

```bash
kubectl port-forward -n track-fraude svc/track-fraude-server 8080:8080
# outro terminal: curl http://127.0.0.1:8080/login
```

### Play enfileirou mas painel trava em "em execução"

**Sintoma:** log mostra `atlas_job:` e `pipeline retirado da fila`, mas o console não avança; `atlas.jobs` fica `queued`; muitos jobs `Failed`/`Complete` no KEDA.

**Causas comuns:**

1. Vários `pipeline_runs` antigos em status `queued`/`running` (Play anterior falhou)
2. Fila RabbitMQ com mensagens acumuladas + KEDA criando jobs demais
3. Worker falhou no **ingest** (POS ausente, vídeo faltando) — veja logs do pod

**Diagnóstico:**

```bash
# Runs ativos no Postgres (queued/running mantêm o painel "em execução")
docker compose -f docker-compose.infra.yml exec postgres \
  psql -U track_fraude -d track_fraude -c \
  "SELECT id, status, date, error_message FROM pipeline_runs ORDER BY id DESC LIMIT 10;"

# Log completo do worker (troque pelo pod Completed ou Error)
kubectl logs -n track-fraude track-fraude-worker-5mkqp-ncgqx --tail=120

# Log do pipeline no NFS (store_db_id da LOJA-01 — confira com SELECT id FROM stores WHERE store_id='LOJA-01')
ls -lt /srv/track_fraude/data/logs/pipeline_*_2026-05-22*.log | head -3
tail -80 /srv/track_fraude/data/logs/pipeline_<STORE_DB_ID>_2026-05-22_*.log
```

**Recuperação (ctrl-p01):**

```bash
kubectl delete jobs -n track-fraude --all

# Cancelar runs presos (ajuste IDs conforme o SELECT acima)
docker compose -f docker-compose.infra.yml exec postgres \
  psql -U track_fraude -d track_fraude -c \
  "UPDATE pipeline_runs SET status='failed', error_message='cancelled manual', finished_at=now(), updated_at=now() WHERE status IN ('queued','running');"

docker compose -f docker-compose.infra.yml exec postgres \
  psql -U track_fraude -d track_fraude -c \
  "UPDATE atlas.jobs SET status='failed', error_message='cancelled manual', finished_at=now(), updated_at=now() WHERE status IN ('queued','running');"

# Esvaziar fila (interface RabbitMQ :15672 → queue track-fraude-pipelines → Purge)
# ou API:
curl -s -u track_fraude:track_fraude -XDELETE \
  http://127.0.0.1:15672/api/queues/%2F/track-fraude-pipelines/contents
```

Depois `git pull`, rebuild worker se houve correção, `kubectl apply -f infra/k8s/worker-scaledjob.yaml`, e **um** Play novo.

> Com 1 GPU, o ScaledJob usa `maxReplicaCount: 1` — só um worker por vez.

### Worker em `ContainerCreating` (sem logs ainda)

**Sintoma:** `kubectl logs ...` responde `waiting to start: ContainerCreating`; painel trava em `pipeline enfileirado`.

**Normal:** o log só avança para `--- pipeline retirado da fila ---` quando o **container já está Running** e o Python consome o RabbitMQ. Enquanto o pod cria, a UI fica parada — isso não é bug do painel.

**Diagnóstico (ctrl-p01):**

```bash
POD=$(kubectl get pods -n track-fraude -l job-name -o jsonpath='{.items[0].metadata.name}')
kubectl get pod -n track-fraude "$POD" -o wide
kubectl describe pod -n track-fraude "$POD" | tail -30
kubectl get events -n track-fraude --sort-by='.lastTimestamp' | tail -15
```

| Evento em `describe` | O que fazer |
|----------------------|-------------|
| `Pulling` / `Pulled` (imagem ~8 GB) | Aguarde 5–20 min na **primeira** vez; ou pre-pull no node-01 (abaixo) |
| `FailedMount` / NFS | Firewall NFS no ctrl-p01 — [config_control_plane Passo 2.1](config_control_plane.md) |
| `FailedCreatePodSandBox` / runtime | `kubectl apply -f infra/k8s/nvidia-runtime-class.yaml` |
| `ImagePullBackOff` | Registry: `curl http://192.168.0.199:5000/v2/_catalog` no node-01; `registries.yaml` |

**Pre-pull no node-01** (evita surpresa no Play):

```bash
sudo k3s crictl pull 192.168.0.199:5000/track-fraude-worker:latest
sudo k3s crictl images | grep track-fraude-worker
```

Depois do pull, reaplique o worker se mudou `imagePullPolicy`:

```bash
kubectl apply -f infra/k8s/worker-scaledjob.yaml
kubectl delete jobs -n track-fraude --all
```

### Logs do worker fora de ordem (`-l job-name -f`)

**Sintoma:** fases intercaladas (ex.: `merge` antes de `track`, dois `resumo` no meio).

**Causa:** `kubectl logs -l job-name` agrega **todos** os pods de jobs (inclusive Completed). Use **um pod**:

```bash
kubectl get pods -n track-fraude -l job-name --sort-by=.metadata.creationTimestamp
POD=track-fraude-worker-xxxxx-yyyyy   # o mais recente
kubectl logs -n track-fraude "$POD" --tail=120
```

### Play para em `pipeline enfileirado` (sem `retirado da fila`)

**Sintoma:** console mostra só `atlas_job:` / `message_id: pipeline-N`, **sem** `--- pipeline retirado da fila ---` (pod já **Running** há minutos).

**Causa:** mensagem na fila, mas KEDA não criou job ou pod worker Pending (GPU, runtime, node errado).

```bash
curl -s -u track_fraude:track_fraude \
  http://127.0.0.1:15672/api/queues/%2F/track-fraude-pipelines | jq '.messages'
kubectl get scaledjob,jobs,pods -n track-fraude -o wide
kubectl describe node node-01 | grep -A3 nvidia.com/gpu
kubectl describe pod -n track-fraude -l job-name 2>/dev/null | tail -25
kubectl logs -n keda -l app=keda-operator --tail=30
```

| O que ver | Ação |
|-----------|------|
| `messages: 1`, sem job | Reaplique ScaledJob; confira KEDA e Secret `rabbitmq-url` |
| Pod **Pending** 20+ min, `NODE` vazio | `kubectl describe pod ...` — quase sempre GPU |
| `node-01` Ready mas **`nvidia.com/gpu: 0`** | Refazer Passo 8 [config_node.md](config_node.md#passo-8--device-plugin-nvidia-no-cluster): label, RuntimeClass, device plugin, symlink no node-01 |
| job Pending `Insufficient nvidia.com/gpu` | Corrigir GPU acima; depois `kubectl delete jobs -n track-fraude --all` |
| job Pending no ctrlp01 | `kubectl apply -f infra/k8s/worker-scaledjob.yaml` (affinity GPU) |

### Play enfileirou mas nada processa

Checklist:

```bash
curl -s http://127.0.0.1:30090/v1/health
curl -s -u track_fraude:track_fraude http://127.0.0.1:15672/api/queues/%2F/track-fraude-pipelines | jq '.messages'
kubectl get scaledjob -n track-fraude
kubectl get jobs,pods -n track-fraude
```

### Pod Error / CrashLoopBackOff (painel ou API)

```bash
kubectl logs -n track-fraude <pod> --tail=80
kubectl logs -n track-fraude <pod> --previous --tail=80
kubectl describe pod -n track-fraude <pod>
```

Corrija (imagem, ConfigMap, Postgres) e:

```bash
kubectl rollout restart deployment/<nome> -n track-fraude
```

### Teste de isolamento (Fase 0)

Worker deve continuar mesmo com painel offline:

```bash
kubectl delete pod -n track-fraude -l app=track-fraude-server
kubectl get jobs -n track-fraude -w
```

---

## 6. Health checks fora do kubectl

```bash
curl -s http://127.0.0.1:30080/health    # painel
curl -s http://127.0.0.1:30090/v1/health # Atlas Platform API
```

---

## 7. Cheat sheet (copiar e colar)

```bash
NS=track-fraude

# Listar
kubectl get pods,jobs,deploy,svc,scaledjob -n $NS

# Logs painel + API
kubectl logs -n $NS -l app=track-fraude-server --tail=30
kubectl logs -n $NS -l app=atlas-platform-api --tail=30

# Por que Pending?
kubectl describe pod -n $NS <POD>

# Limpar jobs worker Pending
kubectl delete jobs -n $NS --all

# Reiniciar painel / API
kubectl rollout restart deployment/track-fraude-server -n $NS
kubectl rollout restart deployment/atlas-platform-api -n $NS

# GPU no cluster?
kubectl get nodes
kubectl describe node <NODE> | grep -A5 nvidia.com/gpu
```

---

## 8. O que **não** deletar sem necessidade


| Recurso                         | Motivo                              |
| ------------------------------- | ----------------------------------- |
| `namespace track-fraude`        | Remove tudo do app                  |
| PVC `track-fraude-data`         | Dados NFS (vídeos, logs, processed) |
| PV `track-fraude-data-nfs`      | Bind do storage                     |
| ScaledJob `track-fraude-worker` | KEDA para de observar a fila        |


Para **pausar** workers temporariamente sem remover o ScaledJob, esvazie a fila RabbitMQ e delete os jobs Pending.

---

## 9. Referências


| Documento                                                             | Conteúdo                       |
| --------------------------------------------------------------------- | ------------------------------ |
| [config_control_plane.md](config_control_plane.md)                    | Instalação completa do ctrlp01 |
| [config_node.md](config_node.md)                                      | GPU node + NVIDIA              |
| [fase1_atlas_fundacao.md](fase1_atlas_fundacao.md)                    | Deploy Atlas Platform API      |
| [Documentação kubectl](https://kubernetes.io/docs/reference/kubectl/) | Referência oficial             |


