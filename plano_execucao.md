# Plano final de execução — track_fraude

Guia completo do MVP até o projeto fechado, em fases sequenciais. Cada fase tem **objetivo**, **entregas**, **critério de conclusão** e **dependências**. Só avance quando a fase anterior estiver validada.

---

## Visão do produto final

Sistema batch (processamento noturno) que:

1. Ingere vídeo de 2 câmeras + POS (simulado → API real)  
2. Sincroniza timestamps, rastreia pessoas, une câmeras  
3. Detecta entrada, sessões de caixa (múltiplas), saída  
4. Cruza com POS e aplica regras R1–R5  
5. Gera alertas com timeline + clips cam1/cam2 para revisão humana  

**Stack base:** Python, Ultralytics YOLOv8, OpenCV, Shapely, JSON/Parquet (MVP), FFmpeg, FastAPI (futuro).

**Fora de escopo no núcleo:** LLM, identificação de SKU pelo vídeo, condenação automática.

---

## Mapa das fases

```mermaid
flowchart LR
  F1[Fase 1\nFundação]
  F2[Fase 2\nTracking 1 cam]
  F3[Fase 3\nZonas + R1]
  F4[Fase 4\n2 câmeras + merge]
  F5[Fase 5\nEvidências]
  F6[Fase 6\nRegras R2-R5]
  F7[Fase 7\nBatch diário]
  F7b[Fase 7b\nYOLO só movimento]
  F8[Fase 8\nRevisão]
  F9[Fase 9\nPOS real + calibração]
  F10[Fase 10\nProdução]

  F1 --> F2 --> F3 --> F4 --> F5 --> F6 --> F7 --> F7b --> F8 --> F9 --> F10
```

| Fase | Nome | Duração sugerida | Complexidade |
|------|------|------------------|--------------|
| **1** | Fundação e sync temporal | 1–2 semanas | Baixa |
| **2** | Tracking em 1 câmera | 1–2 semanas | Média |
| **3** | Zonas, eventos e R1 | 1–2 semanas | Média |
| **4** | 2 câmeras + Re-ID / merge | 2 semanas | Alta |
| **5** | Pacotes de evidência (clips) | 1 semana | Média |
| **6** | Regras completas + multi-sessão caixa | 2 semanas | Alta |
| **7** | Pipeline batch diário (24 h) | ~1 semana | Média |
| **7b** | Otimização: YOLO só com movimento | ~3–5 dias | Média |
| **8** | Interface de revisão | 2 semanas | Média |
| **9** | POS real, calibração e métricas | 2–3 semanas | Alta |
| **10** | Produção e escala | contínuo | Alta |

**Total estimado até MVP operacional (Fases 1–8):** ~12–17 semanas  
**Projeto completo (Fases 1–10):** ~17–23 semanas (depende de acesso à loja/POS)

---

## Fase 1 — Fundação e sync temporal

### Objetivo
Estabelecer estrutura do projeto, POS simulado e **relógio unificado** vídeo ↔ POS.

### Entregas
- Estrutura de pastas (`core/`, `server/`, `data/` com `raw/`, `pos/`, `processed/`, `output/`, `src/`, `jobs/`)
- Pacote `track-fraude-core` (SQLite) + painel web (`server/`) para cadastro de lojas
- Schema JSON POS + cenários simulados (normal, sem venda, cancelada)
- Interface `PosClient` + `FilePosClient`
- OCR de timestamp (ROI fixa) → `sync_map.json` por câmera
- Script de validação: dado um horário, localiza frame e transações POS no intervalo
- `pipeline_state.json` (esqueleto)
- Repositórios abstratos (`TrackRepository`, etc.) — implementação em arquivo

### Critério de conclusão
- [ ] 1 vídeo de teste + 1 JSON POS com horários alinhados  
- [ ] Script responde: “frame X = 06:14:22” e “vendas entre 06:10–06:15 na lane 3”  
- [ ] Documentação do schema POS e sync_map  

### Não fazer ainda
YOLO, zonas, alertas, clips.

---

## Fase 2 — Tracking em 1 câmera

### Objetivo
Detectar e rastrear **múltiplas pessoas** em uma câmera; persistir tracks.

