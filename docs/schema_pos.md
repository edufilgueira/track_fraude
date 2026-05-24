# Schema POS — `data/pos/{date}/transactions.json`

## Campos raiz

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `store_id` | string | Identificador da loja |
| `date` | string | Data no formato `YYYY-MM-DD` |
| `timezone` | string | Fuso IANA (ex.: `America/Sao_Paulo`) |
| `transactions` | array | Lista de transações do dia |

## Transação

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `transaction_id` | string | ID único |
| `t_sale` | string ISO | Data/hora da venda |
| `lane_id` | int | Número do self-checkout |
| `status` | string | `paid`, `completed`, `cancelled` |
| `items` | array | Itens escaneados |
| `qty_total` | int | Quantidade total paga |
| `total_value` | float | Valor total |

## Item

| Campo | Tipo |
|-------|------|
| `sku` | string |
| `name` | string |
| `qty` | int |
| `unit_price` | float |

## Consulta padrão (FilePosClient)

Por default, `get_transactions_between` retorna apenas `paid` e `completed`.
Transações `cancelled` são ignoradas salvo se `statuses` for informado.

## Exemplo

Ver `data/pos/2026-05-22/transactions.json`.
