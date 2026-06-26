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
             payment_method: str | None = None, status: str = "paid",
             due_date: str | None = None) -> dict:
    return _rpc("agent_register_by_phone", {
        "p_phone": phone,
        "p_type": type_,
        "p_amount": amount,
        "p_description": description,
        "p_payment_method": payment_method,
        "p_status": status,
        "p_due_date": due_date,
    })


def set_balance(phone: str, balance: float) -> dict:
    return _rpc("agent_set_balance_by_phone", {"p_phone": phone, "p_balance": balance})
