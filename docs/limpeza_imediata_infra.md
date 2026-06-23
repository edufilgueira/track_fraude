Criei o script em [`infra/scripts/ctrl-disk-prune.sh`](infra/scripts/ctrl-disk-prune.sh), baseado na cron do doc. Ele detecta sozinho a raiz do repo (`track_fraude`) a partir do caminho do script.

## Como executar (no `ctrl-p01`, via SSH)

Na raiz do projeto:

```bash
# Limpeza leve (cache >24h, imagens dangling, containers parados)
./infra/scripts/ctrl-disk-prune.sh light

# Limpeza completa (+ K3s prune + garbage collection do registry)
./infra/scripts/ctrl-disk-prune.sh full
```

Se ainda não tiver permissão de execução:

```bash
chmod +x infra/scripts/ctrl-disk-prune.sh
```

Ou rode com bash:

```bash
bash infra/scripts/ctrl-disk-prune.sh light
```

## O que cada modo faz

| Modo | Ação |
|------|------|
| `light` | `builder prune` (>24h), imagens dangling, containers parados. Se disco ≥ 85% ou &lt; 10 GB livres, escala para prune full **sem** GC do registry |
| `full` | Prune completo do Docker + `k3s crictl rmi --prune` + GC do registry (~30s off em `:5000`) |

**Segurança:** não mexe em volumes (Postgres, RabbitMQ, registry-data). Pula a limpeza pesada se houver `docker build` em andamento.

## Variáveis opcionais

```bash
TRACK_FRAUDE_DIR=/caminho/alternativo \
REGISTRY_VOLUME=track_fraude_registry-data \
CTRL_PRUNE_LOG=/var/log/ctrl-disk-prune.log \
./infra/scripts/ctrl-disk-prune.sh full
```

## Instalação no cron (opcional)

No servidor, você pode apontar o cron para o script do repo:

```cron
*/30 * * * * /home/eduardo/track_fraude/infra/scripts/ctrl-disk-prune.sh light >> /var/log/ctrl-disk-prune.log 2>&1
15 3 * * * /home/eduardo/track_fraude/infra/scripts/ctrl-disk-prune.sh full >> /var/log/ctrl-disk-prune.log 2>&1
```

Ou copiar para `/usr/local/bin/` como no doc original.

Quer que eu atualize o `docs/Limpeza_imediata_cron.md` para referenciar esse arquivo em vez do bloco inline?