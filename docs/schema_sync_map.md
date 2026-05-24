# Schema sync_map — `data/processed/{group_code}/{store_id}/{date}/{camera_id}/sync_map.json`

## Propósito

Mapeia **frame do vídeo** ↔ **timestamp absoluto** para cruzar eventos visuais com o POS.

## Campos

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `camera_id` | string | Ex.: `cam1`, `cam2` |
| `date` | string | `YYYY-MM-DD` |
| `video_path` | string | Caminho do vídeo fonte |
| `fps` | float | FPS do vídeo |
| `frame_count` | int | Total de frames |
| `timezone` | string | Fuso da loja |
| `build_method` | string | `ocr+interpolation` |
| `anchor` | object | Ancora frame ↔ tempo |
| `samples` | array | Amostras OCR ao longo do vídeo |

## anchor

| Campo | Tipo |
|-------|------|
| `frame_idx` | int |
| `t_abs` | string ISO |
| `source` | string (`ocr`) |

## samples[]

| Campo | Tipo |
|-------|------|
| `frame_idx` | int |
| `t_abs` | string ISO |
| `confidence` | float |
| `raw_text` | string |

## Interpolação

Entre amostras OCR, o tempo é calculado linearmente por FPS:

```
t(frame) = anchor.t_abs + (frame - anchor.frame_idx) / fps
```

## API em código

```python
sync_map.timestamp_at_frame(6550)  # -> datetime
sync_map.frame_at_timestamp(dt)    # -> int
```

## Requisitos

Sync temporal usa **somente OCR (Tesseract)** na ROI cadastrada no painel web.  
Se falhar, instale/configure o Tesseract — não há fallback por arquivo auxiliar.

## Fallbacks

Não há fallback: o job `run_sync` exige Tesseract no PATH e timestamp visível na ROI.
