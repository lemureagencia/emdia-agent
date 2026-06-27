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
             status: str = "paid", due_date: str | None = None) -> dict:
    return _rpc("agent_register_by_phone", {
        "p_phone": phone,
        "p_type": type_,
        "p_amount": amount,
        "p_description": description,
        "p_category": category,  # coluna "Nome" (cliente) no app
        "p_payment_method": payment_method,
        "p_status": status,
        "p_due_date": due_date,
    })


def set_balance(phone: str, balance: float) -> dict:
    return _rpc("agent_set_balance_by_phone", {"p_phone": phone, "p_balance": balance})


def recent_messages(phone: str, limit: int = 8) -> list:
    """Últimas mensagens da conversa (ordem cronológica). Resiliente a falha."""
    try:
        return _rpc("agent_recent_messages", {"p_phone": phone, "p_limit": limit}) or []
    except Exception:  # noqa: BLE001 — memória é opcional, nunca quebra a resposta
        return []


def log_message(phone: str, role: str, content: str) -> None:
    """Grava uma mensagem (user/assistant) na memória. Resiliente a falha."""
    try:
        _rpc("agent_log_message", {"p_phone": phone, "p_role": role, "p_content": content})
    except Exception:  # noqa: BLE001
        pass
