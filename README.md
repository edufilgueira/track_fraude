# track_fraude

Sistema de análise de fraude em self-checkout (vídeo + POS).

## Arquitetura (3 pacotes)


| Pacote           | Pasta            | Função                                                     |
| ---------------- | ---------------- | ---------------------------------------------------------- |
| **Core**         | `core/`          | SQLite, schema, `load_store_config` (compartilhado)        |
| **Servidor web** | `server/`        | Login, grupos, lojas, endereço, OCR ROI — **independente** |
| **Worker**       | `src/` + `jobs/` | Sync, YOLO, batch noturno, alertas                         |


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
  processed/            ← sync_map, tracks, events, alertas, pipeline_state
  output/               ← reservado (exportações / revisão — fases futuras)
```

**Configuração de lojas:** somente pelo painel web (SQLite). Não há mais `config/store.yaml`.

## Setup — worker (processamento)

```powershell
pip install -e ./core
pip install -e ".[dev,track]"
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

Copie `**server/` + `core/**` para outro servidor; ajuste `server/config/settings.yaml` → `database.path` para o mesmo SQLite (local ou rede).

## Fase 1 — Sync temporal

Saídas técnicas em `data/processed/{group_code}/{store_id}/{date}/`  
(inclui `events/timelines.json`, `alerts/index.json` e, nas fases futuras, clips por alerta).

```powershell
python tools/generate_test_video.py --store-id LOJA-01 --group-code cometa --camera cam2 --date 2026-05-22
python jobs/run_sync.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/validate_sync_pos.py --date 2026-05-22 --camera cam2 --frame 6550 --store-id LOJA-01 --group-code cometa
```

Use `--group-code` quando existir mais de uma loja com o mesmo `store_id` no banco.

OCR obrigatório: instale [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows) ou `sudo apt install tesseract-ocr` (Linux) e garanta que está no PATH.

## Fase 2 — Tracking (1 câmera)

Requer Fase 1 (`sync_map.json`) e `pip install -e ".[track]"` (Ultralytics YOLOv8).

```powershell
python jobs/run_track.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default --vid-stride 5
python tools/render_track_overlay.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
```

Saída: `data/processed/{group_code}/{store_id}/{date}/{camera}/tracks.parquet` + `manifest.json`.  
Colunas: `track_id`, `frame_idx`, `t_abs`, `x1`, `y1`, `x2`, `y2` (bbox).  
`--vid-stride` processa 1 a cada N frames (CPU ok com `yolov8n.pt`).

Para validar ≥3 pessoas, use um vídeo real com tráfego (`--video caminho.mp4`).

## Testes

Suíte enxuta (regras de negócio, zonas SQLite, migração DB, OCR):

```powershell
pip install -e ./core
pip install -e ".[dev]"
pip install -e ./server
pytest tests/
```

Validação com vídeo real continua manual (sync → track → events → alertas).

