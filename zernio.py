"""Camada de transporte WhatsApp via Zernio API (oficial).

Interface unificada (igual a evolution.py):
- parse_webhook(body) -> (phone, text, msg_id, reply_to)
- send(reply_to, text)   # reply_to = conversationId na Zernio
"""
import re
import requests
import config

_BASE = (config.ZERNIO_BASE_URL or "https://zernio.com/api/v1").rstrip("/")
_HEADERS = {
    "Authorization": f"Bearer {config.ZERNIO_API_KEY}",
    "Content-Type": "application/json",
}


_account_id_cache = None


def _account_id() -> str | None:
    """ID da conta WhatsApp na Zernio (config ou busca automática, com cache)."""
    global _account_id_cache
    if config.ZERNIO_ACCOUNT_ID:
        return config.ZERNIO_ACCOUNT_ID
    if _account_id_cache:
        return _account_id_cache
    try:
        r = requests.get(f"{_BASE}/accounts", headers=_HEADERS, timeout=15)
        for a in r.json().get("accounts", []):
            if a.get("platform") == "whatsapp":
                _account_id_cache = a.get("_id")
                return _account_id_cache
    except Exception as e:  # noqa: BLE001
        print(f"[zernio:accounts erro] {e}")
    return None


def send(reply_to: str, text: str) -> None:
    """Envia mensagem numa conversa (reply_to = conversationId).
    POST /api/v1/inbox/conversations/{conversationId}/messages  body {"text","accountId"}"""
    if not config.ZERNIO_API_KEY:
        print(f"[zernio:simulado] -> conv {reply_to}: {text}")
        return
    try:
        r = requests.post(
            f"{_BASE}/inbox/conversations/{reply_to}/messages",
            json={"message": text, "accountId": _account_id()},
            headers=_HEADERS,
            timeout=20,
        )
        if r.status_code >= 300:
            print(f"[zernio:send {r.status_code}] {r.text[:300]}")
        else:
            print(f"[zernio:send ok] conv {reply_to}")
    except Exception as e:  # noqa: BLE001
        print(f"[zernio:erro] {e}")


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def parse_webhook(body: dict) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Extrai (phone, text, msg_id, conversationId, audio_url) do webhook da Zernio.

    audio_url é preenchido quando a mensagem é de áudio; text será None nesse caso.
    Só processa o evento de mensagem recebida.
    """
    event = (body.get("event") or "").lower()
    if event and event not in ("message.received", "conversation.started"):
        return None, None, None, None, None

    msg = body.get("message") or body.get("data") or {}
    text = msg.get("text") or msg.get("message") or msg.get("body")
    conv = (
        msg.get("conversationId")
        or msg.get("conversation_id")
        or (body.get("conversation") or {}).get("id")
    )
    msg_id = msg.get("id") or body.get("id")

    # O remetente vem em message.sender = {id, name, phoneNumber, contactId}
    sender = msg.get("sender")
    if isinstance(sender, dict):
        raw = sender.get("phoneNumber") or sender.get("id") or ""
    else:
        raw = str(sender or msg.get("senderId") or msg.get("from") or "")
    phone = _only_digits(raw)
    if len(phone) < 8:
        phone = raw or None

    # Detecta mensagem de áudio via lista de attachments (estrutura real da Zernio)
    audio_url = None
    if not text:
        for att in (msg.get("attachments") or []):
            if "audio" in (att.get("type") or "").lower():
                audio_url = att.get("url")
                break

    return (phone or None), (text.strip() if text else None), msg_id, conv, (audio_url or None)


def get_download_headers() -> dict:
    """Headers necessários para baixar mídia protegida da API Zernio."""
    return {"Authorization": f"Bearer {config.ZERNIO_API_KEY}"} if config.ZERNIO_API_KEY else {}
