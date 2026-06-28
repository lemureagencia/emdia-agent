"""Serviço FastAPI: recebe o webhook da Evolution API, processa e responde no WhatsApp.

Rodar:  uvicorn main:app --reload --port 8000
Testar: POST /test  {"phone": "5511...", "text": "paguei 150 de luz"}
"""
import sys
from fastapi import FastAPI, Request, HTTPException
import config
import handler
import kiwify
import transcribe

# Escolhe a camada de transporte do WhatsApp
if config.TRANSPORT == "zernio":
    import zernio as transport
else:
    import evolution as transport

# Evita UnicodeEncodeError no console do Windows (emojis nas mensagens)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

app = FastAPI(title="EmDia - Agente WhatsApp")


@app.get("/")
def health():
    return {"status": "ok", "service": "emdia-agent"}


# Evita processar a mesma mensagem duas vezes (dedupe por id)
_seen_ids: set[str] = set()


@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()
    phone, text, msg_id, reply_to, audio_url = transport.parse_webhook(body)

    # Log temporário: mostra body completo quando chega sem texto (ajuda a mapear áudio)
    if phone and not text and not audio_url:
        print(f"[debug:sem-texto] phone={phone} body={body}")

    # Áudio sem texto: tenta transcrever antes de continuar
    if phone and not text and audio_url:
        print(f"[audio] {phone}: transcrevendo {audio_url[:80]}")
        text = transcribe.transcribe_audio(audio_url)
        if text:
            print(f"[audio] transcrito: {text[:80]}")
        else:
            print(f"[audio] falha na transcrição — ignorando mensagem")

    if not (phone and text):
        return {"ok": True}
    if msg_id:
        if msg_id in _seen_ids:
            return {"ok": True}
        _seen_ids.add(msg_id)
        if len(_seen_ids) > 2000:
            _seen_ids.clear()

    print(f"[msg] {phone}: {text}")
    try:
        reply = handler.handle(phone, text)
    except Exception as e:  # noqa: BLE001
        print(f"[handler:erro] {e}")
        reply = "Tive um problema ao processar. Tente novamente em instantes."
    if reply is None:
        print(f"[ignorado] {phone} não é cadastrado — sem resposta")
        return {"ok": True}
    transport.send(reply_to or phone, reply)
    return {"ok": True}


@app.post("/webhook/kiwify")
async def webhook_kiwify(req: Request):
    """Recebe eventos do Kiwify e atualiza o plano do usuário no EmDia."""
    token = req.query_params.get("token") or ""
    if token != config.KIWIFY_WEBHOOK_TOKEN:
        raise HTTPException(status_code=403, detail="token inválido")
    body = await req.json()
    return kiwify.handle_webhook(body)


@app.post("/test")
async def test(req: Request):
    """Endpoint para testar sem WhatsApp: envia {phone, text} e vê a resposta."""
    body = await req.json()
    phone = body.get("phone")
    text = body.get("text")
    if not phone or not text:
        return {"error": "envie phone e text"}
    return {"reply": handler.handle(phone, text)}
