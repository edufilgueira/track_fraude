from __future__ import annotations

CAMERA_ROLE_ENTRANCE = "entrance"
CAMERA_ROLE_CHECKOUT = "checkout"
CAMERA_ROLE_SUPPORT = "support"

CAMERA_ROLES = (
    CAMERA_ROLE_ENTRANCE,
    CAMERA_ROLE_CHECKOUT,
    CAMERA_ROLE_SUPPORT,
)

CAMERA_ROLE_LABELS = {
    CAMERA_ROLE_ENTRANCE: "Entrada",
    CAMERA_ROLE_CHECKOUT: "Caixa (checkout)",
    CAMERA_ROLE_SUPPORT: "Suporte",
}


def normalize_camera_role(value: str | None) -> str:
    role = str(value or CAMERA_ROLE_SUPPORT).strip().lower()
    if role not in CAMERA_ROLES:
        raise ValueError(f"Tipo de câmera inválido: {value!r}")
    return role


def infer_camera_role(*, camera_id: str, description: str) -> str:
    text = f"{camera_id} {description}".lower()
    if "checkout" in text or "caixa" in text or camera_id == "cam2":
        return CAMERA_ROLE_CHECKOUT
    if "entrada" in text or "porta" in text or camera_id == "cam1":
        return CAMERA_ROLE_ENTRANCE
    return CAMERA_ROLE_SUPPORT
