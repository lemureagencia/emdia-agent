"""Integração Kiwify → EmDia: recebe webhook e atualiza profiles.plan."""
import logging
from datetime import date, timedelta
import requests
import config

logger = logging.getLogger(__name__)

_BASE = config.SUPABASE_URL.rstrip("/") + "/rest/v1/rpc"
_HEADERS = {
    "apikey": config.SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

# IDs dos planos EmDia no Kiwify → tipo interno
_PLAN_ID_MAP: dict[str, str] = {
    "3f3be049-c3ac-43c2-aefa-356b999de441": "mensal",
    "7b052499-9ac9-4d02-87ab-1b34ab6ef8ef": "semestral",
    "e5963fd8-389a-4065-95a1-10f2bc23ce70": "anual",
}

# Duração de cada plano em dias
_PLAN_DAYS: dict[str, int] = {
    "mensal": 31,
    "semestral": 184,
    "anual": 365,
}


def _resolve_plan(data: dict) -> str | None:
    """Extrai o tipo de plano do payload do Kiwify (tenta várias estruturas)."""
    sub = data.get("Subscription") or data.get("subscription") or {}

    # Tenta via objeto plan aninhado
    plan_obj = sub.get("plan") or sub.get("Plan") or {}
    plan_id = plan_obj.get("id") or ""
    plan_name = (plan_obj.get("name") or "").lower().strip()

    # Tenta via id direto da Subscription (alguns produtos enviam assim)
    if not plan_id:
        plan_id = sub.get("id") or ""

    if plan_id in _PLAN_ID_MAP:
        return _PLAN_ID_MAP[plan_id]

    if plan_name in _PLAN_DAYS:
        return plan_name

    # Tenta correspondência parcial pelo nome (ex: "Plano Mensal" → "mensal")
    for key in _PLAN_DAYS:
        if key in plan_name:
            return key

    return None


def _set_plan(email: str, plan: str | None, expires_at: date | None) -> bool:
    """Atualiza profiles.plan via RPC. Retorna True se usuário foi encontrado."""
    try:
        payload: dict = {
            "p_email": email,
            "p_plan": plan or "mensal",
        }
        if expires_at:
            payload["p_expires_at"] = expires_at.isoformat()

        resp = requests.post(f"{_BASE}/set_plan_by_email", json=payload,
                             headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        return bool(result.get("found"))
    except Exception as e:
        logger.error("[kiwify] Erro ao atualizar plano: %s", e)
        return False


def handle_webhook(body: dict) -> dict:
    """
    Processa o payload do webhook Kiwify.
    Retorna {"ok": True, "action": "..."}.
    """
    event = body.get("type") or body.get("event") or ""
    data = body.get("data") or {}

    customer = data.get("Customer") or data.get("customer") or {}
    email = (customer.get("email") or "").strip().lower()

    if not email:
        logger.warning("[kiwify] Webhook sem email de cliente — ignorado. event=%s", event)
        return {"ok": True, "action": "ignored_no_email"}

    # Cancelamento / reembolso → volta para mensal (sem data de expiração)
    if event in ("subscription_canceled", "compra_reembolsada", "chargeback"):
        _set_plan(email, "mensal", None)
        logger.info("[kiwify] Plano resetado para mensal — %s (%s)", email, event)
        return {"ok": True, "action": "plan_reset"}

    # Compra aprovada ou renovação → ativa/mantém plano
    if event in ("compra_aprovada", "subscription_renewed"):
        plan = _resolve_plan(data)
        if not plan:
            logger.warning("[kiwify] Não foi possível identificar o plano. email=%s data=%s",
                           email, data)
            return {"ok": True, "action": "ignored_unknown_plan"}

        days = _PLAN_DAYS[plan]
        expires_at = date.today() + timedelta(days=days)
        found = _set_plan(email, plan, expires_at)

        logger.info("[kiwify] Plano %s → %s (expira %s, encontrado=%s)",
                    plan, email, expires_at, found)
        return {"ok": True, "action": f"plan_set:{plan}", "found": found}

    # Outros eventos (boleto_gerado, pix_gerado, etc.) — ignora
    logger.debug("[kiwify] Evento ignorado: %s", event)
    return {"ok": True, "action": "ignored_event"}
