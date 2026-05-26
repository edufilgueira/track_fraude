# Schema POS — `data/pos/transactions.json` + API provisória

## Arquivo local

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `store_id` | string | Identificador da loja |
| `date` | string | Data `YYYY-MM-DD` |
| `timezone` | string | Fuso IANA |
| `transactions` | array | Vendas do dia |

Para vários dias no mesmo arquivo, use `"exports": [ { store_id, date, transactions }, ... ]`.

## API provisória (Node)

```powershell
node data/pos/server.js
# http://127.0.0.1:3099
```


### Matar o processo na porta 3099

```powershell
netstat -ano | findstr :3099
taskkill /PID <numero_do_pid> /F
```

### Rotas

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Status |
| GET | `/day?store_id=&date=` | Export completo do dia |
| GET | `/transactions?store_id=&date=&t_from=&t_to=&lane_id=` | Filtro por intervalo |
| POST | `/transactions/query` | Mesmo filtro via JSON body |

Parâmetros de tempo: ISO (`2026-05-22T10:01:00`) ou `HH:MM:SS` (usa `date`).

### Worker Python (API)

```powershell
python jobs/run_pos_match.py --date 2026-05-22 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
python jobs/validate_sync_pos.py --date 2026-05-22 --camera cam2 --time 10:01:00 --lane 1 --store-id LOJA-01 --group-code default --pos-api-url http://127.0.0.1:3099
```

Sem `--pos-api-url`, o worker lê `data/pos/transactions.json` diretamente (`FilePosClient`).

## Transação

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `transaction_id` | string | ID único (livre) |
| `t_sale` | string ISO | Data/hora da venda |
| `lane_id` | int | Número do caixa |
| `status` | string | `paid`, `completed`, `cancelled` |
| `items` | array | Itens |
| `qty_total` | int | Quantidade |
| `total_value` | float | Valor total |

## Exemplo

Ver `data/pos/transactions.json`.

```powershell
curl "http://127.0.0.1:3099/transactions?store_id=LOJA-01&date=2026-05-22&t_from=2026-05-22T10:00:00&t_to=2026-05-22T10:02:00&lane_id=1"
```