### Entregas
- `pip install ultralytics opencv-python pyarrow` (Parquet)
- `jobs/run_track.py --camera cam1 --date YYYY-MM-DD`
- YOLOv8 + ByteTrack (`vid_stride` configurável)
- Saída: `processed/{date}/cam1/tracks.parquet` + `manifest.json`
- Cada linha: `track_id`, `frame_idx`, `t_abs`, `bbox`
- (Opcional) embeddings Re-ID por track para Fase 4
- Teste com clip 5–15 min, CPU ok (`yolov8n`)

### Critério de conclusão
- [ ] Vídeo curto: ≥3 pessoas com `track_id` estável na maior parte do tempo  
- [ ] Parquet legível + overlay de debug (bbox + id no vídeo)  
- [ ] Tempo absoluto em cada detecção via sync_map  

### Dependências
Fase 1 (`sync_map` pronto).



### Checklist Fase 2 (plano)

| Critério | Status no seu teste |
|----------|---------------------|
| `run_track.py` + Parquet + manifest | ✅ cam1 rodou (`tracks.parquet`, 30 detecções) |
| Colunas `track_id`, `frame_idx`, `t_abs`, bbox | ✅ |
| `t_abs` via `sync_map` | ✅ (sync cam1 ok) |
| Parquet legível | ✅ (pode inspecionar com pandas/pyarrow) |
| Overlay debug (`render_track_overlay.py`) | ⚠️ confirme se rodou e revisou o MP4 |
| **≥3 pessoas** com ID estável | ⚠️ seu run deu **2 tracks únicos** — abaixo do critério |
| Clip 5–15 min (opcional no plano) | ⚠️ seu clip parece ~1 min |

### Conclusão prática

- **Tecnicamente (software):** Fase 2 **implementada** ✅  
- **Validação de negócio (loja real):** Fase 2 **parcial** ⚠️ — falta provar tracking com **≥3 pessoas** e IDs estáveis no overlay.

Isso não impede avançar no **código** da Fase 3, mas o plano diz: *“só avance quando a fase anterior estiver validada”*.

### Recomendação

**Antes da Fase 3 (ideal):**
1. Rodar overlay na cam1 e olhar se os 2 IDs fazem sentido.
2. Testar com vídeo onde apareçam **≥3 pessoas** (ou `--vid-stride 2` se perder detecção).
3. Quando tiver **cam2 fixa no caixa**: sync + track cam2 (Fase 3 usa **cam2** de verdade).

**Pode ir para Fase 3 se:**
- Aceita fechar Fase 2 como “pipeline ok, qualidade a refinar com cam2”.
- Fase 3 precisa sobretudo de **cam2 + zonas + POS** — aí cam2 vira prioridade de configuração, não só de tracking.

### Fase 3 — o que vem

- Polígonos de zona (lanes checkout, entrada/saída)
- `run_events.py` → timeline (entrou, sessão caixa, saiu)
- Match POS + **R1** (ficou no caixa sem venda)

**Resumo:** não é “só ir para Fase 3” cegamente — **sim, o próximo passo do produto é Fase 3**, mas marque Fase 2 como concluída quando tiver overlay revisado e ideally **≥3 pessoas** (ou documente que cam1 provisória só deu 2). A **cam2 do caixa** será central na Fase 3 de qualquer forma.




---

## Fase 3 — Zonas, eventos e primeira regra (R1)

### Objetivo
Configurar polígonos, gerar timeline e **primeiro alerta de fraude** (ficou no caixa sem venda).

### Entregas
- Ferramenta/script de desenho de polígonos → `config/zones_cam2.json` (lanes + entrada/saída cam1)
- Validação visual: overlay polígono + foot point + track_id
- Job `run_events.py`: FSM com histerese (~3 s)
  - `entered`, `left`, `checkout_sessions[]` (suporta múltiplas sessões desde já)
- Job `run_pos_match.py`: match por sessão `[t_start - δ, t_end + δ]`, `lane_id`
- Job `run_alerts.py`: **R1** apenas
- Saída: `data/processed/{group}/{store}/{date}/events/timelines.json`, `data/output/{group}/{store}/{date}/alerts/index.json`

### Critério de conclusão
- [ ] Cenário simulado: pessoa no caixa 3, 5 min, zero venda → alerta R1  
- [ ] Cenário normal: venda no intervalo → sem R1  
- [ ] Duas pessoas em lanes diferentes → alertas independentes  

### Dependências
Fases 1–2.

---

## Fase 4 — Duas câmeras + merge (Re-ID)

### Objetivo
Processar cam1 e cam2 **em fila**, persistir por câmera, **unificar** mesma pessoa.

