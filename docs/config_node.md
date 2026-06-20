# Configuração do GPU Node — `node_01`

Guia passo a passo para adicionar o **primeiro servidor GPU** ao cluster K3s do `track_fraude`.

Neste cenário:

- O **control plane** já está pronto (`ctrlp01` / `PC1_IP`) — veja [config_control_plane.md](config_control_plane.md).
- Este guia configura **`node_01`**, que entra no cluster como **K3s agent** e processa pipelines via container `track-fraude-worker`.
- Você **não** instala Python, Ultralytics ou worker `.venv` no host — tudo roda na imagem Docker puxada do registry do PC1.

**Sistema alvo:** Ubuntu Server (somente terminal, sem interface gráfica).

---

## O que este node faz

| Função | O que roda aqui |
|--------|-----------------|
| Processamento GPU | Jobs KEDA → `track-fraude-worker` (1 GPU por job) |
| Orquestração | K3s **agent** conectado ao `ctrlp01` |
| Dados | Monta o mesmo NFS do PC1 (`/srv/track_fraude/data`) dentro dos pods |
| Imagens | Puxa `track-fraude-worker` do registry `PC1_IP:5000` |

**Este node não roda:** painel, RabbitMQ, Postgres, registry ou KEDA (isso fica no control plane).

---

## Pré-requisitos no control plane (`ctrlp01`)

Antes de ligar o `node_01`, confirme no PC1:

| Item | Como verificar |
|------|----------------|
| K3s server `Ready` | `kubectl get nodes` no PC1 |
| Registry com imagem worker | `curl -s http://PC1_IP:5000/v2/_catalog` |
| RabbitMQ no ar | `docker compose -f docker-compose.infra.yml ps` |
| NFS export ativo | `showmount -e localhost` → `/srv/track_fraude/data` |
| KEDA instalado | `kubectl get pods -n keda` |
| ScaledJob criado | `kubectl get scaledjob -n track-fraude` |
| NVIDIA Device Plugin | `kubectl get ds -n kube-system nvidia-device-plugin-daemonset` |
| Painel `mode: queue` | `infra/k8s/app-config.yaml` |

---

## Antes de começar — checklist

Preencha estes valores:

| Variável | Exemplo | Seu valor |
|----------|---------|-----------|
| `PC1_IP` | `192.168.0.199` | ______________ |
| `NODE01_IP` | `192.168.0.201` | ______________ |
| `NODE01_HOSTNAME` | `node_01` | ______________ |
| `NODE01_DNS` | `node-01` | ______________ |
| `NODE01_MAC` | `AA:BB:CC:DD:EE:01` | ______________ |
| `USUARIO` | `eduardo` | ______________ |
| `K3S_TOKEN` | (copiar do PC1) | ______________ |

Requisitos de hardware sugeridos:

- GPU NVIDIA (RTX série 30/40 ou equivalente com driver Linux)
- CPU 4+ núcleos, 16 GB+ RAM
- SSD 256 GB+ para sistema
- Rede cabeada (IP fixo no roteador)
- **Não** precisa de disco grande de vídeos — os dados vêm do NFS do PC1

---

## Visão do que vamos instalar

```text
node_01 (este guia)
├── Ubuntu Server
├── Driver NVIDIA + nvidia-smi
├── NVIDIA Container Toolkit (GPU nos containers)
├── nfs-common (cliente NFS para volumes K8s)
├── K3s agent → conecta em https://PC1_IP:6443
└── registries.yaml → puxa imagens de PC1_IP:5000

ctrlp01 (já pronto)
├── K3s server + KEDA + ScaledJob
├── Registry :5000
├── RabbitMQ :5672
└── NFS export /srv/track_fraude/data
```

Fluxo após configurado:

```text
Play no painel → RabbitMQ → KEDA → Job no node_01 → GPU → NFS → status no banco
```

---

## Passo 0 — Ubuntu Server base

Conecte por SSH no `node_01` recém-instalado.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  curl wget git vim ca-certificates gnupg lsb-release \
  nfs-common \
  build-essential pkg-config
```

Fuso horário:

```bash
sudo timedatectl set-timezone America/Sao_Paulo
sudo timedatectl set-ntp true
timedatectl status
```

Hostname e IP fixo (ajuste interface e IP):

```bash
sudo hostnamectl set-hostname node_01

