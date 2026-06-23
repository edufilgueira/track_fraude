Estou em **Ask mode** — não consigo criar o arquivo no repo. Abaixo vai o script completo para você colar no `ctrl-p01`. Se quiser que eu adicione em `docs/Limpeza_imediata.md` ou em `infra/scripts/`, mude para **Agent mode**.

---

## Estratégia recomendada

| Frequência | Modo | O que faz |
|------------|------|-----------|
| A cada **30 min** | `light` | Cache antigo, imagens dangling, containers parados |
| **1× por dia** (ex.: 03:15) | `full` | Limpeza completa + GC do registry + K3s prune |

O script **não mexe em volumes** (Postgres, RabbitMQ, registry-data, NFS) e **pula** se houver `docker build` em andamento.

---

## 1. Script — `/usr/local/bin/ctrl-disk-prune.sh`

```bash
#!/usr/bin/env bash
# Limpeza segura de disco no ctrl-p01 (Docker build cache, imagens órfãs, registry GC).
# Uso: ctrl-disk-prune.sh [light|full]
set -euo pipefail

MODE="${1:-light}"
LOG="/var/log/ctrl-disk-prune.log"
LOCK="/run/ctrl-disk-prune.lock"
TRACK_FRaude_DIR="${TRACK_FRaude_DIR:-$HOME/track_fraude}"
REGISTRY_VOLUME="${REGISTRY_VOLUME:-track_fraude_registry-data}"
MIN_FREE_GB_LIGHT=10
MIN_FREE_GB_FULL=5
DISK_WARN_PCT=85

log() { echo "[$(date -Iseconds)] [$MODE] $*" | tee -a "$LOG"; }

free_gb() {
  df -BG / | awk 'NR==2 {gsub(/G/,"",$4); print $4}'
}

disk_used_pct() {
  df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}'
}

docker_build_running() {
  pgrep -f 'docker (build|buildx build)' >/dev/null 2>&1
}

acquire_lock() {
  exec 9>"$LOCK"
  if ! flock -n 9; then
    log "SKIP: outra instância em execução"
    exit 0
  fi
}

prune_docker_light() {
  log "Docker light: builder (>24h), dangling images, stopped containers"
  docker builder prune -f --filter "until=24h" 2>&1 | tee -a "$LOG" || true
  docker image prune -f 2>&1 | tee -a "$LOG" || true
  docker container prune -f 2>&1 | tee -a "$LOG" || true
}

prune_docker_full() {
  log "Docker full: build cache + imagens não usadas + redes órfãs"
  docker builder prune -af 2>&1 | tee -a "$LOG" || true
  docker image prune -af 2>&1 | tee -a "$LOG" || true
  docker container prune -f 2>&1 | tee -a "$LOG" || true
  docker network prune -f 2>&1 | tee -a "$LOG" || true
  # NUNCA: docker volume prune / docker system prune --volumes
}

prune_k3s() {
  if command -v k3s >/dev/null 2>&1; then
    log "K3s: crictl rmi --prune (imagens não usadas)"
    sudo k3s crictl rmi --prune 2>&1 | tee -a "$LOG" || true
  fi
}

registry_gc() {
  local compose_file="$TRACK_FRaude_DIR/docker-compose.infra.yml"
  if [[ ! -f "$compose_file" ]]; then
    log "SKIP registry GC: $compose_file não encontrado"
    return 0
  fi

  if ! docker volume inspect "$REGISTRY_VOLUME" >/dev/null 2>&1; then
    log "SKIP registry GC: volume $REGISTRY_VOLUME não existe"
    return 0
  fi

  log "Registry GC: stop → garbage-collect → start (~30s indisponível)"
  (
    cd "$TRACK_FRaude_DIR"
    docker compose -f docker-compose.infra.yml stop registry
    docker run --rm \
      -v "${REGISTRY_VOLUME}:/var/lib/registry" \
      registry:2 \
      garbage-collect /etc/docker/registry/config.yml
    docker compose -f docker-compose.infra.yml up -d registry
  ) 2>&1 | tee -a "$LOG" || {
    log "ERRO no registry GC — tentando subir registry"
    (cd "$TRACK_FRaude_DIR" && docker compose -f docker-compose.infra.yml up -d registry) || true
  }
}

main() {
  [[ "$MODE" == "light" || "$MODE" == "full" ]] || {
    echo "Uso: $0 [light|full]" >&2
    exit 1
  }

  acquire_lock

  local before after used_pct
  before="$(free_gb)"
  used_pct="$(disk_used_pct)"
  log "=== INÍCIO free=${before}GB used=${used_pct}% ==="

  if docker_build_running; then
    log "SKIP: docker build em andamento — só prune mínimo (dangling)"
    docker image prune -f 2>&1 | tee -a "$LOG" || true
    exit 0
  fi

  case "$MODE" in
    light)
      prune_docker_light
      # Se disco apertado, escalona para full sem registry GC
      if (( used_pct >= DISK_WARN_PCT || before < MIN_FREE_GB_LIGHT )); then
        log "Disco >= ${DISK_WARN_PCT}% ou < ${MIN_FREE_GB_LIGHT}GB — escalonando prune full (sem registry GC)"
        prune_docker_full
      fi
      ;;
    full)
      prune_docker_full
      prune_k3s
      registry_gc
      ;;
  esac

  after="$(free_gb)"
  used_pct="$(disk_used_pct)"
  log "=== FIM free=${after}GB (liberou ~$((after - before))GB) used=${used_pct}% ==="
  docker system df 2>&1 | tee -a "$LOG" || true

  if (( after < MIN_FREE_GB_FULL )); then
    log "ALERTA: ainda < ${MIN_FREE_GB_FULL}GB livres — considere expandir LVM ou limpeza manual"
  fi
}

main "$@"
```

