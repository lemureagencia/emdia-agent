"""Configuração via variáveis de ambiente (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()

# Supabase (use a SERVICE ROLE / secret key — ignora RLS, fica só aqui no servidor)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://vwlscymvrtmkuejtkies.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Transporte do WhatsApp: "zernio" (API oficial) ou "evolution"
TRANSPORT = os.getenv("TRANSPORT", "zernio").lower()

# Zernio API (WhatsApp oficial)
ZERNIO_BASE_URL = os.getenv("ZERNIO_BASE_URL", "https://zernio.com/api/v1")
ZERNIO_API_KEY = os.getenv("ZERNIO_API_KEY", "")
ZERNIO_ACCOUNT_ID = os.getenv("ZERNIO_ACCOUNT_ID", "")  # opcional; senão busca automático

# Evolution API (WhatsApp via Baileys) — legado
EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")

# LLM: provider = rule | openai | gemini | anthropic
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "rule").lower()
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")

# Kiwify: token de segurança do webhook (definir no Easypanel como KIWIFY_WEBHOOK_TOKEN)
KIWIFY_WEBHOOK_TOKEN = os.getenv("KIWIFY_WEBHOOK_TOKEN", "")
