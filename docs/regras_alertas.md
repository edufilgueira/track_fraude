# Regras de alerta R1–R5 — referência detalhada

Documentação das regras de fraude implementadas na **Fase 6** do pipeline `track_fraude`.  
Job principal: `jobs/run_alerts.py` → gera `data/processed/{group}/{store}/{date}/alerts/index.json`.

---

## Visão geral do fluxo

Antes de qualquer regra disparar, o pipeline precisa ter produzido:

| Etapa | Job | O que alimenta as regras |
|-------|-----|--------------------------|
| Tracking | `run_track.py` | `tracks.parquet` (bbox por frame) |
| Eventos | `run_events.py` | `entered`/`left` (cam1), `checkout_sessions[]` (cam2) |
| Merge | `run_merge.py` | `global_person_id` ligando cam1 + cam2 |
| POS match | `run_pos_match.py` | `pos_matches[]` em cada sessão de caixa |
| Visão (opcional) | `run_vision.py` | `vision_signals` no track cam1 (bbox + YOLO) |
| Alertas | `run_alerts.py` | `alerts/index.json` |

As regras operam sobre **`PersonVisit`**: uma visita agrega todos os tracks com o mesmo `global_person_id` (ex.: cam1 = porta, cam2 = caixa).

Arquivos centrais:

- `src/track_fraude/alerts/config.py` — parâmetros (`AlertRuleConfig`)
- `src/track_fraude/alerts/rules.py` — lógica R1–R5
- `src/track_fraude/alerts/visit.py` — montagem da visita
- `src/track_fraude/alerts/scoring.py` — pontuação e severidade
- `src/track_fraude/vision/carry.py` — sinais visuais de carga (R2, R3, R5)

---

## Onde cada parâmetro vive

Legenda usada nas tabelas abaixo:

| Origem | Significado |
|--------|-------------|
| **SQLite** | Coluna em `data/track_fraude.db`, editável na tela **Regras** (`/stores/{id}/rules`) |
| **Código** | Constante ou default em `AlertRuleConfig` / módulo Python |
| **CLI** | Argumento de linha de comando em `run_alerts.py` ou `run_vision.py` |
| **Derivado** | Calculado em runtime a partir de timelines, POS ou vídeo |

### Parâmetros por origem

| Regra | Significado das variáveis principais |
|-------|--------------------------------------|
| **R1** | `r1_min_checkout_duration_sec` — tempo mínimo (em segundos) que a pessoa precisa permanecer na zona do caixa para a sessão ser considerada suspeita; abaixo desse valor, a permanência é tratada como normal. `pos_match_delta_sec` (δ) — margem temporal somada ao início e fim da sessão na hora de buscar vendas POS; evita perder transações registradas alguns segundos antes ou depois do intervalo detectado pela câmera. |
| **R1b** | `t_return_sec` — janela máxima (em segundos) após sair do caixa em que a pessoa pode voltar, pagar na mesma `lane_id`, e fazer o R1 da sessão anterior ser descartado; modela o caso “esqueci algo, voltei e paguei”. |
| **R2** | `require_left_store` — exige evento `left` na porta (cam1) antes de avaliar a regra; garante que a visita terminou. `carry_confidence_threshold` — confiança mínima do perfil visual para considerar o indício de carga confiável. `net_carry_score_threshold` — incremento mínimo do `carry_score` (proxy bbox) entre entrada e saída quando YOLO não confirma objeto. Variáveis visuais (`hand_objects`, `carry_delta`, etc.) — descrevem se a pessoa saiu carregando mais do que entrou. |
| **R3** | `r3_visual_margin` — tolerância em itens entre o que o POS registrou (`qty_total`) e a `visual_estimate`; só dispara se POS < visual − margem. `carry_confidence_threshold` — mesma confiança mínima visual; evita R3 quando o proxy bbox/YOLO é incerto. |
| **R4** | `r4_min_items` — quantidade mínima de itens pagos no POS para a sessão ser candidata. `r4_fast_duration_sec` — tempo máximo no caixa considerado “rápido demais” para aquela quantidade de itens. `enable_r4` — liga ou desliga a regra globalmente. |
| **R5** | `delta_sec` (fixo em 60 s) — margem temporal em torno de `visit_start`/`visit_end` para buscar transações POS com status `cancelled`. Mesmas variáveis visuais de R2 (`carry_confidence_threshold`, `carry_delta.positive`) — confirmam saída com indício de carga após o cancelamento. |
| **Visão** | YOLO `conf` — confiança mínima da detecção de objetos carregáveis (handbag, bottle, etc.). YOLO `model` — pesos do detector usado em `run_vision.py`. Constantes bbox em `carry.py` (`_ASPECT_CARRY_THRESHOLD`, `_WIDTH_CARRY_RATIO`, janelas de snapshot) — proxies geométricos quando YOLO não roda ou não vê o objeto. |
| **Scoring** | `rule_weights` — peso base de cada regra no `suspicion_score` (multiplicado pela `confidence`); define prioridade relativa entre R1, R2, R3, R4 e R5 no ranking de alertas. |
| **Evidência** | `buffer_before_sec` / `buffer_after_sec` — margem nos clips completos cam1/cam2. `checkout_buffer_before_sec` / `checkout_buffer_after_sec` — margem no clip curto do caixa (cam2). Usados por `run_evidence.py`, não entram na lógica R1–R5. |
| **Pré-requisito** | `hysteresis_sec` — tempo mínimo dentro/fora de uma zona antes de confirmar entrada, saída ou sessão de caixa; reduz flicker quando a bbox oscila na borda do polígono. |

