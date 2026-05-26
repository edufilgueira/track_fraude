# Servidor web (painel)

Interface para **cadastro e configuração** — roda separado da máquina de processamento de vídeo.

## Responsabilidades

- Login de usuários
- CRUD de lojas
- Configuração de câmeras e OCR ROI
- (Futuro) revisão de alertas, usuários, etc.

## Não faz

- YOLO / tracking / batch de vídeo → use `jobs/` na máquina de processamento
- OpenCV / Tesseract → só no worker

## Dependências

Este pacote é **independente**: FastAPI, Jinja2, Uvicorn + `track-fraude-core` (SQLite).  
O editor de ROI usa o seletor de arquivo do navegador; se o codec não for reproduzível no browser (ex.: `mp4v`), o frame é extraído no servidor via OpenCV headless.

## Configuração

Edite `config/settings.yaml`:

| Chave | Descrição |
|-------|-----------|
| `database.path` | SQLite compartilhado com o worker (local, absoluto ou rede) |
| `auth.admin_*` | Usuário inicial (criado no primeiro start se DB vazio) |
| `app.secret_key` | Troque em produção |
| `app.host` / `app.port` | Bind do Uvicorn |

Para rodar o painel em **outro servidor** com o mesmo banco, copie a pasta `server/` + `core/`, ajuste `database.path` para o SQLite acessível na rede e execute normalmente.

## Executar

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_db.py
python main.py
```

Acesse: http://127.0.0.1:8080/login

## Testes (a partir da raiz do repo)

```powershell
pip install -e ./core
pip install -e ./server
pip install -e ".[dev]"
pytest tests/test_zone_editor.py tests/test_db_migration.py
```

## Arquitetura

```text
server/          ← esta máquina (UI + config)
  config/        ← settings.yaml
  routes/        ← rotas FastAPI
  templates/     ← páginas HTML
  static/        ← CSS

core/            ← pacote compartilhado (schema + repositório)
jobs/ + src/     ← máquina de processamento (batch noturno)
data/            ← SQLite + vídeos + POS (compartilhado ou sincronizado)
```
