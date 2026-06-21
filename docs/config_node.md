# Configuração do GPU Node — `node-01`

Guia passo a passo para adicionar o **primeiro servidor GPU** ao cluster K3s do `track_fraude`.

Neste cenário:

- O **control plane** já está pronto (`ctrl-p01` / `PC1_IP`) — veja [config_control_plane.md](config_control_plane.md).
- **Fase 0 + Fase 1** concluídas no PC1: Postgres, Atlas Platform API, painel enfileirando via API — [fase1_atlas_fundacao.md](fase1_atlas_fundacao.md).
- Este guia configura **`node-01`**, que entra no cluster como **K3s agent** e processa pipelines via container `track-fraude-worker`.
- Você **não** instala Python, Ultralytics ou worker `.venv` no host — tudo roda na imagem Docker puxada do registry do PC1.

**Sistema alvo:** Ubuntu Server (somente terminal, sem interface gráfica).

---

## O que este node faz


| Função            | O que roda aqui                                                     |
| ----------------- | ------------------------------------------------------------------- |
| Processamento GPU | Jobs KEDA → `track-fraude-worker` (1 GPU por job)                   |
| Orquestração      | K3s **agent** conectado ao `ctrl-p01`                               |
| Dados             | Monta o mesmo NFS do PC1 (`/srv/track_fraude/data`) dentro dos pods |
| Imagens           | Puxa `track-fraude-worker` do registry `PC1_IP:5000`                |


**Este node não roda:** painel, RabbitMQ, Postgres, registry ou KEDA (isso fica no control plane).

---

## Pré-requisitos no control plane (`ctrl-p01`)

Antes de ligar o `node-01`, confirme no PC1:


| Item                        | Como verificar                                                                    |
| --------------------------- | --------------------------------------------------------------------------------- |
| K3s server `Ready`          | `kubectl get nodes` no PC1                                                        |
| Registry com imagens        | `curl -s http://PC1_IP:5000/v2/_catalog` → server, worker, **atlas-platform-api** |
| RabbitMQ no ar              | `docker compose -f docker-compose.infra.yml ps`                                   |
| Postgres + schema `atlas.`* | `python tools/apply_atlas_schema.py` (se ainda não rodou)                         |
| NFS export ativo            | `showmount -e localhost` → `/srv/track_fraude/data`                               |
| KEDA instalado              | `kubectl get pods -n keda`                                                        |
| ScaledJob criado            | `kubectl get scaledjob -n track-fraude`                                           |
| RuntimeClass `nvidia`       | `kubectl get runtimeclass nvidia` (aplicada no Passo 11 do control plane)         |
| NVIDIA Device Plugin DS     | `kubectl get ds -n kube-system nvidia-device-plugin-daemonset`                    |
| Atlas Platform API          | `curl -s http://127.0.0.1:30090/v1/health` → `ok`                                 |
| Painel + Atlas no ConfigMap | `grep -E 'mode: queue|api_url' infra/k8s/app-config.yaml`                         |
| Verificação Fase 1          | `python tools/verify_fase1.py --api-url http://127.0.0.1:30090`                   |


Opcional antes do primeiro Play com GPU: limpar jobs worker antigos em Pending (sem GPU):

```bash
kubectl delete jobs -n track-fraude --all
```

Ver [k3s_comandos_operacionais.md](k3s_comandos_operacionais.md).

---

## Antes de começar — checklist

Preencha estes valores:


| Variável          | Exemplo             | Seu valor      |
| ----------------- | ------------------- | -------------- |
| `PC1_IP`          | `192.168.0.199`     | ______________ |
| `NODE01_IP`       | `192.168.0.201`     | ______________ |
| `NODE01_HOSTNAME` | `node-01`           | ______________ |
| `NODE01_DNS`      | `node-01`           | ______________ |
| `NODE01_MAC`      | `AA:BB:CC:DD:EE:01` | ______________ |
| `USUARIO`         | `eduardo`           | ______________ |
| `K3S_TOKEN`       | (copiar do PC1)     | ______________ |


Requisitos de hardware sugeridos:

- GPU NVIDIA (RTX série 30/40/50 ou equivalente com driver Linux recente)
- CPU 4+ núcleos, 16 GB+ RAM
- SSD 256 GB+ para sistema
- Rede cabeada (IP fixo no roteador)
- **Não** precisa de disco grande de vídeos — os dados vêm do NFS do PC1