Acesse o painel: **[http://127.0.0.1:8080/login](http://127.0.0.1:8080/login)** (`admin` / `admin123` — altere em `server/config/settings.yaml`)

Próximo passo: **Fase 7** — pipeline batch diário (`run_daily_pipeline.py`); depois **Fase 7b** — YOLO só em trechos com movimento.

## Fase 6 — Regras completas (R1–R5)

Requer timelines enriquecidos (`run_events.py`, `run_merge.py`, `run_pos_match.py`).

```powershell
# Opcional: proxy visual de carga (bbox cam1 → vision_signals)
python jobs/run_vision.py --date 2026-05-22 --store-id LOJA-01 --group-code default

python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default
# R1b: janela de retorno ao caixa (default 30 min)
# ... --t-return-sec 1800
```

| Regra | Cenário |
|-------|---------|
| **R1** | Ficou no caixa sem venda |
| **R1b** | Suprime R1 se voltou ao mesmo caixa e pagou dentro de `T_return` |
| **R2** | Entrou **sem passar no caixa**, zero POS, saiu com **carga líquida** acima da entrada |
| **R3** | POS registrou menos itens que estimativa visual |
| **R4** | Muitos itens POS em tempo curto no caixa |
| **R5** | Transação cancelada + saída com indício de carga |

Cada alerta inclui `suspicion_score`, `vision_signals` (quando disponível) e `severity`. R2/R5 exigem `left` na timeline da loja (mesma visita).

Quando **R1 e R2** disparam na **mesma visita**, o motor gera **um único alerta** (`rule_id: R1+R2`). Com R2 restrita a skip checkout, isso raramente ocorre — **R1** cobre quem passou no caixa; **R2** cobre quem **nunca** entrou na zona de caixa.

**Carga (baseline):** na entrada registra `carry_baseline` (mãos vazias/objetos); na saída compara delta **líquido** (`net_objects`, `net_score`) — entrou vazio e saiu vazio → sem R2.

## Fase 5 — Pacotes de evidência (clips)

Requer alertas (`run_alerts.py`) e vídeos em `data/raw/video/{date}/` (ou `manifest.json` com chunks).

```powershell
python jobs/run_evidence.py --date 2026-05-22 --store-id LOJA-01 --group-code default
# Só JSON/summary (sem FFmpeg):  ... --skip-clips
# Ajustar janela:  ... --buffer-before 20 --buffer-after 20 --max-duration 300
```

Requer **FFmpeg** no PATH para gerar os MP4.

Saídas em `data/review/{group}/{store}/{date}/`:

```text
alerts/AL-20260522-0001/
  timeline.json
  pos_context.json
  summary.txt
  cam1_clip.mp4
  cam2_clip.mp4
  cam2_checkout_clip.mp4   ← foco na sessão de caixa
  evidence.json
index.json                 ← alertas + caminhos das evidências
```

## Fase 4 — Re-ID cross-camera

Requer `tracks.parquet` da **cam1 (entrada)** e **cam2 (caixa)**.

```powershell
# 1. Sync + track nas duas câmeras (se ainda não rodou)
python jobs/run_sync.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
python jobs/run_sync.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/run_track.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default --vid-stride 5
python jobs/run_track.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default --vid-stride 5

# 2. Eventos (cam1 + cam2) — opcional antes do merge; melhora horário de entrada
python jobs/run_events.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
python jobs/run_events.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default

# 3. Merge Re-ID → global_person_id
python jobs/run_merge.py --date 2026-05-22 --store-id LOJA-01 --group-code default
# Só temporal (rápido):  ... --skip-appearance

# 4. POS + alertas (timelines já enriquecido com global_person_id)
python jobs/run_pos_match.py --date 2026-05-22 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default

# 5. Evidências (clips cam1 + cam2 por alerta)
python jobs/run_evidence.py --date 2026-05-22 --store-id LOJA-01 --group-code default
```

Saídas em `data/processed/{group}/{store}/{date}/`:

- `merge/persons.json` — `global_person_id` + tracks por câmera
- `merge/cross_camera_links.json` — pares cam1↔cam2 com score
- `events/timelines.json` — tracks com `global_person_id` (após merge)
- `alerts/index.json` — R1–R5 com `global_person_id`, `store_timeline`, `suspicion_score`

## Fase 3 — Zonas, eventos e R1

Requer Fase 2 (`tracks.parquet`) e polígonos cadastrados no **painel web** (SQLite — `camera_zones`).

```powershell
# Painel web: Editar câmera → tipo Entrada/Caixa → "Definir zona no vídeo"
# Cam2 (checkout): abas Caixa 1, 2, 3… — "+ Adicionar caixa", desenhe e salve cada lane
# http://127.0.0.1:8080/stores/{id}/cameras/{id}/zone-editor

# Validar overlay: polígono + foot point + track_id
python tools/render_zone_overlay.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default

# Pipeline de eventos
python jobs/run_events.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default

# POS provisório (Node) — simula API real
node data/pos/server.js
# outro terminal:
python jobs/run_pos_match.py --date 2026-05-22 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default
```

Dados POS em `data/pos/transactions.json`. Sem API, omita `--pos-api-url` (leitura direta do arquivo).

```powershell
# Consulta manual à API
curl "http://127.0.0.1:3099/transactions?store_id=LOJA-01&date=2026-05-22&t_from=2026-05-22T10:00:00&t_to=2026-05-22T10:02:00&lane_id=1"
```

Saídas anteriores do pipeline:

- `data/processed/{group}/{store}/{date}/events/timelines.json` — `checkout_sessions[]`, `entered`/`left` (cam1)
- `data/processed/{group}/{store}/{date}/alerts/index.json` — alertas **R1–R5**

**R1:** duração no caixa acima do tempo mínimo configurado no **zone-editor** da câmera de caixa (`r1_min_checkout_duration_sec`, default 60 s) e zero transação POS em `[t_start ± δ, t_end ± δ]` na mesma `lane_id`.  
δ vem de `pos_match_delta_sec` da loja (SQLite, default 60 s).

**Porta única (cam1):** use zona `portal` — um polígono na porta. A 1ª passagem gera `entered`, a 2ª gera `left`.  
Opcional: `entry_vector: [dx, dy]` (pixels) indica o sentido de **entrada na loja**; o movimento na passagem classifica entered vs left.  
Se `entrance` e `exit` tiverem o **mesmo polígono**, o sistema trata automaticamente como portal.

# Fase 2

### Cam1 (porta):

```powershell
python jobs/run_sync.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
python jobs/run_track.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default --vid-stride 5
python tools/render_track_overlay.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
```

### Cam2 (caixa):

```powershell
python jobs/run_sync.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/run_track.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default --vid-stride 5
python tools/render_track_overlay.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
```

### Validar sync ↔ POS (cam2, se tiver POS alinhado):

python jobs/validate_sync_pos.py --date 2026-05-22 --camera cam2 --frame 6550 --store-id LOJA-01 --group-code default

<!-- # Fase 3

```powershell
# 1. Zonas no painel web (zone-editor) ou fallback JSON acima

# 2. Validar visualmente
python tools/render_zone_overlay.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default

# 3. Eventos → POS → alertas
python jobs/run_events.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/run_pos_match.py --date 2026-05-22 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default
``` -->


# Fase 4
```powershell
python jobs/run_events.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
python jobs/run_events.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/run_merge.py --date 2026-05-22 --store-id LOJA-01 --group-code default
python jobs/run_pos_match.py --date 2026-05-22 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default
```

# Fase 5
```powershell
python jobs/run_evidence.py --date 2026-05-22 --store-id LOJA-01 --group-code default
```


# Fase 6
```powershell
### Cam1 (caixa):
python jobs/run_sync.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
python jobs/run_track.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default --vid-stride 5
python tools/render_track_overlay.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
### Cam2 (caixa):
python jobs/run_sync.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/run_track.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default --vid-stride 5
python tools/render_track_overlay.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
# Validar sync ↔ POS (cam2, se tiver POS alinhado):
python jobs/validate_sync_pos.py --date 2026-05-22 --camera cam2 --frame 6550 --store-id LOJA-01 --group-code default
# Eventos
python jobs/run_events.py --date 2026-05-22 --camera cam1 --store-id LOJA-01 --group-code default
python jobs/run_events.py --date 2026-05-22 --camera cam2 --store-id LOJA-01 --group-code default
python jobs/run_merge.py --date 2026-05-22 --store-id LOJA-01 --group-code default
python jobs/run_pos_match.py --date 2026-05-22 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
python jobs/run_vision.py --date 2026-05-22 --store-id LOJA-01 --group-code default  # opcional
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default
# Produzir evidencias
python jobs/run_evidence.py --date 2026-05-22 --store-id LOJA-01 --group-code default
```
