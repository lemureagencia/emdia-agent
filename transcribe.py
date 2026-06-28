"""Transcrição de áudio via Groq Whisper (whisper-large-v3).

Usa a mesma LLM_API_KEY já configurada para o Groq — sem nova chave.
"""
import io
import requests
import config

_GROQ_BASE = "https://api.groq.com/openai/v1"


def transcribe_audio(audio_url: str, request_headers: dict | None = None) -> str | None:
    """Baixa o áudio da URL e transcreve via Groq Whisper.

    request_headers: cabeçalhos extras para baixar o arquivo (ex.: Authorization da Zernio).
    Retorna o texto transcrito, ou None em caso de falha.
    """
    api_key = config.GROQ_API_KEY
    if not api_key:
        print("[transcribe] GROQ_API_KEY não configurada — áudio ignorado")
        return None

    # 1. Baixa o arquivo de áudio
    try:
        dl_headers = request_headers or {}
        resp = requests.get(audio_url, headers=dl_headers, timeout=30)
        resp.raise_for_status()
        audio_bytes = resp.content
        content_type = resp.headers.get("Content-Type", "audio/ogg")
    except Exception as e:
        print(f"[transcribe] erro ao baixar áudio: {e}")
        return None

    # Groq Whisper aceita ogg, mp3, mp4, wav, webm, m4a
    ext = _ext_from_content_type(content_type)

    # 2. Manda para o Groq Whisper via openai SDK
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=_GROQ_BASE)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = f"audio.{ext}"
        result = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=audio_file,
            language="pt",
            response_format="text",
        )
        transcript = (result or "").strip()
        print(f"[transcribe] ok: {transcript[:80]}")
        return transcript or None
    except Exception as e:
        print(f"[transcribe] erro na API Groq Whisper: {e}")
        return None


def _ext_from_content_type(ct: str) -> str:
    ct = ct.lower()
    if "ogg" in ct:
        return "ogg"
    if "mp4" in ct or "m4a" in ct:
        return "m4a"
    if "webm" in ct:
        return "webm"
    if "wav" in ct:
        return "wav"
    if "mp3" in ct or "mpeg" in ct:
        return "mp3"
    return "ogg"  # padrão WhatsApp