# Exemplo netplan — EDITE conforme sua rede
sudo tee /etc/netplan/01-track-fraude.yaml >/dev/null <<'EOF'
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: false
      addresses:
        - 192.168.0.201/24
      routes:
        - to: default
          via: 192.168.0.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
EOF

sudo netplan apply
hostname
ip a
```

- `hostname` mostra `node_01`
- `ip a` mostra `NODE01_IP` correto

---

## Passo 0.1 — Nomes locais (DNS / hosts)

Configure os mesmos nomes do [config_control_plane.md](config_control_plane.md) (Passo 0.1) neste PC e no seu notebook.

| Nome (SSH) | IP | Este node |
|------------|-----|-----------|
| `ctrl-p01` | `192.168.0.199` | control plane |
| `node-01`  | `192.168.0.201` | **este guia** |

No `node_01`:

```bash
sudo tee -a /etc/hosts >/dev/null <<'EOF'
192.168.0.199   ctrl-p01 ctrlp01
192.168.0.201   node-01 node01
EOF
```

Teste:

```bash
ping -c1 ctrl-p01
hostname -f   # ou hostname → node_01
```

A partir do notebook ou do ctrl-p01:

```bash
ssh ${USUARIO}@node-01
```

No Power Manager (`config.json` no PC1), use nome em vez de IP:

```json
"ssh_host": "node-01"
```

> Manifests Kubernetes no PC1 podem continuar com IP (`192.168.0.199`). Nomes locais são para SSH, browser e operação.

- `ping ctrl-p01` funciona a partir do node
- `ssh usuario@ctrl-p01` funciona (opcional, para manutenção cruzada)

---

## Passo 1 — Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

O node **não** expõe painel nem registry. O tráfego principal é:

- **Saída** para `PC1_IP:6443` (K3s API)
- **Saída** para `PC1_IP:5000` (registry)
- **Saída** para `PC1_IP:2049` (NFS)

No **PC1**, confirme que a rede dos nodes pode montar NFS (já configurado no guia do control plane):

```bash
# No ctrlp01 — porta 2049 liberada para a LAN
sudo ufw status | grep 2049
```

---

## Passo 2 — Driver NVIDIA

Instale o driver recomendado para sua GPU:

```bash
sudo ubuntu-drivers devices
sudo ubuntu-drivers autoinstall
```

Ou escolha uma versão específica (exemplo):

```bash
sudo apt install -y nvidia-driver-550
```

Reinicie:

```bash
sudo reboot
```

Após voltar, valide:

```bash
nvidia-smi
```

Esperado: tabela com nome da GPU, driver e memória. Se falhar, o restante do guia não funciona.

> Ative Wake-on-LAN na BIOS/UEFI se planejar usar o Power Manager para ligar o node sob demanda.

---

## Passo 3 — NVIDIA Container Toolkit

Permite que containers do K3s usem a GPU.

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
```

---

## Passo 4 — Cliente NFS (teste de conectividade)

O worker monta `data/` via volume NFS do Kubernetes. O node precisa alcançar o export do PC1.

Substitua `PC1_IP`:

```bash
PC1_IP=192.168.0.199

showmount -e ${PC1_IP}
sudo mkdir -p /srv/track_fraude/data
sudo mount -t nfs ${PC1_IP}:/srv/track_fraude/data /srv/track_fraude/data
ls -la /srv/track_fraude/data
sudo umount /srv/track_fraude/data
```

- `showmount` lista o export
- `mount` funciona sem erro

> Esse mount manual é só teste. Em produção, quem monta nos workers é o **kubelet** ao subir o pod.

---

## Passo 5 — Token do cluster (no `ctrlp01`)

No **control plane**, copie o token de join:

```bash
# No ctrlp01
sudo cat /var/lib/rancher/k3s/server/node-token
```

Anote o valor em `K3S_TOKEN`.

Confirme que o node alcança a API:

```bash
# No node_01
PC1_IP=192.168.0.199
# ou: PC1_DNS=ctrl-p01

curl -k https://${PC1_IP}:6443/ping
# curl -k https://ctrl-p01:6443/ping
```

Resposta esperada: `pong`

---

## Passo 6 — Registry no K3s agent

Antes de entrar no cluster, configure o mirror do registry local (substitua `PC1_IP`):

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
```

---

## Passo 7 — Entrar no cluster como K3s agent

No `node_01`:

```bash
PC1_IP=192.168.0.199
K3S_TOKEN="COLE_O_TOKEN_DO_PC1_AQUI"
K3S_NODE_NAME=node_01