Instalação:

```bash
sudo tee /usr/local/bin/ctrl-disk-prune.sh << 'EOF'
# ... cole o script acima ...
EOF
sudo chmod +x /usr/local/bin/ctrl-disk-prune.sh
sudo touch /var/log/ctrl-disk-prune.log
sudo chown root:root /var/log/ctrl-disk-prune.log
```

Teste manual:

```bash
sudo /usr/local/bin/ctrl-disk-prune.sh light
sudo /usr/local/bin/ctrl-disk-prune.sh full   # teste fora de horário de build
tail -50 /var/log/ctrl-disk-prune.log
```

---

## 2. Agendamento — cron (simples)

```bash
sudo crontab -e
```

```cron
# Limpeza leve a cada 30 minutos
*/30 * * * * /usr/local/bin/ctrl-disk-prune.sh light >> /var/log/ctrl-disk-prune.log 2>&1

# Limpeza completa + registry GC 1× por dia às 03:15
15 3 * * * /usr/local/bin/ctrl-disk-prune.sh full >> /var/log/ctrl-disk-prune.log 2>&1
```

---

## 3. Alternativa — systemd timer (mais robusto)

**`/etc/systemd/system/ctrl-disk-prune-light.service`**

```ini
[Unit]
Description=Ctrl-p01 disk prune (light)
After=docker.service

[Service]
Type=oneshot
Environment=TRACK_FRaude_DIR=/home/eduardo/track_fraude
ExecStart=/usr/local/bin/ctrl-disk-prune.sh light
```

**`/etc/systemd/system/ctrl-disk-prune-light.timer`**

```ini
[Unit]
Description=Run light disk prune every 30 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

**`/etc/systemd/system/ctrl-disk-prune-full.service`**

```ini
[Unit]
Description=Ctrl-p01 disk prune (full + registry GC)
After=docker.service

[Service]
Type=oneshot
Environment=TRACK_FRaude_DIR=/home/eduardo/track_fraude
ExecStart=/usr/local/bin/ctrl-disk-prune.sh full
```

**`/etc/systemd/system/ctrl-disk-prune-full.timer`**

```ini
[Unit]
Description=Daily full disk prune at 03:15

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

Ativar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ctrl-disk-prune-light.timer
sudo systemctl enable --now ctrl-disk-prune-full.timer
systemctl list-timers | grep ctrl-disk
```

---

## O que o script apaga (e o que não apaga)

| Ação | Seguro? | Efeito |
|------|---------|--------|
| `builder prune --filter until=24h` | Sim | Cache de build com mais de 24h |
| `builder prune -af` (full) | Sim* | Todo cache não referenciado |
| `image prune -f` | Sim | Só camadas dangling (sem tag) |
| `image prune -af` (full) | Sim | Imagens locais sem container rodando — **registry remoto intacto** |
| `container/network prune` | Sim | Containers parados, redes órfãs |
| Registry `garbage-collect` | Sim | Só blobs **não referenciados** por nenhuma tag |
| `k3s crictl rmi --prune` | Sim | Imagens K3s não usadas por pods |

\* Pula se `docker build` estiver rodando.

**Nunca faz:**
- `docker volume prune` (apagaria dados do Postgres/RabbitMQ se parados)
- `docker system prune --volumes`
- Apagar tags do registry manualmente

---

## Ajuste fino

- **`TRACK_FRaude_DIR`**: caminho do repo no servidor (`/home/eduardo/track_fraude`).
- **Registry GC só no `full`**: evita indisponibilidade de `:5000` a cada 30 min (~30s off).
- **Modo `light` escalona para `full`** se disco ≥ 85% ou &lt; 10 GB livres (sem GC do registry).
- **Expandir LVM** continua sendo a melhor solução de longo prazo — o script só evita encher os 98 GB de novo.

Se quiser, no Agent mode posso criar `infra/scripts/ctrl-disk-prune.sh` e uma seção em `docs/Limpeza_imediata.md` com esses blocos.