### Entregas
- Pipeline fila: TRACK cam1 → TRACK cam2 → MERGE
- `processed/{date}/cam2/tracks.parquet`
- Job `run_merge.py`:
  - embedding + janela temporal
  - saída: `persons.json`, `cross_camera_links.json`
- Job EVENTS lê `global_person_id` (timeline unificada)
- POS match e R1 por pessoa unificada
- `pipeline_state.json`: status por câmera + merge

### Critério de conclusão
- [ ] Mesma pessoa entrada (cam1) + checkout (cam2) → 1 `global_person_id`  
- [ ] 2 pessoas cruzando → 2 persons sem troca  
- [ ] R1 funciona com timeline das duas câmeras  

### Dependências
Fases 1–3 (zones cam1 entrada/saída, cam2 checkout).

---

## Fase 5 — Pacotes de evidência (clips)

### Objetivo
Revisor recebe **timeline + clips cam1/cam2** por alerta, não o dia inteiro.

### Entregas
- Job `run_evidence.py`
- `evidence_window`: `buffer_before` / `buffer_after` (default 20 s)
- Corte FFmpeg por timestamp (suporta chunks horários via manifest)
- Estrutura por alerta:

```text
data/review/{group_code}/{store_id}/{date}/alerts/AL-XXXX/
  timeline.json
  pos_context.json
  summary.txt
  cam1_clip.mp4
  cam2_clip.mp4
```

- Cap de duração (ex.: 5 min) + clip opcional focado no checkout

### Critério de conclusão
- [ ] Alerta R1 inclui clips sincronizados + resumo textual  
- [ ] Revisor entende o caso sem abrir vídeo de 24 h  

### Dependências
Fase 4 (persons + alertas).


### Checklist Fase 5

1. Aumentar --max-duration (solução direta)
O que --max-duration limita
Limita a janela total do clip principal, usada nas duas câmeras (cam1_clip.mp4 e cam2_clip.mp4 com o mesmo intervalo):
2. Definir uma tela para reduzir os tamanhos dos arquivos gerados para o revisor
3. O buffer de 20s esta sendo aplicado tanto no caixa quanto na estrada do video. Verificar se deve separar

---

## Fase 6 — Regras completas e multi-sessão no caixa

### Objetivo
Cobrir skip checkout, cancelamento, inconsistência de itens; tratar **sair do caixa e voltar**.

### Entregas
- **R2**: entrou, não passou no caixa (ou zero POS), saiu com sacola  
- **R5**: transação cancelada + sacola na saída  
- **R3** (Fase 1 visual): sacola grande + `qty_total` POS baixo (margem conservadora)  
- **R4** (opcional): tempo curto vs muitos itens POS  
- **R1b**: suprimir/rebaixar R1 se sessão posterior tiver venda no mesmo lane dentro de `T_return` (ex.: 30 min)  
- Alertas só após `left_store` ou com flag de prioridade  
- Detecção sacola (YOLO classe ou proxy)  
- Score composto (pesos por regra × confiança)

### Critério de conclusão
- [ ] Cenários simulados para R1, R1b, R2, R5 passam  
- [ ] “Saiu do caixa, pegou item, voltou e pagou” → sem falso positivo grave  
- [ ] “Entrou, não passou no caixa, saiu com sacola” → R2  

### Dependências
Fases 3–5.

### Limitações honestas (importante para calibrar expectativa)
1. Não dá para saber se o objeto é da loja só pelo vídeo amplo (regra de ouro do projeto: itens pagos = POS; itens levados = estimativa visual).
2. Sacola escura / mochila nas costas / carrinho reduzem precisão — por isso margem conservadora e revisão humana.
3. Funcionário com uniforme, cliente recorrente com sacola ecológica, família no mesmo frame geram ruído — calibração por loja na Fase 9.
4. O ideal técnico é capturar carry na cam1 (entrada/saída), não só no checkout — você já tem portal + timeline entered/left para isso.

---

## Fase 7 — Pipeline batch diário (orquestração)

### Objetivo
Processar **1 dia completo** (24 h ou turno) ponta a ponta com um único comando — sem otimização de movimento ainda (`vid_stride` fixo).

