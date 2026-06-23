# Verificar worker GPU (raw cache + env) — rodar no ctrl-p01 após deploy

## 1. Manifest aplicado

```bash
kubectl get scaledjob track-fraude-worker -n track-fraude -o yaml | grep -E 'TRACK_FRAUDE_RAW|raw-cache|emptyDir'
```

Esperado: `TRACK_FRAUDE_RAW_CACHE_DIR`, volume `raw-cache`, mount `/cache/raw`.

## 2. Imagem nova no registry

Após `docker build` / `push`, no pod do **próximo** job:

```bash
POD=$(kubectl get pods -n track-fraude -l job-name --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n track-fraude "$POD" -- python -c "import track_fraude.storage.raw_cache as c; print(c.WORKER_BUILD_ID)"
```

Esperado: `raw-cache-v2`.

## 3. Log do pipeline (início do job)

```bash
kubectl logs -n track-fraude "$POD" | head -30
```

Esperado:

```text
raw cache: configurado (raw-cache-v2) cache_dir=/cache/raw
raw cache: /app/data/raw/... -> /cache/raw/... | N arquivo(s), X MB em Ys (raw-cache-v2)
track vídeo: /cache/raw/.../cam1.mp4 (raw cache: /cache/raw)
```

Se aparecer `AVISO raw cache: TRACK_FRAUDE_RAW_CACHE_DIR não definido` → refaça `kubectl apply -f infra/k8s/worker-scaledjob.yaml`.

## 4. Tempo esperado

`pipeline_run_summary.json`: total ~40s (não ~165s).