| Parâmetro | Regra(s) | Origem | Valor default | Como alterar |
|-----------|----------|--------|---------------|--------------|
| `buffer_before_sec` | evidência | **SQLite** (`stores`) | 20 s | Tela Regras → bloco “Recorte de vídeo” |
| `buffer_after_sec` | evidência | **SQLite** (`stores`) | 20 s | Tela Regras |
| `checkout_buffer_before_sec` | evidência | **SQLite** (`stores`) | 5 s | Tela Regras |
| `checkout_buffer_after_sec` | evidência | **SQLite** (`stores`) | 5 s | Tela Regras |
| `r1_min_checkout_duration_sec` | R1 | **SQLite** (`stores`) | 20 s | Tela Regras |
| `pos_match_delta_sec` | R1 (indireto) | **SQLite** (`stores`) | 20 s | Tela Regras; usado em `run_pos_match.py` |
| `t_return_sec` | R1b | **SQLite** (`stores`) | 1800 s (30 min) | Tela Regras; override `--t-return-sec` no `run_alerts.py` |
| `require_left_store` | R2, R5 | **CLI** + **Código** | `true` | `--no-require-left` (somente testes) |
| `carry_confidence_threshold` | R2, R3, R5 | **SQLite** (`stores`) | 0.55 | Tela Regras |
| `net_carry_score_threshold` | R2, R5 | **Código** | 0.15 | Editar `AlertRuleConfig` |
| `r3_visual_margin` | R3 | **SQLite** (`stores`) | 2 itens | Tela Regras |
| `r4_min_items` | R4 | **SQLite** (`stores`) | 5 itens | Tela Regras |
| `r4_fast_duration_sec` | R4 | **SQLite** (`stores`) | 90 s | Tela Regras |
| `enable_r4` | R4 | **SQLite** (`stores`) | `true` | Tela Regras |
| `r5_cancelled_delta_sec` | R5 | **SQLite** (`stores`) | 60 s | Tela Regras |
| `rule_weights` (R1–R5) | scoring | **Código** | ver seção scoring | Editar `AlertRuleConfig` |
| `hysteresis_sec` (FSM zonas) | pré-requisito | **Código** | 3.0 s | `build_zones_payload()` / `ZonesConfig` |
| YOLO `conf` | visão | **CLI** | 0.35 | `--conf` no `run_vision.py` |
| YOLO `model` | visão | **CLI** | `yolov8n.pt` | `--model` no `run_vision.py` |

> **Nota:** Parâmetros de R1–R5 e buffers de evidência ficam no SQLite e são editados na tela **Regras**. `run_alerts.py` e `run_evidence.py` leem a loja via `load_job_store_config()`; CLI pode sobrescrever alguns valores pontualmente.

---

## Conceito: `PersonVisit`

Cada pessoa (`global_person_id`, ex. `P-0003`) vira uma visita com:

| Campo | Origem | Uso nas regras |
|-------|--------|----------------|
| `store_timeline` | track cam1 | `entered` / `left` na loja |
| `checkout_sessions` | track(s) cam2 | R1, R1b, R3, R4 |
| `carry_profile` | cam1 + `vision_signals` ou cálculo bbox | R2, R3, R5 |
| `visit_start` / `visit_end` | timeline ou sessões | R5 (busca POS cancelado) |