### Entregas
- `data/raw/video/{date}/` + `manifest.json` (1 ou N chunks/câmera com `t_start`)
- Job **INGEST** (`jobs/run_ingest.py`): valida integridade, gaps entre chunks, POS do dia
- **`jobs/run_daily_pipeline.py --date --store`**
- Ordem: INGEST → SYNC → TRACK cam1 → TRACK cam2 → MERGE → EVENTS → POS → VISION → ALERTS → EVIDENCE
- `vid_stride` configurável por câmera na CLI do pipeline (default 5–10)
- Rerodar fase isolada (`--from merge`, `--only track --camera cam2`)
- Agendador (Task Scheduler / cron) batch noturno
- Retenção: política raw vs `tracks.parquet` vs clips
- Log de duração por fase

### Critério de conclusão
- [ ] 1 dia simulado (2 câmeras) processa ponta a ponta via `run_daily_pipeline.py`
- [ ] `alerts/index.json` + pacotes de evidência prontos de manhã
- [ ] Rerodar job isolado (ex.: só MERGE) funciona

### Dependências
Fases 1–6.

---

## Fase 7b — YOLO só onde há movimento (performance)

### Objetivo
Acelerar o batch quando a loja fica **vazia a maior parte do dia** — YOLO/ByteTrack apenas nos trechos com movimento, mantendo vídeo raw 24 h intacto.

### Entregas
- **Pré-scan de movimento (CPU)** no INGEST: intervalos ativos por câmera (ROI portal cam1, lanes cam2)
- `active_windows.json` (ou bloco no manifest): `[t_start, t_end]` + **padding** 30–60 s
- Duração mínima do trecho (≥10 s); janelas **independentes** por câmera
- `run_track.py`: `--windows` ou leitura automática do INGEST; Parquet com **`t_abs` absoluto**
- `vid_stride` adaptativo **dentro** dos trechos ativos (corredor 8–15, checkout 5–8)
- Flag `--full-day-track` no pipeline (desliga filtro — debug/calibração)
- Integração no `run_daily_pipeline.py` (7b ativa por default; `--full-day-track` para modo 7 puro)

### Regras de ouro
1. Raw 24 h intacto — evidência usa arquivo completo ou chunks com `t_start`
2. Horário absoluto sempre — merge, POS e alertas dependem de `t_abs` real
3. Padding nas bordas — não perder `entered`/`left` ou início de sessão no caixa
4. `track_id` pode reiniciar entre trechos — aceitável

### Ganho esperado (RTX 3060, loja ~85–90% vazia)

| Modo | Tempo total (2 câmeras) |
|------|-------------------------|
| Fase 7 (dia inteiro) | ~4–8 h |
| Fase 7b (só movimento) | ~1,5–3 h |

### Critério de conclusão
- [ ] INGEST gera janelas; TRACK ignora trechos vazios; `t_abs` correto no Parquet
- [ ] Comparar 1 dia `--full-day-track` vs movimento: mesmos alertas críticos (± borda)
- [ ] Pipeline noturno termina dentro da janela operacional (ex.: antes das 7h)

### Dependências
Fase 7.

---

## Fase 8 — Interface de revisão

### Objetivo
Operador revisa fila de alertas sem abrir pastas manualmente.

### Entregas (MVP UI)
- FastAPI backend lendo `data/output/{group}/{store}/`
- Lista: data, score, regras, horários entrada/saída, lane
- Detalhe: timeline, POS, player 2 clips (cam1 | cam2)
- Status: `pending_review` | `confirmed` | `dismissed`
- Persistir decisão (JSON ou SQLite inicial)

### Critério de conclusão
- [ ] Revisor processa 10 alertas do dia na UI  
- [ ] Marca falso positivo / confirmado  
- [ ] Link direto para clips  

### Dependências
Fase 5–7 (7b recomendada antes de produção 24 h, mas não bloqueia UI).

**Alternativa mínima:** pasta + `index.json` + player local — UI pode ser Fase 8b se atrasar.

---

## Fase 9 — POS real, calibração e métricas

### Objetivo
Trocar simulado por API/export real; calibrar loja; medir qualidade.

### Entregas
- `HttpPosClient` ou import CSV do POS real
- Mapeamento `lane_id` vídeo ↔ terminal POS
- Calibração: `T_min`, `δ`, buffers, thresholds por loja
- Conjunto de casos rotulados manualmente (30–50 eventos)
- Métricas: precision/recall alertas, taxa match track↔TX, falsos positivos/turno
- Ajuste zonas e Re-ID com vídeo real da loja

### Critério de conclusão
- [ ] Pipeline roda com POS real por ≥1 semana piloto  
- [ ] Precision@K documentada em casos revisados  
- [ ] Parâmetros calibrados por loja no **painel web** (SQLite)  

