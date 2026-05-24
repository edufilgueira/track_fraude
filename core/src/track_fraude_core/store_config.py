from __future__ import annotations

from pathlib import Path
from typing import Any

from track_fraude_core.db.store_repository import StoreRepository


def load_store_config(
    *,
    store_id: str | None = None,
    group_code: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Carrega configuração da loja a partir do SQLite.

    Cadastro feito pelo painel web (server/).
    """
    repo = StoreRepository(db_path)

    if store_id:
        if group_code:
            store = repo.get_store_by_code(store_id, group_code=group_code)
            if store is None:
                raise ValueError(
                    f"Loja não encontrada no banco: {store_id!r} (grupo {group_code})"
                )
            return repo.to_config_dict(store)

        matches = repo.list_stores_by_code(store_id)
        if not matches:
            raise ValueError(f"Loja não encontrada no banco: {store_id!r}")
        if len(matches) > 1:
            raise ValueError(
                f"Múltiplas lojas com store_id {store_id!r}. Informe --group-code."
            )
        return repo.to_config_dict(matches[0])

    active = repo.list_stores(active_only=True)
    if len(active) == 1:
        return repo.to_config_dict(active[0])
    if not active:
        raise ValueError(
            "Nenhuma loja cadastrada. Use o painel web (server/) para cadastrar."
        )
    raise ValueError(
        "Múltiplas lojas ativas. Informe --store-id (ex: LOJA-01)."
    )