Funções auxiliares importantes:

- `has_entered_store` — existe evento `entered`
- `has_left_store` — existe evento `left`
- `paid_qty_total()` — soma `qty_total` de matches com status `paid` ou `completed`
- `ready_for_visit_rules(require_left_store)` — R2/R5 exigem `left` quando `require_left_store=true`

---

## Sinais visuais compartilhados (`vision_signals`)

Gerados por `run_vision.py` (bbox + YOLO) ou calculados on-the-fly a partir do `tracks.parquet` cam1.

### Snapshots

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `carry_at_enter` | Estado na entrada (`entered`) | bbox ± YOLO |
| `carry_at_exit` | Estado 2–10 s antes do `left` | bbox ± YOLO |
| `carry_baseline` | Cópia de `carry_at_enter` | derivado |
| `carry_delta` | Delta líquido entrada → saída | derivado |
| `confidence` | 0–0.95, combina delta e acordo YOLO | derivado |
| `visual_estimate` | Estimativa de itens visíveis | derivado |
| `source` | `"hand_proxy"`, `"bbox+yolo"` ou `"preset"` | derivado |

### Campos dentro de cada snapshot (`carry_at_enter` / `carry_at_exit`)

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `hands_empty` | Sem indício de carga (bbox **e** YOLO) | derivado |
| `hand_objects_bbox` | 0 ou 1 via aspecto/largura da bbox | **Código** (`carry.py`) |
| `hand_objects_yolo` | Contagem YOLO de objetos carregáveis | **Derivado** (YOLO) ou `null` se não rodou |
| `hand_objects` | `max(hand_objects_bbox, hand_objects_yolo)` | derivado |
| `carry_score` | 0–1, proxy de braços estendidos | **Código** (fórmula aspecto) |
| `aspect` | largura / altura média da bbox | derivado |
| `bbox_width` | largura média da bbox (px) | derivado |
| `bbox_area` | área média da bbox | derivado |
| `bag` | Indício de sacola (aspect ≥ 0.52 ou label YOLO) | derivado |
| `yolo_labels` | Classes detectadas (ex. `bottle`, `handbag`) | derivado |
| `yolo_frame_idx` | Frame usado na inferência | derivado |

### Constantes bbox (fixas no código — `carry.py`)

| Constante | Valor | Efeito |
|-----------|-------|--------|
| `_ASPECT_CARRY_THRESHOLD` | 0.38 | aspect ≥ valor → 1 objeto bbox |
| `_WIDTH_CARRY_RATIO` | 1.10 | largura saída ≥ 110% da entrada → 1 objeto |
| carry_score objeto | ≥ 0.55 | força 1 objeto se aspecto não bastou |
| hands_empty | carry_score < 0.35 | mãos “vazias” no proxy bbox |
| bag | aspect ≥ 0.52 | classifica sacola |
| `exit_snapshot_start_before_sec` | 10 s | janela estável antes do portal na saída |
| `exit_snapshot_end_before_sec` | 2 s | fim da janela antes do `left` |

### Constantes YOLO (fixas no código — `object_carry.py`)

| Constante | Valor | Efeito |
|-----------|-------|--------|
| `CARRY_CLASS_IDS` | backpack, handbag, suitcase, bottle, cup, cell phone, book | classes COCO monitoradas |
| `conf` (default CLI) | 0.35 | confiança mínima YOLO |
| margem ROI pessoa | 30% | expande bbox antes de filtrar detecções |

### Lógica de `carry_delta.positive` (roubo líquido visual)

Usado por **R2** e **R5** via `has_net_carry_theft()`.

**Com YOLO disponível nos dois instantes:**

- `net_objects_yolo = exit_yolo - enter_yolo` (mínimo 0)
- Dispara se `net_objects_yolo > 0`, ou `new_bag`, ou (entrou vazio **e** YOLO vê objeto na saída com `net_score ≥ 0.15`)
- **Supressão:** se YOLO = 0 na entrada **e** na saída, **não dispara** mesmo que bbox alargue (evita falso positivo ao devolver produto)

**Sem YOLO:**

- Usa delta bbox: `net_objects_bbox`, `new_bag`, ou entrada vazia + saída com carga + `net_score ≥ 0.15`

---

## Pontuação e severidade

Cada alerta recebe `suspicion_score = peso_da_regra × confidence` (arredondado).

