# Passo a passo — subir o track_fraude após `git clone`

Guia para **Ubuntu/Linux** (servidor). No Windows troque `source .venv/bin/activate` por `.venv\Scripts\activate`.

---

## Visão geral

São **dois ambientes Python separados**:

| Ambiente | Pasta | Pacotes | Função |
|----------|-------|---------|--------|
| **Worker** | `.venv` na **raiz** | `track-fraude-core`, `track-fraude` + `[track]` (pyarrow, opencv, ultralytics…) | Pipeline de vídeo (botão Play) |
| **Painel** | `server/.venv` | `track-fraude-core`, FastAPI, Uvicorn, opencv-headless | Site web (login, lojas, config) |

O botão **Play** no painel **não** usa o `server/.venv`. Ele chama o Python do worker (`.venv` na raiz ou `pipeline.python` em `settings.yaml`).

---

## 1. Pré-requisitos no servidor

### Pacotes do sistema

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip \
  tesseract-ocr ffmpeg libgl1 libglib2.0-0
```

| Pacote | Para quê |
|--------|----------|
| `python3-venv` | Ambientes virtuais |
| `tesseract-ocr` | OCR no sync (timestamp no vídeo) |
| `ffmpeg` | Clips de evidência |
| `libgl1` | OpenCV no servidor |

### Python do worker

Use o `python3` disponível no servidor:

```bash
python3 --version
```

O guia abaixo cria os ambientes com `python3 -m venv`. Se alguma dependência do worker (`pyarrow`, `opencv`, `ultralytics`, `torch`) falhar no `pip install`, instale Python 3.12 ou 3.11 e recrie o `.venv` com essa versão. Isso só é necessário em servidores cuja versão padrão do Python ainda não tenha wheels compatíveis para essas bibliotecas.

Exemplo de fallback com Python 3.12:

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version
```

---

## 2. Clonar o projeto

```bash
cd ~
git clone https://github.com/edufilgueira/track_fraude.git
cd track_fraude
```

---

## 3. Remover `.venv` antigos (reinstalação ou correção)

Se já tentou instalar antes, **apague os dois ambientes** antes de recriar:

```bash
cd ~/track_fraude

# Sair de qualquer venv ativo
deactivate 2>/dev/null || true

# Remover worker e painel
rm -rf .venv
rm -rf server/.venv
```

Confirme que sumiram:

```bash
ls -la .venv server/.venv 2>&1
# deve retornar "No such file or directory"
```

---

## 4. Worker (raiz) — obrigatório para o Play

Crie o venv com `python3` e instale o pacote worker com extras `[track]`:

```bash
cd ~/track_fraude

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -e ./core
pip install -e ".[track]"
```

### O que o worker instala (`pyproject.toml` na raiz)

| Pacote | Grupo |
|--------|-------|
| `track-fraude-core` | base |
| `opencv-python`, `numpy`, `pytesseract`, `pyarrow` | base |
| `ultralytics` (YOLO) | extra `[track]` |

### Validar (obrigatório antes de subir o painel)

```bash
cd ~/track_fraude
.venv/bin/python -c "import pyarrow; import track_fraude; print('Worker OK')"
.venv/bin/python --version
# Esperado: versão do Python + "Worker OK"
```

Se falhar em `pyarrow`, `opencv`, `ultralytics` ou `torch`, não prossiga — o Play vai quebrar. Use o fallback do passo 1 para instalar Python 3.12/3.11, remova o `.venv` antigo e recrie o worker com o comando da versão instalada, por exemplo `python3.12 -m venv .venv`.

**Opcional — banco + loja demo:**

```bash
source .venv/bin/activate
python tools/init_db.py
python tools/seed_demo_store.py   # grupo + LOJA-01 de exemplo
deactivate
```

Se não rodar o seed, cadastre grupo/loja pelo painel depois.

---

## 5. Painel web (`server/`)

Pacotes **enxutos** — sem pyarrow, sem ultralytics, sem `track-fraude` worker:

```bash
cd ~/track_fraude/server

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
python scripts/init_db.py
```

### O que o painel instala (`server/requirements.txt`)

| Pacote | Função |
|--------|--------|
| `track-fraude-core` | SQLite, schema, repositórios |
| `fastapi`, `uvicorn`, `jinja2` | Servidor web |
| `opencv-python-headless` | Captura de frame no editor ROI |

O `init_db` cria/atualiza o SQLite em `data/track_fraude.db` (relativo à raiz do repo).

---

## 6. Configuração (`server/config/settings.yaml`)

Edite antes de subir em produção. **Defina o Python do worker com caminho absoluto** — evita o painel usar outro Python sem as dependências:

```yaml
app:
  host: 0.0.0.0      # aceita acesso da rede (192.168.x.x)
  port: 8080
  secret_key: troque-esta-chave-em-producao   # ← mude

auth:
  admin_username: admin
  admin_password: admin123   # ← mude

database:
  path: data/track_fraude.db   # relativo à raiz track_fraude/

pipeline:
  python: /home/eduardo/track_fraude/.venv/bin/python   # ← ajuste o usuário/caminho
```

Troque `/home/eduardo` pelo seu usuário real (`echo $HOME`).

---

## 7. Pastas de dados

O git traz `.gitkeep`; na primeira execução o app cria o que faltar:

```text
track_fraude/
  data/
    track_fraude.db          ← banco (criado no init_db)
    raw/{group}/{store}/{date}/   ← vídeos MP4 (cam1.mp4, cam2.mp4)
    processed/               ← saídas do pipeline
    logs/                    ← logs do Play
```

**Vídeos para processar** — exemplo:

```text
data/raw/default/LOJA-01/2026-05-22/cam1.mp4
data/raw/default/LOJA-01/2026-05-22/cam2.mp4
```

(`default` = `group_code` no banco; `LOJA-01` = código da loja.)

---

## 8. Firewall (segurança e acesso pela rede)

> **Importante:** Se você estiver conectado ao servidor via SSH, **não utilize `ufw reset`**. Remover todas as regras pode causar perda de acesso remoto caso a porta SSH não seja liberada novamente antes de ativar o firewall.

### Verificar o status atual do firewall

```bash
sudo ufw status verbose
```

### Definir política padrão

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

### Liberar SSH (obrigatório)

```bash
sudo ufw allow 22/tcp
```

### Ativar o firewall

```bash
sudo ufw enable
```

### Liberar porta do painel

```bash
sudo ufw allow 8080/tcp
```

### Descobrir o IP do servidor

```bash
hostname -I
```

Exemplo: `192.168.0.192`

### Testar acesso de outro computador

```text
http://192.168.0.192:8080/login
```

### Diagnóstico rápido

```bash
sudo ss -tulpn | grep 8080
sudo ufw status verbose
```

Se o acesso não funcionar:

1. Verifique se a aplicação está em execução.
2. Verifique se a porta foi liberada no UFW.
3. Verifique se `app.host` é `0.0.0.0` em `settings.yaml`.
4. Verifique se não existe outro firewall bloqueando o tráfego.

---

## 9. Subir o painel

```bash
cd ~/track_fraude/server
source .venv/bin/activate
python main.py
```

**Não** use `python server/main.py` dentro de `server/` — o caminho correto é `python main.py`.

Saída esperada:

```text
Painel web (local): http://127.0.0.1:8080/login
Painel web (rede):  http://<IP-do-servidor>:8080/login
Uvicorn running on http://0.0.0.0:8080
```

**Acesso:**

- No servidor: http://127.0.0.1:8080/login
- Na rede: http://192.168.0.192:8080/login (troque pelo IP)

Login padrão: `admin` / `admin123` (até você alterar no YAML).

---

## 10. Primeiro uso no painel

1. **Login**
2. **Novo grupo** (ex.: código `default`, nome qualquer)
3. **Nova loja** no grupo (ex.: `LOJA-01`)
4. **Configurar** → cadastrar câmeras `cam1`, `cam2`
5. **Regras** → ajustar parâmetros (vid_stride, etc.)
6. Colocar vídeos em `data/raw/{group_code}/{store_id}/{date}/`
7. Na listagem de lojas → botão **Play** → escolher data → pipeline roda

No log do console, confira:

```text
python: /home/eduardo/track_fraude/.venv/bin/python
```

Se aparecer `/usr/bin/python3` ou outro Python do sistema em vez do `.venv` da raiz, o `pipeline.python` em `settings.yaml` está errado ou o worker não foi instalado.

---

## 11. Rodar pipeline manualmente (terminal)

```bash
cd ~/track_fraude
source .venv/bin/activate

python jobs/run_daily_pipeline.py \
  --date 2026-05-22 \
  --store-id LOJA-01 \
  --group-code default
```

---

## 12. Checklist rápido de problemas

| Problema | Causa provável | Solução |
|----------|----------------|---------|
| Site não abre na rede | `host: 127.0.0.1` ou firewall | `host: 0.0.0.0` + `ufw allow 8080` |
| Play: "Python do worker não encontrado" | Falta `.venv` na raiz ou sem pyarrow | Passos 3 e 4 |
| Log do Play: `python: /usr/bin/python3` | `pipeline.python` vazio, worker ausente, ou bug antigo que resolvia symlink do venv | Passo 6 — caminho absoluto do `.venv`; atualize o código e reinicie o painel |
| `ModuleNotFoundError: pyarrow` | Worker não instalado no Python certo | Passos 3–4; se o `pip install` falhar, use Python 3.12/3.11 |
| Console trava / `unable to open database file` durante Play | Concorrência SQLite entre painel e pipeline | Atualize o código; reinicie o painel; confira `ls -la data/track_fraude.db*` e `df -h .` |
| Play: "Nenhuma data importada" | Sem vídeos em `data/raw/...` | Copiar MP4s |
| Sync falha | Tesseract ausente | `sudo apt install tesseract-ocr` |
| Evidence falha | FFmpeg ausente | `sudo apt install ffmpeg` |
| `python server/main.py` dá erro | Comando errado dentro de `server/` | Use `python main.py` |

---

## 13. Manter rodando (opcional, produção)

```bash
screen -S track_fraude
cd ~/track_fraude/server && source .venv/bin/activate && python main.py
# Ctrl+A, D para desanexar
```

---

## Ordem resumida (copiar e colar)

Substitua `eduardo` pelo seu usuário (`whoami`).

```bash
# 1) Sistema + Python disponível no servidor
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip tesseract-ocr ffmpeg libgl1 libglib2.0-0
python3 --version

# 2) Clone
cd ~
git clone https://github.com/edufilgueira/track_fraude.git
cd track_fraude

# 3) Limpar venvs antigos
deactivate 2>/dev/null || true
rm -rf .venv server/.venv

# 4) Worker (raiz) — track-fraude[track]
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ./core
pip install -e ".[track]"
.venv/bin/python -c "import pyarrow; import track_fraude; print('Worker OK')"
deactivate

# 5) Painel (server/) — deps enxutas
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python scripts/init_db.py

# 6) Editar server/config/settings.yaml:
#    - trocar senha/secret_key
#    - pipeline.python: /home/eduardo/track_fraude/.venv/bin/python

# 7) Subir
sudo ufw allow 8080/tcp
python main.py
```
