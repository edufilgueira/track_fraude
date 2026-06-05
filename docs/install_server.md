# Passo a passo — subir o track_fraude após `git clone`

Guia para **Ubuntu/Linux** (servidor). No Windows troque `source .venv/bin/activate` por `.venv\Scripts\activate`.

---

## Visão geral

São **dois ambientes Python separados**:

| Ambiente | Pasta | Pacotes | Função |
|----------|-------|---------|--------|
| **Worker** | `.venv` na **raiz** | `track-fraude-core`, `track-fraude` + `[track]` (pyarrow, opencv, ultralytics…) | Pipeline de vídeo (botão Play) |
| **Painel** | `server/.venv` | `track-fraude-core`, FastAPI, Uvicorn, opencv-headless | Site web (login, lojas, config) |

O botão **Play** no painel **não** usa o `server/.venv`. Ele chama o Python do worker: auto-detect do `.venv` na raiz (padrão) ou o caminho em `pipeline.python` em `settings.yaml`.

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

Use o `python3` **já instalado no servidor** — não é necessário instalar outra versão antes de começar:

```bash
python3 --version
# Ex.: Python 3.14.x — funciona se o passo 4 (`Worker OK`) passar
```

O guia cria os dois venvs com `python3 -m venv`. Em servidores recentes (incluindo **Python 3.14**), `pyarrow`, `opencv` e `ultralytics` instalam via `pip` sem instalar outra versão de Python.

> **Você não precisa** do PPA deadsnakes nem de Python 3.12 se o passo 4 terminar com `Worker OK` — como no seu servidor.

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