| Regra | Peso (`rule_weights`) | Confidence típica |
|-------|----------------------|-------------------|
| R1 | 40 | 1.0 (fixa) |
| R2 | 40 | `carry_profile.confidence` |
| R5 | 35 | `carry_profile.confidence` |
| R3 | 25 | `carry_profile.confidence` |
| R4 | 15 | 0.85 (fixa no código) |

**Severidade** (`score_band`):

- ≥ 70 → `high`
- ≥ 40 → `medium`
- < 40 → `low`

R1, R2, R5 e alerta consolidado **R1+R2** são forçados para `high` quando score ≥ 40.

---

# R1 — Permanência no caixa sem venda POS

## Objetivo

Detectar quando uma pessoa **fica tempo demais na fila/caixa** sem que o POS registre venda na mesma `lane_id` dentro da janela temporal da sessão.

## Tipo de alerta

- **Escopo:** por `checkout_session` (cam2)
- **`rule_id`:** `"R1"`
- **Função:** `evaluate_r1_session()` em `rules.py`

## Condições (todas obrigatórias)

1. Sessão **encerrada** (`t_end` presente)
2. `duration_sec > min_checkout_duration_sec`
3. `pos_matches` existe e está **vazio** (`len == 0`)

## Variáveis

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `session.duration_sec` | Tempo dentro da zona `checkout_lane_N` | **Derivado** (FSM cam2, histerese 3 s) |
| `session.lane_id` | Número do caixa | **SQLite** (zona desenhada no zone-editor) |
| `session.pos_matches` | Transações POS associadas | **Derivado** (`run_pos_match.py`) |
| `min_checkout_duration_sec` | Tempo mínimo para suspeita | **SQLite** → `stores.r1_min_checkout_duration_sec` |
| `pos_match_delta_sec` (δ) | Margem `[t_start−δ, t_end+δ]` na busca POS | **SQLite** → `stores.pos_match_delta_sec` |

## Pré-requisitos upstream

- Zonas `checkout_lane_*` desenhadas na cam2
- FSM de checkout com histerese (~3 s) — evita flicker na borda do polígono
- `run_pos_match.py` executado (senão `run_alerts.py` aborta)

## Exemplo narrativo

> Maria entra na loja (cam1), vai ao caixa 1 (cam2). Permanece na zona `checkout_lane_1` por **85 segundos**. O POS não registra nenhuma transação com `lane_id=1` entre `t_start−60s` e `t_end+60s`.  
> **Resultado:** alerta R1 — *"Permaneceu no caixa 1 por 85s sem venda registrada"*.

## Cenários de falha / limitações

| Cenário | O que acontece |
|---------|----------------|
| POS fora da janela δ | Venda real não aparece em `pos_matches` → **falso positivo R1** |
| Venda em `lane_id` errado | Mesmo caixa físico, lane errada no cadastro → falso positivo |
| Permanência < limiar | 55 s com limiar 60 s → **não dispara** (by design) |
| Sessão ainda aberta (`t_end` null) | Ignorada |
| `pos_matches` ausente | Sessão ignorada (pipeline incompleto) |
| Duas pessoas no caixa, POS de outro | POS pode associar venda à sessão errada se timing coincidir |
| Sessão curta com intenção de pagar | Não gera R1 (duração insuficiente) — pode ser comportamento normal |

---

# R1b — Supressão “voltou e pagou”

## Objetivo

**Não é um alerta.** É uma regra de **supressão** do R1: se a pessoa teve sessão suspeita no caixa mas **voltou em seguida e pagou**, o R1 da primeira sessão é descartado.

## Tipo

- **`rule_id`:** não gera alerta próprio
- **Função:** `is_r1_suppressed_by_r1b()` em `rules.py`

## Condições para suprimir R1

Para a sessão candidata a R1, existe **outra sessão posterior** na **mesma `lane_id`** tal que:

1. `other.t_start > session.t_end`
2. `(other.t_start - session.t_end) ≤ t_return_sec`
3. `other.pos_matches` contém pelo menos uma transação com status `paid` ou `completed`

## Variáveis

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `t_return_sec` | Janela máxima entre sair e voltar | **CLI** `--t-return-sec` (default **1800 s = 30 min**) |
| `lane_id` | Deve ser o mesmo caixa | derivado da sessão |

## Exemplo narrativo