curl -sfL https://get.k3s.io | \
  K3S_URL="https://${PC1_IP}:6443" \
  K3S_TOKEN="${K3S_TOKEN}" \
  sh -s - agent --node-name "${K3S_NODE_NAME}"
```

Aguarde o serviço subir:

```bash
sudo systemctl status k3s-agent --no-pager
```

No **ctrlp01**, confirme que o node apareceu:

```bash
kubectl get nodes
```

Esperado:

```text
NAME      STATUS   ROLES                  AGE   VERSION
ctrlp01   Ready    control-plane,master   ...   v1.x.x+k3s
node_01   Ready    <none>                 ...   v1.x.x+k3s
```

---

## Passo 8 — GPU no containerd do K3s

Configure o runtime NVIDIA no containerd usado pelo K3s agent:

```bash
sudo nvidia-ctk runtime configure \
  --runtime=containerd \
  --config /var/lib/rancher/k3s/agent/etc/containerd/config.toml

sudo systemctl restart k3s-agent
```

Valide que o runtime enxerga a GPU:

```bash
sudo k3s crictl info | grep -i nvidia
```

---

## Passo 9 — Validar GPU no cluster (no `ctrlp01`)

O NVIDIA Device Plugin já foi aplicado no control plane. Após o `node_01` entrar, confira:

```bash
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds -o wide
kubectl describe node node_01 | grep -A6 "nvidia.com/gpu"
```

Esperado em `Capacity` e `Allocatable`:

```text
nvidia.com/gpu:  1
```

(ou `2`, se a máquina tiver duas GPUs)

---

## Passo 10 — Teste de pipeline (Play)

1. No painel (`http://ctrl-p01:30080` ou `http://PC1_IP:30080`), cadastre grupo/loja/câmeras se ainda não existirem.
2. Coloque vídeos em `data/raw/...` no NFS do PC1 (`/srv/track_fraude/data/raw/...`).
3. Clique **Play** em uma data com vídeo importado.

No **ctrlp01**, acompanhe:

```bash
# Fila RabbitMQ
curl -s -u track_fraude:track_fraude \
  http://192.168.0.199:15672/api/queues/%2F/track-fraude-pipelines

# Jobs criados pelo KEDA
kubectl get jobs -n track-fraude -w

# Pod do worker (deve ir para node_01)
kubectl get pods -n track-fraude -o wide

# Logs do job (substitua o nome)
kubectl logs -n track-fraude job/<nome-do-job> -f
```

Sucesso esperado:

- Mensagem na fila RabbitMQ
- Job `track-fraude-worker-...` criado
- Pod `Running` no `node_01`
- Logs mostram `run_daily_pipeline.py` executando

Capacidade:

```text
1 GPU  = 1 pipeline simultâneo neste node
2 GPUs = 2 pipelines simultâneos neste node
```

---

## Passo 11 — Power Manager (opcional)

Para ligar/desligar nodes sob demanda com **rodízio por tempo ligado**, configure o Power Manager no **ctrlp01** (não neste node).

Política `total_on_sec`:

| Ação | Regra |
|------|--------|
| Wake-on-LAN | Node offline com **menor** tempo acumulado ligado |
| Shutdown | Node ocioso com **maior** tempo acumulado ligado |

```bash
# No ctrlp01
cd ~/track_fraude
cp infra/power-manager/config.example.json infra/power-manager/config.json
```

Edite `infra/power-manager/config.json`:

```json
{
  "rabbitmq_api_url": "http://192.168.0.199:15672/api/queues/%2F/track-fraude-pipelines",
  "rabbitmq_username": "track_fraude",
  "rabbitmq_password": "track_fraude",
  "namespace": "track-fraude",
  "worker_label_selector": "scaledjob.keda.sh/name=track-fraude-worker",
  "poll_interval_sec": 30,
  "idle_shutdown_after_sec": 900,
  "nodes": [
    {
      "name": "node_01",
      "mac": "AA:BB:CC:DD:EE:01",
      "broadcast": "192.168.0.255",
      "ssh_host": "node-01",
      "ssh_user": "eduardo"
    }
  ]
}
```

Suba o serviço no PC1 conforme [config_control_plane.md](config_control_plane.md) (Passo 14).

---

## Validação final do `node_01`

Execute no **ctrlp01**:

```bash
PC1_IP=192.168.0.199

kubectl get nodes
kubectl describe node node_01 | grep -E "nvidia.com/gpu|Ready"
kubectl get scaledjob -n track-fraude
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds -o wide
```

