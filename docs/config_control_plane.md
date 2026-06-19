# Configuração do PC 01 — Control Plane unificado + Storage

Guia passo a passo para montar o **primeiro servidor** da arquitetura `pipeline.mode: queue`.

Neste cenário inicial:

- **PC 01** concentra control plane **e** storage (PC 1 + PC 2 do diagrama unificados).
- Você ainda **não precisa** de 3 GPU nodes; basta preparar o orquestrador.
- Depois você adiciona **1 GPU node** (ou mais) sem refazer este servidor.

**Sistema alvo:** Ubuntu Server (somente terminal, sem interface gráfica).

---

## O que este PC faz


| Função              | O que roda aqui                                                |
| ------------------- | -------------------------------------------------------------- |
| Painel web          | Interface FastAPI (botão Play em `mode: queue`)                |
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
| `PC1_IP`             | `192.168.0.10`         | ______________ |
| `PC1_HOSTNAME`       | `ctrl_p01`             | ______________ |
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

Defina hostname e IP fixo (ajuste interface e IP):

```bash
sudo hostnamectl set-hostname ctrl_p01

# Exemplo netplan — EDITE conforme sua rede
sudo tee /etc/netplan/01-track-fraude.yaml >/dev/null <<'EOF'
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: false
      addresses:
        - 192.168.0.10/24
      routes:
        - to: default
          via: 192.168.0.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
EOF

sudo netplan apply
```

- `hostname` mostra `ctrl_p01`
- `ip a` mostra o IP fixo correto (`PC1_IP`)

---

## Passo 1 — Usuário e firewall

```bash
# Se ainda não existe, use o usuário criado na instalação do Ubuntu
whoami
sudo ufw status

sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp    # painel web
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

Substitua `PC1_IP` pelo IP real (ex.: `192.168.0.10`):

```bash
PC1_IP=192.168.0.10

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

```bash
cd ~/track_fraude
PC1_IP=192.168.0.10   # ajuste

docker build -f Dockerfile.server -t ${PC1_IP}:5000/track-fraude-server:latest .
docker build -f Dockerfile.worker -t ${PC1_IP}:5000/track-fraude-worker:latest .

docker push ${PC1_IP}:5000/track-fraude-server:latest
docker push ${PC1_IP}:5000/track-fraude-worker:latest
```

Validação:

```bash
curl -s http://${PC1_IP}:5000/v2/_catalog
```

Deve listar `track-fraude-server` e `track-fraude-worker`.

- Imagens no registry local

> O build do worker é pesado (CUDA/PyTorch). Pode levar vários minutos na primeira vez.

---

## Passo 10 — Preparar manifests Kubernetes

Edite os placeholders antes de aplicar.

### 10.1 NFS (`infra/k8s/data-nfs-pvc.yaml`)

Troque:

```yaml
server: CHANGE_ME_NAS_IP
path: /exports/track_fraude/data
```

Por:

```yaml
server: 192.168.0.10        # PC1_IP
path: /srv/track_fraude/data
```

### 10.2 Imagens (`infra/k8s/server-deployment.yaml` e `worker-scaledjob.yaml`)

Troque `CHANGE_ME_REGISTRY:5000` por `192.168.0.10:5000`.

### 10.3 Segredos (`infra/k8s/app-config.yaml`)

Troque `CHANGE_ME_RANDOM_SECRET` por uma chave forte e ajuste senha do admin se quiser.

### 10.4 RabbitMQ no worker (host, não cluster interno)

Os serviços RabbitMQ rodam via **docker-compose no host**, não dentro do K8s.  
Edite `infra/k8s/app-config.yaml` e o Secret para usar o IP do PC1:

```yaml
queue_url: amqp://track_fraude:track_fraude@192.168.0.10:5672/%2F
```

E em `infra/k8s/worker-scaledjob.yaml`, confirme:

```yaml
- name: PIPELINE_QUEUE_URL
  value: amqp://track_fraude:track_fraude@192.168.0.10:5672/%2F
```

> Use o IP da LAN (`PC1_IP`), não `127.0.0.1`, porque os pods do K3s precisam alcançar o RabbitMQ no host.

Checklist de edição:

- `data-nfs-pvc.yaml` com IP e path corretos
- Imagens com `${PC1_IP}:5000`
- `secret-key` trocada
- `queue_url` apontando para `PC1_IP:5672`

---

## Passo 11 — Aplicar manifests no cluster

Ainda na raiz do repo:

```bash
cd ~/track_fraude

# Namespace, NFS, secrets, server, worker scaledjob, nvidia plugin
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/data-nfs-pvc.yaml
kubectl apply -f infra/k8s/app-config.yaml
kubectl apply -f infra/k8s/server-deployment.yaml
kubectl apply -f infra/k8s/worker-scaledjob.yaml
kubectl apply -f infra/k8s/nvidia-device-plugin.yaml
```

