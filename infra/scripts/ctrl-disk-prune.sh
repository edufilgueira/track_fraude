#!/usr/bin/env bash
# Limpeza segura de disco no control plane (Docker build cache, imagens órfãs, registry GC).
# Uso (a partir da raiz do repo):
#   ./infra/scripts/ctrl-disk-prune.sh light
#   ./infra/scripts/ctrl-disk-prune.sh full
#
# Variáveis opcionais:
#   TRACK_FRAUDE_DIR   — raiz do repo (auto-detectada se omitida)
#   REGISTRY_VOLUME    — volume Docker do registry (default: track_fraude_registry-data)
#   CTRL_PRUNE_LOG     — arquivo de log (default: /var/log/ctrl-disk-prune.log)
set -euo pipefail

MODE="${1:-light}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACK_FRAUDE_DIR="${TRACK_FRAUDE_DIR:-${TRACK_FRaude_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}}"
REGISTRY_VOLUME="${REGISTRY_VOLUME:-track_fraude_registry-data}"
LOG="${CTRL_PRUNE_LOG:-/var/log/ctrl-disk-prune.log}"
LOCK="/run/ctrl-disk-prune.lock"
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
  local compose_file="$TRACK_FRAUDE_DIR/docker-compose.infra.yml"
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
    cd "$TRACK_FRAUDE_DIR"
    docker compose -f docker-compose.infra.yml stop registry
    docker run --rm \
      -v "${REGISTRY_VOLUME}:/var/lib/registry" \
      registry:2 \
      garbage-collect /etc/docker/registry/config.yml
    docker compose -f docker-compose.infra.yml up -d registry
  ) 2>&1 | tee -a "$LOG" || {
    log "ERRO no registry GC — tentando subir registry"
    (cd "$TRACK_FRAUDE_DIR" && docker compose -f docker-compose.infra.yml up -d registry) || true
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
  log "=== INÍCIO free=${before}GB used=${used_pct}% repo=${TRACK_FRAUDE_DIR} ==="

  if docker_build_running; then
    log "SKIP: docker build em andamento — só prune mínimo (dangling)"
    docker image prune -f 2>&1 | tee -a "$LOG" || true
    exit 0
  fi

  case "$MODE" in
    light)
      prune_docker_light
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
