O erro acontece **durante o `docker build`**, não no push. O BuildKit/containerd não consegue extrair a camada do PyTorch (`libtorch_cuda.so` sozinha pode passar de **2–4 GB**). Com builds repetidos do `Dockerfile.worker`, cache + imagens antigas + registry enchem o disco rápido mesmo com 512 GB.

Execute tudo **no `ctrl-p01`** via SSH.

---

## 1. Diagnóstico — onde está o espaço

```bash
# Espaço geral
df -h

# O que mais ocupa (pode demorar um pouco)
sudo du -xh /var/lib/docker /var/lib/containerd /var/lib/rancher 2>/dev/null | sort -h | tail -20

# Resumo Docker
docker system df -v

# Imagens locais (worker é a maior)
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | sort -k3 -h

# Registry — o que tem publicado
curl -s http://127.0.0.1:5000/v2/_catalog | jq .
# Para cada repo:
curl -s http://127.0.0.1:5000/v2/track-fraude-worker/tags/list | jq .
curl -s http://127.0.0.1:5000/v2/track-fraude-server/tags/list | jq .
curl -s http://127.0.0.1:5000/v2/atlas-platform-api/tags/list | jq .

# Volume do registry (Compose)
docker volume inspect track_fraude_registry-data 2>/dev/null || \
  docker volume ls | grep registry
sudo du -sh /var/lib/docker/volumes/*registry* 2>/dev/null
```

Provavelmente você verá algo grande em:
- `/var/lib/containerd/...` (build em andamento / cache)
- `/var/lib/docker` (imagens + build cache)
- volume `registry-data` (várias versões do worker)

---

## 2. Limpeza imediata (segura) — Docker local

Ordem recomendada: **cache de build primeiro** (libera mais sem afetar pods rodando).

```bash
cd ~/track_fraude   # ou onde está o repo

# 1) Cache do BuildKit (principal suspeito em builds que falharam)
docker builder prune -af

# 2) Imagens não usadas por nenhum container
docker image prune -af

# 3) Limpeza geral (containers parados, redes, cache restante)
docker system prune -af

# 4) Conferir
df -h
docker system df
```

Se ainda estiver apertado e **não houver containers importantes parados**:

```bash
# Remove TODAS as imagens locais não usadas (registry continua intacto)
docker rmi $(docker images -q) 2>/dev/null || true
docker builder prune -af
```

> Os pods do K3s no ctrl-p01 (server, atlas) usam imagens via **containerd do K3s**, não necessariamente as do Docker Engine — essa limpeza não derruba o cluster, mas você precisará rebuild/push de novo.

---

## 3. Limpar o registry local (provável segundo maior consumidor)

O registry **não apaga blobs sozinho**. Cada `docker push` de `:latest` deixa camadas antigas órfãs até rodar garbage collection.

### 3.1 Ver tamanho e tags

```bash
REG=http://127.0.0.1:5000

curl -s $REG/v2/_catalog

for repo in track-fraude-worker track-fraude-server atlas-platform-api; do
  echo "=== $repo ==="
  curl -s $REG/v2/$repo/tags/list | jq .
done
```

### 3.2 Apagar tags antigas (mantenha só `latest`)

Se existirem tags como `v1`, `20250620`, `old`, etc.:

```bash
REG=http://127.0.0.1:5000
REPO=track-fraude-worker
TAG=tag-antiga-a-apagar   # troque pelo nome real

# Obter digest da tag
DIGEST=$(curl -sI -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  "$REG/v2/$REPO/manifests/$TAG" | grep -i Docker-Content-Digest | awk '{print $2}' | tr -d $'\r')

# Apagar manifest
curl -X DELETE "$REG/v2/$REPO/manifests/$DIGEST"
```

Repita para cada tag que não precisa mais.

### 3.3 Garbage collect no registry

```bash
# Parar registry momentaneamente
docker compose -f docker-compose.infra.yml stop registry

# GC (modo read-only no volume)
docker run --rm \
  -v track_fraude_registry-data:/var/lib/registry \
  registry:2 \
  garbage-collect /etc/docker/registry/config.yml

# Se o volume tiver outro nome, descubra com:
# docker volume ls | grep registry

# Subir de novo
docker compose -f docker-compose.infra.yml up -d registry
```

> Se o nome do volume for diferente (ex.: `track_fraude_registry-data` vs `registry-data`), ajuste o `-v`.

---

## 4. K3s no ctrl-p01 (opcional, se ainda faltar espaço)

```bash
# Imagens que o K3s baixou no control plane
sudo k3s crictl images

# Remove imagens não usadas pelo runtime do K3s
sudo k3s crictl rmi --prune
```

No **node-01** (GPU), imagens antigas do worker também ocupam muito — depois de push novo:

```bash
sudo k3s crictl images | grep track-fraude-worker
sudo k3s crictl rmi 10.10.0.100:5000/track-fraude-worker:latest   # IP real do registry
```

---

## 5. Rebuild do worker (depois de liberar ~15–20 GB)

A imagem worker com CUDA 12.8 + PyTorch costuma precisar de **~12–20 GB** só para extrair camadas durante o build.

```bash
cd ~/track_fraude

# Confirme espaço livre (ideal: >25 GB)
df -h /

# Build (use o IP/hostname real do registry)
REG=10.10.0.100:5000   # ou 192.168.0.199:5000 — o que você usa hoje

docker build -f Dockerfile.worker -t $REG/track-fraude-worker:latest .

docker push $REG/track-fraude-worker:latest
```

Se quiser evitar acumular cache gigante no meio do build:

```bash
docker builder prune -af   # antes
docker build --progress=plain -f Dockerfile.worker -t $REG/track-fraude-worker:latest .
docker builder prune -af   # depois (opcional)
```

---

## 6. Checklist rápido

| Ordem | Ação | Risco |
|-------|------|-------|
| 1 | `docker builder prune -af` | Baixo — só cache de build |
| 2 | `docker system prune -af` | Baixo — não mexe no registry volume |
| 3 | Apagar tags velhas no registry + `garbage-collect` | Médio — só apague tags que não usa |
| 4 | `k3s crictl rmi --prune` no ctrl-p01 | Baixo |
| 5 | Limpar imagens worker antigas no node-01 | Baixo — puxa de novo no próximo job |

---

## 7. Prevenção (depois que estabilizar)

1. **Antes de cada rebuild do worker:** `docker builder prune -af`
2. **No registry:** manter só `latest` (sem tags experimentais acumulando)
3. **Agendar GC mensal** do registry (stop → `garbage-collect` → start)
4. **Monitorar:** `df -h /` e `docker system df` no ctrl-p01

---

Se quiser, cole aqui a saída de `df -h` e `docker system df` do ctrl-p01 que eu te digo exatamente qual passo priorizar e se o gargalo é build cache, registry ou outra coisa (logs NFS, Postgres, etc.).