> João fica 2 min no caixa 1 sem POS (R1 candidato). Sai, pega um produto esquecido, **volta em 5 minutos** ao mesmo caixa e paga.  
> **Resultado:** R1 da primeira sessão **suprimido** por R1b.

## Cenários de falha

| Cenário | O que acontece |
|---------|----------------|
| Pagou em **outro caixa** (`lane_id` diferente) | R1b **não suprime** — alerta R1 permanece |
| Voltou após `t_return_sec` | R1b não aplica — R1 dispara |
| Segunda sessão sem POS pago | Supressão não ocorre |
| Pagamento `pending` / outro status | Ignorado — precisa `paid` ou `completed` |
| POS com delay > δ na segunda sessão | Pode não ver pagamento → R1 não suprimido |

---

# Consolidação R1 + R2

Quando a **mesma visita** gera R1 e R2 no mesmo ciclo, o motor **fundé** em um único alerta:

- **`rule_id`:** `"R1+R2"`
- **`rule_ids`:** `["R1", "R2"]`
- **Score:** `max(score_R1, score_R2)`
- **Summary:** texto combinado

> **Importante:** R2 exige `checkout_sessions == []` (nunca passou no caixa). Na prática, **R1 e R2 são mutuamente exclusivos** na lógica atual — a consolidação só ocorreria em cenários de teste ou dados inconsistentes. O código mantém a consolidação por desenho histórico.

---

# R2 — Skip checkout (entrou, não pagou, saiu carregando)

## Objetivo

Detectar pessoa que **entrou na loja**, **nunca passou pelo caixa**, **não tem pagamento POS** e **saiu com mais carga do que na entrada** (delta líquido visual).

## Tipo de alerta

- **Escopo:** por `PersonVisit` (cam1 + merge)
- **`rule_id`:** `"R2"`
- **Função:** `evaluate_r2()` em `rules.py`

## Condições (todas obrigatórias)

1. `has_entered_store == true`
2. `ready_for_visit_rules` — com default, exige evento `left` na timeline cam1
3. `checkout_sessions` **vazio** (nunca detectado na zona de caixa cam2)
4. `paid_qty_total() == 0`
5. `carry_profile` presente
6. `carry_profile.has_net_carry_theft()` → `carry_delta.positive == true` **e** `confidence ≥ 0.55`

## Variáveis

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `require_left_store` | Exige `left` antes de R2 | **Código** / **CLI** `--no-require-left` |
| `carry_confidence_threshold` | Confiança mínima visual | **Código** (0.55) |
| `net_carry_score_threshold` | Delta mínimo de `carry_score` | **Código** (0.15) |
| `vision_signals` / `carry_profile` | Perfil de carga entrada/saída | `run_vision.py` ou cálculo bbox |
| `checkout_sessions` | Sessões cam2 | **Derivado** (`run_events.py` cam2) |

## Exemplo narrativo

> Ana entra pela porta (cam1), circula na loja, **nunca aparece** na zona de checkout (cam2). Na saída, YOLO detecta uma `bottle` que não existia na entrada. Nenhuma transação POS no dia.  
> **Resultado:** R2 — *"Entrou na loja sem passar no caixa, não pagou e saiu carregando mais do que na entrada"*.

## Cenários de falha

| Cenário | O que acontece |
|---------|----------------|
| Passou no caixa brevemente (< histerese) | Pode não gerar sessão → R2 dispara indevidamente |
| Passou no caixa (sessão cam2) | R2 **bloqueado** — mesmo sem pagar (vai para R1) |
| Bbox alarga na saída sem objeto real | Com YOLO: **suprimido** se YOLO=0 nos dois instantes |
| YOLO não instalado / `--skip-yolo` | Só bbox — mais falsos positivos por postura |
| Sem `left` (ainda dentro) | R2 não dispara (`require_left_store=true`) |
| Entrou com sacola própria | Baseline na entrada — delta líquido pode ser 0 → sem R2 |
| Objeto pequeno fora das classes COCO | YOLO não vê → pode **falso negativo** |
| `confidence < 0.55` | Não dispara mesmo com delta positivo |
| Merge errado (pessoa trocada) | R2 atribuído à pessoa errada |

---

# R3 — POS paga menos que estimativa visual

## Objetivo

Detectar **discrepância** entre quantidade paga no POS e estimativa visual de itens carregados na visita.

## Tipo de alerta

- **Escopo:** por `checkout_session` com POS pago
- **`rule_id`:** `"R3"`
- **Função:** `evaluate_r3_session()` em `rules.py`