Se falhar em `pyarrow`, `opencv`, `ultralytics` ou `torch`, não prossiga — o Play vai quebrar. Primeiro tente `pip install --upgrade pip` e repetir o install. Só em máquinas onde isso não resolver, veja o apêndice [Python 3.12 (só se pip falhar)](#apêndice-python-312-só-se-pip-falhar).

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

Edite antes de subir em produção (troque `secret_key` e senha do admin):

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

# Python do worker. Deixe vazio para auto-detect (.venv na raiz).
pipeline:
  python:
```

### `pipeline.python`

| Opção | Quando usar |
|-------|-------------|
| **Vazio** (padrão do repo) | Worker instalado e validado no passo 4 (`Worker OK`) |
| **Caminho absoluto** | Produção ou servidor com vários Pythons — mais previsível |

Exemplo com caminho explícito (troque `eduardo` por `whoami` ou `echo $HOME`):

```yaml
pipeline:
  python: /home/eduardo/track_fraude/.venv/bin/python
```

O auto-detect procura, nesta ordem: valor em `pipeline.python` → `.venv/bin/python` na raiz → valida com `import pyarrow; import track_fraude`.

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

### Parar instância anterior (se precisar)

```bash
pkill -f "server/main.py"
# ou
sudo lsof -i :8080
kill -9 PID
```

### Opção A — dentro de `server/` (recomendado)

```bash
cd ~/track_fraude/server
source .venv/bin/activate
python main.py
```

### Opção B — a partir da raiz do repo

```bash
cd ~/track_fraude
source server/.venv/bin/activate
python server/main.py
```

Ambas funcionam: o `main.py` resolve caminhos pelo próprio arquivo. **Não** rode `python server/main.py` quando o diretório atual já for `server/` — nesse caso use `python main.py`.

### Limite de arquivos abertos (recomendado em produção)

Se o servidor roda pipelines longas, aumente o limite antes de subir o painel:

```bash
ulimit -n 4096
ulimit -n   # confirme (ideal ≥ 4096)
```

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

No log do console, confira que o caminho aponta para o **venv da raiz**:

```text
python: /home/eduardo/track_fraude/.venv/bin/python
```

O interpretador por baixo pode ser Python 3.14 — isso é normal no Linux.

Se aparecer **`/usr/bin/python3`** ou **`/usr/bin/python3.14`** direto (sem passar pelo `.venv`), o painel não está usando o worker — refaça o passo 4, rode `git pull` e reinicie o painel. Em último caso, defina `pipeline.python` com caminho absoluto (passo 6).

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

## Atualizar instalação existente

Se o servidor **já foi instalado** e você só precisa do código mais recente (correções do Play, SQLite, cancelamento, etc.):

```bash
cd ~/track_fraude
git pull

# Confirme que o worker ainda está OK
.venv/bin/python -c "import pyarrow; import track_fraude; print('Worker OK')"

# Reinicie o painel
pkill -f "server/main.py" 2>/dev/null || true
cd server && source .venv/bin/activate && python main.py
```

Não é necessário recriar os venvs se o teste `Worker OK` passar. Recrie apenas se mudou a versão do Python ou se `pip install` falhou (passos 3–5).

Se o `git pull` alterou dependências, reinstale no ambiente afetado:

```bash
# Worker (se mudou pyproject.toml na raiz ou em core/)
cd ~/track_fraude && source .venv/bin/activate
pip install -e ./core && pip install -e ".[track]"

# Painel (se mudou server/requirements.txt)
cd ~/track_fraude/server && source .venv/bin/activate
pip install -r requirements.txt
```

---

## 12. Checklist rápido de problemas

| Problema | Causa provável | Solução |
|----------|----------------|---------|
| Site não abre na rede | `host: 127.0.0.1` ou firewall | `host: 0.0.0.0` + `ufw allow 8080` |
| Play: "Python do worker não encontrado" | Falta `.venv` na raiz ou sem pyarrow | Passos 3 e 4 |
| Log do Play: `python: /usr/bin/python3.14` | Worker ausente ou código antigo (symlink do venv resolvido incorretamente) | Passos 3–4; `git pull`; reinicie o painel; ou passo 6 com caminho absoluto |
| `ModuleNotFoundError: pyarrow` | Worker não instalado no venv da raiz | Passos 3–4; apêndice Python 3.12 só se `pip install` falhar na versão padrão |
| `/api/pipeline/status` 500 / `unable to open database file` | Concorrência SQLite entre painel e pipeline | `git pull`; reinicie o painel; confira `ls -la data/track_fraude.db*` e `df -h .` |
| Console trava durante Play | Mesmo que acima ou polling sem fallback | Atualize o código (status degradado usa estado local do subprocesso) |
| `Too many open files` / falha ao cancelar | Muitos FDs abertos durante pipeline longa | `git pull`; reinicie o painel; `ulimit -n 4096` (passo 9) |
| Play: "Nenhuma data importada" | Sem vídeos em `data/raw/...` | Copiar MP4s |
| Sync falha | Tesseract ausente | `sudo apt install tesseract-ocr` |
| Evidence falha | FFmpeg ausente | `sudo apt install ffmpeg` |
| `python server/main.py` dá erro | Comando rodado **dentro** de `server/` | Use `python main.py`; ou rode `python server/main.py` **da raiz** do repo (passo 9) |

---

## 13. Manter rodando (opcional, produção)

```bash
ulimit -n 4096
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
#    - pipeline.python: deixe vazio (auto-detect) ou caminho absoluto do .venv

# 7) Subir (de dentro de server/)
sudo ufw allow 8080/tcp
ulimit -n 4096
python main.py
```

---

## Apêndice: Python 3.12 (só se pip falhar)

**Ignore esta seção** se você já passou no teste `Worker OK` com o `python3` do servidor (ex.: Python 3.14). Ela existe só para máquinas antigas em que `pip install -e ".[track]"` quebra por falta de wheels (`pyarrow`, `torch`, etc.) na versão padrão do Python.

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev

cd ~/track_fraude
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ./core
pip install -e ".[track]"
.venv/bin/python -c "import pyarrow; import track_fraude; print('Worker OK')"
```
