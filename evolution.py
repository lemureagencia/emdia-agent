"""Cliente da Evolution API para enviar mensagens no WhatsApp."""
import time
import requests
import config

# Só processa mensagens recebidas nos últimos N segundos (evita o "history sync"
# que dispara o histórico inteiro quando o WhatsApp conecta).
_MAX_AGE_SECONDS = 120


def send_text(phone: str, text: str) -> None:
    """Envia uma mensagem de texto. Se a Evolution não estiver configurada,
    apenas imprime no console (útil para testar local sem WhatsApp)."""
    if not config.EVOLUTION_BASE_URL or not config.EVOLUTION_INSTANCE:
        print(f"[evolution:simulado] -> {phone}: {text}")
        return

    url = f"{config.EVOLUTION_BASE_URL.rstrip('/')}/message/sendText/{config.EVOLUTION_INSTANCE}"
    try:
        requests.post(
            url,
            json={"number": phone, "text": text},
            headers={"apikey": config.EVOLUTION_API_KEY, "Content-Type": "application/json"},
            timeout=20,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[evolution:erro] {e}")


def send(reply_to: str, text: str) -> None:
    """Interface unificada: na Evolution, reply_to = telefone."""
    send_text(reply_to, text)


def parse_webhook(body: dict) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Interface unificada: (phone, text, msg_id, reply_to=phone, audio_url=None)."""
    phone, text, msg_id = extract_message(body)
    return phone, text, msg_id, phone, None


def extract_message(body: dict) -> tuple[str | None, str | None, str | None]:
    """Extrai (telefone, texto, id_da_mensagem) do webhook da Evolution API.
    Retorna (None, None, None) para tudo que NÃO deve ser respondido:
    eventos que não são mensagem, grupos, mensagens próprias (fromMe) ou antigas."""
    event = (body.get("event") or "").lower().replace(".", "_")
    if event and event != "messages_upsert":
        return None, None, None

    data = body.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}

    key = data.get("key") or {}
    if key.get("fromMe"):
        return None, None, None

    remote = key.get("remoteJid") or ""
    if "@g.us" in remote or "@broadcast" in remote:  # grupos / status
        return None, None, None
    phone = remote.split("@")[0] if remote else None
    msg_id = key.get("id")

    # ignora mensagens antigas (sincronização de histórico ao conectar)
    ts = data.get("messageTimestamp")
    try:
        if ts and (time.time() - int(ts)) > _MAX_AGE_SECONDS:
            return None, None, None
    except (TypeError, ValueError):
        pass

    msg = data.get("message") or {}
    text = (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or (msg.get("imageMessage") or {}).get("caption")
    )
    return phone, (text.strip() if text else None), msg_id