## Condições (todas obrigatórias)

1. Sessão tem `pos_matches` com status `paid` ou `completed`
2. `carry_profile` presente
3. `carry_profile.confidence ≥ 0.55`
4. `pos_items < visual_estimate - r3_visual_margin`

Onde:

- `pos_items` = soma de `qty_total` dos matches pagos **da sessão**
- `visual_estimate` = máximo entre objetos/bolsas entrada, saída e delta (ver `CarryProfile.visual_estimate`)

## Variáveis

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `r3_visual_margin` | Tolerância em itens | **Código** (default **2**) |
| `carry_confidence_threshold` | Confiança mínima | **Código** (0.55) |
| `visual_estimate` | Itens estimados visualmente | **Derivado** (`carry.py`) |
| `qty_total` | Itens no POS | **Derivado** (transação POS) |

## Exemplo narrativo

> Carlos passa no caixa e paga **1 item**. A estimativa visual na saída (`visual_estimate = 4`) indica ~4 objetos/sacola. Margem = 2 → limiar = 4−2 = 2. POS (1) < 2.  
> **Resultado:** R3 — *"POS registrou 1 item(ns), estimativa visual ~4"*.

## Cenários de falha

| Cenário | O que acontece |
|---------|----------------|
| Estimativa visual imprecisa | **Falso positivo** — proxy bbox/YOLO ≠ itens reais |
| Pagou itens agrupados (qty correto no ticket) | Se visual superestima → falso positivo |
| `confidence < 0.55` | R3 ignorado |
| Sacola grande vazia na saída | `visual_estimate` inflado → falso positivo |
| POS com qty errada | Falso positivo ou negativo conforme erro POS |
| Só itens pequenos não detectados | **Falso negativo** |

---

# R4 — Compra rápida com muitos itens

## Objetivo

Detectar sessão de caixa **curta** com **muitos itens** pagos — padrão de passagem rápida suspeita (ex.: não passou todos os produtos).

## Tipo de alerta

- **Escopo:** por `checkout_session` com POS pago
- **`rule_id`:** `"R4"`
- **Função:** `evaluate_r4_session()` em `rules.py`

## Condições (todas obrigatórias)

1. `enable_r4 == true`
2. Sessão tem matches `paid` / `completed`
3. `pos_items ≥ r4_min_items`
4. `duration_sec < r4_fast_duration_sec`

## Variáveis

| Variável | Descrição | Origem |
|----------|-----------|--------|
| `r4_min_items` | Mínimo de itens no POS | **Código** (default **5**) |
| `r4_fast_duration_sec` | Tempo máximo “rápido” | **Código** (default **90 s**) |
| `enable_r4` | Liga/desliga regra | **Código** (default `true`) |
| `duration_sec` | Tempo na zona caixa | **Derivado** (FSM cam2) |
| `confidence` no alerta | Fixa 0.85 | **Código** |

## Exemplo narrativo

> Funcionário ou cliente passa **8 itens** no POS em **45 segundos** no caixa 1.  
> **Resultado:** R4 — *"Permaneceu 45s no caixa 1 com 8 itens no POS (tempo curto)"*.

## Cenários de falha

| Cenário | O que acontece |
|---------|----------------|
| Compra legítima rápida (self-checkout ágil) | **Falso positivo** |
| POS agrupa qty (1 linha, qty=8) vs 8 scans | Depende de como `qty_total` vem do POS |
| Permanência ≥ 90 s | Não dispara — considerado tempo normal |
| Menos de 5 itens | Não dispara |
| `enable_r4 = false` | Regra desligada globalmente |
| Duração FSM imprecisa (bordas zona) | Pode subestimar/overestimar tempo |

---

# R5 — Transação cancelada + saída com carga

## Objetivo

Detectar visita em que houve **transação POS cancelada** no intervalo da visita **e** a pessoa **saiu com indício de carga** (mesmo critério visual de delta positivo usado em R2).

## Tipo de alerta

- **Escopo:** por `PersonVisit`
- **`rule_id`:** `"R5"`
- **Função:** `evaluate_r5()` em `rules.py`

## Condições (todas obrigatórias)

1. Existe ≥1 transação POS com status `cancelled` no intervalo `[visit_start−60s, visit_end+60s]`
2. `ready_for_visit_rules` (exige `left` por default)
3. `carry_profile.has_carry_increase()` → delega para `has_net_carry_theft()` (mesma lógica delta líquido de R2)
4. `confidence ≥ 0.55`

