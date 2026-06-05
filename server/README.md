# Servidor web (painel)

Interface para **cadastro e configuração** — roda separado da máquina de processamento de vídeo.

## Responsabilidades

- Login de usuários
- CRUD de lojas
- Configuração de câmeras e OCR ROI
- **Revisão de alertas** (Fase 8): fila, clips cam1/cam2, confirmar/falso positivo
- Indicador de **pipeline em execução** nas listagens de grupo/loja
- **Console ao vivo** abaixo da loja durante o processamento (espelho do log do pipeline). O log é truncado (~120k caracteres) e o polling desacelera com a aba em segundo plano, para evitar travar a interface do browser.

## Não faz

- YOLO / tracking / batch de vídeo → use `jobs/` na máquina de processamento
- OpenCV / Tesseract → só no worker

## Dependências

Este pacote é **independente**: FastAPI, Jinja2, Uvicorn + `track-fraude-core` (SQLite).  
O editor de ROI/zona salva o **frame capturado no servidor** em `server/upload/editor_frames/{loja}/{camera_db_id}/frame.jpg` (ex.: `1/1/frame.jpg`), acessível de qualquer dispositivo. Toda a pasta `server/upload/` pode ser copiada junto com o painel para outro servidor. Frames antigos em `data/editor_frames/` (legado) são migrados automaticamente para `server/upload/` na subida do app. O MP4 em `data/raw/{group}/{store}/{date}/` **não é removido** — continua disponível para o pipeline de processamento.

## Configuração

Edite `config/settings.yaml`:

| Chave | Descrição |
|-------|-----------|
| `database.path` | SQLite compartilhado com o worker (local, absoluto ou rede) |
| `auth.admin_*` | Usuário inicial (criado no primeiro start se DB vazio) |
| `app.secret_key` | Troque em produção |
| `app.host` / `app.port` | Bind do Uvicorn (`0.0.0.0` = aceita conexões da rede; `127.0.0.1` = só nesta máquina) |

Para rodar o painel em **outro servidor** com o mesmo banco, copie a pasta `server/` (incluindo `server/upload/editor_frames/`) + `core/`, ajuste `database.path` para o SQLite acessível na rede e execute normalmente.

## Executar Windows

```powershell
# 1) Worker (raiz do repo) — pipeline de vídeo
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[track]"

# 2) Painel web
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_db.py
python main.py
```


## Executar Linux

```bash
# 1) Worker (raiz do repo) — pipeline de vídeo
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[track]"

# 2) Painel web
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
python main.py
```

O botão **Play** na listagem de lojas usa o Python do worker (`.venv` na raiz ou `pipeline.python` em `config/settings.yaml`), não o venv mínimo do painel.

Acesse na própria máquina: http://127.0.0.1:8080/login  
Acesse de outro PC na rede: http://192.168.0.192:8080/login (troque pelo IP do servidor)

### Acesso na rede local

O `settings.yaml` padrão usa `app.host: 0.0.0.0` para escutar em todas as interfaces.  
Alternativa sem editar o arquivo:

```bash
python main.py --host 0.0.0.0 --port 8080
```

No Ubuntu, libere a porta no firewall se necessário:

```bash
sudo ufw allow 8080/tcp
```

Use só `127.0.0.1` se o painel não precisar ser acessado fora do servidor.

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