**Não aplique** `infra/k8s/control-plane-services.yaml` neste cenário — RabbitMQ e Postgres já rodam via `docker-compose.infra.yml`.

Verificar:

```bash
kubectl get pods -n track-fraude
kubectl get pvc -n track-fraude
kubectl get scaledjob -n track-fraude
```

- Namespace `track-fraude` criado
- PVC `track-fraude-data` bound
- Pod do painel `track-fraude-server` Running (pode demorar no primeiro pull)
- ScaledJob `track-fraude-worker` criado

Painel via Kubernetes:

```text
http://PC1_IP:30080/login
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
  python:
  queue_url: amqp://track_fraude:track_fraude@192.168.0.10:5672/%2F
  queue_name: track-fraude-pipelines
```

Subir painel:

```bash
cd ~/track_fraude
PC1_IP=192.168.0.10

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
- `settings.prod.yaml` com `mode: queue`

> Use **ou** painel no K8s (porta 30080) **ou** painel no Docker (porta 8080), não os dois ao mesmo tempo sem necessidade.

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
```

- Migração concluída (se já existia banco)

---

## Passo 14 — Power Manager (quando tiver GPU node separado)

Só configure depois que existir pelo menos **1 GPU node** com Wake-on-LAN ou SSH.

```bash
cd ~/track_fraude
cp infra/power-manager/config.example.json infra/power-manager/config.json
# Edite MAC, IP, nome do node
python3 infra/power-manager/power_manager.py --config infra/power-manager/config.json
```

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

- Power manager configurado (pode pular nesta fase)

---

## Passo 15 — Validação final do PC 01

Execute esta checklist:

```bash
PC1_IP=192.168.0.10

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

# RabbitMQ fila (após primeiro Play)
curl -s -u track_fraude:track_fraude http://${PC1_IP}:15672/api/queues/%2F/track-fraude-pipelines
```

Checklist manual:

- PC1 responde ping na rede
- Registry, RabbitMQ e Postgres rodando
- K3s node Ready
- KEDA Running
- NFS export visível
- Imagens server e worker no registry
- Painel abre no navegador
- `pipeline.mode: queue` no settings do painel

---

## O que ainda falta (próximo PC — GPU node)

Este guia **não** processa vídeo sozinho. Falta **1 GPU node** mínimo:


| Item                                       | GPU node |
| ------------------------------------------ | -------- |
| Ubuntu Server                              | Sim      |
| Driver NVIDIA + `nvidia-smi`               | Sim      |
| NVIDIA Container Toolkit                   | Sim      |
| K3s **agent** apontando para `PC1_IP`      | Sim      |
| Montar NFS `PC1_IP:/srv/track_fraude/data` | Sim      |
| Registry `PC1_IP:5000` em registries.yaml  | Sim      |


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
2. [ ] Storage `/srv/track_fraude/data` + NFS
3. [ ] Clone do repo
4. [ ] Docker + Compose (registry, rabbitmq, postgres)
5. [ ] K3s server
6. [ ] Registry no K3s
7. [ ] KEDA
8. [ ] Build/push imagens
9. [ ] Editar manifests (`PC1_IP`, NFS, secrets)
10. [ ] `kubectl apply` namespace, nfs, app, server, worker
11. [ ] Painel `mode: queue`
12. [ ] Validar serviços
13. [ ] Adicionar GPU node (próximo guia)

---

## Referências no repositório


| Arquivo                                  | Uso                                 |
| ---------------------------------------- | ----------------------------------- |
| `docker-compose.infra.yml`               | Registry, RabbitMQ, Postgres no PC1 |
| `infra/k8s/`                             | Manifests K3s/KEDA                  |
| `infra/k3s/registries.yaml.example`      | Modelo registry                     |
| `infra/power-manager/`                   | Liga/desliga GPU nodes              |
| `docs/arquitetura_serverless_on_prem.md` | Visão geral da arquitetura          |
| `infra/README.md`                        | Comandos operacionais               |


---

## Problemas comuns


| Sintoma               | Causa provável                       | Ação                                       |
| --------------------- | ------------------------------------ | ------------------------------------------ |
| Pod worker não sobe   | Sem GPU node no cluster              | Adicionar GPU node                         |
| `ImagePullBackOff`    | Registry inacessível                 | Conferir `PC1_IP:5000` e `registries.yaml` |
| Play não enfileira    | `mode: local` ou URL RabbitMQ errada | `mode: queue` + IP LAN                     |
| NFS mount falha       | Export ou firewall                   | `showmount -e`, ufw porta 2049             |
| Fila cheia, nada roda | KEDA ou ScaledJob                    | `kubectl get scaledjob -n track-fraude`    |


Quando o GPU node estiver pronto, o fluxo completo fica:

```text
Play no painel → RabbitMQ → KEDA → Job no K3s → GPU node → NFS → status no banco
```