### Dependências
Fases 1–8 + acesso POS/loja.

---

## Fase 10 — Produção e escala

### Objetivo
Operação estável, manutenção, evolução opcional.

### Entregas
- Migrar metadados para **PostgreSQL** (jobs, persons, alerts, review)
- Manter tracks em Parquet ou object storage
- Monitoramento: job falhou, gap vídeo, OCR drift
- Multi-loja: `store_id` em todos artefatos
- LGPD: retenção, blur rosto (se exigido), base legal
- (Opcional) balança checkout / câmera top-down / near-real-time
- Documentação operacional e runbook

### Critério de conclusão
- [ ] 1 loja em produção batch estável  
- [ ] Runbook: o que fazer se NVR falhar, POS atrasar, GPU cair  
- [ ] Roadmap pós-MVP definido (multi-loja, DB, sensores)  

---

## Artefatos por fase (referência rápida)

| Fase | Arquivos / jobs principais |
|------|----------------------------|
| 1 | `transactions.json`, `sync_map.json`, `PosClient` |
| 2 | `tracks.parquet`, `run_track.py` |
| 3 | `zones_*.json`, `timelines.json`, R1 |
| 4 | `persons.json`, `run_merge.py` |
| 5 | `AL-*/cam*_clip.mp4`, `summary.txt` |
| 6 | R2–R5, score, R1b |
| 7 | `manifest.json`, `run_ingest.py`, `run_daily_pipeline.py` |
| 7b | `active_windows.json`, track por janelas, `--full-day-track` |
| 8 | API + UI revisão |
| 9 | `HttpPosClient`, métricas, calibração |
| 10 | Postgres, multi-loja, runbook |

---

## Regras de ouro do projeto

1. **Sync antes de tracking** — sem relógio, nada fecha.  
2. **Uma pessoa = um `global_person_id`** — loop em persons, não “a loja”.  
3. **Caixa = polígono pré-configurado** + foot point + histerese.  
4. **POS por sessão de caixa** — múltiplas idas = múltiplas sessões.  
5. **Itens pagos = POS**; **itens levados = estimativa visual** — nunca SKU pelo vídeo amplo.  
6. **Alerta ≠ condenação** — sempre revisão humana + clip.  
7. **MVP em arquivos** — DB na Fase 10 (ou 8 se UI exigir SQLite).  
8. **Sem LLM** no núcleo.

---

## Por onde começar amanhã (Fase 1 — dia 1)

1. Subir painel web (`server/`) e cadastrar loja + câmeras (OCR ROI)  
2. Definir schema `transactions.json` + 3 cenários de teste  
3. Implementar `FilePosClient`  
4. Extrair 1 frame, validar ROI do timestamp, rodar OCR  
5. Gerar `sync_map.json` e script que cruza intervalo com POS  

Quando os 5 itens da Fase 1 estiverem ok → **Fase 2**.

---

## Checklist master (projeto completo)

```
Fase 1  [ ] POS simulado  [ ] OCR sync  [ ] validação temporal
Fase 2  [ ] YOLO track 1 cam  [ ] tracks.parquet
Fase 3  [ ] zonas  [ ] timeline  [ ] R1  [ ] match POS
Fase 4  [ ] 2 câmeras  [ ] merge/Re-ID  [ ] persons.json
Fase 5  [ ] clips cam1+cam2  [ ] summary + timeline alerta
Fase 6  [x] R2 R3 R4 R5  [x] R1b multi-sessão  [x] score
Fase 7   [ ] batch 24h  [ ] manifest  [ ] pipeline diário
Fase 7b  [ ] INGEST movimento  [ ] YOLO só trechos ativos  [ ] validação vs full-day
Fase 8  [ ] UI revisão  [ ] status alertas
Fase 9  [ ] POS real  [ ] calibração  [ ] métricas
Fase 10 [ ] produção  [ ] DB  [ ] runbook  [ ] LGPD
```

---

Este plano consolida tudo que definimos: batch noturno, JSON/Parquet, fila por câmera + merge, zonas, multi-pessoa, multi-sessão no caixa, buffers, regras R1–R5 e revisão com clips.

Se quiser, em **Agent mode** posso gravar este plano no `esbouço.md` como seção **“Plano final de execução”** e alinhar as semanas antigas (839+) a estas 10 fases para ficar um único guia no repositório.