## Variáveis

| Variável | Descrição | Origem |
|----------|-----------|--------|
| Janela canceladas | ±60 s em torno da visita | **Código** fixo em `_cancelled_transactions_for_visit()` |
| Status POS | `"cancelled"` | arquivo/API POS |
| Demais variáveis visuais | Igual R2 | ver seção visão |

## Exemplo narrativo

> Pedro inicia pagamento, operador **cancela** a venda no POS. Pedro sai pela porta com objeto detectado na saída que não tinha na entrada.  
> **Resultado:** R5 — *"Transação cancelada no intervalo da visita e saída com indício de carga"*.

## Cenários de falha

| Cenário | O que acontece |
|---------|----------------|
| Cancelamento fora da janela ±60 s | **Não associa** — falso negativo |
| Cancelamento de outro cliente (timing) | **Falso positivo** se visita coincidente |
| Cancelou e devolveu produto | YOLO 0/0 → delta negativo — **sem R5** (correto) |
| POS não exporta cancelamentos | R5 nunca dispara |
| Mesmas limitações visuais de R2 | bbox/YOLO, confidence, etc. |

---

## Pré-requisitos comuns (FSM e zonas)

Estes parâmetros **não são das regras R1–R5 diretamente**, mas afetam a qualidade dos inputs:

| Parâmetro | Valor | Origem | Efeito |
|-----------|-------|--------|--------|
| `hysteresis_sec` | 3.0 s | **Código** (`events/fsm.py`, `ZonesConfig`) | Tempo mínimo na borda antes de confirmar enter/exit ou sessão caixa |
| Zonas `portal`, `checkout_lane_*` | polígonos | **SQLite** (`camera_zones`) | Define onde eventos e sessões nascem |
| `entry_vector` (portal) | [dx, dy] opcional | **SQLite** | Classifica entered vs left na porta única |
| `entrance_camera` | default `cam1` | **Derivado** (`persons_ref` no merge) | Qual câmera alimenta timeline da loja |

---

## Saída do alerta (`alerts/index.json`)

Cada alerta contém, entre outros:

```json
{
  "alert_id": "AL-20260522-0001",
  "rule_id": "R1",
  "rule_ids": ["R1", "R2"],
  "severity": "high",
  "suspicion_score": 40.0,
  "global_person_id": "P-0003",
  "store_timeline": [ ... ],
  "vision_signals": { ... },
  "checkout_session": { ... },
  "pos_matches": [ ... ]
}
```

O bloco `rule_config` no índice espelha parâmetros usados na execução (para auditoria):

```json
"rule_config": {
  "t_return_sec": 1800.0,
  "carry_confidence_threshold": 0.55,
  "r3_visual_margin": 2,
  "r4_min_items": 5,
  "r4_fast_duration_sec": 90.0,
  "require_left_store": true
}
```

---

## Referência rápida: qual regra usar quando?

| Situação observada | Regra |
|--------------------|-------|
| Ficou no caixa, POS silencioso | **R1** |
| Voltou e pagou logo depois | **R1b** suprime R1 |
| Entrou e saiu sem passar no caixa, com carga | **R2** |
| Pagou menos itens que o visual sugere | **R3** |
| Pagou muitos itens muito rápido | **R4** |
| POS cancelou e saiu carregando | **R5** |

---

## Comandos úteis

```powershell
# Pipeline completo de alertas (após events + pos_match + vision)
python jobs/run_vision.py --date 2026-05-22 --store-id LOJA-01 --group-code default
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default

# Ajustar janela R1b
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default --t-return-sec 3600

# Testes sem exigir evento left
python jobs/run_alerts.py --date 2026-05-22 --store-id LOJA-01 --group-code default --no-require-left

# Visão só bbox (sem YOLO)
python jobs/run_vision.py --date 2026-05-22 --store-id LOJA-01 --group-code default --skip-yolo
```

---

## Evolução futura (não implementado)

Parâmetros hoje fixos em código que poderiam migrar para SQLite / painel:

- `t_return_sec`, `r3_visual_margin`, `r4_min_items`, `r4_fast_duration_sec`
- limiares visuais (`carry_confidence_threshold`, `net_carry_score_threshold`)
- pesos de scoring por regra
- janela ±60 s de cancelamentos (R5)
- `hysteresis_sec` por loja