> GPUs RTX 50 (Blackwell, ex. RTX 5060) exigem driver **570+** (ex.: 595) e imagem worker **PyTorch 2.7 + CUDA 12.8**. PyTorch 2.5 falha com `no kernel image is available for execution on the device`. Se `nvidia-smi` falhar no host, verifique BIOS **Above 4G Decoding** e `pci=realloc=off` ([Passo 2](#passo-2--driver-nvidia)).

---

## Visão do que vamos instalar

```text
node-01 (este guia)
├── Ubuntu Server
├── Driver NVIDIA + nvidia-smi
├── NVIDIA Container Toolkit (GPU nos containers)
├── nfs-common (cliente NFS para volumes K8s)
├── K3s agent → conecta em https://PC1_IP:6443
└── registries.yaml → puxa imagens de PC1_IP:5000

ctrl-p01 (já pronto)
├── K3s server + KEDA + ScaledJob
├── Atlas Platform API (:30090)
├── Registry :5000
├── RabbitMQ :5672
├── Postgres :5432 (schemas track_fraude + atlas)
└── NFS export /srv/track_fraude/data
```

Fluxo após configurado:

```text
Play no painel → Atlas Platform API → RabbitMQ → KEDA → Job no node-01 → GPU → NFS → status no banco
```

---

## Passo 0 — Ubuntu Server base

Conecte por SSH no `node-01` recém-instalado.

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
sudo hostnamectl set-hostname node-01

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

- `hostname` mostra `node-01`
- `ip a` mostra `NODE01_IP` correto

---

## Passo 0.1 — Nomes locais (DNS / hosts)

Configure os mesmos nomes do [config_control_plane.md](config_control_plane.md) (Passo 0.1) neste PC e no seu notebook.


| Nome (SSH) | IP              | Este node     |
| ---------- | --------------- | ------------- |
| `ctrl-p01` | `192.168.0.199` | control plane |
| `node-01`  | `192.168.0.201` | **este guia** |


No `node-01`:

```bash
sudo tee -a /etc/hosts >/dev/null <<'EOF'
192.168.0.199   ctrl-p01
192.168.0.201   node-01
EOF
```

Teste:

```bash
ping -c1 ctrl-p01
hostname -f   # ou hostname → node-01
```

A partir do notebook ou do ctrl-p01:

```bash
ssh ${USUARIO}@node-01
```

### Power Manager (opcional)

Só necessário se quiser **ligar/desligar este node automaticamente** (Wake-on-LAN + SSH). Pule se o node ficará sempre ligado.

**Quando fazer cada parte** (evita confusão de ordem):


| Momento                                                         | O que fazer                                                          | Onde                                          |
| --------------------------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------------- |
| Agora (Passo 0.1)                                               | Coletar MAC/`ssh_user`, criar `config.json`, `/etc/hosts`, chave SSH | A–D abaixo                                    |
| Depois do [Passo 7](#passo-7--entrar-no-cluster-como-k3s-agent) | Validar `"name"` com `kubectl get nodes`                             | Seção no Passo 7                              |
| Depois (ou no fim)                                              | Subir o serviço Power Manager                                        | [Passo 11](#passo-11--power-manager-opcional) |


> **Não rode `kubectl get nodes` aqui** — o node só aparece no cluster **depois** do Passo 7. Se fizer agora, verá só o control plane.

O arquivo de configuração fica **no ctrl-p01**, não neste PC:

```text
~/track_fraude/infra/power-manager/config.json
```

Crie a partir do modelo (`cp config.example.json config.json`) — detalhes no passo **B** abaixo.

#### A — Coletar dados neste node (`node-01`)

**1. Usuário SSH (`ssh_user`)**

```bash
whoami
```

Anote a saída (ex.: `eduardo`) → será `"ssh_user": "eduardo"`.

**2. MAC da Ethernet (`mac`) — não use Wi‑Fi**

Wake-on-LAN só funciona pela placa **com cabo de rede**. Conecte o cabo antes de continuar.

Liste as interfaces:

```bash
ip link show
```

Exemplo de saída:

```text
2: enp12s0: <BROADCAST,MULTICAST,UP,LOWER_UP> ... state UP
    link/ether 34:5a:60:7b:86:77 brd ff:ff:ff:ff:ff:ff
3: wlp13s0: <BROADCAST,MULTICAST,UP,LOWER_UP> ... state UP
    link/ether 84:9e:56:03:68:13 brd ff:ff:ff:ff:ff:ff
```


| Interface                                 | Usar no Power Manager?                 |
| ----------------------------------------- | -------------------------------------- |
| `enp…` / `eth0` com `UP` e cabo conectado | **Sim** → `"mac": "34:5a:60:7b:86:77"` |
| `wlp…` (Wi‑Fi)                            | **Não** — não acorda PC desligado      |


Confirme qual é a interface cabeada (troque `enp12s0` pelo nome real):

```bash
# Deve mostrar UP, sem NO-CARRIER
ip link show enp12s0

# MAC em uma linha
cat /sys/class/net/enp12s0/address
```

Se `enp12s0` mostrar `NO-CARRIER` / `state DOWN`, o cabo não está conectado ou a link não subiu — corrija o netplan (Passo 0) antes de seguir.

**3. Rede cabeada vs Wi‑Fi**

Para K3s, NFS e Wake-on-LAN, use **Ethernet como rota principal**. Desligar Wi‑Fi evita conflito de rotas:

```bash
sudo nmcli radio wifi off
# ou: sudo ip link set wlp13s0 down
```

**4. Anote estes valores**


| Campo       | Valor neste guia                     | Seu valor      |
| ----------- | ------------------------------------ | -------------- |
| `name`      | `node-01`                            | ______________ |
| `ssh_host`  | `node-01` (igual ao `name`)          | ______________ |
| `ssh_user`  | saída do `whoami`                    | ______________ |
| `mac`       | MAC da Ethernet (`enp…`)             | ______________ |
| `broadcast` | `192.168.0.255` (LAN 192.168.0.0/24) | ______________ |


> `name` e `ssh_host` devem ser **iguais** ao hostname deste PC (`node-01`) e ao nome que aparecerá em `kubectl get nodes` após o Passo 7.

#### B — Ir para o ctrl-p01 e editar `config.json`

Até aqui você estava executando comandos no **node-01**. Agora mude para o **ctrl-p01**, porque o Power Manager roda no control plane.

Se você está conectado por SSH no `node-01`, saia:

```bash
exit
```

Entre no **ctrl-p01** (ou abra um terminal local nele):

```bash
ssh eduardo@ctrl-p01
```

Todos os comandos abaixo são no **ctrl-p01**.

```bash
cd ~/track_fraude

# Criar config local (só na primeira vez)
cp infra/power-manager/config.example.json infra/power-manager/config.json

# Abrir para editar
vim infra/power-manager/config.json
# ou: nano infra/power-manager/config.json
```

Preencha o bloco `nodes[]` com os valores anotados no passo A:

```json
"nodes": [
  {
    "name": "node-01",
    "mac": "34:5a:60:7b:86:77",
    "broadcast": "192.168.0.255",
    "ssh_host": "node-01",
    "ssh_user": "eduardo"
  }
]
```

#### C — Garantir que `node-01` resolve no ctrl-p01

Ainda no **ctrl-p01**, confirme que o nome `node-01` aponta para o IP do GPU node:

```bash
grep node-01 /etc/hosts
# esperado:
# 192.168.0.201   node-01
```

Se não aparecer essa linha, adicione:

```bash
echo "192.168.0.201   node-01" | sudo tee -a /etc/hosts
```

Teste o nome:

```bash
ping -c1 node-01
```

Sem isso, `ssh_host: "node-01"` não resolve quando o Power Manager tentar desligar o node.

#### D — Configurar SSH sem senha do ctrl-p01 para o node-01

O Power Manager roda no **ctrl-p01** e não digita senha. Por isso o ctrl-p01 precisa conseguir entrar no `node-01` por chave SSH.

Ainda no **ctrl-p01**:

```bash
# Gere uma chave se ainda não existir
test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# Copie a chave para o node-01 (troque eduardo pelo seu ssh_user)
ssh-copy-id eduardo@node-01

# Teste: este comando deve responder "ok" sem pedir senha
ssh eduardo@node-01 'echo ok'
```

Se `ssh eduardo@node-01` não funcionar, o Power Manager também não conseguirá desligar o node.

Próximos passos do Power Manager ( **não** faça agora):

1. [Passo 7](#passo-7--entrar-no-cluster-como-k3s-agent) — entrar no K3s e validar `"name"` no `config.json`
2. [Passo 11](#passo-11--power-manager-opcional) — subir o serviço

> Manifests Kubernetes no PC1 podem continuar com IP literal (`192.168.0.199`). Nomes locais (`ctrl-p01`, `node-01`) são para SSH, browser e Power Manager.

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

No **ctrl-p01**, confirme que a rede dos nodes pode montar NFS (Passo 2.1 do [config_control_plane.md](config_control_plane.md)):

```bash
# No ctrl-p01 — portas NFS liberadas para a LAN
sudo ufw status | grep -E '111|2049|32768'
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

**RTX 50 / `nvidia-smi` falha no host (antes do K3s):**

```bash
# Driver carregado?
lsmod | grep nvidia
cat /proc/driver/nvidia/version

# Erros de BAR/PCI no boot?
sudo dmesg | grep -iE 'nvrm|nvidia|pci'
```

| Sintoma no host | Ação |
| --------------- | ---- |
| `couldn't communicate with the NVIDIA driver` | Reinstale driver (`ubuntu-drivers autoinstall`); reinicie |
| `PCI I/O region ... invalid` / `BAR0 is 0M` | BIOS: habilite **Above 4G Decoding**; teste `pci=realloc=off` no GRUB |
| `Driver/library version mismatch` | Reboot; se persistir, reinstale driver limpo |

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

O worker monta `data/` via volume NFS do Kubernetes. O node precisa alcançar o export do **ctrl-p01**.

> Firewall e export NFS ficam no **ctrl-p01** (Passo 2.1 de [config_control_plane.md](config_control_plane.md)). **Não** instale `nfs-server` no GPU node — aqui você só testa como **cliente**.

Substitua `PC1_IP`:

```bash
PC1_IP=192.168.0.199

# Rede básica
ping -c3 ${PC1_IP}

# rpcbind (porta 111) — se falhar, firewall no ctrl-p01
timeout 5 bash -c "echo > /dev/tcp/${PC1_IP}/111" && echo "111 OK" || echo "111 FALHOU"

# Lista exports (use timeout — trava se mountd estiver bloqueado no ctrl-p01)
timeout 10 showmount -e ${PC1_IP}
```

Esperado:

```text
Export list for 192.168.0.199:
/srv/track_fraude/data 192.168.0.0/24
```

Mount manual de teste:

```bash
sudo mkdir -p /mnt/nfs-test
sudo mount -t nfs ${PC1_IP}:/srv/track_fraude/data /mnt/nfs-test
ls -la /mnt/nfs-test
sudo umount /mnt/nfs-test
```

- `showmount` responde em poucos segundos (não trava)
- `mount` funciona sem erro

**Se `showmount` travar:** no **ctrl-p01**, abra portas RPC — [config_control_plane.md — Passo 2.1](config_control_plane.md#21--firewall-nfs-para-gpu-nodes). Não configure ufw/NFS no GPU node para corrigir isso.

> Esse mount manual é só teste. Em produção, quem monta nos workers é o **kubelet** ao subir o pod.

---

## Passo 5 — Token do cluster (no `ctrl-p01`)

No **control plane**, copie o token de join:

```bash
# No ctrl-p01
sudo cat /var/lib/rancher/k3s/server/node-token
```

Anote o valor em `K3S_TOKEN`.

Confirme que o node alcança a API:

```bash
# No node-01
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

No `node-01`:

```bash
PC1_IP=192.168.0.199
K3S_TOKEN="COLE_O_TOKEN_DO_PC1_AQUI"
K3S_NODE_NAME=node-01

curl -sfL https://get.k3s.io | \
  K3S_URL="https://${PC1_IP}:6443" \
  K3S_TOKEN="${K3S_TOKEN}" \
  sh -s - agent --node-name "${K3S_NODE_NAME}"
```

Aguarde o serviço subir:

```bash
sudo systemctl status k3s-agent --no-pager
```

No **ctrl-p01**, confirme que o node apareceu:

```bash
kubectl get nodes
```

Esperado:

```text
NAME      STATUS   ROLES                  AGE   VERSION
ctrl-p01  Ready    control-plane,master   ...   v1.x.x+k3s
node-01   Ready    <none>                 ...   v1.x.x+k3s
```

> O nome do control plane em `kubectl get nodes` pode aparecer como `ctrl-p01` ou `ctrlp01` (hostname sem hífen). O importante é bater com `K3S_NODE_NAME` / Power Manager `"name"`.

### Validar Power Manager (se configurou no Passo 0.1)

Só faça isto **agora**, depois que `node-01` aparecer acima.

No **ctrl-p01**, confirme que o `"name"` no `config.json` bate com a coluna `NAME`:

```bash
kubectl get nodes
grep '"name"' ~/track_fraude/infra/power-manager/config.json
```

Deve ser o mesmo valor (ex.: `node-01`). Se no JSON estiver diferente, edite:

```bash
nano ~/track_fraude/infra/power-manager/config.json
```

```json
"name": "node-01",
"ssh_host": "node-01"
```

Se `kubectl get nodes` mostrar outro nome, corrija o JSON **ou** refaça o join no node-01 com `K3S_NODE_NAME=node-01`.

Para **subir o serviço** Power Manager, continue no [Passo 11](#passo-11--power-manager-opcional).

---

## Passo 8 — GPU no containerd do K3s

**Onde:** todos os comandos abaixo rodam no **`node-01`** (GPU node), não no ctrl-p01.

Pré-requisito: Passo 3 concluído (`nvidia-ctk` instalado) e `nvidia-smi` funcionando.

Configure o runtime NVIDIA no containerd usado pelo K3s agent:

```bash
# No node-01
sudo nvidia-ctk runtime configure \
  --runtime=containerd \
  --config /var/lib/rancher/k3s/agent/etc/containerd/config.toml

sudo systemctl restart k3s-agent
```

Valide no **node-01**:

```bash
sudo k3s crictl info | grep -i nvidia
```

Deve aparecer referência a `nvidia` na saída. Se `nvidia-ctk: command not found`, volte ao Passo 3.

### 8.1 — Symlink device-plugins (obrigatório no K3s)

O kubelet do K3s usa `/var/lib/rancher/k3s/agent/kubelet/device-plugins`, mas o NVIDIA Device Plugin monta `/var/lib/kubelet/device-plugins`. Sem o symlink correto, o plugin falha com `context deadline exceeded` ou `No devices found`.

**Importante:** se `/var/lib/kubelet/device-plugins` já existir como **pasta**, remova antes de criar o symlink (senão o `ln -s` cria um link *dentro* da pasta, errado).

No **node-01** (obrigatório — o device plugin roda só em nodes GPU):

```bash
sudo rm -rf /var/lib/kubelet/device-plugins
sudo ln -sfn /var/lib/rancher/k3s/agent/kubelet/device-plugins /var/lib/kubelet/device-plugins
sudo ls -la /var/lib/kubelet/device-plugins
# esperado: symlink → .../rancher/k3s/agent/kubelet/device-plugins
```

No **ctrl-p01** o symlink **não** é necessário para o device plugin (ele não agenda lá). Opcional se outros pods usarem device-plugins no control plane.

Reinicie o agent no **node-01** se o symlink foi corrigido:

```bash
sudo systemctl restart k3s-agent
```

### 8.2 — RuntimeClass e label do node GPU

No **ctrl-p01**, crie a RuntimeClass `nvidia` (K3s não usa NVIDIA como runtime default) e marque o node GPU:

```bash
cd ~/track_fraude
git pull
kubectl apply -f infra/k8s/nvidia-runtime-class.yaml
kubectl label node node-01 track-fraude/gpu=true --overwrite
```

Depois aplique o device plugin **no ctrl-p01**:

```bash
kubectl apply -f infra/k8s/nvidia-device-plugin.yaml
kubectl rollout restart ds/nvidia-device-plugin-daemonset -n kube-system
```

> O plugin usa `runtimeClassName: nvidia` e só agenda em nodes com label `track-fraude/gpu=true`. Workers GPU (`worker-scaledjob.yaml`) também usam `runtimeClassName: nvidia` — aplique a RuntimeClass **antes** do primeiro job worker.

---

## Passo 9 — Validar GPU no cluster

Este passo tem duas partes em máquinas diferentes.

### A — Pré-requisito no `node-01` (antes de validar no cluster)

Confirme no **node-01**:

```bash
nvidia-smi
sudo k3s crictl info | grep -i nvidia
sudo systemctl status k3s-agent --no-pager
```

Se algo falhar, corrija os Passos 2, 3 ou 8 **no node-01** antes de continuar.

### B — Validar no `ctrl-p01`

Saia do node-01 se estiver conectado por SSH (`exit`) e entre no **ctrl-p01**:

```bash
ssh eduardo@ctrl-p01
cd ~/track_fraude
```

Todos os comandos abaixo são no **ctrl-p01** (usa `kubectl` contra o cluster):

```bash
# Plugin rodando em cada node?
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds -o wide

# GPU registrada no node-01?
kubectl describe node node-01 | grep -A6 "nvidia.com/gpu"
```

Esperado na coluna `NODE` do primeiro comando: um pod **Running** em `node-01`.

Esperado no segundo comando (`Capacity` / `Allocatable`):

```text
nvidia.com/gpu:  1
```

(ou `2`, se a máquina tiver duas GPUs)

> O plugin roda **apenas no `node-01`** (label `track-fraude/gpu=true`). O ctrl-p01 não precisa ter GPU nem device plugin.

### C — Se `nvidia.com/gpu` não aparecer

**Sintoma nos logs:** `Could not register device plugin: context deadline exceeded` → symlink errado (pasta em vez de link).

**Sintoma nos logs:** `Incompatible strategy detected auto` / `No devices found` → confira `DEVICE_DISCOVERY_STRATEGY` no manifest (versões antigas); após `git pull`, use o manifest atual com `runtimeClassName: nvidia`.

**Sintoma nos logs:** `Failed to initialize NVML: Unknown Error` → o container do plugin está com bibliotecas NVML incompatíveis com o driver do host. **Não** monte `/usr/lib/x86_64-linux-gnu` manualmente. Use `runtimeClassName: nvidia`, aplique `nvidia-runtime-class.yaml`, rotule o node (`track-fraude/gpu=true`) e reaplique o plugin (Passo 8.2).

Causa do symlink: se `/var/lib/kubelet/device-plugins` já era **pasta**, o `ln -s` criou link *dentro* dela. Corrija com [Passo 8.1](#81--symlink-device-plugins-obrigatório-no-k3s) (`rm -rf` antes do `ln -sfn`).

**No node-01**, confira:

```bash
ls -la /var/lib/kubelet/device-plugins
sudo ls -la /var/lib/rancher/k3s/agent/kubelet/device-plugins/
# esperado: kubelet.sock e (com plugin ativo) nvidia-gpu.sock
```

Se `/var/lib/kubelet/device-plugins` não for symlink, faça o [Passo 8.1](#81--symlink-device-plugins-obrigatório-no-k3s).

**No ctrl-p01**, reaplique RuntimeClass, label e plugin:

```bash
cd ~/track_fraude
git pull
kubectl apply -f infra/k8s/nvidia-runtime-class.yaml
kubectl label node node-01 track-fraude/gpu=true --overwrite
kubectl apply -f infra/k8s/nvidia-device-plugin.yaml
kubectl rollout restart ds/nvidia-device-plugin-daemonset -n kube-system
```

Aguarde ~30s. Logs (substitua `$POD` pelo nome do pod no node-01):

```bash
POD=$(kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds --field-selector spec.nodeName=node-01 -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kube-system "$POD" --tail=20
kubectl describe node node-01 | grep -A6 "nvidia.com/gpu"
```

Esperado nos logs: `Registered device plugin for 'nvidia.com/gpu'` (sem `context deadline exceeded` nem `Failed to initialize NVML`).

> Evento `CIDRAssignmentFailed` em `kubectl describe node node-01` é comum em clusters pequenos K3s e **não** impede GPU ou jobs.

Se ainda falhar:

1. **No node-01:** refaça Passo 8 + 8.1 e `sudo systemctl restart k3s-agent`.
2. **No ctrl-p01**, reinicie o pod do plugin no node-01:

```bash
kubectl delete pod -n kube-system "$POD"
```

---

## Passo 9.1 — Imagem worker no registry (no `ctrl-p01`)

Confirme que a imagem worker está atualizada (inclui `infra/postgres` para schema no startup):

```bash
cd ~/track_fraude
PC1_IP=192.168.0.199

docker build -f Dockerfile.worker -t ${PC1_IP}:5000/track-fraude-worker:latest .
docker push ${PC1_IP}:5000/track-fraude-worker:latest

curl -s http://${PC1_IP}:5000/v2/track-fraude-worker/tags/list
```

> Com `database.backend: postgres` no painel, o worker precisa de `psycopg` na imagem (`pip install -e "./core[postgres]"` no `Dockerfile.worker`). Sem isso, pods falham em poucos segundos com `ModuleNotFoundError: psycopg`.

> O build da imagem worker **baixa `yolov8n.pt`** em `/app/models/` (precisa de internet no **ctrl-p01** durante `docker build`). O GPU node **não** precisa de internet em runtime.

> Base da imagem: `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime` (RTX 50 / Blackwell). O build demora mais e a imagem fica ~8 GB.

---

## Passo 10 — Teste de pipeline (Play)

1. No painel (`http://ctrl-p01:30080` ou `http://PC1_IP:30080`), cadastre grupo/loja/câmeras se ainda não existirem.
2. Coloque vídeos em `/srv/track_fraude/data/raw/...` no PC1 (NFS — **não** só no clone `~/track_fraude/data/`).
3. (Opcional) Limpe jobs Pending antigos: `kubectl delete jobs -n track-fraude --all`
4. Clique **Play** em uma data com vídeo importado.

No console do painel, espere ver:

```text
atlas_job: <uuid>
queue: track-fraude-pipelines
```

No **ctrl-p01**, acompanhe:

```bash
# Atlas + fila
curl -s http://127.0.0.1:30090/v1/health
curl -s -u track_fraude:track_fraude \
  http://127.0.0.1:15672/api/queues/%2F/track-fraude-pipelines \
  | jq '.messages, .consumers'

# Job no Postgres Atlas
docker compose -f docker-compose.infra.yml exec postgres \
  psql -U track_fraude -d track_fraude -c \
  "SELECT public_id, status, pipeline_run_id FROM atlas.jobs ORDER BY id DESC LIMIT 3;"

# Jobs KEDA
kubectl get jobs -n track-fraude -w

# Pod do worker (deve ir para node-01 e ficar Running)
kubectl get pods -n track-fraude -o wide

# Logs (substitua pelo nome do pod, ex.: track-fraude-worker-6fxzg-pb6cc)
kubectl logs -n track-fraude track-fraude-worker-6fxzg-pb6cc --tail=100

# ou pelo label do job:
kubectl logs -n track-fraude -l job-name=track-fraude-worker-6fxzg --tail=100
```

Sucesso esperado:

- Log do painel com `atlas_job:`
- Registro em `atlas.jobs` (status evolui conforme o worker)
- Mensagem na fila RabbitMQ (pode ir a 0 quando o worker consumir)
- Job `track-fraude-worker-...` criado
- Pod **Running** no `node-01` (não Pending)
- Logs mostram `--- pipeline retirado da fila ---` e `run_daily_pipeline.py`

Capacidade:

```text
1 GPU  = 1 pipeline simultâneo neste node
2 GPUs = 2 pipelines simultâneos neste node
```

---

## Passo 11 — Power Manager (opcional)

Continuação do [Passo 0.1 — Power Manager](#power-manager-opcional).

**Pré-requisitos:**

- `config.json` criado nos passos A–D do Passo 0.1
- Node no cluster ([Passo 7](#passo-7--entrar-no-cluster-como-k3s-agent)) com `"name"` validado

Automatiza **ligar** (Wake-on-LAN) e **desligar** (SSH) nodes GPU conforme a fila RabbitMQ e pods pendentes. Roda **somente no ctrl-p01**.

**Não é obrigatório** para processar pipelines. Pule se o node ficará sempre ligado.

### O que o script faz


| Evento                                         | Ação              | Como                                         |
| ---------------------------------------------- | ----------------- | -------------------------------------------- |
| Fila com jobs, node offline, sem GPU livre     | **Ligar** node    | Magic packet Wake-on-LAN (campo `mac`)       |
| Node online, fila vazia, ocioso por N segundos | **Desligar** node | `kubectl drain` + SSH `sudo shutdown -h now` |


Política `total_on_sec` (rodízio de tempo ligado):


| Ação        | Regra                                             |
| ----------- | ------------------------------------------------- |
| Wake-on-LAN | Node offline com **menor** tempo acumulado ligado |
| Shutdown    | Node ocioso com **maior** tempo acumulado ligado  |


Código: `infra/power-manager/power_manager.py`.

### Referência rápida — campos do `config.json`


| Campo           | Onde obter                                                 | Regra                                                            |
| --------------- | ---------------------------------------------------------- | ---------------------------------------------------------------- |
| `**name`**      | `kubectl get nodes` no ctrl-p01                            | Idêntico à coluna `NAME` (ex.: `node-01`)                        |
| `**ssh_host**`  | Passo 0.1                                                  | Igual ao `name` neste guia; resolve via `/etc/hosts` no ctrl-p01 |
| `**mac**`       | `ip link show` / `cat /sys/class/net/enp…/address` no node | Ethernet com cabo — **não** Wi‑Fi                                |
| `**broadcast`** | Sub-rede LAN                                               | `192.168.0.255` para `192.168.0.0/24`                            |
| `**ssh_user**`  | `whoami` no node                                           | Usuário do `ssh-copy-id`                                         |


Passo a passo com comandos: [Passo 0.1 — Power Manager](#power-manager-opcional).

Teste manual:

```bash
cd ~/track_fraude
python3 infra/power-manager/power_manager.py --config infra/power-manager/config.json
```

Logs esperados:

```text
wake node-01: queue=2 free_gpus=0 pending_workers=1 total_on_sec=3600
shutdown node-01: idle_for=900s total_on_sec=86400
```

Para rodar sempre ligado no ctrl-p01, siga o **Passo 14** do [config_control_plane.md](config_control_plane.md) (unit systemd `track-fraude-power-manager`).

### Problemas comuns


| Sintoma               | Causa                                  | Ação                                                    |
| --------------------- | -------------------------------------- | ------------------------------------------------------- |
| Node nunca acorda     | MAC errado ou Wi‑Fi em vez de Ethernet | MAC da interface cabeada; WOL na BIOS; cabo conectado   |
| Node nunca desliga    | `name` ≠ `kubectl get nodes`           | Corrigir `"name": "node-01"`                            |
| Shutdown falha        | SSH pede senha                         | `ssh-copy-id` do ctrl-p01 para o node                   |
| `kubectl drain` falha | Nome errado em `name`                  | Conferir `NAME` em `kubectl get nodes`                  |
| Script não vê fila    | `rabbitmq_api_url` errada              | Usar `http://192.168.0.199:15672/...` ou IP do ctrl-p01 |


---

## Validação final do `node-01`

Execute no **ctrl-p01**:

```bash
PC1_IP=192.168.0.199

kubectl get nodes
kubectl describe node node-01 | grep -E "nvidia.com/gpu|Ready"
kubectl get scaledjob -n track-fraude
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds -o wide
curl -s http://127.0.0.1:30090/v1/health
curl -s http://127.0.0.1:30080/health
```

Checklist manual:

- `node-01` aparece `Ready` em `kubectl get nodes`
- `nvidia-smi` funciona no `node-01`
- `nvidia.com/gpu` visível em `kubectl describe node node-01`
- `showmount -e PC1_IP` funciona no `node-01`
- Play no painel mostra `atlas_job:` no log
- Job worker **Running** no `node-01` (não Pending)
- Logs do worker progridem sem `ImagePullBackOff` nem erro de NFS/schema

---

## Adicionar `node-02`, `node-03`...

Repita este guia em cada PC GPU novo:

1. Ubuntu + driver NVIDIA + Container Toolkit
2. IP fixo + hostname único (`node-02`, etc.)
3. `registries.yaml` apontando para o mesmo `PC1_IP:5000`
4. `k3s agent` com `--node-name` único e o **mesmo** `K3S_TOKEN`
5. Passo 8 (`nvidia-ctk` + symlink 8.1) + restart `k3s-agent`
6. No **ctrl-p01**: `kubectl label node node-02 track-fraude/gpu=true --overwrite`
7. Validar `kubectl describe node node-02 | grep nvidia.com/gpu`

**Não** é necessário refazer registry, RabbitMQ, KEDA ou ScaledJob no PC1.

Capacidade total:

```text
pipelines simultâneos = soma de todas as GPUs em todos os nodes Ready
```

---

## Resumo — ordem de instalação

1. [ ] Control plane pronto ([config_control_plane.md](config_control_plane.md))
2. [ ] Ubuntu + IP fixo + hostname `node-01`
3. [ ] Nomes locais (`/etc/hosts`: `ctrl-p01`, `node-01`)
4. [ ] Driver NVIDIA + `nvidia-smi`
5. [ ] NVIDIA Container Toolkit
6. [ ] Teste NFS (`showmount` / `mount` do PC1)
7. [ ] Token K3s copiado do PC1
8. [ ] `registries.yaml` no agent
9. [ ] `k3s agent` join no cluster
10. [ ] `nvidia-ctk` + symlink device-plugins (8.1) + restart `k3s-agent`
11. [ ] RuntimeClass `nvidia` + label `track-fraude/gpu=true` + device plugin (8.2)
12. [ ] Validar `nvidia.com/gpu` no node (Passo 9)
13. [ ] Rebuild/push imagem worker (Passo 9.1)
14. [ ] Teste Play → job no `node-01` (Passo 10)
15. [ ] (Opcional) Power Manager no PC1 (Passo 11)

---

## Referências no repositório


| Arquivo                                                                | Uso                               |
| ---------------------------------------------------------------------- | --------------------------------- |
| [config_control_plane.md](config_control_plane.md)                     | Setup do `ctrl-p01`               |
| [fase1_atlas_fundacao.md](fase1_atlas_fundacao.md)                     | Atlas Platform API                |
| [k3s_comandos_operacionais.md](k3s_comandos_operacionais.md)           | Limpar jobs Pending, logs, delete |
| `infra/k3s/registries.yaml.example`                                    | Modelo registry para agents       |
| `infra/k8s/worker-scaledjob.yaml`                                      | Job GPU escalado por KEDA (`runtimeClassName: nvidia`) |
| `infra/k8s/nvidia-runtime-class.yaml`                                  | RuntimeClass NVIDIA para K3s      |
| `infra/k8s/nvidia-device-plugin.yaml`                                  | Expõe GPUs no cluster (só nodes com label) |
| `infra/power-manager/`                                                 | Liga/desliga nodes GPU            |
| [arquitetura_serverless_on_prem.md](arquitetura_serverless_on_prem.md) | Visão geral                       |


---

## Problemas comuns


| Sintoma                                           | Causa provável                             | Ação                                                                                                                             |
| ------------------------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `node-01` não aparece em `kubectl get nodes`      | Token errado ou firewall no PC1 (`6443`)   | Refazer join; `curl -k https://PC1_IP:6443/ping`                                                                                 |
| `nvidia-smi` falha                                | Driver não instalado ou reboot pendente    | Passo 2                                                                                                                          |
| Sem `nvidia.com/gpu` no node                      | Toolkit, symlink, RuntimeClass ou label    | Passos 8.1–8.2, 9; label `track-fraude/gpu=true`                                                                                 |
| Worker `ImagePullBackOff`                         | Registry inacessível                       | `registries.yaml` no node; testar `curl http://PC1_IP:5000/v2/_catalog`                                                          |
| Worker `Pending` (GPU)                            | Sem GPU alocável no cluster                | `kubectl describe node node-01`; device plugin Running; ver [k3s_comandos_operacionais.md](k3s_comandos_operacionais.md)         |
| Worker `ContainerCreating` (runtime)            | Falta RuntimeClass `nvidia`                | `kubectl apply -f infra/k8s/nvidia-runtime-class.yaml`; worker usa `runtimeClassName: nvidia`                                    |
| Worker `ContainerCreating` (pull, sem logs)       | Download da imagem ~8 GB ou NFS            | `kubectl describe pod ...` → Events; pre-pull: `sudo k3s crictl pull PC1_IP:5000/track-fraude-worker:latest` no node-01         |
| Worker falha ao montar volume / `showmount` trava | Firewall RPC no **ctrl-p01** (não no node) | [config_control_plane.md — Passo 2.1](config_control_plane.md#21--firewall-nfs-para-gpu-nodes); `timeout 10 showmount -e PC1_IP` |
| Worker `Error` track CUDA `no kernel image`        | PyTorch antigo (RTX 50 / sm_120)       | Rebuild worker com `pytorch:2.7.1-cuda12.8` (Passo 9.1)                                                                          |
| Worker `Error` na fase track (`No module named 'lap'`) | ByteTrack sem dep `lap`            | Rebuild `Dockerfile.worker` (`lap>=0.5.12`)                                                                                     |
| Worker `Error` (schema Postgres)                  | Imagem worker antiga                       | Rebuild/push `Dockerfile.worker` (Passo 9.1)                                                                                     |
| Job criado mas não roda no node                   | Node `NotReady` ou sem GPU livre           | `kubectl describe node`; jobs antigos ocupando GPU                                                                               |
| ScaledJob `READY Unknown`                         | Normal sem fila ou KEDA validando          | Enfileirar job com Play; checar logs do KEDA                                                                                     |
| Play não enfileira                                | Atlas API down ou config errada            | `curl :30090/v1/health`; `atlas.api_url` no ConfigMap; logs `atlas-platform-api`                                                 |
| Play sem `atlas_job` no log                       | Painel sem rebuild ou ConfigMap antigo     | Rebuild server + `kubectl apply app-config.yaml`                                                                                 |


---

## Comandos úteis no dia a dia

```bash
# No ctrl-p01 — visão geral
kubectl get nodes
kubectl get pods -n track-fraude -o wide
kubectl get jobs -n track-fraude

# No node-01 — saúde local
nvidia-smi
sudo systemctl status k3s-agent
sudo k3s crictl ps
```

Quando tudo estiver certo:

```text
Play no painel → Atlas Platform API → RabbitMQ → KEDA → Job no node-01 → GPU → NFS → status no banco
```

