# track-fraude-core

Pacote compartilhado entre **servidor web** (`server/`) e **worker** (`src/` + `jobs/`).

- Schema SQLite (`stores`, `cameras`, `users`)
- `StoreRepository` — CRUD de lojas e câmeras (OCR ROI)
- `load_store_config()` — lê config da loja **somente do SQLite**

Cadastro de lojas: painel web em `server/`, não arquivos YAML.

## Instalação

```powershell
pip install -e ./core
```

## Uso no worker

```python
from track_fraude_core.store_config import load_store_config

config = load_store_config(store_id="LOJA-01", db_path="data/track_fraude.db")
```