Checklist manual:

- [ ] `node_01` aparece `Ready` em `kubectl get nodes`
- [ ] `nvidia-smi` funciona no `node_01`
- [ ] `nvidia.com/gpu` visível em `kubectl describe node node_01`
- [ ] `showmount -e PC1_IP` funciona no `node_01`
- [ ] Play no painel cria job e pod no `node_01`
- [ ] Logs do worker progridem sem `ImagePullBackOff` nem erro de NFS

---

## Adicionar `node_02`, `node_03`...

Repita este guia em cada PC GPU novo:

1. Ubuntu + driver NVIDIA + Container Toolkit
2. IP fixo + hostname único (`node_02`, etc.)
3. `registries.yaml` apontando para o mesmo `PC1_IP:5000`
4. `k3s agent` com `--node-name` único e o **mesmo** `K3S_TOKEN`
5. `nvidia-ctk` + restart `k3s-agent`
6. Validar `kubectl describe node node_02`

**Não** é necessário refazer registry, RabbitMQ, KEDA ou ScaledJob no PC1.

Capacidade total:

```text
pipelines simultâneos = soma de todas as GPUs em todos os nodes Ready
```

---

## Resumo — ordem de instalação

1. [ ] Control plane pronto ([config_control_plane.md](config_control_plane.md))
2. [ ] Ubuntu + IP fixo + hostname `node_01`
3. [ ] Nomes locais (`/etc/hosts`: `ctrl-p01`, `node-01`)
4. [ ] Driver NVIDIA + `nvidia-smi`
5. [ ] NVIDIA Container Toolkit
6. [ ] Teste NFS (`showmount` / `mount` do PC1)
7. [ ] Token K3s copiado do PC1
8. [ ] `registries.yaml` no agent
9. [ ] `k3s agent` join no cluster
10. [ ] `nvidia-ctk` + restart `k3s-agent`
11. [ ] Validar `nvidia.com/gpu` no node
12. [ ] Teste Play → job no `node_01`
13. [ ] (Opcional) Power Manager no PC1

---

## Referências no repositório

| Arquivo | Uso |
|---------|-----|
| [config_control_plane.md](config_control_plane.md) | Setup do `ctrlp01` |
| `infra/k3s/registries.yaml.example` | Modelo registry para agents |
| `infra/k8s/worker-scaledjob.yaml` | Job GPU escalado por KEDA |
| `infra/k8s/nvidia-device-plugin.yaml` | Expõe GPUs no cluster |
| `infra/power-manager/` | Liga/desliga nodes GPU |
| [arquitetura_serverless_on_prem.md](arquitetura_serverless_on_prem.md) | Visão geral |

---

## Problemas comuns

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| `node_01` não aparece em `kubectl get nodes` | Token errado ou firewall no PC1 (`6443`) | Refazer join; `curl -k https://PC1_IP:6443/ping` |
| `nvidia-smi` falha | Driver não instalado ou reboot pendente | Passo 2 |
| Sem `nvidia.com/gpu` no node | Container Toolkit ou device plugin | Passos 3, 8, 9 |
| Worker `ImagePullBackOff` | Registry inacessível | `registries.yaml` no node; testar `curl http://PC1_IP:5000/v2/_catalog` |
| Worker `Pending` (GPU) | Sem GPU alocável no cluster | `kubectl describe node node_01`; device plugin Running |
| Worker falha ao montar volume | NFS bloqueado | `showmount -e PC1_IP`; ufw porta 2049 no PC1 |
| Job criado mas não roda no node | Node `NotReady` ou sem GPU livre | `kubectl describe node`; jobs antigos ocupando GPU |
| ScaledJob `READY Unknown` | Normal sem fila ou KEDA validando | Enfileirar job com Play; checar logs do KEDA |
| Play não enfileira | Painel fora de `mode: queue` | `app-config.yaml` no PC1 |

---

## Comandos úteis no dia a dia

```bash
# No ctrlp01 — visão geral
kubectl get nodes
kubectl get pods -n track-fraude -o wide
kubectl get jobs -n track-fraude

# No node_01 — saúde local
nvidia-smi
sudo systemctl status k3s-agent
sudo k3s crictl ps
```

Quando tudo estiver certo:

```text
Play no painel → RabbitMQ → KEDA → Job no node_01 → GPU → NFS → status no banco
```
