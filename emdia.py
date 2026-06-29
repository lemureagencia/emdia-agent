"""Cliente das funções RPC do Supabase (EmDia). Usa a service_role key."""
import requests
import config

_BASE = config.SUPABASE_URL.rstrip("/") + "/rest/v1/rpc"
_HEADERS = {
    "apikey": config.SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


def _rpc(fn: str, payload: dict):
    resp = requests.post(f"{_BASE}/{fn}", json=payload, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_summary(phone: str) -> dict:
    return _rpc("get_summary_by_phone", {"p_phone": phone})


def register(phone: str, type_: str, amount: float, description: str,
             category: str | None = None, payment_method: str | None = None,
             status: str = "paid", due_date: str | None = None,
             service_type: str | None = None) -> dict:
    return _rpc("agent_register_by_phone", {
        "p_phone": phone,
        "p_type": type_,
        "p_amount": amount,
        "p_description": description,
        "p_category": category,  # coluna "Nome" (cliente) no app
        "p_payment_method": payment_method,
        "p_status": status,
        "p_due_date": due_date,
        "p_service_type": service_type,
    })


def set_balance(phone: str, balance: float) -> dict:
    return _rpc("agent_set_balance_by_phone", {"p_phone": phone, "p_balance": balance})


def recent_messages(phone: str, limit: int = 8) -> list:
    """Últimas mensagens da conversa (ordem cronológica). Resiliente a falha."""
    try:
        return _rpc("agent_recent_messages", {"p_phone": phone, "p_limit": limit}) or []
    except Exception:  # noqa: BLE001 — memória é opcional, nunca quebra a resposta
        return []


def get_descriptions(phone: str) -> list:
    """Descrições padrão do usuário (por telefone). Resiliente a falha."""
    try:
        result = _rpc("get_descriptions_by_phone", {"p_phone": phone})
        if not result:
            return []
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return [r.get("text", "") for r in result if r.get("text")]
        return [str(r) for r in result if r]
    except Exception:  # noqa: BLE001
        return []


def find_pending(phone: str, search: str) -> list:
    """Busca pendências por nome ou descrição. Retorna lista (máx 5)."""
    try:
        return _rpc("agent_find_pending_by_phone", {"p_phone": phone, "p_search": search}) or []
    except Exception:  # noqa: BLE001
        return []


def edit_pending(phone: str, item_id: str, amount: float | None = None,
                 due_date: str | None = None, description: str | None = None,
                 category: str | None = None, mark_paid: bool = False) -> dict:
    """Edita campos de uma pendência ou a marca como paga."""
    payload: dict = {"p_phone": phone, "p_id": item_id, "p_mark_paid": mark_paid}
    if amount is not None:
        payload["p_amount"] = amount
    if due_date is not None:
        payload["p_due_date"] = due_date
    if description is not None:
        payload["p_description"] = description
    if category is not None:
        payload["p_category"] = category
    return _rpc("agent_edit_pending_by_phone", payload)


def delete_pending(phone: str, item_id: str) -> dict:
    """Exclui uma pendência pelo ID."""
    return _rpc("agent_delete_pending_by_phone", {"p_phone": phone, "p_id": item_id})


def log_message(phone: str, role: str, content: str) -> None:
    """Grava uma mensagem (user/assistant) na memória. Resiliente a falha."""
    try:
        _rpc("agent_log_message", {"p_phone": phone, "p_role": role, "p_content": content})
    except Exception:  # noqa: BLE001
        pass
