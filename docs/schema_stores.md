# Schema SQLite — grupos, lojas e câmeras

Configuração **somente via painel web** (`server/`).  
Persistido em `data/track_fraude.db` (ou caminho em `server/config/settings.yaml` → `database.path`).

## Tabela `groups`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER PK | ID interno |
| `group_code` | TEXT UNIQUE | Código (ex: `cometa`) |
| `name` | TEXT | Nome exibido (ex: Grupo Cometa) |
| `active` | INTEGER | 1 = ativo |

## Tabela `stores`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER PK | ID interno |
| `group_db_id` | INTEGER FK | Referência `groups.id` |
| `store_id` | TEXT | Código da loja no grupo (ex: `LOJA-01`) |
| `name` | TEXT | Nome exibido |
| `street` | TEXT | Rua |
| `number` | TEXT | Número |
| `neighborhood` | TEXT | Bairro |
| `city` | TEXT | Cidade |
| `state` | TEXT | UF (2 letras) |
| `cep` | TEXT | CEP |
| `timezone` | TEXT | Fuso IANA |
| `ocr_sample_interval_sec` | INTEGER | Intervalo OCR no worker |
| `ocr_min_confidence` | REAL | Confiança mínima OCR |
| `pos_match_delta_sec` | INTEGER | Margem δ consulta POS |
| `active` | INTEGER | 1 = ativa |

**Unique:** `(group_db_id, store_id)` — o mesmo código pode existir em grupos diferentes.

## Tabela `cameras`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | INTEGER PK | ID interno |
| `store_db_id` | INTEGER FK | Referência `stores.id` |
| `camera_id` | TEXT | Ex: `cam1`, `cam2` |
| `description` | TEXT | Entrada, checkout, etc. |
| `ocr_x`, `ocr_y` | INTEGER | ROI timestamp (pixels) |
| `ocr_width`, `ocr_height` | INTEGER | Tamanho ROI |

## Tabela `users`

Usuários do painel web (login).

## API

```python
from track_fraude_core.store_config import load_store_config

config = load_store_config(
    store_id="LOJA-01",
    group_code="cometa",  # opcional se store_id for único no banco
    db_path="data/track_fraude.db",
)
# config["group_code"], config["address"], config["cameras"]...
```

## Fluxo no painel

1. Cadastrar **grupo** (ex: Cometa)
2. Abrir grupo → **Nova loja** (endereço + OCR/POS)
3. Abrir loja → cadastrar **câmeras** e ROI

## Deploy em servidores separados

1. **Servidor web:** `server/` + `core/` + SQLite acessível (`database.path`)
2. **Worker:** `src/` + `jobs/` + `core/` + mesmo `database.path`

Ambos leem a mesma configuração; alterações no painel refletem no próximo job do worker.
