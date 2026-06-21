# Configuração do PC 01 — Control Plane unificado + Storage

Guia passo a passo para montar o **primeiro servidor** da arquitetura `pipeline.mode: queue`.

Neste cenário inicial:

- **PC 01** concentra control plane **e** storage (PC 1 + PC 2 do diagrama unificados).
- Você ainda **não precisa** de 3 GPU nodes; basta preparar o orquestrador.
- Depois você adiciona **1 GPU node** (ou mais) sem refazer este servidor.

**Sistema alvo:** Ubuntu Server (somente terminal, sem interface gráfica).

> **Onde editar os arquivos?** Os passos 10 e 11 assumem que você edita e aplica os manifests **no próprio `ctrl-p01`** (`~/track_fraude`). Se você editar no Windows (ou outro PC), precisa **sincronizar** antes do `kubectl apply` — veja [Sincronizar alterações no servidor](#sincronizar-alterações-no-servidor).

> **Fase 0 (Atlas Worker):** checklist e critérios de saída em [fase0_base_operacional.md](fase0_base_operacional.md).

> **Fase 1 (Atlas Platform API):** painel enfileira via API, não RabbitMQ direto — [fase1_atlas_fundacao.md](fase1_atlas_fundacao.md).

---

## O que este PC faz


| Função              | O que roda aqui                                                |
| ------------------- | -------------------------------------------------------------- |
| Painel web          | Interface FastAPI (botão Play → Atlas Platform API)            |
| Atlas Platform API  | Enfileira jobs (`POST /v1/jobs`) → RabbitMQ → worker           |
| Fila                | RabbitMQ                                                       |
| Banco               | PostgreSQL (recomendado) + SQLite em `data/` durante transição |
| Imagens Docker      | Registry local                                                 |
| Orquestração        | K3s server + KEDA                                              |
| Storage             | Pasta `data/` exportada via NFS para os GPU nodes              |
| Economia de energia | Power Manager (quando existir GPU node separado)               |


**Este PC não precisa de GPU** para subir os serviços. Quem processa vídeo são os GPU nodes que você ligar depois.

---

## Antes de começar — checklist

Preencha estes valores (anote num papel ou arquivo):


| Variável             | Exemplo                | Seu valor      |
| -------------------- | ---------------------- | -------------- |
| `PC1_IP`             | `192.168.0.199`        | ______________ |
| `PC1_HOSTNAME`       | `ctrl-p01`             | ______________ |
| `PC1_DNS`            | `ctrl-p01`             | ______________ |
| `USUARIO`            | `ubuntu`               | ______________ |
| `SENHA_ADMIN_PAINEL` | troque em produção     | ______________ |
| `SECRET_KEY`         | string aleatória longa | ______________ |


Requisitos de hardware sugeridos:

- CPU 4+ núcleos
- 16 GB RAM (mínimo; 32 GB se storage grande no mesmo disco)
- SSD 256 GB+ para sistema + serviços
- Disco extra ou partição grande para `/srv/track_fraude/data` (vídeos)
- Rede cabeada (IP fixo no roteador)

---

## Visão do que vamos instalar

```text
PC 01 (este guia)
├── Ubuntu Server
├── Docker + Compose
│   ├── Registry :5000
│   ├── RabbitMQ :5672 / :15672
│   └── Postgres :5432
├── NFS export → /srv/track_fraude/data
├── K3s server (Kubernetes leve)
├── KEDA (escala workers pela fila)
├── Imagens Docker
│   ├── track-fraude-server
│   └── track-fraude-worker
└── Painel web (container Docker)
```

---

## Passo 0 — Ubuntu Server base

Conecte por SSH ou terminal local no servidor recém-instalado.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  curl wget git vim ca-certificates gnupg lsb-release \
  nfs-kernel-server nfs-common \
  python3 python3-venv python3-pip \
  build-essential pkg-config
```

fuso horario

```bash
timedatectl list-timezones | grep Sao_Paulo
sudo timedatectl set-timezone America/Sao_Paulo
timedatectl
timedatectl status # Procure por System clock synchronized: yes
sudo timedatectl set-ntp true
```

Defina hostname e IP fixo (ajuste interface e IP):

```bash
sudo hostnamectl set-hostname ctrl-p01

# Exemplo netplan — EDITE conforme sua rede
sudo tee /etc/netplan/01-track-fraude.yaml >/dev/null <<'EOF'
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: false
      addresses:
        - 192.168.0.199/24
      routes:
        - to: default
          via: 192.168.0.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
EOF

sudo netplan apply
```

- `hostname` mostra `ctrl-p01`
- `ip a` mostra o IP fixo correto (`PC1_IP`)

---

## Passo 0.1 — Nomes locais (DNS / hosts)

Use **nomes estáveis** na LAN para SSH, navegador e `scp`, em vez de decorar IPs.

| Nome (SSH / browser) | IP fixo | Hostname sistema | Nome no K3s |
| -------------------- | ------- | ---------------- | ----------- |
| `ctrl-p01`           | `192.168.0.199` | `ctrl-p01` | `ctrl-p01` |
| `node-01`            | `192.168.0.201` | `node-01`  | `node-01` |
| `node-02`            | `192.168.0.202` | `node-02`  | `node-02` |
| `node-03`            | `192.168.0.203` | `node-03`  | `node-03` |

> Use o **mesmo nome** (`ctrl-p01`, `node-01`, …) em DNS, hostname Linux e nome do node K3s.

### Opção A — `/etc/hosts` (recomendado para começar)

No **ctrl-p01** (e repita no notebook e em cada GPU node):

```bash
sudo tee -a /etc/hosts >/dev/null <<'EOF'
192.168.0.199   ctrl-p01
192.168.0.201   node-01
192.168.0.202   node-02
192.168.0.203   node-03
EOF
```

Teste:

```bash
ping -c1 ctrl-p01
ping -c1 node-01
ssh ${USUARIO}@node-01
```

Painel no navegador (de outro PC na rede, com o mesmo `/etc/hosts` ou DNS):

```text
http://ctrl-p01:30080/login
```

### Opção B — DNS central com `dnsmasq` no ctrl-p01 (opcional)

Se quiser que **toda a LAN** resolva nomes sem editar cada PC:

```bash
sudo apt install -y dnsmasq
sudo tee /etc/dnsmasq.d/track-fraude.conf >/dev/null <<'EOF'
address=/ctrl-p01/192.168.0.199
address=/node-01/192.168.0.201
address=/node-02/192.168.0.202
address=/node-03/192.168.0.203
EOF
sudo systemctl restart dnsmasq
```

No roteador, configure o DHCP para apontar **DNS primário = `192.168.0.199`**.

### O que continua com IP nos manifests

Os YAMLs do Kubernetes (`app-config.yaml`, NFS, registry) **podem manter IP** (`192.168.0.199`) — pods do K3s resolvem melhor assim. Nomes locais são para **operação humana** (SSH, browser, Power Manager).

No Power Manager (`~/track_fraude/infra/power-manager/config.json`), configure cada GPU node conforme o [Passo 0.1 — Power Manager em config_node.md](config_node.md#power-manager-opcional) (`name`, `mac`, `ssh_host`, `ssh_user`).

- `ping ctrl-p01` e `ping node-01` funcionam
- `ssh usuario@ctrl-p01` funciona

---

## Passo 1 — Usuário e firewall

```bash
# Se ainda não existe, use o usuário criado na instalação do Ubuntu
whoami
sudo ufw status

sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp    # painel web (Docker direto, Passo 12)
sudo ufw allow 30080/tcp   # painel web no K3s (NodePort, Passo 11)
sudo ufw allow 5000/tcp    # registry
sudo ufw allow 5672/tcp    # rabbitmq
sudo ufw allow 15672/tcp   # rabbitmq management
sudo ufw allow 5432/tcp    # postgres (só rede interna se possível)
sudo ufw allow 6443/tcp    # k3s api
sudo ufw allow from 192.168.0.0/24 to any port 2049 proto tcp  # NFS
sudo ufw enable
```

- Firewall ativo sem bloquear SSH

---

## Passo 2 — Storage local (PC 1 + PC 2 unificados)

Crie a pasta de dados que será compartilhada com os GPU nodes:

```bash
sudo mkdir -p /srv/track_fraude/data/{raw,processed,logs,pos}
sudo chown -R $USER:$USER /srv/track_fraude/data
```

Export NFS (substitua a rede se necessário):

```bash
echo '/srv/track_fraude/data 192.168.0.0/24(rw,sync,no_subtree_check,no_root_squash)' | sudo tee -a /etc/exports
sudo exportfs -ra
sudo systemctl enable --now nfs-server
```

Teste local:

```bash
showmount -e localhost
ls -la /srv/track_fraude/data
```

- NFS export ativo
- Pastas `raw`, `processed`, `logs`, `pos` existem

> Se você já tem vídeos/SQLite em outra máquina, copie para `/srv/track_fraude/data/` antes de subir o painel.

**No K8s**, o painel e o worker montam **`/srv/track_fraude/data`** como `/app/data` dentro do pod. Arquivos colocados só em `~/track_fraude/data/` **não** aparecem no painel — use sempre o export NFS:

```text
/srv/track_fraude/data/raw/{grupo}/{loja}/{YYYY-MM-DD}/cam1.mp4
```

Exemplo: `/srv/track_fraude/data/raw/default/LOJA-01/2026-05-22/cam1.mp4`

Se os vídeos estiverem no clone do repo, sincronize:

```bash
rsync -av ~/track_fraude/data/raw/ /srv/track_fraude/data/raw/
```

---

## Passo 3 — Clonar o projeto

```bash
cd ~
git clone https://github.com/edufilgueira/track_fraude.git
cd track_fraude
```

Se o repositório for privado ou estiver em pendrive, copie a pasta `track_fraude/` para `~/track_fraude`.

- Pasta `~/track_fraude` existe com `Dockerfile.server`, `docker-compose.infra.yml`, `infra/`

---

## Sincronizar alterações no servidor

O `kubectl apply` lê os YAMLs **do disco do `ctrl-p01`**, não do seu notebook. Se você editou manifests em outro lugar e não sincronizou, o cluster recebe a versão antiga (sintoma típico: `grep storageClassName` vazio, `CHANGE_ME_REGISTRY` no pod, PVC com `local-path`).

**Opção A — editar direto no servidor (mais simples)**

```bash
ssh eduardo@192.168.0.199
cd ~/track_fraude
nano infra/k8s/data-nfs-pvc.yaml   # etc.
```

**Opção B — editar no Windows e enviar via git**

```bash
# No Windows (após commit)
git push

# No ctrl-p01 (antes dos passos 10.5 e 11)
cd ~/track_fraude
git pull
```

**Opção C — copiar arquivos com `scp` (sem git)**

```powershell
# No Windows (PowerShell) — ajuste usuário e IP
scp infra/k8s/data-nfs-pvc.yaml eduardo@192.168.0.199:~/track_fraude/infra/k8s/
scp infra/k8s/server-deployment.yaml eduardo@192.168.0.199:~/track_fraude/infra/k8s/
scp infra/k8s/worker-scaledjob.yaml eduardo@192.168.0.199:~/track_fraude/infra/k8s/
scp infra/k8s/atlas-platform-api.yaml eduardo@192.168.0.199:~/track_fraude/infra/k8s/
scp infra/k8s/app-config.yaml eduardo@192.168.0.199:~/track_fraude/infra/k8s/
```

Confirme no servidor **antes** de cada `kubectl apply`:

```bash
grep -c storageClassName infra/k8s/data-nfs-pvc.yaml   # deve ser 2
grep image infra/k8s/server-deployment.yaml            # deve ter PC1_IP:5000
```

---

## Passo 4 — Docker e Docker Compose

```bash
# Instalar Docker oficial
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker
```

- `docker run hello-world` funciona sem sudo

---

## Passo 5 — Subir Registry, RabbitMQ e Postgres

Na raiz do repo:

```bash
cd ~/track_fraude
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.infra.yml ps
```

Serviços esperados:


| Serviço       | URL / porta                                                       |
| ------------- | ----------------------------------------------------------------- |
| Registry      | `http://PC1_IP:5000`                                              |
| RabbitMQ AMQP | `PC1_IP:5672`                                                     |
| RabbitMQ UI   | `http://PC1_IP:15672` (user `track_fraude` / pass `track_fraude`) |
| Postgres      | `PC1_IP:5432` (db `track_fraude`, user/pass `track_fraude`)       |


- Os 3 containers estão `running`
- RabbitMQ UI abre no navegador

---

## Passo 6 — K3s server (orquestrador)

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --write-kubeconfig-mode 644 \
  --disable traefik

# kubectl para o usuário atual
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config

kubectl get nodes
```

- Node `Ready` aparece em `kubectl get nodes`

---

## Passo 7 — Registry local no K3s

Substitua `PC1_IP` pelo IP real (ex.: `192.168.0.199`):

```bash
PC1_IP=192.168.0.199

sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<EOF
mirrors:
  "${PC1_IP}:5000":
    endpoint:
      - "http://${PC1_IP}:5000"

configs:
  "${PC1_IP}:5000":
    tls:
      insecure_skip_verify: true
EOF

sudo systemctl restart k3s
sleep 10
kubectl get nodes
```

- K3s reiniciou sem erro

> O `registries.yaml` acima vale só para o **K3s puxar imagens** nos pods.
> O comando `docker push` no host usa o Docker Engine e precisa do passo **9.1**.

---

## Passo 8 — KEDA (scheduler por fila)

```bash
kubectl apply --server-side -f https://github.com/kedacore/keda/releases/download/v2.16.1/keda-2.16.1.yaml
kubectl get pods -n keda
```

Aguarde pods `keda-operator` e `keda-metrics-apiserver` ficarem `Running`.

- KEDA instalado

---

## Passo 9 — Build e push das imagens Docker

### 9.1 Registry HTTP no Docker host (obrigatório antes do push)

O registry local (`registry:2` no Compose) fala **HTTP** na porta 5000, sem TLS.
Por padrão o Docker tenta **HTTPS** e o push falha com:

```text
http: server gave HTTP response to HTTPS client
```

Configure `insecure-registries` no Docker Engine do PC1 (substitua o IP):

```bash
PC1_IP=192.168.0.199   # ajuste

sudo tee /etc/docker/daemon.json >/dev/null <<EOF
{
  "insecure-registries": [
    "${PC1_IP}:5000",
    "localhost:5000",
    "127.0.0.1:5000"
  ]
}
EOF

sudo systemctl restart docker
```

Confirme:

```bash
docker info 2>/dev/null | grep -A5 "Insecure Registries"
```

Deve listar `${PC1_IP}:5000`.

> Se já existir `/etc/docker/daemon.json`, **não sobrescreva** o arquivo inteiro.
> Adicione `"insecure-registries"` ao JSON existente e reinicie o Docker.

### 9.2 Build e push

Confirme que o registry está no ar:

```bash
cd ~/track_fraude
docker compose -f docker-compose.infra.yml up -d registry
```

Build e push:

```bash
PC1_IP=192.168.0.199   # ajuste

docker build -f Dockerfile.server -t ${PC1_IP}:5000/track-fraude-server:latest .
docker build -f Dockerfile.worker -t ${PC1_IP}:5000/track-fraude-worker:latest .
docker build -f Dockerfile.atlas-platform-api -t ${PC1_IP}:5000/atlas-platform-api:latest .

docker push ${PC1_IP}:5000/track-fraude-server:latest
docker push ${PC1_IP}:5000/track-fraude-worker:latest
docker push ${PC1_IP}:5000/atlas-platform-api:latest
```

Sucesso esperado no push:

```text
latest: digest: sha256:... size: ...
```

Validação:

```bash
curl -s http://${PC1_IP}:5000/v2/_catalog
curl -s http://${PC1_IP}:5000/v2/track-fraude-server/tags/list
curl -s http://${PC1_IP}:5000/v2/track-fraude-worker/tags/list
curl -s http://${PC1_IP}:5000/v2/atlas-platform-api/tags/list
```

O `_catalog` deve listar `track-fraude-server`, `track-fraude-worker` e `atlas-platform-api`.

- Imagens no registry local

> O build do worker é pesado (CUDA/PyTorch). Pode levar vários minutos na primeira vez.
> O push do worker também pode demorar (imagem grande).

---

## Passo 10 — Preparar manifests Kubernetes

Edite os placeholders **no `ctrl-p01`** (ou sincronize do seu PC — seção [Sincronizar alterações no servidor](#sincronizar-alterações-no-servidor)) antes de aplicar.

### 10.1 NFS (`infra/k8s/data-nfs-pvc.yaml`)

Confirme que `server` e `path` apontam para o storage deste PC:

```yaml
nfs:
  server: 192.168.0.199        # PC1_IP
  path: /srv/track_fraude/data
```

O manifest usa `storageClassName: track-fraude-nfs` no PV e no PVC. No K3s, sem isso o PVC herda `local-path` (padrão) e fica em `Pending` com `VolumeMismatch`.

> Confirme no servidor antes do apply: `grep storageClassName infra/k8s/data-nfs-pvc.yaml` deve listar **duas** linhas. Se vier vazio, o arquivo no `ctrl-p01` está desatualizado (`git pull` ou copie do repo).

### 10.2 Imagens (`infra/k8s/server-deployment.yaml`, `worker-scaledjob.yaml`, `atlas-platform-api.yaml`)

Troque `CHANGE_ME_REGISTRY:5000` por `${PC1_IP}:5000` (ex.: `192.168.0.199:5000`) **nos três arquivos**.

### 10.3 Segredos (`infra/k8s/app-config.yaml`)

Gere uma chave forte no terminal:

```bash
openssl rand -hex 32
```

Use **o mesmo valor** em `secret-key` (Secret) e `secret_key` (ConfigMap). Troque também `admin_password` se quiser.

### 10.4 RabbitMQ e Postgres no host (não no cluster K8s)

RabbitMQ e Postgres rodam via **docker-compose no host** (`docker-compose.infra.yml`), não como pods no K3s.

Edite **somente** `infra/k8s/app-config.yaml` — troque `rabbitmq.track-fraude.svc.cluster.local` (ou placeholder) pelo IP do PC1.

No **Secret** (`stringData`):

```yaml
rabbitmq-url: amqp://track_fraude:track_fraude@192.168.0.199:5672/%2F
postgres-url: postgresql://track_fraude:track_fraude@192.168.0.199:5432/track_fraude
atlas-api-key: atlas-dev-internal-key   # troque em produção
```

No **ConfigMap** (`settings.yaml`):

```yaml
pipeline:
  mode: queue

atlas:
  api_url: http://atlas-platform-api:8090
  api_key: atlas-dev-internal-key
```

O painel **não** publica mais direto no RabbitMQ — o Play chama a Platform API, que grava em `atlas.jobs` e publica na fila. A URL `rabbitmq-url` continua no Secret para a **Platform API**, o **worker** e o **KEDA**.

**Não** coloque a URL do RabbitMQ diretamente em `worker-scaledjob.yaml`. O worker e o KEDA já leem `rabbitmq-url` do Secret:

```yaml
- name: PIPELINE_QUEUE_URL
  valueFrom:
    secretKeyRef:
      name: track-fraude-secrets
      key: rabbitmq-url
```

Confirme que `worker-scaledjob.yaml` está assim (é o padrão do repositório). Se estiver, nenhuma edição extra no worker é necessária — basta corrigir `app-config.yaml` e aplicar de novo.

> Use o IP da LAN (`PC1_IP`), não `127.0.0.1`, porque os pods do K3s não alcançam `localhost` do host.

Checklist de edição:

- `data-nfs-pvc.yaml` com IP e path corretos
- Imagens com `${PC1_IP}:5000`
- `secret-key` trocada
- `app-config.yaml`: `rabbitmq-url` no Secret; `atlas.api_url` no ConfigMap
- `worker-scaledjob.yaml`: `PIPELINE_QUEUE_URL` via `secretKeyRef` (sem URL hardcoded)
- `atlas-platform-api.yaml`: imagem `${PC1_IP}:5000/atlas-platform-api:latest`

### 10.5 Conferir antes do `kubectl apply`

**Não aplique** os manifests com placeholders ainda presentes. Valide no terminal:

```bash
cd ~/track_fraude
PC1_IP=192.168.0.199   # ajuste

grep -c storageClassName infra/k8s/data-nfs-pvc.yaml    # deve imprimir 2
grep -nE 'CHANGE_ME|cluster\.local' infra/k8s/*.yaml || echo "OK: sem placeholders óbvios"
grep -n 'image:' infra/k8s/server-deployment.yaml infra/k8s/worker-scaledjob.yaml infra/k8s/atlas-platform-api.yaml
grep -nE 'server:|path:|storageClassName' infra/k8s/data-nfs-pvc.yaml
grep -nE 'rabbitmq-url|atlas-api-key|api_url' infra/k8s/app-config.yaml
```

Se `grep -c storageClassName` imprimir `0`, **pare** — sincronize os arquivos antes de continuar.

Esperado:

- Imagens com `${PC1_IP}:5000` (não `CHANGE_ME_REGISTRY`)
- NFS com `server: ${PC1_IP}` e `storageClassName: track-fraude-nfs` (duas linhas no grep)
- RabbitMQ com `${PC1_IP}:5672` (não `cluster.local`)
- Nenhum `CHANGE_ME_*` restante nos arquivos que você vai aplicar

---

## Passo 11 — Aplicar manifests no cluster

Confirme o **Passo 10.5** antes de continuar. Aplique **somente depois** de editar ou sincronizar os YAMLs no disco do `ctrl-p01` — o `kubectl apply` não enxerga arquivos que existem só no seu PC de desenvolvimento.

Confirme também que a infra Docker está no ar:

```bash
docker compose -f docker-compose.infra.yml ps
```

Ainda na raiz do repo:

```bash
cd ~/track_fraude

# Namespace, NFS, secrets, Atlas API, server, worker scaledjob, nvidia plugin
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/data-nfs-pvc.yaml
kubectl apply -f infra/k8s/app-config.yaml
kubectl apply -f infra/k8s/atlas-platform-api.yaml
kubectl apply -f infra/k8s/server-deployment.yaml
kubectl apply -f infra/k8s/worker-scaledjob.yaml
kubectl apply -f infra/k8s/nvidia-device-plugin.yaml
```

**Antes do primeiro deploy (Postgres já existente):** aplique o schema Atlas:

```bash
python tools/apply_atlas_schema.py
```

Instalações novas via `docker compose` já incluem `schema_atlas.sql` no initdb.

**Não aplique** `infra/k8s/control-plane-services.yaml` neste cenário — RabbitMQ e Postgres já rodam via `docker-compose.infra.yml`.

Verificar:

```bash
kubectl get pods -n track-fraude
kubectl get pvc -n track-fraude
kubectl get scaledjob -n track-fraude
```

- Namespace `track-fraude` criado
- PVC `track-fraude-data` bound
- Pod `atlas-platform-api` Running
- Pod do painel `track-fraude-server` Running (pode demorar no primeiro pull)
- ScaledJob `track-fraude-worker` criado

Atlas Platform API:

```text
http://PC1_IP:30090/v1/health
```

Painel via Kubernetes:

```text
http://ctrl-p01:30080/login
```

(ou `http://PC1_IP:30080/login` se não configurou DNS local)

Se o PVC ficou `Pending` com `storageClassName does not match`:

```bash
# 1. Arquivo no servidor tem storageClassName? (obrigatório)
grep storageClassName infra/k8s/data-nfs-pvc.yaml

# 2. Recriar PV+PVC (PV antigo pode ter storage class diferente)
kubectl delete pvc track-fraude-data -n track-fraude --ignore-not-found
kubectl delete pv track-fraude-data-nfs --ignore-not-found
kubectl apply -f infra/k8s/data-nfs-pvc.yaml

kubectl get pvc -n track-fraude   # deve mostrar Bound
kubectl rollout restart deployment/track-fraude-server -n track-fraude
```

Se o pod mostrar `Image: CHANGE_ME_REGISTRY:5000/...`, o deployment no servidor ainda não foi editado — corrija `server-deployment.yaml` e reaplique:

```bash
kubectl apply -f infra/k8s/server-deployment.yaml
kubectl rollout restart deployment/track-fraude-server -n track-fraude
```

---

## Passo 12 — Painel em `mode: queue` (alternativa: Docker no host)

Se preferir rodar o painel **fora** do K8s (mais simples para depurar no início), crie `server/config/settings.prod.yaml`:

```yaml
app:
  name: track_fraude
  host: 0.0.0.0
  port: 8080
  secret_key: SUA_SECRET_KEY_AQUI

database:
  path: /app/data/track_fraude.db

auth:
  admin_username: admin
  admin_password: SUA_SENHA_AQUI
  admin_display_name: Administrador

pipeline:
  mode: queue

atlas:
  api_url: http://192.168.0.199:8090   # Platform API no host ou K8s NodePort
  api_key: atlas-dev-internal-key
```

> Se a Platform API estiver no K8s, use `http://PC1_IP:30090` a partir do host. Dentro do cluster, o painel usa `http://atlas-platform-api:8090` (Service).

Subir painel:

```bash
cd ~/track_fraude
PC1_IP=192.168.0.199

docker run -d --name track-fraude-server --restart unless-stopped \
  -p 8080:8080 \
  -v /srv/track_fraude/data:/app/data \
  -v $(pwd)/server/config/settings.prod.yaml:/app/server/config/settings.yaml:ro \
  ${PC1_IP}:5000/track-fraude-server:latest \
  python server/main.py --settings /app/server/config/settings.yaml --host 0.0.0.0 --port 8080
```

Acesso:

```text
http://PC1_IP:8080/login
```

- Login funciona
- `settings.prod.yaml` com `mode: queue` e `atlas.api_url` apontando para a Platform API

> Use **ou** painel no K8s (porta 30080) **ou** painel no Docker (porta 8080), não os dois ao mesmo tempo sem necessidade. Em ambos os casos a Platform API deve estar no ar (K8s `:30090` ou processo local).

---

## Passo 13 — Migrar SQLite para Postgres (opcional, recomendado)

Enquanto a aplicação ainda usa SQLite no painel, Postgres já fica pronto para a próxima etapa.

```bash
cd ~/track_fraude
python3 -m venv .venv
source .venv/bin/activate
pip install "psycopg[binary]>=3.1"

python tools/migrate_sqlite_to_postgres.py \
  --sqlite /srv/track_fraude/data/track_fraude.db \
  --postgres-url postgresql://track_fraude:track_fraude@127.0.0.1:5432/track_fraude

python tools/apply_atlas_schema.py
```

- Migração concluída (se já existia banco)
- Schema `atlas.*` aplicado (workloads, jobs, api_keys)

---

## Passo 14 — Power Manager (quando tiver GPU node separado)

Só configure depois que existir pelo menos **1 GPU node** com Wake-on-LAN e SSH.

Guia detalhado dos campos (`name`, `mac`, `ssh_host`, `ssh_user`, comandos para obter MAC): **[config_node.md — Passo 0.1 Power Manager](config_node.md#power-manager-opcional)**. Subir o serviço: [Passo 11](config_node.md#passo-11--power-manager-opcional).

Resumo no **ctrl-p01**:

```bash
cd ~/track_fraude
cp infra/power-manager/config.example.json infra/power-manager/config.json
# Edite ~/track_fraude/infra/power-manager/config.json (MAC Ethernet, name = kubectl get nodes)
python3 infra/power-manager/power_manager.py --config infra/power-manager/config.json
```

O Power Manager balanceia **tempo ligado** entre os nodes (`total_on_sec`):

- **Ligar:** escolhe o node **offline** com **menor** `total_on_sec`
- **Desligar:** escolhe o node **ocioso** com **maior** `total_on_sec` (após `idle_shutdown_after_sec`)
- **Estado:** persiste em `infra/power-manager/power_state.json` (configurável via `state_file`)

Acorda node extra quando a fila tem mensagens e não há GPU livre (`free_gpus == 0`), há pods `Pending`, ou `mensagens > GPUs livres`.

Para systemd (sempre ligado no PC1):

```bash
sudo tee /etc/systemd/system/track-fraude-power-manager.service >/dev/null <<EOF
[Unit]
Description=Track Fraude Power Manager
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/track_fraude
ExecStart=$HOME/track_fraude/.venv/bin/python infra/power-manager/power_manager.py --config infra/power-manager/config.json
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now track-fraude-power-manager
```

Logs esperados:

```text
wake node-03: queue=2 free_gpus=0 pending_workers=1 total_on_sec=3600
shutdown node-01: idle_for=900s total_on_sec=86400
```

- Power manager configurado (pode pular nesta fase)

---

## Passo 15 — Validação final do PC 01

Execute esta checklist:

```bash
PC1_IP=192.168.0.199

# Infra Docker
docker compose -f ~/track_fraude/docker-compose.infra.yml ps

# Kubernetes
kubectl get nodes
kubectl get pods -n track-fraude
kubectl get scaledjob -n track-fraude

# Registry
curl -s http://${PC1_IP}:5000/v2/_catalog

# NFS
showmount -e ${PC1_IP}

# Atlas Platform API
curl -s http://${PC1_IP}:30090/v1/health

# RabbitMQ fila (após primeiro Play)
curl -s -u track_fraude:track_fraude http://${PC1_IP}:15672/api/queues/%2F/track-fraude-pipelines
```

Checklist manual:

- PC1 responde ping na rede
- Registry, RabbitMQ e Postgres rodando
- K3s node Ready
- KEDA Running
- NFS export visível
- Imagens server, worker e **atlas-platform-api** no registry
- Pod `atlas-platform-api` Running; `GET /v1/health` ok
- Painel abre no navegador
- `pipeline.mode: queue` e `atlas.api_url` no settings do painel

---

## O que ainda falta (próximo PC — GPU node)

Este guia **não** processa vídeo sozinho. Antes de adicionar o GPU node, confirme no **ctrl-p01**:

```bash
cd ~/track_fraude
python tools/verify_fase1.py --api-url http://127.0.0.1:30090
curl -s http://127.0.0.1:30090/v1/health
curl -s http://127.0.0.1:30080/health
kubectl get pods -n track-fraude
kubectl delete jobs -n track-fraude --all   # opcional: limpar Pending sem GPU
```

Para adicionar o primeiro GPU node, siga o guia dedicado:

**[docs/config_node.md](config_node.md)** — passo a passo para `node-01` (K3s agent + NVIDIA + NFS).

Resumo do que o GPU node precisa:

| Item                                       | GPU node |
| ------------------------------------------ | -------- |
| Ubuntu Server                              | Sim      |
| Driver NVIDIA + `nvidia-smi`               | Sim      |
| NVIDIA Container Toolkit                   | Sim      |
| K3s **agent** apontando para `PC1_IP`      | Sim      |
| Acesso ao NFS `PC1_IP:/srv/track_fraude/data` | Sim   |
| Registry `PC1_IP:5000` em `registries.yaml` | Sim   |


Quando o GPU node entrar no cluster:

```bash
kubectl describe node <nome-gpu-node> | grep -A5 nvidia.com/gpu
```

Capacidade:

```text
1 GPU  = 1 pipeline simultâneo
2 GPUs = 2 pipelines simultâneos
```

---

## Resumo — ordem de instalação

1. [ ] Ubuntu + IP fixo + firewall
2. [ ] Nomes locais (`/etc/hosts` ou dnsmasq)
3. [ ] Storage `/srv/track_fraude/data` + NFS
4. [ ] Clone do repo
5. [ ] Docker + Compose (registry, rabbitmq, postgres)
6. [ ] K3s server
7. [ ] Registry no K3s
8. [ ] KEDA
9. [ ] `insecure-registries` no Docker (`daemon.json`)
10. [ ] Build/push imagens (server, worker, **atlas-platform-api**)
11. [ ] Editar manifests (`PC1_IP`, NFS, secrets, Atlas API)
12. [ ] Sincronizar no `ctrl-p01` (`git pull` ou `scp`) se editou em outro PC
13. [ ] Conferir YAMLs com `grep` (Passo 10.5)
14. [ ] `python tools/apply_atlas_schema.py` (Postgres existente)
15. [ ] `kubectl apply` namespace, nfs, app, **atlas-platform-api**, server, worker
16. [ ] Painel `mode: queue` + Platform API `:30090/health` ok
17. [ ] Validar serviços
18. [ ] Adicionar GPU node — [config_node.md](config_node.md)

---

## Referências no repositório


| Arquivo                                  | Uso                                 |
| ---------------------------------------- | ----------------------------------- |
| `docker-compose.infra.yml`               | Registry, RabbitMQ, Postgres no PC1 |
| `infra/k8s/`                             | Manifests K3s/KEDA                  |
| `docs/fase0_base_operacional.md`         | Checklist Fase 0                    |
| `docs/fase1_atlas_fundacao.md`           | Platform API + schema `atlas.*`     |
| `docs/k3s_comandos_operacionais.md`      | kubectl: listar, logs, limpar Pending |
| `docs/config_node.md`                    | Setup GPU node (`node-01`)          |
| `Dockerfile.atlas-platform-api`          | Imagem da Platform API              |
| `tools/apply_atlas_schema.py`            | Schema Atlas em Postgres existente  |
| `infra/k3s/registries.yaml.example`      | Modelo registry                     |
| `infra/power-manager/`                   | Liga/desliga GPU nodes              |
| `docs/arquitetura_serverless_on_prem.md` | Visão geral da arquitetura          |
| `infra/README.md`                        | Comandos operacionais               |


---

## Problemas comuns


| Sintoma                                 | Causa provável                       | Ação                                       |
| --------------------------------------- | ------------------------------------ | ------------------------------------------ |
| YAMLs corretos no Windows, cluster errado | Alterações não sincronizadas no servidor | `git pull` ou `scp` no `ctrl-p01`; Passo 10.5 |
| PVC `Pending`, `VolumeMismatch`         | Arquivo sem `storageClassName` ou K3s usou `local-path` | `grep storageClassName` no servidor; recriar PV+PVC (Passo 11) |
| Pod painel `Pending`, PVC não bound     | PVC sem bind ao PV NFS               | `kubectl describe pvc`; recriar claim (Passo 11) |
| `:30080` não abre de outro PC           | Pod não `Running` ou firewall        | `kubectl get pods`; `sudo ufw allow 30080/tcp` |
| `ImagePullBackOff` no painel            | Registry inacessível ou imagem errada | Conferir `PC1_IP:5000`, `registries.yaml`; imagem não pode ser `CHANGE_ME_REGISTRY` |
| `_catalog` vazio após push              | Push falhou ou registry parado       | Ver saída do `docker push`; Passo 9.1      |
| `HTTP response to HTTPS client` no push | Falta `insecure-registries`          | Passo 9.1 (`/etc/docker/daemon.json`)      |
| Pod worker não sobe                     | Sem GPU node no cluster              | [config_node.md](config_node.md); limpar jobs Pending → [k3s_comandos_operacionais.md](k3s_comandos_operacionais.md) |
| Play não enfileira                      | Atlas API down, `atlas.api_url` errada ou API key inválida | `curl :30090/v1/health`; logs `atlas-platform-api`; `app-config.yaml` |
| Play: “Nenhuma data importada”          | Vídeos fora do export NFS ou pod sem ver o mount | Copiar para `/srv/track_fraude/data/raw/...`; `kubectl exec -n track-fraude deploy/track-fraude-server -- ls /app/data/raw/default/LOJA-01` |
| Pod `atlas-platform-api` Error          | Schema `atlas.*` ausente ou Postgres inacessível | `python tools/apply_atlas_schema.py`; `kubectl logs -n track-fraude -l app=atlas-platform-api` |
| NFS mount falha                         | Export ou firewall                   | `showmount -e`, ufw porta 2049             |
| Fila cheia, nada roda                   | KEDA ou ScaledJob                    | `kubectl get scaledjob -n track-fraude`    |


Quando o GPU node estiver pronto, o fluxo completo fica:

```text
Play no painel → Atlas Platform API → RabbitMQ → KEDA → Job no K3s → GPU node → NFS → status no banco
```

