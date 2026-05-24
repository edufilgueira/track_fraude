# track_fraude

Sistema de análise de fraude em self-checkout (vídeo + POS).

## Arquitetura (3 pacotes)

| Pacote | Pasta | Função |
|--------|-------|--------|
| **Core** | `core/` | SQLite, schema, `load_store_config` (compartilhado) |
| **Servidor web** | `server/` | Login, grupos, lojas, endereço, OCR ROI — **independente** |
| **Worker** | `src/` + `jobs/` | Sync, YOLO, batch noturno, alertas |

O painel web e o worker compartilham o **mesmo SQLite** (`data/track_fraude.db`).  
O servidor pode rodar em outra máquina apontando para o mesmo banco (caminho local, UNC ou montagem de rede).

```text
core/                   ← track-fraude-core (sem OpenCV/FastAPI)
server/                 ← painel web (venv próprio, deps enxutas)
  config/settings.yaml  ← host, auth, database.path
jobs/ + src/            ← processamento de vídeo (OpenCV, Tesseract)
data/
  track_fraude.db       ← grupos, lojas, câmeras, usuários
  pos/                  ← vendas simuladas
  raw/video/            ← gravações
  processed/            ← sync_map, tracks, pipeline_state
  output/               ← alertas, clips, índice para revisão
```

**Configuração de lojas:** somente pelo painel web (SQLite). Não há mais `config/store.yaml`.

## Setup — worker (processamento)

```powershell
pip install -e ./core
pip install -e ".[dev]"
python tools/init_db.py              # schema SQLite
python tools/seed_demo_store.py      # opcional: grupo Cometa + LOJA-01 + cam1/cam2
```

Ou cadastre a loja pelo painel web (`server/main.py`).

## Setup — servidor web (independente)

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_db.py
python main.py
```

Copie **`server/` + `core/`** para outro servidor; ajuste `server/config/settings.yaml` → `database.path` para o mesmo SQLite (local ou rede).

## Fase 1 — Sync temporal

Saídas técnicas em `data/processed/{group_code}/{store_id}/{date}/`.  
Alertas e evidências (fases futuras) em `data/output/{group_code}/{store_id}/{date}/`.

```powershell
python tools/generate_test_video.py --store-id LOJA-01 --group-code cometa --camera cam2 --date 2026-05-22
python jobs/run_sync.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/validate_sync_pos.py --date 2026-05-22 --camera cam2 --frame 6550 --store-id LOJA-01 --group-code cometa
```

Use `--group-code` quando existir mais de uma loja com o mesmo `store_id` no banco.

OCR obrigatório: instale [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows) ou `sudo apt install tesseract-ocr` (Linux) e garanta que está no PATH.

## Testes

```powershell
pip install -e ./core
pip install -e ".[dev]"
pip install -e ./server
pytest
```

Acesse o painel: **http://127.0.0.1:8080/login** (`admin` / `admin123` — altere em `server/config/settings.yaml`)

Próximo passo: **Fase 2** — YOLO + tracking (`jobs/run_track.py`).
